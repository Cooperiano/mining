const pool = require('./pool');
const vast = require('./vast');
const store = require('./session-store');
const price = require('./price');

const EARN_RATE = 3.226;

function earningsPerHour(th_s, prlPrice) {
  return (th_s / 1000) * EARN_RATE * (prlPrice || 0.80);
}

function breakEvenTH(costPerHour, prlPrice) {
  if (!prlPrice || prlPrice <= 0) return Infinity;
  return (costPerHour / prlPrice) * 1000 / EARN_RATE;
}

async function profitabilitySnapshot() {
  const data = await pool.getDashboardData();
  if (data.error) return data;

  const priceData = await price.getCurrentPrice();
  const currentPrlPrice = priceData.price;

  const sessions = store.getActiveSessions();
  const allSessions = store.getAllSessions();

  // Calculate electricity cost for owned workers
  const config = store.loadConfig();
  const elecPrice = config.electricity_price_usd_kwh || 0.122;
  const totalWatts = config.owned_total_watts || 500;
  const ownedElectricityHr = (totalWatts / 1000) * elecPrice;

  // Baseline electricity: always-on owned hardware since start date
  const miningStart = new Date('2026-05-31T12:25:00+08:00').getTime();
  const baselineHours = Math.max(0, (Date.now() - miningStart) / 3600000);
  const baselineElecCost = ownedElectricityHr * baselineHours;

  // Aggregate rental cost: sum dph_total of all running instances from vast.ai
  let activeRentalCostHr = 0;
  try {
    const { instances } = await vast.listInstances();
    activeRentalCostHr = instances
      .filter(i => i.status === 'running')
      .reduce((acc, i) => acc + (i.price || 0), 0);
  } catch (_) {}

  // Vast billed total
  let vastBilledTotal = 0;
  try {
    const billing = await vast.getBillingTotal();
    if (billing > 0) {
      vastBilledTotal = billing;
    }
  } catch (_) {}

  const now = Date.now();
  let electricityTotalCost = baselineElecCost;

  // Fallback if API didn't return data: manual calculation from sessions
  if (vastBilledTotal <= 0) {
    allSessions.forEach(s => {
      const end = s.ended_at ? new Date(s.ended_at).getTime() : now;
      const start = s.started_at ? new Date(s.started_at).getTime() : null;
      const hours = start ? Math.max(0, (end - start) / 3600000) : 0;
      vastBilledTotal += (s.rental_total_cost > 0 ? s.rental_total_cost : (s.rental_cost_per_hour || 0) * hours);
    });
  }

  // Always add running (unbilled) costs for active sessions
  // Active sessions haven't appeared in billing API yet
  allSessions.forEach(s => {
    if (s.status !== 'mining') return;
    const start = s.started_at ? new Date(s.started_at).getTime() : null;
    if (!start) return;
    const hours = Math.max(0, (now - start) / 3600000);
    // Subtract any already-counted rental_total_cost to avoid double-counting
    const unbilled = (s.rental_cost_per_hour || 0) * hours - (s.rental_total_cost || 0);
    if (unbilled > 0) vastBilledTotal += unbilled;
  });

  // Electricity from sessions
  allSessions.forEach(s => {
    const end = s.ended_at ? new Date(s.ended_at).getTime() : now;
    const start = s.started_at ? new Date(s.started_at).getTime() : null;
    const hours = start ? Math.max(0, (end - start) / 3600000) : 0;
    if (s.electricity_total_cost > 0) {
      electricityTotalCost += s.electricity_total_cost;
    } else {
      electricityTotalCost += (s.electricity_cost_per_hour || 0) * hours;
    }
  });

  const totalCostHr = activeRentalCostHr + ownedElectricityHr;
  const totalEarningsHr = earningsPerHour(data.total_live_th, currentPrlPrice);
  const netProfitHr = totalEarningsHr - totalCostHr;

  // Session-level detail
  const sessionDetails = sessions.map(s => {
    if (s.status !== 'mining') {
      return {
        id: s.id, status: s.status, workerName: s.worker_name,
        liveTh: 0, earnPerHr: 0, rentalCostHr: s.rental_cost_per_hour || 0,
        elecCostHr: s.electricity_cost_per_hour || 0, totalCostHr: s.total_cost_per_hour || 0,
        profitHr: -(s.total_cost_per_hour || 0),
      };
    }
    const miner = (data.workers || []).filter(w =>
      s.worker_name && w.name.includes(s.worker_name.split('-gpu')[0])
    );
    const sessionLive = miner.reduce((sum, w) => sum + w.live_th, 0);
    const earnHr = earningsPerHour(sessionLive, currentPrlPrice);
    const rentalHr = s.rental_cost_per_hour || 0;
    const elecHr = s.electricity_cost_per_hour || 0;
    return {
      id: s.id,
      status: s.status,
      workerName: s.worker_name,
      liveTh: sessionLive,
      earnPerHr: parseFloat(earnHr.toFixed(6)),
      rentalCostHr: parseFloat(rentalHr.toFixed(6)),
      elecCostHr: parseFloat(elecHr.toFixed(6)),
      totalCostHr: parseFloat((rentalHr + elecHr).toFixed(6)),
      profitHr: parseFloat((earnHr - rentalHr - elecHr).toFixed(6)),
    };
  });

  // Add owned workers (not tracked as sessions)
  const ownedWorkers = (data.workers || []).filter(w => {
    const n = w.name;
    return n === 'miner1' || n.includes('miner2') || n === 'miner3';
  });
  if (ownedWorkers.length > 0) {
    const elecHr = ownedElectricityHr;
    const ownedLive = ownedWorkers.reduce((s, w) => s + w.live_th, 0);
    const earnHr = earningsPerHour(ownedLive, currentPrlPrice);
    sessionDetails.push({
      id: 'owned',
      status: 'owned',
      workerName: ownedWorkers.length + ' owned GPUs',
      liveTh: ownedLive,
      earnPerHr: parseFloat(earnHr.toFixed(6)),
      rentalCostHr: 0,
      elecCostHr: parseFloat(elecHr.toFixed(6)),
      totalCostHr: parseFloat(elecHr.toFixed(6)),
      profitHr: parseFloat((earnHr - elecHr).toFixed(6)),
    });
  }

  return {
    balance: data.balance,
    paid: data.paid,
    prlPrice: currentPrlPrice,
    priceSource: priceData.source,
    earningsPerHr: parseFloat(totalEarningsHr.toFixed(6)),
    rentalCostHr: parseFloat(activeRentalCostHr.toFixed(6)),
    electricityCostHr: parseFloat(ownedElectricityHr.toFixed(6)),
    vastBilledTotal: parseFloat(vastBilledTotal.toFixed(6)),
    electricityTotalCost: parseFloat(electricityTotalCost.toFixed(6)),
    totalCostHr: parseFloat(totalCostHr.toFixed(6)),
    netProfitHr: parseFloat((totalEarningsHr - totalCostHr).toFixed(6)),
    activeSessions: sessionDetails,
    total_live_th: data.total_live_th,
  };
}

