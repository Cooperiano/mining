const fs = require('fs');
const path = require('path');

const { writeRecord, readRecords, tailRecords, readRawLines } = require('./rotate-wrapper');


const DEFAULT_STATE_DIR = path.join(__dirname, 'state');
let stateDir = DEFAULT_STATE_DIR;

function ensureDir() {
  if (!fs.existsSync(stateDir)) fs.mkdirSync(stateDir, { recursive: true });
}

function stateFile(name) {
  return path.join(stateDir, name);
}

function configureStateDir(dir) {
  stateDir = dir;
  ensureDir();
  for (const name of ['config.json', 'sessions.json', 'price_cache.json', 'deployed.json', 'bad.json']) {
    const target = stateFile(name);
    const source = path.join(DEFAULT_STATE_DIR, name);
    if (!fs.existsSync(target) && fs.existsSync(source)) {
      fs.copyFileSync(source, target);
    }
  }
}

function readJSON(filepath, fallback) {
  try {
    if (fs.existsSync(filepath)) {
      return JSON.parse(fs.readFileSync(filepath, 'utf8'));
    }
  } catch (_) {}
  return fallback;
}

function writeJSON(filepath, data) {
  ensureDir();
  fs.writeFileSync(filepath, JSON.stringify(data, null, 2));
}

// --- Sessions ---

function loadSessions() {
  return readJSON(stateFile('sessions.json'), []);
}

function saveSessions(sessions) {
  writeJSON(stateFile('sessions.json'), sessions);
}

function getSession(id) {
  return loadSessions().find(s => s.id === id) || null;
}

function getActiveSessions() {
  return loadSessions().filter(s => ['created', 'searching', 'renting', 'deploying', 'mining'].includes(s.status));
}

function getAllSessions() {
  return loadSessions();
}

function startSession(instanceId, details = {}) {
  const sessions = loadSessions();
  const existing = sessions.find(s =>
    String(s.instance_id) === String(instanceId) &&
    ['created', 'searching', 'renting', 'deploying', 'mining'].includes(s.status)
  );
  if (existing) {
    Object.assign(existing, details, { status: 'mining', started_at: existing.started_at || new Date().toISOString() });
    saveSessions(sessions);
    return existing;
  }

  const now = new Date().toISOString();
  const session = {
    id: `s_${Date.now()}`,
    created_at: now,
    started_at: now,
    ended_at: null,
    status: 'mining',
    instance_id: String(instanceId),
    worker_name: details.worker_name || '',
    gpu_type: details.gpu_type || '',
    gpu_count: details.gpu_count || 1,
    is_owned: false,
    rental_cost_per_hour: details.rental_cost_per_hour || 0,
    electricity_cost_per_hour: 0,
    total_cost_per_hour: details.rental_cost_per_hour || 0,
    rental_total_cost: 0,
    electricity_total_cost: 0,
    total_cost: 0,
    earnings_prl: 0,
    earnings_usd: 0,
    peak_hashrate: 0,
    avg_hashrate: 0,
    hashrate_samples: [],
    actions: [{ time: now, action: 'deploy_succeeded' }],
  };
  sessions.push(session);
  saveSessions(sessions);
  return session;
}

