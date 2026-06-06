// --- State ---
let allWorkers = [];
let allSessions = [];
const cache = {};
const inFlight = new Map();
const renderedHtml = new WeakMap();
let activeTab = localStorage.getItem('activeTab') || 'dashboard';
let activeTabRefreshInterval = null;
const tabRefreshMs = {
  records: 20000,
  instances: 5000,
  autodeploy: 10000,
  config: 30000,
};
let configDirty = false;

// Records sub-navigation
let activeRecordsView = 'sessions';

function cached(key, fetchFn, renderFn, ttlMs) {
  return async function(force = false) {
    const now = Date.now();
    if (!force && cache[key] && (now - cache[key].time < ttlMs)) {
      renderFn(cache[key].data);
      return cache[key].data;
    }
    if (inFlight.has(key)) return inFlight.get(key);

    const request = (async () => {
      try {
        const data = await fetchFn();
        cache[key] = { time: Date.now(), data };
        renderFn(data);
        return data;
      } catch (_) {
        return cache[key]?.data;
      } finally {
        inFlight.delete(key);
      }
    })();
    inFlight.set(key, request);
    return request;
  };
}

function singleFlight(key, task) {
  if (inFlight.has(key)) return inFlight.get(key);
  const request = Promise.resolve()
    .then(task)
    .finally(() => inFlight.delete(key));
  inFlight.set(key, request);
  return request;
}

function setText(el, value) {
  if (el && el.textContent !== String(value)) el.textContent = value;
}

function setHtml(el, html) {
  if (!el || renderedHtml.get(el) === html) return false;
  el.innerHTML = html;
  renderedHtml.set(el, html);
  return true;
}

function isNearBottom(el, threshold = 48) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

function setScrollableText(el, text, stickToBottom = false) {
  if (!el || el.textContent === text) return;
  const shouldStick = stickToBottom && isNearBottom(el);
  const oldTop = el.scrollTop;
  el.textContent = text;
  requestAnimationFrame(() => {
    el.scrollTop = shouldStick ? el.scrollHeight : oldTop;
  });
}

function appendLog(el, html) {
  if (!el) return;
  const shouldStick = isNearBottom(el);
  el.insertAdjacentHTML('beforeend', html);
  if (shouldStick) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}

function isVisibleTab(name) {
  return activeTab === name && !document.hidden;
}

function refreshActiveTab(force = false) {
  if (activeTab === 'dashboard') return refreshDashboard(force);
  if (activeTab === 'records') {
    window.api.refreshInstanceHealth(false);
    return refreshRecordsView(force);
  }
  if (activeTab === 'instances') return refreshInstances(force);
  if (activeTab === 'autodeploy') return refreshAutodeploy(force);
  if (activeTab === 'config') return refreshConfig();
}

function scheduleActiveTabRefresh() {
  if (activeTabRefreshInterval) clearInterval(activeTabRefreshInterval);
  const interval = tabRefreshMs[activeTab];
  if (!interval) return;
  activeTabRefreshInterval = setInterval(() => {
    if (!document.hidden) refreshActiveTab();
  }, interval);
}

function invalidate(key) { delete cache[key]; }

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initDashboard();
  initTableWheelPassthrough();
  initRecords();
  initInstances();
  initAutodeploy();
  initConfig();
  initIPCListeners();
  refreshActiveTab();
  scheduleActiveTabRefresh();

  // Window controls (frameless on Windows)
  document.getElementById('win-minimize')?.addEventListener('click', () => window.api.minimize());
  document.getElementById('win-maximize')?.addEventListener('click', () => window.api.maximize());
  document.getElementById('win-close')?.addEventListener('click', () => window.api.close());

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshActiveTab();
  });
});

function initTableWheelPassthrough() {
  document.querySelectorAll('.table-wrap:not(.records-table-wrap)').forEach(container => {
    container.addEventListener('wheel', event => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      event.preventDefault();
      window.scrollBy(0, event.deltaY);
    }, { passive: false });
  });
}

// --- Tabs ---
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (activeTab === tab.dataset.tab) return;
      activeTab = tab.dataset.tab;
      localStorage.setItem('activeTab', activeTab);
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
      document.querySelectorAll('.tab-content').forEach(c => {
        c.classList.toggle('active', c.id === 'tab-' + activeTab);
      });
      refreshActiveTab();
      scheduleActiveTabRefresh();
    });
  });

  // Restore last active tab on startup
  if (activeTab !== 'dashboard') {
    const targetTab = document.querySelector(`.tab[data-tab="${activeTab}"]`);
    if (targetTab) {
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === targetTab));
      document.querySelectorAll('.tab-content').forEach(c => {
        c.classList.toggle('active', c.id === 'tab-' + activeTab);
      });
    } else {
      activeTab = 'dashboard';
    }
  }
}

// --- IPC Listeners ---
function initIPCListeners() {
  window.api.onDashboardUpdate((data) => {
    if (!data || data.error) return;
    allWorkers = data.workers || [];
    window._lastDashboardData = data;
    if (activeTab === 'dashboard') renderDashboard(data);
  });

  window.api.onDeployResult((data) => {
    if (!data) return;
    const statusOutput = document.getElementById('status-output');
    if (statusOutput) {
      const timestamp = data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
      const output = data.output || '';
      const error = data.error || '';
      appendLog(statusOutput, `
        <div style="margin-bottom:4px;color:var(--text-dim)">[${timestamp}]</div>
        <pre style="white-space:pre-wrap;margin:0">${escapeHtml(output + error)}</pre>
      `);
    }
    if (isVisibleTab('autodeploy')) {
      refreshStatus(true);
      refreshBlacklist(true);
    }
  });

  window.api.onInstanceDeployStart((instanceId) => {
    const log = document.getElementById('instance-deploy-log');
    if (log) {
      const ts = new Date().toLocaleTimeString();
      log.innerHTML = `<div style="color:var(--yellow)">[${ts}] Deploying to ${escapeHtml(instanceId)}...</div>`;
    }
    if (isVisibleTab('instances')) refreshInstances(true);
  });

  window.api.onInstanceDeployOutput((data) => {
    const log = document.getElementById('instance-deploy-log');
    if (!log || !data?.output) return;
    const color = data.stream === 'stderr' ? 'var(--red)' : 'var(--text)';
    appendLog(log, `<span style="white-space:pre-wrap;color:${color}">${escapeHtml(data.output)}</span>`);
  });

  window.api.onInstanceDeployResult((data) => {
    const log = document.getElementById('instance-deploy-log');
    if (log) {
      const ts = new Date().toLocaleTimeString();
      const color = data.success ? 'var(--accent)' : 'var(--red)';
      const status = data.success ? 'Deploy succeeded' : 'Deploy failed';
      appendLog(log, `<div style="color:${color};margin-top:8px">[${ts}] ${escapeHtml(data.instanceId)}: ${status}</div>`);
    }
    deployingInstances.delete(data.instanceId);
    invalidate('sessions');
    if (isVisibleTab('instances')) refreshInstances(true);
  });

  window.api.onInstanceHealthUpdate((instances) => {
    if (!Array.isArray(instances)) return;
    cache.instances = { time: Date.now(), data: instances };
    if (activeTab === 'instances') renderInstances(instances);
    invalidate('sessions');
    if (activeTab === 'records') refreshRecordsView(true);
  });
}

