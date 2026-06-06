const https = require('https');
const http = require('http');
const store = require('./session-store');
const responseCache = new Map();
const requests = new Map();

function fetchJSON(url) {
  return new Promise((resolve) => {
    const client = url.startsWith('https') ? https : http;
    const req = client.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout: 10000 }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(null);
        }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

function getApiUrl() {
  const config = store.loadConfig();
  return `${config.api_url}${config.wallet}`;
}

function cachedJSON(key, url, ttlMs) {
  const cached = responseCache.get(key);
  if (cached && Date.now() - cached.time < ttlMs) return Promise.resolve(cached.data);
  if (requests.has(key)) return requests.get(key);
  const request = fetchJSON(url)
    .then(data => {
      if (data) responseCache.set(key, { time: Date.now(), data });
      return data || cached?.data || null;
    })
    .finally(() => requests.delete(key));
  requests.set(key, request);
  return request;
}

async function fetchPoolData() {
  return cachedJSON('miner', getApiUrl(), 5000);
}

async function fetchPoolStats() {
  return cachedJSON('stats', 'https://pearl.alphapool.tech/api/stats', 60000);
}

async function getDashboardData() {
  const data = await fetchPoolData();
  if (!data) return { error: 'API unreachable' };

  const stats = await fetchPoolStats().catch(() => null);

  const config = store.loadConfig();
  const allWorkers = data.workers || [];
  const onlineWorkers = allWorkers.filter(w => w.online);
  const totalLive = onlineWorkers.reduce((sum, w) => {
    const val = parseFloat((w.hashrate_live || '0').split(' ')[0]);
    return sum + (isNaN(val) ? 0 : val);
  }, 0);

  const totalEarnings = totalLive / 1000 * config.earn_rate * config.prl_price;

  let estH1 = 0;
  let estH24 = 0;
  try {
    estH1 = parseFloat((data.estHash1h || '0').split(' ')[0]);
    estH24 = parseFloat((data.estHash24h || '0').split(' ')[0]);
  } catch (_) {}
  // Ratio for per-worker 24h estimation (proportional distribution)
  const ratio24h = estH1 > 0 ? estH24 / estH1 : 0;

  return {
    balance: parseFloat(data.balance_prl || 0),
    paid: parseFloat(data.total_paid_prl || 0),
    est_1h: estH1 || 0,
    est_24h: estH24 || 0,
    total_live_th: parseFloat(totalLive.toFixed(1)),
    earnings_per_hour: parseFloat(totalEarnings.toFixed(4)),
    worker_count: onlineWorkers.length,
    worker_total: allWorkers.length,
    prl_price: config.prl_price,
    pool_hashrate: stats?.pool?.hashrate || '',
    pool_workers: stats?.pool?.workers || 0,
    pool_blocks_24h: stats?.pool?.blocks24h || 0,
    workers: allWorkers.map(w => {
      const h1 = parseFloat((w.hashrate_1h || '0').split(' ')[0]) || 0;
      // AlphaPool has no per-worker hashrate_24h; estimate proportionally from pool totals
      const h24 = ratio24h > 0 ? h1 * ratio24h : 0;
      return {
        name: w.name,
        online: w.online,
        live_th: parseFloat((w.hashrate_live || '0').split(' ')[0]) || 0,
        h1_th: h1,
        h24_th: parseFloat(h24.toFixed(1)),
        difficulty: w.difficulty || 0,
      };
    }),
  };
}

function classifyWorker(name) {
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

module.exports = {
  fetchPoolData,
  fetchPoolStats,
  getDashboardData,
  classifyWorker,
  fetchJSON,
};