function syncInstanceSessions(instances) {
  const sessions = loadSessions();
  const instanceMap = new Map((instances || []).map(inst => [String(inst.id), inst]));
  const now = new Date();
  let changed = false;

  for (const instance of instances || []) {
    if (instance.status !== 'running' || !instance.miner_running) continue;
    const hasActive = sessions.some(session =>
      String(session.instance_id) === String(instance.id) && session.status === 'mining'
    );
    if (hasActive) continue;
    const createdAt = now.toISOString();
    sessions.push({
      id: `s_${Date.now()}_${instance.id}`,
      created_at: createdAt,
      started_at: createdAt,
      ended_at: null,
      status: 'mining',
      instance_id: String(instance.id),
      worker_name: '',
      gpu_type: instance.gpu_name || '',
      gpu_count: instance.num_gpus || 1,
      is_owned: false,
      rental_cost_per_hour: instance.price || 0,
      electricity_cost_per_hour: 0,
      total_cost_per_hour: instance.price || 0,
      rental_total_cost: 0,
      electricity_total_cost: 0,
      total_cost: 0,
      earnings_prl: 0,
      earnings_usd: 0,
      peak_hashrate: instance.local_hashrate || 0,
      avg_hashrate: instance.local_hashrate || 0,
      hashrate_samples: [],
      actions: [{ time: createdAt, action: 'discovered_running_miner' }],
    });
    changed = true;
  }

  for (const session of sessions) {
    if (session.status !== 'mining' || !session.instance_id) continue;
    const instance = instanceMap.get(String(session.instance_id));
    if (instance?.status === 'running') {
      const live = Number(instance.local_hashrate || instance.pool_hashrate || 0);
      if (live > 0) {
        session.peak_hashrate = Math.max(session.peak_hashrate || 0, live);
        session.avg_hashrate = live;
        changed = true;
      }
      continue;
    }

    const started = session.started_at ? new Date(session.started_at) : now;
    const hours = Math.max(0, (now - started) / 3600000);
    session.ended_at = now.toISOString();
    session.status = 'completed';
    session.reason = instance ? `instance_${instance.status}` : 'instance_removed';
    session.rental_total_cost = (session.rental_cost_per_hour || 0) * hours;
    session.total_cost = session.rental_total_cost + (session.electricity_total_cost || 0);
    changed = true;
  }

  if (changed) saveSessions(sessions);
  return changed;
}

function updateSession(id, updates) {
  const sessions = loadSessions();
  const idx = sessions.findIndex(s => s.id === id);
  if (idx === -1) return null;
  Object.assign(sessions[idx], updates);
  saveSessions(sessions);
  return sessions[idx];
}

function updateHashrate(sessionId, liveTh, h1Th) {
  const session = getSession(sessionId);
  if (!session) return null;

  const samples = [...(session.hashrate_samples || []), {
    time: new Date().toISOString(),
    live: liveTh,
    h1: h1Th,
  }];

  const trimmed = samples.slice(-1000);
  const sum = trimmed.reduce((a, s) => a + s.live, 0);
  const avg = trimmed.length > 0 ? sum / trimmed.length : 0;
  const peak = Math.max(session.peak_hashrate || 0, liveTh);

  return updateSession(sessionId, {
    hashrate_samples: trimmed,
    avg_hashrate: parseFloat(avg.toFixed(1)),
    peak_hashrate: parseFloat(peak.toFixed(1)),
  });
}

// --- Config ---

function loadConfig() {
  return readJSON(stateFile('config.json'), {
    wallet: 'REDACTED_WALLET',
    api_url: 'https://pearl.alphapool.tech/api/miner/',
    prl_price: 0.21,
    earn_rate: 3.226,
    electricity_price_usd_kwh: 0.122,
    owned_total_watts: 500,
    automation_enabled: true,
    auto_deploy_enabled: true,
    auto_destroy_enabled: false,
    auto_repair_enabled: false,
    dry_run: false,
    max_destroys_per_hour: 2,
    consecutive_failures_before_destroy: 3,
    new_instance_protection_minutes: 15,
    th_per_dollar_hr_threshold: 400,
    whitelist_regions: ['North America', 'Asia', 'Europe'],
  });
}

function writeAuditEvent(event) {
  const auditPath = path.join(stateDir, 'audit.jsonl');
  const record = { ts: new Date().toISOString().replace('T', ' ').slice(0, 19), ...event };
  ensureDir();
  fs.appendFileSync(auditPath, JSON.stringify(record) + '\n');
}