// ============ DASHBOARD ============

let workerSort = { key: 'live_th', asc: false };

function initDashboard() {
  document.querySelectorAll('#workers-table th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (workerSort.key === key) {
        workerSort.asc = !workerSort.asc;
      } else {
        workerSort.key = key;
        workerSort.asc = (key === 'machine' || key === 'gpu' || key === 'status');
      }
      renderDashboard(window._lastDashboardData);
    });
  });

  const hideIdleCheckbox = document.getElementById('hide-idle');
  if (hideIdleCheckbox) {
    hideIdleCheckbox.addEventListener('change', () => {
      renderDashboard(window._lastDashboardData);
    });
  }
}

function sortWorkers(workers) {
  const key = workerSort.key;
  return [...workers].sort((a, b) => {
    let va, vb;
    if (key === 'live_th' || key === 'h1_th' || key === 'h24_th') {
      va = a[key] || 0;
      vb = b[key] || 0;
    } else if (key === 'power') {
      va = parseInt((a.name || '').match(/(\d+)W/)?.[1] || classifyWorkerDOM(a.name).power || '0');
      vb = parseInt((b.name || '').match(/(\d+)W/)?.[1] || classifyWorkerDOM(b.name).power || '0');
    } else {
      const clsA = classifyWorkerDOM(a.name);
      const clsB = classifyWorkerDOM(b.name);
      va = (key === 'machine' ? clsA.machine : key === 'gpu' ? clsA.gpu : (a.online ? 1 : 0)) || '';
      vb = (key === 'machine' ? clsB.machine : key === 'gpu' ? clsB.gpu : (b.online ? 1 : 0)) || '';
    }
    if (typeof va === 'string') {
      const cmp = String(va).localeCompare(String(vb), undefined, { numeric: true });
      return workerSort.asc ? cmp : -cmp;
    }
    return workerSort.asc ? va - vb : vb - va;
  });
}

async function refreshDashboard(force = false) {
  return singleFlight('dashboard', async () => {
    try {
      const data = await window.api.getDashboard();
    if (data && !data.error) {
      allWorkers = data.workers || [];
      renderDashboard(data);
    }
    } catch (_) {}
  });
}

function renderDashboard(data) {
  if (!data) return;
  // Store for re-sort
  window._lastDashboardData = data;

  // Store PRL price globally
  window._prlPrice = data.prl_price || 0.80;

  // Header stats
  setText(document.getElementById('header-hashrate'), `${data.total_live_th.toFixed(0)} TH/s`);
  setText(document.getElementById('header-balance'), `${data.balance.toFixed(2)} PRL`);
  setText(document.getElementById('header-earnings'), `$${data.earnings_per_hour.toFixed(2)}/hr`);
  setText(document.getElementById('header-workers'), `${data.worker_count} workers`);

  // Workers table
  const hideIdle = document.getElementById('hide-idle')?.checked;
  let allTableWorkers = data.workers && data.workers.length ? sortWorkers(data.workers) : [];
  let tableWorkers = hideIdle ? allTableWorkers.filter(w => w.online !== false) : allTableWorkers;
  const showingCount = tableWorkers.length;
  const totalCount = allTableWorkers.length;
  document.getElementById('workers-count').textContent = showingCount !== totalCount ? `showing ${showingCount} of ${totalCount}` : '';
  const tbody = document.getElementById('workers-body');
  if (!tableWorkers.length) {
    setHtml(tbody, '<tr><td colspan="8" class="loading">No workers</td></tr>');
  } else {
    setHtml(tbody, tableWorkers.map(w => {
      const cls = classifyWorkerDOM(w.name);
      let powerDisplay = cls.power;
      const isOnline = w.online !== false;
      const liveColor = isOnline ? (w.live_th > 200 ? 'green' : w.live_th > 100 ? 'yellow' : 'red') : '';
      const statusBadge = isOnline
        ? '<span class="badge badge-mining">ONLINE</span>'
        : '<span class="badge badge-killed">OFFLINE</span>';
      const rowStyle = isOnline ? '' : 'style="opacity:0.5"';
      return `
        <tr ${rowStyle}>
          <td>${esc(cls.machine)}</td>
          <td>${esc(cls.gpu)}</td>
          <td class="val ${liveColor}">${isOnline ? w.live_th.toFixed(1) : '—'}</td>
          <td>${isOnline ? w.h1_th.toFixed(1) : '—'}</td>
          <td class="val green">${isOnline ? '$' + ((w.h1_th / 1000) * 3.226 * (window._prlPrice || 0.80)).toFixed(6) : '—'}</td>
          <td>${isOnline ? (w.h24_th || 0).toFixed(1) : '—'}</td>
          <td>${powerDisplay}</td>
          <td>${statusBadge}</td>
        </tr>`;
    }).join(''));
  }

  // Update sort indicators
  document.querySelectorAll('#workers-table th.sortable').forEach(th => {
    const key = th.dataset.sort;
    th.textContent = th.textContent.replace(/ [▴▾]$/, '') + (key === workerSort.key ? (workerSort.asc ? ' ▴' : ' ▾') : '');
  });

  const onlineOnly = allTableWorkers.filter(w => w.online !== false);
  const totalH24 = onlineOnly.reduce((s, w) => s + (w.h24_th || 0), 0);

  setHtml(document.getElementById('workers-foot'), `
    <tr>
      <td><strong>TOTAL</strong></td>
      <td>${data.worker_count}/${data.worker_total || data.worker_count} GPUs</td>
      <td class="val">${data.total_live_th.toFixed(1)}</td>
      <td>${data.est_1h.toFixed(1)}</td>
      <td class="val green">$${ ((data.est_1h / 1000) * 3.226 * (data.prl_price || 0.80)).toFixed(6) }</td>
      <td>${totalH24.toFixed(1)}</td>
      <td>—</td>
      <td>—</td>
    </tr>`);

  // Profitability
  document.getElementById('profit-prl-price').textContent = `$${data.prl_price || data.prlPrice?.toFixed(4) || '0.8000'} ${data.priceSource ? '('+data.priceSource+')' : ''}`;
  document.getElementById('profit-earn-hr').textContent = `$${data.earningsPerHr?.toFixed(6) || data.earnings_per_hour?.toFixed(4) || '0.00'}`;
  document.getElementById('profit-est-th').textContent = `${(data.total_live_th || 0).toFixed(0)} TH/s`;
  document.getElementById('profit-pool-hash').textContent = data.pool_hashrate || '—';

  // Cost breakdown
  document.getElementById('profit-elec-hr').textContent = `$${(data.electricityCostHr || 0).toFixed(4)}`;
  document.getElementById('profit-vast-rate').textContent = `$${(data.rentalCostHr || 0).toFixed(4)}`;
  document.getElementById('profit-total-cost-hr').textContent = `$${(data.totalCostHr || 0).toFixed(4)}`;
  const netProfit = data.netProfitHr || ((data.earningsPerHr || data.earnings_per_hour || 0) - (data.totalCostHr || 0));
  document.getElementById('profit-net-hr').textContent = `$${netProfit.toFixed(6)}`;
  document.getElementById('profit-net-hr').className = 'val ' + (netProfit >= 0 ? 'green' : 'red');
  document.getElementById('profit-net-hr').style.fontSize = '15px';

  // Wallet
  document.getElementById('wallet-balance').textContent = `${data.balance.toFixed(2)} PRL`;
  document.getElementById('wallet-paid').textContent = `${data.paid.toFixed(2)} PRL`;
  document.getElementById('wallet-price').textContent = `$${(data.prl_price || data.prlPrice || 0).toFixed(4)}`;
  document.getElementById('wallet-vast-billed').textContent = `$${(data.vastBilledTotal || 0).toFixed(4)}`;
  document.getElementById('wallet-elec-total').textContent = `$${(data.electricityTotalCost || 0).toFixed(4)}`;

  const prlPrice = data.prl_price || data.prlPrice || 0;
  const totalPrlValue = (data.balance + data.paid) * prlPrice;
  const totalCosts = (data.vastBilledTotal || 0) + (data.electricityTotalCost || 0);
  const netValue = totalPrlValue - totalCosts;
  const netEl = document.getElementById('wallet-net-value');
  netEl.textContent = `$${netValue.toFixed(4)}`;
  netEl.className = 'val ' + (netValue >= 0 ? 'green' : 'red');
}

