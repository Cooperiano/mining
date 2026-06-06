const { execFile } = require('child_process');
const path = require('path');
const os = require('os');

// Resolve vastai binary — conda env may not be on Electron's PATH
const VASTAI_BIN = process.env.VASTAI_PATH ||
  path.join(os.homedir(), 'miniconda3', 'envs', 'xiaohongshu', 'Scripts',
    process.platform === 'win32' ? 'vastai.exe' : 'vastai');

const cache = new Map();
const inFlight = new Map();

function vastCli(args, timeout = 15000) {
  return new Promise((resolve, reject) => {
    execFile(VASTAI_BIN, [...args, '--raw'], {
      encoding: 'utf8',
      timeout,
      maxBuffer: 1024 * 1024,
    }, (error, stdout) => {
      if (error) reject(error);
      else resolve(stdout.trim());
    });
  });
}

function cached(key, ttlMs, load) {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.time < ttlMs) return Promise.resolve(entry.data);
  if (inFlight.has(key)) return inFlight.get(key);
  const request = load()
    .then(data => {
      cache.set(key, { time: Date.now(), data });
      return data;
    })
    .catch(error => {
      if (entry) return entry.data;
      throw error;
    })
    .finally(() => inFlight.delete(key));
  inFlight.set(key, request);
  return request;
}

function parseVastInstances(data) {
  const instances = Array.isArray(data) ? data : (data.instances || []);
  return instances.map(obj => ({
    id: String(obj.id),
    status: obj.actual_status || obj.status || 'unknown',
    gpu_name: obj.gpu_name || '',
    num_gpus: obj.num_gpus || 1,
    price: parseFloat(obj.dph_total || obj.min_bid || 0),
    dph_total: parseFloat(obj.dph_total || obj.min_bid || 0),
    is_bid: !!obj.is_bid,
    min_bid: parseFloat(obj.min_bid || 0),
    dlperf_per_dphtotal: parseFloat(obj.dlperf_per_dphtotal || 0),
    ssh_host: obj.ssh_host || obj.direct_port_host || '',
    ssh_port: obj.ssh_port || obj.direct_port_start || 22,
  }));
}

async function listInstances() {
  try {
    const raw = await cached('instances', 15000, () => vastCli(['show', 'instances']));
    const data = JSON.parse(raw);
    return { instances: parseVastInstances(data) };
  } catch (e) {
    return { error: e.message, instances: [] };
  }
}

async function getBillingTotal() {
  try {
    return await cached('billing', 300000, async () => {
      // Use spawn to handle interactive "Fetch next page?" prompts
      const { spawn } = require('child_process');
      let grandTotal = 0;
      let nextToken = null;
      let pageCount = 0;

      do {
        pageCount++;
        const args = ['show', 'invoices-v1', '--charges', '--limit', '100', '--raw'];
        if (nextToken) args.push('--next-token', nextToken);

        const pageData = await new Promise((resolve) => {
          const child = spawn(VASTAI_BIN, args, {
            stdio: ['pipe', 'pipe', 'pipe'],
            timeout: 15000,
          });

          let stdout = '';
          let stderr = '';

          child.stdout.on('data', (chunk) => {
            stdout += chunk.toString();
            // Auto-answer 'y' to pagination prompts
            if (stdout.includes('Fetch next page?') || stderr.includes('Fetch next page?')) {
              child.stdin.write('y\n');
            }
          });

          child.stderr.on('data', (chunk) => {
            const text = chunk.toString();
            stderr += text;
            // Prompts may appear on stderr
            if (text.includes('Fetch next page?')) {
              child.stdin.write('y\n');
            }
          });

          child.on('close', () => resolve(stdout));
          child.on('error', () => resolve(stdout));
        });

        try {
          const data = JSON.parse(pageData);
          const results = data.results || [];
          for (const charge of results) {
            if (charge.amount) {
              grandTotal += parseFloat(charge.amount);
            }
          }
          nextToken = data.next_token || null;
        } catch (_) {
          nextToken = null;
        }
      } while (nextToken && pageCount < 10);

      return grandTotal;
    });
  } catch (_) {
    return 0;
  }
}

module.exports = { listInstances, getBillingTotal };