function readAuditLog(opts = {}) {
  const auditPath = path.join(stateDir, 'audit.jsonl');
  if (!fs.existsSync(auditPath)) return [];
  const limit = opts.limit || 100;
  const instanceId = opts.instance_id || '';
  const eventType = opts.event_type || '';
  const results = [];
  try {
    const lines = fs.readFileSync(auditPath, 'utf8').trim().split('\n');
    for (const line of lines) {
      if (!line) continue;
      try {
        const record = JSON.parse(line);
        if (instanceId && record.instance_id !== instanceId) continue;
        if (eventType && record.event !== eventType) continue;
        results.push(record);
      } catch (_) {}
    }
  } catch (_) {}
  results.reverse();
  return results.slice(0, limit);
}

function saveConfig(updates) {
  const before = loadConfig();
  const allowed = [
    'wallet', 'api_url', 'prl_price', 'earn_rate', 'electricity_price_usd_kwh',
    'owned_total_watts',
    'min_th_5090', 'min_th_5080', 'min_th_5070_ti', 'min_th_5070',
    'min_th_4090', 'min_th_4080_super', 'min_th_4080',
    'min_th_4070_ti_super', 'min_th_4070_ti', 'min_th_4070_super', 'min_th_4070',
    'min_th_4060_ti', 'min_th_4060',
    'min_th_3090_ti', 'min_th_3090', 'min_th_3080_ti', 'min_th_3080',
    'min_th_3070_ti', 'min_th_3070', 'min_th_3060_ti', 'min_th_3060',
    'min_th_h100', 'min_th_h200', 'min_th_b200',
    'min_th_a100', 'min_th_a6000', 'min_th_a5000', 'min_th_a4000',
    'min_th_l40s', 'min_th_l40',
    'kill_threshold_gpu_count', 'vast_search_gpu', 'vast_search_min_gpus',
    'vast_verified_only', 'vast_max_price', 'vastai_disk_gb',
    'autodeploy_interval_sec', 'kill_on_bad_network',
    'automation_enabled', 'auto_deploy_enabled', 'auto_destroy_enabled',
    'cost_kill_enabled', 'performance_kill_enabled',
    'cost_blacklist_enabled', 'performance_blacklist_enabled',
    'auto_repair_enabled', 'dry_run', 'max_destroys_per_hour',
    'consecutive_failures_before_destroy', 'new_instance_protection_minutes',
    'th_per_dollar_hr_threshold', 'whitelist_regions',
    'orchestrator_mode', 'tick_interval_sec', 'instance_check_interval_sec',
    'orchestrator_interval_sec',
    'max_concurrent_deploys', 'deploy_script', 'vastai_image',
    'dynamic_bid_enabled', 'bid_cooldown_sec', 'bid_min_margin_hr',
    'bid_safe_margin_hr', 'bid_watch_margin_hr', 'bid_raise_max_pct',
    'bid_lower_pct', 'bid_min_adjustment_usd', 'bid_consecutive_before_adjust',
    'bid_consecutive_before_lower', 'reject_dlperf_per_dollar',
    'min_dlperf_per_dollar', 'preferred_dlperf_per_dollar',
  ];
  for (const key of allowed) {
    if (Object.prototype.hasOwnProperty.call(updates, key)) before[key] = updates[key];
  }
  const after = { ...before };
  // Restore before values by copying from loadConfig
  // Actually no — 'before' was cloned to the updates side above. Let me redo.
  // Actually the original code mutates `current` and returns it.
  // Let me just compare with the proper before.
  const original = loadConfig();
  let current = { ...original };
  for (const key of allowed) {
    if (Object.prototype.hasOwnProperty.call(updates, key)) current[key] = updates[key];
  }
  const changedKeys = allowed.filter(k =>
    Object.prototype.hasOwnProperty.call(updates, k) && updates[k] !== original[k]
  );
  writeJSON(stateFile('config.json'), current);

  // Audit + config log
  if (changedKeys.length > 0) {
    writeAuditEvent({
      event: 'config_change',
      trigger: 'config',
      details: `Changed: ${changedKeys.join(', ')}`,
      extra: Object.fromEntries(changedKeys.map(k => [k, updates[k]])),
    });

    // Write structured config change record
    writeRecord('config_log.jsonl', {
      trigger: 'electron_ui',
      changed_keys: changedKeys,
      before: Object.fromEntries(changedKeys.map(k => [k, original[k]])),
      after: Object.fromEntries(changedKeys.map(k => [k, current[k]])),
    });
  }

  return current;
}