function classifyWorkerDOM(name) {
  if (name === 'miner1') return { machine: 'station', gpu: 'RTX 3080', power: '320W' };
  if (name.includes('miner2')) return { machine: 'lab1', gpu: '4060Ti', power: '160W' };
  if (name === 'miner3') return { machine: 'laptop', gpu: 'RTX 3060', power: '95W' };
  // Generic worker name: "{GPU}x{N}-{suffix}" (e.g. "5090x4-abcd", "4090x2-ef01")
  const m = name.match(/^(\d+)(x(\d+))?-[a-f0-9]{4}/);
  const gpuNum = m ? m[1] : '';
  const gpuCount = m && m[3] ? m[3] : '';
  let gpu = gpuNum || name.substring(0, 8);
  let powerMap = { '5090': '575W', '5080': '360W', '5070': '250W', '4090': '450W', '4070': '220W', '3090': '350W', '3070': '220W', '3060Ti': '200W', '4060Ti': '160W', '4060': '115W', '3080': '320W', '3060': '170W', 'A100': '400W', 'H100': '700W', 'H200': '700W' };
  let power = powerMap[gpuNum] || '?';
  if (name.includes('gpu')) {
    const gpuId = name.match(/gpu(\d+)/);
    if (gpuId) gpu += ' #' + gpuId[1];
  }
  return { machine: name.substring(0, Math.min(16, name.length)), gpu, power };
}

// ============ RECORDS TAB ============

function initRecords() {
  // Sub-navigation buttons
  document.querySelectorAll('.records-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (activeRecordsView === btn.dataset.recordsView) return;
      activeRecordsView = btn.dataset.recordsView;
      document.querySelectorAll('.records-nav-btn').forEach(b => {
        b.classList.toggle('active', b === btn);
      });
      document.querySelectorAll('.records-view').forEach(v => {
        v.classList.toggle('active', v.id === 'records-view-' + activeRecordsView);
      });
      refreshRecordsView(true);
    });
  });

  // CSV Export button
  const exportBtn = document.getElementById('export-csv-btn');
  if (exportBtn) {
    exportBtn.addEventListener('click', () => handleExportCSV());
  }

  // Refresh button for earnings timeline
  const refreshEarningsBtn = document.getElementById('refresh-earnings-btn');
  if (refreshEarningsBtn) {
    refreshEarningsBtn.addEventListener('click', () => {
      invalidate('earnings-timeline');
      refreshRecordsView(true);
    });
  }

  // Log viewer controls
  const refreshLogBtn = document.getElementById('refresh-log-viewer-btn');
  if (refreshLogBtn) {
    refreshLogBtn.addEventListener('click', () => refreshLogViewer(true));
  }
  const logTypeSelect = document.getElementById('log-viewer-type');
  const logLimitSelect = document.getElementById('log-viewer-limit');
  if (logTypeSelect) logTypeSelect.addEventListener('change', () => refreshLogViewer(true));
  if (logLimitSelect) logLimitSelect.addEventListener('change', () => refreshLogViewer(true));
}

function refreshRecordsView(force = false) {
  if (activeRecordsView === 'sessions') return refreshSessions(force);
  if (activeRecordsView === 'kill-decisions') return refreshKillDecisions(force);
  if (activeRecordsView === 'cycle-history') return refreshCycleHistory(force);
  if (activeRecordsView === 'earnings-timeline') return refreshEarningsTimeline(force);
  if (activeRecordsView === 'log-viewer') return refreshLogViewer(force);
}

const refreshSessions = cached('sessions',
  () => window.api.getAllSessions().then(data => { allSessions = data; return data; }),
  (data) => renderSessions(data || allSessions),
  30000
);