/**
 * Record earnings tick for all active sessions. Called every 30 seconds.
 * Writes to earnings_log.jsonl and updates session cumulative earnings/cost.
 */
async function recordEarningsForActiveSessions() {
  try {
    const data = await pool.getDashboardData();
    if (data.error) return;

    const priceData = await price.getCurrentPrice();
    const prlPrice = priceData.price;
    const sessions = store.getActiveSessions();

    for (const s of sessions) {
      if (s.status !== 'mining') continue;

      // Find matching pool worker(s) by worker name
      const workerName = s.worker_name || '';
      const workerBase = workerName.includes('-gpu') ? workerName.split('-gpu')[0] : workerName;
      const miners = (data.workers || []).filter(w =>
        workerBase && w.name.includes(workerBase)
      );

      let liveTh = 0;
      let h1Th = 0;
      if (miners.length > 0) {
        liveTh = miners.reduce((sum, w) => sum + (w.live_th || 0), 0);
        h1Th = miners.reduce((sum, w) => sum + (w.h1_th || 0), 0);
      } else if (s.avg_hashrate) {
        // No pool data for this worker — use session avg
        liveTh = s.avg_hashrate;
        h1Th = s.avg_hashrate;
      } else {
        continue; // No data at all
      }

      const earnHr = earningsPerHour(liveTh, prlPrice);
      const rentalHr = s.rental_cost_per_hour || 0;
      const elecHr = s.electricity_cost_per_hour || 0;
      const netProfitHr = earnHr - rentalHr - elecHr;

      store.recordEarning({
        instance_id: s.instance_id,
        session_id: s.id,
        live_th: liveTh,
        h1_th: h1Th,
        prl_price: prlPrice,
        earnings_usd_hr: earnHr,
        rental_cost_hr: rentalHr,
        net_profit_hr: netProfitHr,
      });
    }
  } catch (_) {
    // Silently ignore — don't let earnings recording break dashboard polling
  }
}

module.exports = {
  earningsPerHour,
  breakEvenTH,
  profitabilitySnapshot,
  recordEarningsForActiveSessions,
};