// --- Earnings recording ---

/**
 * Record an earnings tick for a single instance.
 * Writes to earnings_log.jsonl and updates session cumulative totals.
 *
 * @param {object} tick
 * @param {string} tick.instance_id
 * @param {string} tick.session_id
 * @param {number} tick.live_th
 * @param {number} tick.h1_th
 * @param {number} tick.prl_price
 * @param {number} tick.earnings_usd_hr
 * @param {number} tick.rental_cost_hr
 * @param {number} tick.net_profit_hr
 */
function recordEarning(tick) {
  // Update session cumulative totals
  const session = getSession(tick.session_id);
  if (session) {
    const intervalHrs = 30 / 3600; // 30-second ticks
    session.earnings_usd = (session.earnings_usd || 0) + tick.earnings_usd_hr * intervalHrs;
    session.rental_total_cost = (session.rental_total_cost || 0) + tick.rental_cost_hr * intervalHrs;
    session.total_cost = (session.rental_total_cost || 0) + (session.electricity_total_cost || 0);
    saveSessions(loadSessions());
  }

  writeRecord('earnings_log.jsonl', {
    instance_id: String(tick.instance_id),
    session_id: tick.session_id,
    live_th: Math.round((tick.live_th || 0) * 100) / 100,
    h1_th: Math.round((tick.h1_th || 0) * 100) / 100,
    prl_price: tick.prl_price,
    earnings_usd_hr: Math.round((tick.earnings_usd_hr || 0) * 10000) / 10000,
    rental_cost_hr: Math.round((tick.rental_cost_hr || 0) * 10000) / 10000,
    net_profit_hr: Math.round((tick.net_profit_hr || 0) * 10000) / 10000,
    cumulative_earnings_usd: Math.round((session ? session.earnings_usd : 0) * 10000) / 10000,
    cumulative_cost_usd: Math.round((session ? session.total_cost : 0) * 10000) / 10000,
  });
}

/**
 * Add an action entry to a session's action history.
 * @param {string} sessionId
 * @param {string} action - Action description
 */
function addAction(sessionId, action) {
  const session = getSession(sessionId);
  if (!session) return;
  const actions = [...(session.actions || []), {
    time: new Date().toISOString(),
    action,
  }];
  updateSession(sessionId, { actions });
}

/**
 * Add a cost history entry to a session.
 * @param {string} sessionId
 * @param {number} pricePerGpu - Current price per GPU
 * @param {number} dphTotal - Total cost per hour
 */
function addCostHistoryEntry(sessionId, pricePerGpu, dphTotal) {
  const session = getSession(sessionId);
  if (!session) return;
  const costHistory = [...(session.cost_history || []), {
    time: new Date().toISOString(),
    price_per_gpu: Math.round(pricePerGpu * 10000) / 10000,
    dph_total: Math.round(dphTotal * 10000) / 10000,
  }];
  // Keep last 1000 entries
  updateSession(sessionId, { cost_history: costHistory.slice(-1000) });
}

// --- JSONL query functions ---

function readEarningsLog(opts = {}) {
  return readRecords('earnings_log.jsonl', {
    limit: opts.limit || 500,
    beforeEpochMs: opts.beforeEpochMs,
    afterEpochMs: opts.afterEpochMs,
  });
}

function readKillDecisions(opts = {}) {
  return readRecords('kill_decisions.jsonl', {
    limit: opts.limit || 500,
    beforeEpochMs: opts.beforeEpochMs,
    afterEpochMs: opts.afterEpochMs,
  });
}