function renderSessions(sessions) {
  const completed = (sessions || [])
    .filter(s => ['mining', 'completed', 'killed'].includes(s.status))
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  const tbody = document.getElementById('records-sessions-body');

  if (!completed.length) {
    setHtml(tbody, '<tr><td colspan="12" class="loading">No completed sessions</td></tr>');
    return;
  }

  setHtml(tbody, completed.map(s => {
    const started = s.started_at ? formatDate(s.started_at) : '—';
    const ended = s.ended_at ? formatDate(s.ended_at) : '—';
    let duration = '—';
    if (s.started_at) {
      const hours = ((s.ended_at ? new Date(s.ended_at) : new Date()) - new Date(s.started_at)) / 3600000;
      duration = formatDuration(hours);
    }
    const rentalCost = (s.rental_total_cost || 0).toFixed(4);
    const elecCost = (s.electricity_total_cost || 0).toFixed(4);
    const totalCost = (s.total_cost || (s.rental_total_cost || 0) + (s.electricity_total_cost || 0)).toFixed(4);
    const earned = (s.earnings_usd || 0).toFixed(6);
    const net = (parseFloat(earned) - parseFloat(totalCost)).toFixed(6);

    return `
      <tr>
        <td>${started}</td>
        <td>${ended}</td>
        <td>${duration}</td>
        <td>${esc(s.worker_name || '—')}</td>
        <td>${esc(s.gpu_type || '—')}</td>
        <td>${s.peak_hashrate > 0 ? s.peak_hashrate.toFixed(0) : '—'}</td>
        <td class="val red">$${rentalCost}</td>
        <td class="val red">$${elecCost}</td>
        <td class="val red">$${totalCost}</td>
        <td class="val green">$${earned}</td>
        <td class="val ${net >= 0 ? 'green' : 'red'}">$${net}</td>
        <td>${s.status === 'mining'
          ? '<span class="badge badge-mining">MINING</span>'
          : s.status === 'killed'
            ? `<span class="badge badge-killed">${esc(s.reason || 'KILLED')}</span>`
            : `<span class="badge badge-completed">${esc(s.reason || 'DONE')}</span>`}</td>
      </tr>`;
  }).join(''));
}

// --- Kill Decisions ---

const refreshKillDecisions = cached('kill-decisions',
  () => window.api.getKillDecisions({ limit: 200 }),
  (data) => renderKillDecisions(data),
  15000
);

function renderKillDecisions(records) {
  const tbody = document.getElementById('kill-decisions-body');
  const countEl = document.getElementById('kill-decisions-count');

  if (!records || !records.length) {
    setHtml(tbody, '<tr><td colspan="10" class="loading">No kill decisions recorded yet</td></tr>');
    if (countEl) setText(countEl, '');
    return;
  }

  if (countEl) setText(countEl, `(${records.length} records)`);

  setHtml(tbody, records.map(r => {
    const time = r.ts ? formatDate(r.ts) : '—';
    const typeLabels = {
      underperforming: '<span class="badge badge-killed">PERF</span>',
      too_expensive: '<span class="badge badge-unhealthy">COST</span>',
      no_workers_online: '<span class="badge badge-degraded">NO_WORKERS</span>',
      deploy_fail: '<span class="badge badge-unavailable">DEPLOY_FAIL</span>',
      manual: '<span class="badge badge-pending">MANUAL</span>',
    };
    const typeBadge = typeLabels[r.reason_type] || esc(r.reason_type || '—');
    const executed = r.executed
      ? '<span class="badge badge-killed">YES</span>'
      : '<span class="badge badge-completed">NO</span>';

    return `
      <tr>
        <td>${time}</td>
        <td style="font-family:monospace">${esc(r.instance_id || '—')}</td>
        <td>${esc(r.machine_id || '—')}</td>
        <td>${esc(r.gpu_model || '—')}${r.num_gpus ? ` ×${r.num_gpus}` : ''}</td>
        <td class="val">${r.live_th != null ? r.live_th.toFixed(1) : '—'}</td>
        <td class="val">${r.h1_th != null ? r.h1_th.toFixed(1) : '—'}</td>
        <td class="val">${r.min_th_conf != null ? r.min_th_conf.toFixed(0) : r.min_th_calc != null ? r.min_th_calc.toFixed(0) : '—'}</td>
        <td class="val red">${r.price_per_gpu != null ? '$' + r.price_per_gpu.toFixed(4) : '—'}</td>
        <td>${typeBadge}</td>
        <td>${executed}</td>
      </tr>`;
  }).join(''));
}

// --- Cycle History ---

const refreshCycleHistory = cached('cycle-history',
  () => window.api.getCycleLog({ limit: 100 }),
  (data) => renderCycleHistory(data),
  15000
);

function renderCycleHistory(records) {
  const tbody = document.getElementById('cycle-history-body');
  const countEl = document.getElementById('cycle-history-count');

  if (!records || !records.length) {
    setHtml(tbody, '<tr><td colspan="11" class="loading">No cycle history recorded yet</td></tr>');
    if (countEl) setText(countEl, '');
    return;
  }

  if (countEl) setText(countEl, `(${records.length} records)`);

  setHtml(tbody, records.map(r => {
    const time = r.ts ? formatDate(r.ts) : '—';
    const duration = r.duration_seconds != null ? r.duration_seconds.toFixed(1) + 's' : '—';
    const prlPrice = r.prl_price != null ? '$' + r.prl_price.toFixed(4) : '—';
    const maxPrice = r.max_price_per_gpu != null ? '$' + r.max_price_per_gpu.toFixed(4) : '—';
    const instances = r.instances_running != null ? `${r.instances_running} / ${r.instances_fetched || '?'}` : '—';
    const dryRun = r.dry_run
      ? '<span class="badge badge-degraded">DRY</span>'
      : '<span class="badge badge-healthy">LIVE</span>';

    return `
      <tr>
        <td>${time}</td>
        <td>${duration}</td>
        <td class="val">${prlPrice}</td>
        <td class="val">${maxPrice}</td>
        <td class="val red">${r.cost_killed || 0}</td>
        <td class="val red">${r.perf_killed || 0}</td>
        <td class="val yellow">${r.perf_skipped_warming || 0}</td>
        <td class="val green">${r.deploys_succeeded || 0}</td>
        <td class="val red">${r.deploys_failed || 0}</td>
        <td>${instances}</td>
        <td>${dryRun}</td>
      </tr>`;
  }).join(''));
}

// --- Earnings Timeline ---

const refreshEarningsTimeline = cached('earnings-timeline',
  () => window.api.getEarningsLog({ limit: 2880 }), // 24h at 30s intervals
  (data) => renderEarningsTimeline(data),
  30000
);

