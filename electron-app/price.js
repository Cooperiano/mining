const https = require('https');
const http = require('http');
const store = require('./session-store');

const cacheFile = () => store.stateFile('price_cache.json');

const SOURCES = [
  {
    name: 'SafeTrade',
    fetch: async () => {
      // Try multiple SafeTrade API endpoints
      for (const url of [
        'https://api.safetrade.com/api/v2/tickers/prlusdt',
        'https://api.safetrade.com/api/v2/ticker?market=PRL-USDT&type=basic',
        'https://safetrade.com/api/v2/tickers/PRL-USDT',
      ]) {
        const d = await fetchJSON(url, 5000);
        if (d) {
          // Handle array response: [ { ticker: { last: '0.21' } } ]
          if (Array.isArray(d) && d[0]?.ticker?.last) return parseFloat(d[0].ticker.last);
          // Handle object response: { ticker: { last: '0.21' } }
          if (d.ticker?.last) return parseFloat(d.ticker.last);
          // Handle direct: { last: '0.21' }
          if (d.last) return parseFloat(d.last);
          // Handle v2 format
          if (Array.isArray(d) && d[0]?.last) return parseFloat(d[0].last);
        }
      }
      return null;
    },
  },
  {
    name: 'Gate.io',
    fetch: () => fetchJSON('https://api.gateio.ws/api/v4/spot/tickers?currency_pair=PRL_USDT', 5000)
      .then(d => (d && Array.isArray(d) && d[0]?.last) ? parseFloat(d[0].last) : null),
  },
  {
    name: 'MEXC',
    fetch: () => fetchJSON('https://api.mexc.com/api/v3/ticker/price?symbol=PRLUSDT', 5000)
      .then(d => (d && d.price) ? parseFloat(d.price) : null),
  },
  {
    name: 'CoinGecko',
    fetch: async () => {
      for (const id of ['pearl-2', 'pearl-coin', 'pearl', 'prl']) {
        const d = await fetchJSON(`https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd`, 5000);
        if (d && d[id]?.usd > 0) return d[id].usd;
      }
      return null;
    },
  },
];

function fetchJSON(url, timeout = 5000) {
  return new Promise((resolve) => {
    const client = url.startsWith('https') ? https : http;
    const req = client.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => { try { resolve(JSON.parse(data)); } catch (_) { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

// Attempt to fetch from exchanges, returns {price, source} or null
async function tryFetchFromExchanges() {
  for (const source of SOURCES) {
    const price = await source.fetch();
    if (price && price > 0) {
      try { require('fs').writeFileSync(cacheFile(), JSON.stringify({ price, source: source.name, updated: Date.now() })); } catch (_) {}
      return { price, source: source.name };
    }
  }
  return null;
}

// Get price: manual config first, then cached exchanges, then config default
async function getCurrentPrice() {
  const config = store.loadConfig();
  const manual = config.prl_price;

  // 1. Manual config (user-set, most authoritative)
  if (manual && manual > 0) {
    // Still try to fetch in background to show comparison
    return { price: manual, source: 'manual config', manual: true };
  }

  // 2. Cached exchange price (less than 1 hour old)
  try {
    const fs = require('fs');
    if (fs.existsSync(cacheFile())) {
      const cache = JSON.parse(fs.readFileSync(cacheFile(), 'utf8'));
      const age = (Date.now() - cache.updated) / 1000;
      if (cache.price > 0 && age < 3600) {
        return { price: cache.price, source: cache.source + ' (cached)', manual: false };
      }
    }
  } catch (_) {}

  // 3. Try exchanges
  const live = await tryFetchFromExchanges();
  if (live) return { ...live, manual: false };

  // 4. Stale cache
  try {
    const fs = require('fs');
    if (fs.existsSync(cacheFile())) {
      const cache = JSON.parse(fs.readFileSync(cacheFile(), 'utf8'));
      if (cache.price > 0) return { price: cache.price, source: cache.source + ' (stale)', manual: false };
    }
  } catch (_) {}

  // 5. Default
  return { price: 0.21, source: 'default', manual: false };
}

// Force refresh: fetch from exchanges, update cache
async function refreshPrice() {
  const live = await tryFetchFromExchanges();
  if (live) return { ...live, manual: false };
  const config = store.loadConfig();
  return { price: config.prl_price || 0.21, source: 'config (fetch failed)', manual: false };
}

async function checkSessionProfitability(session) {
  if (!session || session.status !== 'mining') return { profitable: true, sessionId: session?.id };
  if (!session.rental_cost_per_hour || session.rental_cost_per_hour <= 0) {
    return { profitable: true, sessionId: session.id, reason: 'no rental cost (owned)' };
  }
  const { price } = await getCurrentPrice();
  const earnRate = session.earn_rate || 3.226;
  const avgTH = session.avg_hashrate || 300;
  const earningsPerHr = (avgTH / 1000) * earnRate * price;
  const costPerHr = session.rental_cost_per_hour;
  return {
    profitable: earningsPerHr > costPerHr,
    sessionId: session.id,
    prlPrice: price,
    earningsPerHr: parseFloat(earningsPerHr.toFixed(6)),
    costPerHr: parseFloat(costPerHr.toFixed(6)),
    margin: parseFloat(((earningsPerHr - costPerHr) / costPerHr * 100).toFixed(1)),
  };
}

module.exports = { getCurrentPrice, refreshPrice, checkSessionProfitability };
