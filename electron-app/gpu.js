function normalizeGpuType(type) {
  if (!type) return '';
  const s = String(type).replace(/\s+/g, '_').toUpperCase();
  return s;
}

function shortGpuName(gpuType) {
  const n = normalizeGpuType(gpuType);
  const m = n.match(/(\d+)/);
  return m ? m[1] : n.substring(0, 8);
}

function workerName(gpuType, gpuCount, instanceId) {
  const short = shortGpuName(gpuType || '');
  const suffix = String(instanceId || '').slice(-4);
  const count = gpuCount && gpuCount > 1 ? `x${gpuCount}` : '';
  return `${short}${count}-${suffix}`;
}

function getMinThreshold(gpuType, config) {
  const n = normalizeGpuType(gpuType);
  // Blackwell (50 series)
  if (n.includes('5090')) return config.min_th_5090 || 250;
  if (n.includes('5080')) return config.min_th_5080 || 130;
  if (n.includes('5070_TI') || n.includes('5070TI')) return config.min_th_5070_ti || 105;
  if (n.includes('5070')) return config.min_th_5070 || 70;
  // Ada Lovelace (40 series)
  if (n.includes('4090')) return config.min_th_4090 || 180;
  if (n.includes('4080_SUPER') || n.includes('4080SUPER')) return config.min_th_4080_super || 115;
  if (n.includes('4080')) return config.min_th_4080 || 110;
  if (n.includes('4070_TI_SUPER') || n.includes('4070TISUPER')) return config.min_th_4070_ti_super || 85;
  if (n.includes('4070_TI') || n.includes('4070TI')) return config.min_th_4070_ti || 80;
  if (n.includes('4070_SUPER') || n.includes('4070SUPER')) return config.min_th_4070_super || 75;
  if (n.includes('4070')) return config.min_th_4070 || 70;
  if (n.includes('4060_TI') || n.includes('4060TI')) return config.min_th_4060_ti || 48;
  if (n.includes('4060')) return config.min_th_4060 || 30;
  // Ampere (30 series)
  if (n.includes('3090_TI') || n.includes('3090TI')) return config.min_th_3090_ti || 85;
  if (n.includes('3090')) return config.min_th_3090 || 80;
  if (n.includes('3080_TI') || n.includes('3080TI')) return config.min_th_3080_ti || 70;
  if (n.includes('3080')) return config.min_th_3080 || 65;
  if (n.includes('3070_TI') || n.includes('3070TI')) return config.min_th_3070_ti || 55;
  if (n.includes('3070')) return config.min_th_3070 || 50;
  if (n.includes('3060_TI') || n.includes('3060TI')) return config.min_th_3060_ti || 45;
  if (n.includes('3060')) return config.min_th_3060 || 18;
  // Hopper / Blackwell datacenter
  if (n.includes('H200')) return config.min_th_h200 || 450;
  if (n.includes('H100')) return config.min_th_h100 || 430;
  if (n.includes('B200')) return config.min_th_b200 || 490;
  // Ampere datacenter
  if (n.includes('A100')) return config.min_th_a100 || 350;
  if (n.includes('A6000')) return config.min_th_a6000 || 140;
  if (n.includes('A5000')) return config.min_th_a5000 || 105;
  if (n.includes('A4000')) return config.min_th_a4000 || 70;
  // Ada datacenter
  if (n.includes('L40S')) return config.min_th_l40s || 125;
  if (n.includes('L40')) return config.min_th_l40 || 100;
  return config.min_th_fallback || 50;
}

function classifyWorker(name, gpuTypeHint) {
  if (!name) return { machine: '?', gpu: '?', power: '?' };

  if (name === 'miner1') return { machine: 'station', gpu: 'RTX 3080', power: '320W' };
  if (name.includes('miner2')) return { machine: 'lab1', gpu: '4060Ti', power: '160W' };
  if (name === 'miner3') return { machine: 'laptop', gpu: 'RTX 3060', power: '95W' };

  // Parse worker name: "{GPU}x{N}-{suffix}"
  const m = name.match(/^(\d+)(x(\d+))?-[a-f0-9]{4}/);
  const gpuNum = m ? m[1] : '';
  const gpuCount = m && m[3] ? m[3] : '';

  let gpu = gpuNum || name.substring(0, 8);
  let power = '?';
  const powerMap = {
    '5090': '575W', '5080': '360W', '5070Ti': '300W', '5070': '250W',
    '4090': '450W', '4080Super': '320W', '4080': '320W', '4070TiSuper': '285W',
    '4070Ti': '285W', '4070Super': '220W', '4070': '220W', '4060Ti': '160W', '4060': '115W',
    '3090Ti': '450W', '3090': '350W', '3080Ti': '350W', '3080': '320W',
    '3070Ti': '290W', '3070': '220W', '3060Ti': '200W', '3060': '170W',
    'A100': '400W', 'A6000': '300W', 'A5000': '230W', 'A4000': '140W',
    'H100': '700W', 'H200': '700W', 'B200': '1000W',
    'L40S': '350W', 'L40': '300W',
  };
  power = powerMap[gpuNum] || '?';

  const machine = name.substring(0, Math.min(20, name.length));
  return { machine, gpu, power };
}

module.exports = {
  normalizeGpuType,
  shortGpuName,
  workerName,
  getMinThreshold,
  classifyWorker,
};