function renderEarningsTimeline(records) {
  const barsEl = document.getElementById('earnings-timeline-bars');
  const axisEl = document.getElementById('earnings-timeline-axis');

  if (!records || !records.length) {
    setHtml(barsEl, '<div style="color:var(--text-dim);padding:40px;text-align:center">No earnings data recorded yet</div>');
    if (axisEl) setHtml(axisEl, '');
    return;
  }

  // Aggregate by 5-minute buckets for display
  const buckets = [];
  const bucketMs = 5 * 60 * 1000; // 5 minutes
  let currentBucket = null;

  for (const r of records) {
    const epoch = r.epoch_ms || (r.ts ? new Date(r.ts).getTime() : 0);
    if (!epoch) continue;
    const bucketKey = Math.floor(epoch / bucketMs) * bucketMs;

    if (!currentBucket || currentBucket.key !== bucketKey) {
      if (currentBucket) buckets.push(currentBucket);
      currentBucket = {
        key: bucketKey,
        time: new Date(bucketKey),
        earnings: 0,
        cost: 0,
        net: 0,
        count: 0,
      };
    }
    currentBucket.earnings += (r.earnings_usd_hr || 0);
    currentBucket.cost += (r.rental_cost_hr || 0);
    currentBucket.net += (r.net_profit_hr || 0);
    currentBucket.count++;
  }
  if (currentBucket && currentBucket.count > 0) buckets.push(currentBucket);

  // Average per bucket
  for (const b of buckets) {
    if (b.count > 1) {
      b.earnings /= b.count;
      b.cost /= b.count;
      b.net /= b.count;
    }
  }

  // Take last 72 buckets (6 hours of 5-min buckets)
  const displayBuckets = buckets.slice(-72);

  if (!displayBuckets.length) {
    setHtml(barsEl, '<div style="color:var(--text-dim);padding:40px;text-align:center">No earnings data available</div>');
    if (axisEl) setHtml(axisEl, '');
    return;
  }

  // Find max value for scaling
  const maxVal = Math.max(
    ...displayBuckets.map(b => Math.max(b.earnings, b.cost, Math.abs(b.net))),
    0.001
  );

  // Generate bar chart
  const barWidth = Math.max(6, Math.floor(100 / displayBuckets.length) - 1);

  setHtml(barsEl, displayBuckets.map((b, i) => {
    const earningsH = (b.earnings / maxVal * 100).toFixed(1);
    const costH = (b.cost / maxVal * 100).toFixed(1);
    const net = b.net;
    const netColor = net >= 0 ? 'var(--accent)' : 'var(--red)';
    const netH = (Math.abs(net) / maxVal * 100).toFixed(1);
    const timeLabel = b.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    return `
      <div class="timeline-bar-group" style="flex:0 0 ${barWidth}px" title="${timeLabel}: Earn $${b.earnings.toFixed(4)}/hr, Cost $${b.cost.toFixed(4)}/hr, Net $${net.toFixed(6)}/hr">
        <div class="timeline-bar timeline-bar-earnings" style="height:${earningsH}%"></div>
        <div class="timeline-bar timeline-bar-cost" style="height:${costH}%"></div>
        <div class="timeline-bar timeline-bar-net" style="height:${netH}%;background:${netColor}"></div>
      </div>`;
  }).join(''));

  // Axis labels
  if (displayBuckets.length > 0) {
    const firstTime = displayBuckets[0].time;
    const lastTime = displayBuckets[displayBuckets.length - 1].time;
    const midTime = displayBuckets[Math.floor(displayBuckets.length / 2)].time;
    setHtml(axisEl, `
      <span>${firstTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      <span>${midTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      <span>${lastTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
    `);
  }
}

// --- Log Viewer ---

function refreshLogViewer(force = false) {
  if (!force && !isVisibleTab('records') && activeRecordsView !== 'log-viewer') return;
  return singleFlight('log-viewer', async () => {
    const typeSelect = document.getElementById('log-viewer-type');
    const limitSelect = document.getElementById('log-viewer-limit');
    const outputEl = document.getElementById('log-viewer-output');

    const logType = typeSelect?.value || 'kill_decisions.jsonl';
    const limit = parseInt(limitSelect?.value || '100');

    if (outputEl) {
      setHtml(outputEl, '<div style="color:var(--text-dim)">Loading...</div>');
    }

    try {
      const data = await window.api.readJsonlRaw(logType, limit);
      renderLogViewer(data, logType);
    } catch (e) {
      if (outputEl) {
        setHtml(outputEl, `<div style="color:var(--red)">Error: ${escapeHtml(String(e))}</div>`);
      }
    }
  });
}

function renderLogViewer(records, logType) {
  const outputEl = document.getElementById('log-viewer-output');
  if (!outputEl) return;

  if (!records || !records.length) {
    setHtml(outputEl, '<div style="color:var(--text-dim);padding:20px;text-align:center">No records found</div>');
    return;
  }

  // Format each record as a collapsible entry
  const lines = records.map((r, i) => {
    const ts = r.ts ? new Date(r.ts).toLocaleString() : '—';
    const json = JSON.stringify(r, null, 2);
    const preview = summarizeRecord(r, logType);

    return `<details class="log-entry-detail" style="margin-bottom:2px">
      <summary style="cursor:pointer;padding:3px 0;color:var(--accent)">
        <span style="color:var(--text-dim)">#${records.length - i}</span>
        <span style="color:var(--text-dim);margin-left:8px">${ts}</span>
        <span style="color:var(--text);margin-left:8px">${escapeHtml(preview)}</span>
      </summary>
      <pre style="background:var(--bg);padding:8px;margin:4px 0;border-radius:3px;overflow-x:auto;font-size:11px;color:var(--text)">${escapeHtml(json)}</pre>
    </details>`;
  }).join('');

  setHtml(outputEl, lines);
}