function readCycleLog(opts = {}) {
  return readRecords('cycle_log.jsonl', {
    limit: opts.limit || 200,
    beforeEpochMs: opts.beforeEpochMs,
    afterEpochMs: opts.afterEpochMs,
  });
}

function readWorkerSnapshots(opts = {}) {
  return readRecords('worker_snapshots.jsonl', {
    limit: opts.limit || 500,
    beforeEpochMs: opts.beforeEpochMs,
    afterEpochMs: opts.afterEpochMs,
  });
}

function readInstanceSnapshots(opts = {}) {
  return readRecords('instance_snapshots.jsonl', {
    limit: opts.limit || 500,
    beforeEpochMs: opts.beforeEpochMs,
    afterEpochMs: opts.afterEpochMs,
  });
}

function readConfigLog(opts = {}) {
  return readRecords('config_log.jsonl', {
    limit: opts.limit || 100,
    beforeEpochMs: opts.beforeEpochMs,
    afterEpochMs: opts.afterEpochMs,
  });
}

/**
 * Read raw lines from any JSONL file, newest first.
 * @param {string} filename - e.g. "kill_decisions.jsonl"
 * @param {number} [limit=500]
 * @returns {string[]}
 */
function readJsonlRaw(filename, limit = 500) {
  return readRawLines(filename, limit);
}

// --- CSV Export ---

/**
 * Export all sessions as CSV string.
 * @returns {string}
 */
function exportHistoryCSV() {
  const sessions = loadSessions();
  const headers = [
    'Session ID', 'Status', 'Instance ID', 'Worker Name', 'GPU Model',
    'GPU Count', 'Started', 'Ended', 'Duration (hrs)',
    'Peak TH/s', 'Avg TH/s',
    'Rent Cost/hr', 'Elec Cost/hr', 'Total Cost/hr',
    'Rent Total', 'Elec Total', 'Total Cost',
    'Earned (USD)', 'Net (USD)', 'Result',
  ];
  const rows = [headers.join(',')];

  for (const s of sessions) {
    const started = s.started_at ? new Date(s.started_at) : null;
    const ended = s.ended_at ? new Date(s.ended_at) : new Date();
    const durationHrs = started ? ((ended - started) / 3600000).toFixed(2) : '0';
    const net = ((s.earnings_usd || 0) - (s.total_cost || 0)).toFixed(4);

    rows.push([
      s.id,
      s.status || '',
      s.instance_id || '',
      `"${(s.worker_name || '').replace(/"/g, '""')}"`,
      `"${(s.gpu_type || '').replace(/"/g, '""')}"`,
      s.gpu_count || 1,
      s.started_at || '',
      s.ended_at || '',
      durationHrs,
      (s.peak_hashrate || 0).toFixed(1),
      (s.avg_hashrate || 0).toFixed(1),
      (s.rental_cost_per_hour || 0).toFixed(4),
      (s.electricity_cost_per_hour || 0).toFixed(4),
      (s.total_cost_per_hour || 0).toFixed(4),
      (s.rental_total_cost || 0).toFixed(4),
      (s.electricity_total_cost || 0).toFixed(4),
      (s.total_cost || 0).toFixed(4),
      (s.earnings_usd || 0).toFixed(4),
      net,
      s.reason || '',
    ].join(','));
  }

  return rows.join('\n');
}

module.exports = {
  getSession,
  getActiveSessions,
  getAllSessions,
  startSession,
  syncInstanceSessions,
  updateSession,
  updateHashrate,
  loadConfig,
  saveConfig,
  configureStateDir,
  stateFile,
  writeAuditEvent,
  readAuditLog,
  // Earnings & session field recording
  recordEarning,
  addAction,
  addCostHistoryEntry,
  // JSONL query functions
  readEarningsLog,
  readKillDecisions,
  readCycleLog,
  readWorkerSnapshots,
  readInstanceSnapshots,
  readConfigLog,
  readJsonlRaw,
  // CSV export
  exportHistoryCSV,
};