function summarizeRecord(r, logType) {
  if (logType.includes('kill_decisions')) {
    return `[${r.reason_type || '?'}] ${r.gpu_model || '?'} h1=${r.h1_th != null ? r.h1_th.toFixed(1) : '?'} min=${r.min_th_conf || r.min_th_calc || '?'} executed=${r.executed}`;
  }
  if (logType.includes('cycle_log')) {
    return `kills: cost=${r.cost_killed || 0} perf=${r.perf_killed || 0} | deploys: ${r.deploys_succeeded || 0} OK / ${r.deploys_failed || 0} fail | PRL=$${r.prl_price || '?'}`;
  }
  if (logType.includes('earnings_log')) {
    return `${r.instance_id || '?'} earnings=$${(r.earnings_usd_hr || 0).toFixed(4)}/hr cost=$${(r.rental_cost_hr || 0).toFixed(4)}/hr net=$${(r.net_profit_hr || 0).toFixed(6)}/hr h1=${r.h1_th != null ? r.h1_th.toFixed(1) : '?'}`;
  }
  if (logType.includes('worker_snapshots')) {
    return `${r.worker_name || '?'} online=${r.online} live=${r.live_th != null ? r.live_th.toFixed(1) : '?'} h1=${r.h1_th != null ? r.h1_th.toFixed(1) : '?'}`;
  }
  if (logType.includes('instance_snapshots')) {
    return `${r.instance_id || '?'} ${r.status || '?'} ${r.gpu_name || '?'} x${r.num_gpus || 1} $${(r.dph_total || 0).toFixed(4)}/hr`;
  }
  if (logType.includes('config_log')) {
    return `changed: [${(r.changed_keys || []).join(', ')}] trigger=${r.trigger || '?'}`;
  }
  return JSON.stringify(r).substring(0, 100);
}

// --- CSV Export ---

async function handleExportCSV() {
  const btn = document.getElementById('export-csv-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Exporting...';
  }

  try {
    const csv = await window.api.exportHistoryCSV();
    // Trigger download via a Blob
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mining-sessions-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error('CSV export failed:', e);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⬇ Export CSV';
    }
  }
}

// ============ HELPERS ============

function esc(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(str ?? '').replace(/[&<>"']/g, c => map[c]);
}

function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function formatDuration(hours) {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleString();
}

// ============ AUTODEPLOY ============

function initAutodeploy() {
  // Deploy Now button
  const deployNowBtn = document.getElementById('deploy-now-btn');
  if (deployNowBtn) {
    deployNowBtn.addEventListener('click', async () => {
      deployNowBtn.disabled = true;
      deployNowBtn.textContent = 'Deploying...';

      const statusOutput = document.getElementById('status-output');
      if (statusOutput) {
        appendLog(statusOutput, '<div style="color:var(--text-dim)">Deploying...</div>');
      }

      try {
        const result = await window.api.deployNow();
        if (statusOutput) {
          const timestamp = new Date().toLocaleTimeString();
          appendLog(statusOutput, `
            <div style="margin-bottom:4px;color:var(--text-dim)">[${timestamp}]</div>
            <pre style="white-space:pre-wrap;margin:0">${escapeHtml(result)}</pre>
          `);
        }
      } catch (e) {
        console.error('Deploy failed:', e);
      } finally {
        deployNowBtn.disabled = false;
        deployNowBtn.textContent = 'Deploy Now';
        refreshStatus();
        refreshBlacklist();
      }
    });
  }

  // Refresh Log button
  const refreshLogBtn = document.getElementById('refresh-log-btn');
  if (refreshLogBtn) {
    refreshLogBtn.addEventListener('click', () => refreshDeployLog(true));
  }

  // Add to Blacklist button
  const addBlacklistBtn = document.getElementById('add-blacklist-btn');
  if (addBlacklistBtn) {
    addBlacklistBtn.addEventListener('click', async () => {
      const input = document.getElementById('blacklist-input');
      if (!input || !input.value.trim()) return;

      const entry = input.value.trim();
      const success = await window.api.addToBlacklist(entry);
      if (success) {
        input.value = '';
        refreshBlacklist();
      } else {
        alert('Failed to add to blacklist');
      }
    });
  }

  // Refresh Audit Log button
  const refreshAuditBtn = document.getElementById('refresh-audit-btn');
  if (refreshAuditBtn) {
    refreshAuditBtn.addEventListener('click', () => refreshAuditLog(true));
  }
}

async function refreshAutodeploy(force = false) {
  return Promise.all([
    refreshStatus(force),
    refreshDeployLog(force),
    refreshBlacklist(force),
    refreshAuditLog(force),
  ]);
}

async function refreshStatus(force = false) {
  return singleFlight('status', async () => {
    try {
      const statusOutput = document.getElementById('status-output');
      const statusSpan = document.getElementById('autodeploy-status');

      const result = await window.api.getStatus();
      if (statusOutput) {
        setScrollableText(statusOutput, result || 'No status');
      }
      if (statusSpan) {
        const lines = result.split('\n').filter(l => l.includes('✅') || l.includes('❌'));
        const running = lines.filter(l => l.includes('✅')).length;
        const failed = lines.filter(l => l.includes('❌')).length;
        setText(statusSpan, `${running} running, ${failed} failed`);
      }
    } catch (e) {
      console.error('Failed to refresh status:', e);
    }
  });
}

async function refreshDeployLog(force = false) {
  if (!force && !isVisibleTab('autodeploy')) return;
  return singleFlight('deploy-log', async () => {
    try {
      const logOutput = document.getElementById('deploy-log');
      const log = await window.api.getDeployLog();
      if (logOutput) {
        setScrollableText(logOutput, log || 'No log available', true);
      }
    } catch (e) {
      console.error('Failed to refresh log:', e);
    }
  });
}

async function refreshBlacklist(force = false) {
  return singleFlight('blacklist', async () => {
    try {
      const blacklistOutput = document.getElementById('blacklist-output');
      const blacklist = await window.api.getBlacklist();
      if (blacklistOutput) {
        setScrollableText(blacklistOutput, blacklist || 'Blacklist empty');
      }
    } catch (e) {
      console.error('Failed to refresh blacklist:', e);
    }
  });
}

async function refreshAuditLog(force = false) {
  if (!force && !isVisibleTab('autodeploy')) return;
  return singleFlight('audit-log', async () => {
    try {
      const auditOutput = document.getElementById('audit-log-output');
      const events = await window.api.getAuditLog({ limit: 50 });
      if (auditOutput) {
        if (!events || events.length === 0) {
          setText(auditOutput, 'No audit events recorded yet.');
          return;
        }
        const lines = events.map(e => {
          const icons = {
            deploy_start: '🚀', deploy_success: '✅', deploy_fail: '❌',
            kill_start: '💀', kill_success: '🔥', kill_skip: '⏭️',
            cycle_start: '🔄', cycle_end: '🏁', config_change: '⚙️',
            protection_skip: '🛡️', rate_limit_skip: '⏳', dry_run: '🔍',
            lock_timeout: '🔒',
          };
          const icon = icons[e.event] || '📌';
          return `${e.ts} ${icon} ${e.event.padEnd(18)} ${e.instance_id ? '#' + e.instance_id + ' ' : ''}${e.details || ''}`;
        }).join('\n');
        setScrollableText(auditOutput, lines, false);
      }
    } catch (e) {
      console.error('Failed to refresh audit log:', e);
    }
  });
}

// ============ INSTANCES ============

let deployingInstances = new Set();

function initInstances() {
  const refreshBtn = document.getElementById('refresh-instances-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => refreshInstances(true));
  }
}

async function refreshInstances(force = false) {
  if (!force && !isVisibleTab('instances')) return cache.instances?.data;
  const refreshBtn = document.getElementById('refresh-instances-btn');
  if (refreshBtn && force) {
    refreshBtn.disabled = true;
    setText(refreshBtn, 'Refreshing...');
  }
  return singleFlight('instances', async () => {
    try {
      const instances = await window.api.listInstances(force);
      cache.instances = { time: Date.now(), data: instances || [] };
      renderInstances(instances || []);
      window.api.refreshInstanceHealth(force);
      return instances;
    } catch (e) {
      console.error('Failed to refresh instances:', e);
      return cache.instances?.data;
    } finally {
      if (refreshBtn && force) {
        refreshBtn.disabled = false;
        setText(refreshBtn, 'Refresh');
      }
    }
  });
}

function renderInstances(instances) {
  const tbody = document.getElementById('instances-body');
  const countEl = document.getElementById('instances-count');
  instances = Array.isArray(instances) ? instances : [];
  if (countEl) {
    const running = instances.filter(inst => inst.status === 'running').length;
    const healthy = instances.filter(inst => inst.health === 'healthy').length;
    const unhealthy = instances.filter(inst => inst.health === 'unhealthy').length;
    const degraded = instances.filter(inst => inst.health === 'degraded').length;
    const checking = instances.filter(inst => inst.health === 'checking').length;
    setText(countEl, instances.length > 0
      ? `${running}/${instances.length} running · ${healthy} healthy · ${degraded} degraded · ${unhealthy} issues${checking ? ` · ${checking} checking` : ''}`
      : '');
  }

  // ── Bid tier summary ──
  const summaryEl = document.getElementById('bid-summary');
  if (summaryEl) {
    const prlPrice = window._prlPrice || 0.80;
    const bidInsts = instances.filter(i => i.is_bid && i.status === 'running');
    let safe = 0, watch = 0, nochase = 0, loss = 0;
    for (const inst of bidInsts) {
      const hasHashrate = inst.pool_hashrate > 0;
      const profitHr = hasHashrate ? (inst.pool_hashrate / 1000) * 3.226 * prlPrice : 0;
      const marginHr = hasHashrate ? profitHr - inst.price : -inst.price;
      if (marginHr > 0.10) safe++;
      else if (marginHr > 0.03) watch++;
      else if (marginHr > 0) nochase++;
      else loss++;
    }
    const parts = [];
    if (safe) parts.push(`<span style="color:#4caf50">${safe} SAFE</span>`);
    if (watch) parts.push(`<span style="color:#e6a817">${watch} WATCH</span>`);
    if (nochase) parts.push(`<span style="color:#ff9800">${nochase} NO$</span>`);
    if (loss) parts.push(`<span style="color:#f44336">${loss} LOSS</span>`);
    summaryEl.innerHTML = bidInsts.length > 0
      ? `Bid: ${parts.join(' · ')}`
      : '';
  }

  if (!instances.length) {
    setHtml(tbody, '<tr><td colspan="13" class="loading">No instances</td></tr>');
    return;
  }

  const changed = setHtml(tbody, instances.map(inst => {
    const isDeploying = deployingInstances.has(inst.id);
    const state = isDeploying ? 'deploying' : inst.health;
    const stateLabels = {
      healthy: 'HEALTHY',
      unhealthy: 'ISSUE',
      degraded: 'DEGRADED',
      pending: 'PENDING',
      checking: 'CHECKING',
      deploying: 'DEPLOYING',
      unavailable: String(inst.status || 'UNAVAILABLE').toUpperCase(),
    };
    const canDeploy = inst.status === 'running' && !isDeploying;
    const btnDisabled = canDeploy ? '' : 'disabled';
    const btnText = isDeploying ? 'Deploying...' : ['healthy', 'checking'].includes(inst.health) ? 'Redeploy' : 'Deploy';
    const vram = inst.vram_total_mb > 0
      ? `${(inst.vram_used_mb / 1024).toFixed(1)}/${(inst.vram_total_mb / 1024).toFixed(1)} GB`
      : '—';
    const gpuLoadClass = inst.gpu_util >= 85 ? 'green' : inst.gpu_util > 0 ? 'red' : '';
    const issue = isDeploying ? 'Deployment in progress' : inst.issue;

    // Profit/Margin: earnings = (pool_hashrate / 1000) * EARN_RATE * PRL_PRICE
    const prlPrice = window._prlPrice || 0.80;
    const hasHashrate = inst.pool_hashrate > 0;
    const profitHr = hasHashrate ? (inst.pool_hashrate / 1000) * 3.226 * prlPrice : 0;
    const marginHr = hasHashrate ? profitHr - inst.price : -inst.price;
    const marginClass = marginHr >= 0 ? 'green' : 'red';

    // ── Bid tier badge for interruptible instances ──
    let bidCell = '—';
    if (inst.is_bid) {
      const safeMargin = 0.10;
      const watchMargin = 0.03;
      let tier, tierClass;
      if (marginHr > safeMargin) { tier = 'SAFE'; tierClass = 'green'; }
      else if (marginHr > watchMargin) { tier = 'WATCH'; tierClass = '#e6a817'; }
      else if (marginHr > 0) { tier = 'NO$'; tierClass = 'orange'; }
      else { tier = 'LOSS'; tierClass = 'red'; }

      const dlperf = inst.dlperf_per_dphtotal || 0;
      const dlperfTag = dlperf >= 400 ? '<span style="color:#4caf50">★</span>'
        : dlperf >= 350 ? '<span style="color:#8bc34a">●</span>'
        : dlperf >= 300 ? '<span style="color:#ff9800">●</span>'
        : dlperf > 0 ? '<span style="color:#f44336">✕</span>' : '';

      bidCell = `<span class="badge" style="background:${tierClass};color:#fff;font-size:10px">${tier}</span> `
        + `<span style="font-size:10px;color:var(--text-muted)">$${(inst.min_bid || inst.price).toFixed(4)}/h</span>`
        + (dlperfTag ? ` ${dlperfTag}` : '');
    }

    return `
      <tr>
        <td style="font-family:monospace">${esc(inst.id)}</td>
        <td>${esc(inst.gpu_name)} ×${inst.num_gpus}</td>
        <td><span class="badge badge-${state}">${esc(stateLabels[state] || state)}</span></td>
        <td class="val ${gpuLoadClass}">${inst.status === 'running' && inst.gpu_util > 0 ? `${inst.gpu_util}%` : '—'}</td>
        <td>${vram}</td>
        <td class="val">${inst.local_hashrate > 0 ? inst.local_hashrate.toFixed(1) : '—'}</td>
        <td class="val">${inst.pool_hashrate == null ? 'API unavailable' : inst.pool_hashrate > 0 ? inst.pool_hashrate.toFixed(1) : '—'}</td>
        <td class="val green">${hasHashrate ? '$' + profitHr.toFixed(6) : '—'}</td>
        <td class="val ${marginClass}">${hasHashrate ? '$' + marginHr.toFixed(6) : '—'}</td>
        <td class="val red">$${inst.price.toFixed(4)}</td>
        <td style="font-size:11px">${bidCell}</td>
        <td class="${state === 'unhealthy' ? 'red' : ''}" title="${esc(issue)}">${esc(issue)}</td>
        <td>
          <button class="btn btn-primary btn-sm deploy-instance-btn"
                  data-instance-id="${esc(inst.id)}"
                  ${btnDisabled}>${btnText}</button>
          <button class="btn btn-danger btn-sm kill-instance-btn"
                  data-instance-id="${esc(inst.id)}"
                  data-instance-gpu="${esc(inst.gpu_name)}"
                  ${inst.status === 'running' ? '' : 'disabled'}>Kill</button>
        </td>
      </tr>`;
  }).join(''));
  if (!changed) return;

  // Wire up deploy buttons
  tbody.querySelectorAll('.deploy-instance-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const instanceId = btn.dataset.instanceId;
      if (!instanceId || deployingInstances.has(instanceId)) return;

      deployingInstances.add(instanceId);
      btn.disabled = true;
      btn.textContent = 'Deploying...';

      try {
        await window.api.deployToInstance(instanceId);
      } catch (e) {
        deployingInstances.delete(instanceId);
        console.error('Deploy failed:', e);
      }

      refreshInstances(true);
    });
  });

  // Wire up kill buttons
  tbody.querySelectorAll('.kill-instance-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const instanceId = btn.dataset.instanceId;
      const gpuName = btn.dataset.instanceGpu || '';
      if (!instanceId) return;

      const reason = prompt(
        `Destroy instance ${instanceId} (${gpuName})?\n\nReason (optional):`,
        ''
      );
      if (reason === null) return; // user cancelled

      btn.disabled = true;
      btn.textContent = 'Killing...';

      try {
        const result = await window.api.killInstance(instanceId, reason);
        console.log('Kill result:', result);
      } catch (e) {
        console.error('Kill failed:', e);
      }

      btn.disabled = false;
      btn.textContent = 'Kill';
      refreshInstances(true);
    });
  });
}

// ============ CONFIG ============

const numericConfigFields = new Set([
  'prl_price', 'earn_rate', 'electricity_price_usd_kwh', 'owned_total_watts',
  'vast_max_price', 'vastai_disk_gb',
  // GPU hashrate thresholds
  'min_th_5090', 'min_th_5080', 'min_th_5070_ti', 'min_th_5070',
  'min_th_4090', 'min_th_4080_super', 'min_th_4080',
  'min_th_4070_ti_super', 'min_th_4070_ti', 'min_th_4070_super', 'min_th_4070',
  'min_th_4060_ti', 'min_th_4060',
  'min_th_3090_ti', 'min_th_3090', 'min_th_3080_ti', 'min_th_3080',
  'min_th_3070_ti', 'min_th_3070', 'min_th_3060_ti', 'min_th_3060',
  'min_th_h100', 'min_th_h200', 'min_th_b200',
  'min_th_a100', 'min_th_a6000', 'min_th_a5000', 'min_th_a4000',
  'min_th_l40s', 'min_th_l40',
  'kill_threshold_gpu_count', 'vast_search_min_gpus',
  'autodeploy_interval_sec', 'max_destroys_per_hour',
  'consecutive_failures_before_destroy', 'new_instance_protection_minutes',
  'th_per_dollar_hr_threshold',
  // Dynamic bidding
  'bid_cooldown_sec', 'bid_min_margin_hr', 'bid_safe_margin_hr',
  'bid_watch_margin_hr', 'bid_raise_max_pct', 'bid_lower_pct',
  'bid_min_adjustment_usd', 'bid_consecutive_before_adjust',
  'bid_consecutive_before_lower',
  'reject_dlperf_per_dollar', 'min_dlperf_per_dollar', 'preferred_dlperf_per_dollar',
]);

function initConfig() {
  const form = document.getElementById('config-form');
  if (!form) return;
  form.addEventListener('input', () => { configDirty = true; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = document.getElementById('config-save-btn');
    const status = document.getElementById('config-status');
    button.disabled = true;
    setText(button, 'Saving...');
    setText(status, 'Saving configuration...');

    const updates = {};
    for (const input of form.elements) {
      if (!input.name) continue;
      if (input.name === 'whitelist_regions') {
        updates[input.name] = input.value.split(',').map(s => s.trim()).filter(Boolean);
        continue;
      }
      if (input.type === 'checkbox') {
        updates[input.name] = input.checked;
      } else if (numericConfigFields.has(input.name)) {
        updates[input.name] = input.value === '' ? null : Number(input.value);
      } else {
        updates[input.name] = input.value.trim();
      }
    }

    try {
      await window.api.saveConfig(updates);
      configDirty = false;
      setText(status, 'Saved. New settings are active.');
      refreshDashboard(true);
    } catch (error) {
      setText(status, `Save failed: ${error.message}`);
    } finally {
      button.disabled = false;
      setText(button, 'Save Configuration');
    }
  });
}

async function refreshConfig() {
  if (configDirty) return;
  return singleFlight('config', async () => {
    const form = document.getElementById('config-form');
    const status = document.getElementById('config-status');
    if (!form) return;
    try {
      const config = await window.api.getConfig();
      for (const input of form.elements) {
        if (!input.name || !Object.prototype.hasOwnProperty.call(config, input.name)) continue;
        if (input.name === 'whitelist_regions') {
          const val = config[input.name];
          input.value = Array.isArray(val) ? val.join(', ') : (val ?? '');
          continue;
        }
        if (input.type === 'checkbox') input.checked = Boolean(config[input.name]);
        else input.value = config[input.name] ?? '';
      }
      setText(status, 'Configuration loaded.');
    } catch (error) {
      setText(status, `Load failed: ${error.message}`);
    }
  });
}
