const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { exec, execFile, spawn } = require('child_process');

const store = require('./session-store');
const pool = require('./pool');
const profit = require('./profit-engine');

const IS_DEV = process.argv.includes('--dev');
let mainWindow = null;
let dashboardInterval = null;
let deployInterval = null;
let restartDeployInterval = null;
let dashboardUpdateInFlight = false;
let autodeployInFlight = false;
let orchestratorProcess = null;
let earningsUpdateInFlight = false;
let earningsInterval = null;
let instanceListCache = { time: 0, data: [] };
let instanceHealthCache = { time: 0, data: [] };
let instanceListPromise = null;
let instanceHealthPromise = null;
let profitCache = { time: 0, data: null };
let profitPromise = null;
let watchers = [];
const MINING_DIR = '/Users/juliancooper/Desktop/projects/mining';

function pythonEnv() {
  return { ...process.env, PEARL_STATE_DIR: path.join(app.getPath('userData'), 'state') };
}

async function getProfitSnapshot(force = false) {
  if (!force && profitCache.data && Date.now() - profitCache.time < 60000) {
    return profitCache.data;
  }
  if (profitPromise) return profitPromise;
  profitPromise = profit.profitabilitySnapshot()
    .then(data => {
      profitCache = { time: Date.now(), data };
      return data;
    })
    .finally(() => { profitPromise = null; });
  return profitPromise;
}

function mergeDashboardData(dashData, profitData = profitCache.data) {
  return {
    ...dashData,
    prl_price: profitData?.prlPrice ?? dashData.prl_price,
    priceSource: profitData?.priceSource ?? 'cached',
    earningsPerHr: profitData?.earningsPerHr ?? dashData.earnings_per_hour,
    rentalCostHr: profitData?.rentalCostHr ?? 0,
    electricityCostHr: profitData?.electricityCostHr ?? 0,
    vastBilledTotal: profitData?.vastBilledTotal ?? 0,
    electricityTotalCost: profitData?.electricityTotalCost ?? 0,
    totalCostHr: profitData?.totalCostHr ?? 0,
    netProfitHr: profitData?.netProfitHr ?? dashData.earnings_per_hour,
    activeSessions: profitData?.activeSessions ?? [],
    total_live_th: dashData.total_live_th,
  };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'Pearl Miner — Analytics',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadFile('index.html');

  if (IS_DEV) {
    mainWindow.webContents.openDevTools();
    setupHotReload();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function registerIPC() {
  // Dashboard
  ipcMain.handle('get-dashboard', async () => {
    const dashData = await pool.getDashboardData();
    const profitData = await getProfitSnapshot().catch(() => null);
    return mergeDashboardData(dashData, profitData);
  });

  // Sessions (read-only)
  ipcMain.handle('session-all', async () => {
    return store.getAllSessions();
  });

  // Profit (read-only)
  ipcMain.handle('profit-snapshot', async () => {
    return getProfitSnapshot();
  });

  ipcMain.handle('config-get', async () => {
    return store.loadConfig();
  });

  ipcMain.handle('config-save', async (_event, updates) => {
    const oldConfig = store.loadConfig();
    const config = store.saveConfig(updates && typeof updates === 'object' ? updates : {});
    profitCache = { time: 0, data: null };
    instanceHealthCache = { time: 0, data: [] };
    // Restart deploy interval if interval or mode config changed
    if (updates && (
      updates.autodeploy_interval_sec !== undefined && updates.autodeploy_interval_sec !== oldConfig.autodeploy_interval_sec ||
      updates.orchestrator_mode !== undefined && updates.orchestrator_mode !== oldConfig.orchestrator_mode ||
      updates.tick_interval_sec !== undefined && updates.tick_interval_sec !== oldConfig.tick_interval_sec
    ) && typeof restartDeployInterval === 'function') {
      restartDeployInterval();
    }
    return config;
  });

  // Audit log
  ipcMain.handle('get-audit-log', async (_event, opts) => {
    return store.readAuditLog(opts || {});
  });

  // JSONL record queries
  ipcMain.handle('get-kill-decisions', async (_event, opts) => {
    return store.readKillDecisions(opts || {});
  });

  ipcMain.handle('get-cycle-log', async (_event, opts) => {
    return store.readCycleLog(opts || {});
  });

  ipcMain.handle('get-worker-snapshots', async (_event, opts) => {
    return store.readWorkerSnapshots(opts || {});
  });

  ipcMain.handle('get-instance-snapshots', async (_event, opts) => {
    return store.readInstanceSnapshots(opts || {});
  });

  ipcMain.handle('get-config-log', async (_event, opts) => {
    return store.readConfigLog(opts || {});
  });

  ipcMain.handle('get-earnings-log', async (_event, opts) => {
    return store.readEarningsLog(opts || {});
  });

  ipcMain.handle('read-jsonl-raw', async (_event, filename, limit) => {
    return store.readJsonlRaw(filename, limit);
  });

  ipcMain.handle('export-history-csv', async () => {
    return store.exportHistoryCSV();
  });

  // Deploy management
  // Interruptible offers scan
  ipcMain.handle('scan-interruptible', async () => {
    return new Promise((resolve) => {
      execFile('python3', ['-m', 'manager.vast'], {
        cwd: MINING_DIR,
        timeout: 120000,
        encoding: 'utf8',
        env: pythonEnv(),
      }, (error, stdout, stderr) => {
        // Also try reading the persisted file directly
        const stateDir = path.join(app.getPath('userData'), 'state');
        const offersPath = path.join(stateDir, 'interruptible_offers.json');
        try {
          if (fs.existsSync(offersPath)) {
            const raw = fs.readFileSync(offersPath, 'utf8');
            const offers = JSON.parse(raw);
            if (Array.isArray(offers)) {
              resolve({ offers, report: error ? `Error: ${error.message}` : stdout });
              return;
            }
          }
        } catch (_) {}
        resolve({
          offers: [],
          report: error ? `Error: ${error.message}\n${stderr || stdout}` : stdout,
        });
      });
    });
  });

  // Read interruptible offers from persisted file
  ipcMain.handle('get-interruptible-offers', async () => {
    const stateDir = path.join(app.getPath('userData'), 'state');
    const offersPath = path.join(stateDir, 'interruptible_offers.json');
    try {
      if (fs.existsSync(offersPath)) {
        const raw = fs.readFileSync(offersPath, 'utf8');
        const offers = JSON.parse(raw);
        return Array.isArray(offers) ? offers : [];
      }
    } catch (_) {}
    return [];
  });

  ipcMain.handle('deploy-now', async () => {
    return new Promise((resolve) => {
      execFile('./manage.sh', ['deploy'], {
        cwd: MINING_DIR,
        timeout: 180000,
        encoding: 'utf8',
        env: pythonEnv()
      }, (error, stdout, stderr) => {
        resolve(error ? `Error: ${error.message}\n${stderr || stdout}` : stdout);
      });
    });
  });

  ipcMain.handle('get-status', async () => {
    return new Promise((resolve) => {
      execFile('./manage.sh', ['status'], {
        cwd: MINING_DIR,
        timeout: 30000,
        encoding: 'utf8',
        env: pythonEnv()
      }, (error, stdout, stderr) => {
        resolve(error ? `Error: ${error.message}\n${stderr || stdout}` : stdout);
      });
    });
  });

  ipcMain.handle('get-blacklist', async () => {
    try {
      const blacklistPath = path.join(MINING_DIR, '.vast_blacklist');
      if (fs.existsSync(blacklistPath)) {
        return fs.readFileSync(blacklistPath, 'utf8');
      }
      return '';
    } catch (e) {
      return `Error: ${e.message}`;
    }
  });

  ipcMain.handle('add-to-blacklist', async (event, entry) => {
    try {
      const blacklistPath = path.join(MINING_DIR, '.vast_blacklist');
      fs.appendFileSync(blacklistPath, entry + '\n');
      return true;
    } catch (e) {
      return false;
    }
  });

  ipcMain.handle('get-deploy-log', async () => {
    try {
      const logPath = path.join(MINING_DIR, 'autodeploy.log');
      if (fs.existsSync(logPath)) {
        const stats = fs.statSync(logPath);
        const maxSize = 100 * 1024; // Last 100KB
        if (stats.size > maxSize) {
          const fd = fs.openSync(logPath, 'r');
          const buffer = Buffer.alloc(maxSize);
          fs.readSync(fd, buffer, 0, maxSize, stats.size - maxSize);
          fs.closeSync(fd);
          return buffer.toString('utf8').split('\n').slice(1).join('\n');
        }
        return fs.readFileSync(logPath, 'utf8');
      }
      return '';
    } catch (e) {
      return `Error: ${e.message}`;
    }
  });

  // Instances
  function runInstanceCommand(command, timeout) {
    return new Promise((resolve) => {
      execFile('python3', ['deploy_one.py', command], {
        cwd: MINING_DIR,
        timeout,
        encoding: 'utf8',
        env: pythonEnv()
      }, (error, stdout) => {
        if (error) {
          resolve(instanceListCache.data);
          return;
        }
        try {
          const instances = JSON.parse(stdout.trim() || '[]');
          resolve(Array.isArray(instances) ? instances : []);
        } catch (_) {
          resolve([]);
        }
      });
    });
  }

  function mergeHealth(instances) {
    const healthById = new Map(instanceHealthCache.data.map(inst => [inst.id, inst]));
    const healthFields = [
      'deployment_state', 'health', 'issue', 'miner_running', 'gpu_util',
      'vram_used_mb', 'vram_total_mb', 'local_hashrate', 'pool_hashrate',
    ];
    return instances.map(inst => {
      const cached = healthById.get(inst.id);
      if (!cached || inst.status !== 'running' || cached.status !== 'running') return inst;
      const merged = { ...inst };
      for (const field of healthFields) merged[field] = cached[field];
      return merged;
    });
  }

  async function getInstanceList(force = false) {
    if (!force && Date.now() - instanceListCache.time < 10000) {
      return mergeHealth(instanceListCache.data);
    }
    if (instanceListPromise) return instanceListPromise;
    instanceListPromise = runInstanceCommand('list', 20000).then(data => {
      instanceListCache = { time: Date.now(), data };
      return mergeHealth(data);
    }).finally(() => { instanceListPromise = null; });
    return instanceListPromise;
  }

  function refreshInstanceHealth(sender, force = false) {
    if (!force && Date.now() - instanceHealthCache.time < 60000) {
      sender.send('instance-health-update', mergeHealth(instanceListCache.data));
      return Promise.resolve(instanceHealthCache.data);
    }
    if (instanceHealthPromise) return instanceHealthPromise;
    instanceHealthPromise = new Promise((resolve) => {
      execFile('python3', ['deploy_one.py', 'health'], {
        cwd: MINING_DIR,
        timeout: 45000,
        encoding: 'utf8',
        env: pythonEnv()
      }, (error, stdout) => {
        let data = [];
        if (!error) {
          try {
            const parsed = JSON.parse(stdout.trim() || '[]');
            data = Array.isArray(parsed) ? parsed : [];
          } catch (_) {}
        }
        if (data.length || !error) {
          instanceHealthCache = { time: Date.now(), data };
          instanceListCache = { time: Date.now(), data };
          store.syncInstanceSessions(data);
        }
        if (!error && !sender.isDestroyed()) sender.send('instance-health-update', data);
        resolve(data);
      });
    }).finally(() => { instanceHealthPromise = null; });
    return instanceHealthPromise;
  }

  ipcMain.handle('list-instances', async (_event, force = false) => {
    return getInstanceList(force);
  });

  ipcMain.handle('refresh-instance-health', async (event, force = false) => {
    refreshInstanceHealth(event.sender, force);
    return { started: true };
  });

  ipcMain.handle('deploy-instance', async (event, instanceId) => {
    const id = String(instanceId || '');
    if (!/^\d+$/.test(id)) {
      return { success: false, output: 'Invalid instance ID' };
    }

    const sender = event.sender;
    sender.send('instance-deploy-start', id);

    return new Promise((resolve) => {
      const child = spawn('python3', ['-u', 'deploy_one.py', 'deploy', id], {
        cwd: MINING_DIR,
        env: pythonEnv(),
        stdio: ['ignore', 'pipe', 'pipe']
      });

      let output = '';
      let timedOut = false;
      let settled = false;
      const sendOutput = (chunk, stream) => {
        const text = chunk.toString();
        output += text;
        sender.send('instance-deploy-output', { instanceId: id, output: text, stream });
      };

      child.stdout.on('data', chunk => sendOutput(chunk, 'stdout'));
      child.stderr.on('data', chunk => sendOutput(chunk, 'stderr'));

      const timer = setTimeout(() => {
        timedOut = true;
        child.kill('SIGKILL');
      }, 180000);

      child.on('error', error => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        const result = { instanceId: id, success: false, output: error.message };
        sender.send('instance-deploy-result', result);
        resolve(result);
      });

      child.on('close', code => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        const success = !timedOut && code === 0 && output.includes('Deployed:');
        const finalOutput = timedOut ? `${output}\nDeploy timed out after 180 seconds.` : output;
        if (success) {
          const instance = instanceListCache.data.find(inst => String(inst.id) === id) || {};
          const workerMatch = output.match(/Deployed:\s+\d+\s+->\s+(\S+)/);
          store.startSession(id, {
            worker_name: workerMatch?.[1] || '',
            gpu_type: instance.gpu_name || '',
            gpu_count: instance.num_gpus || 1,
            rental_cost_per_hour: instance.price || 0,
          });
        }
        const result = { instanceId: id, success, output: finalOutput };
        sender.send('instance-deploy-result', result);
        resolve(result);
      });
    });
  });
}

function startBackgroundTasks() {
  // Dashboard poll every 5 seconds
  dashboardInterval = setInterval(async () => {
    if (!mainWindow || dashboardUpdateInFlight) return;
    dashboardUpdateInFlight = true;
    try {
      const [dashData, profitData] = await Promise.all([
        pool.getDashboardData(),
        getProfitSnapshot(),
      ]);

      // Update hashrate samples for active sessions (historical tracking)
      const activeSessions = store.getActiveSessions();
      const workers = dashData.workers || [];
      for (const session of activeSessions) {
        if (session.status !== 'mining' || !session.worker_name) continue;
        const matching = workers.filter(w =>
          w.name.includes(session.worker_name.split('-gpu')[0])
        );
        if (matching.length > 0) {
          const totalLive = matching.reduce((s, w) => s + w.live_th, 0);
          const totalH1 = matching.reduce((s, w) => s + w.h1_th, 0);
          store.updateHashrate(session.id, totalLive, totalH1);
        }
      }

      mainWindow.webContents.send('dashboard-update', mergeDashboardData(dashData, profitData));
    } catch (_) {
    } finally {
      dashboardUpdateInFlight = false;
    }
  }, 5000);

  // Earnings recording every 30 seconds
  earningsInterval = setInterval(async () => {
    if (earningsUpdateInFlight) return;
    earningsUpdateInFlight = true;
    try {
      await profit.recordEarningsForActiveSessions();
    } catch (_) {
    } finally {
      earningsUpdateInFlight = false;
    }
  }, 30000);
  // Run once immediately
  profit.recordEarningsForActiveSessions().catch(() => {});

  // Autodeploy: supports two modes via orchestrator_mode config key
  function startDeployInterval() {
    stopDeployMode();  // clean up any previous mode
    const config = store.loadConfig();
    restartDeployInterval = startDeployInterval;

    if (config.orchestrator_mode) {
      // ── Orchestrator mode: persistent Python process ──
      startOrchestrator();
    } else {
      // ── Batch mode: periodic manage.sh deploy ──
      const intervalMs = Math.max(30000, (config.autodeploy_interval_sec || 60) * 1000);
      deployInterval = setInterval(async () => {
        if (!mainWindow || autodeployInFlight) return;
        const cfg = store.loadConfig();
        if (!cfg.automation_enabled) return;
        autodeployInFlight = true;
        try {
          exec('./manage.sh deploy', { cwd: MINING_DIR, env: pythonEnv() }, (error, stdout, stderr) => {
            autodeployInFlight = false;
            if (!mainWindow || mainWindow.isDestroyed()) return;
            mainWindow.webContents.send('deploy-result', {
              timestamp: new Date().toISOString(),
              output: stdout,
              error: error?.message || stderr
            });
          });
        } catch (e) {
          autodeployInFlight = false;
          mainWindow.webContents.send('deploy-result', {
            timestamp: new Date().toISOString(),
            output: '',
            error: e.message
          });
        }
      }, intervalMs);
    }
  }

  function startOrchestrator() {
    if (orchestratorProcess) return;  // already running
    const env = pythonEnv();
    const child = spawn('python3', ['manager/orchestrator_main.py'], {
      cwd: MINING_DIR,
      env: env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    child.stdout.on('data', (data) => {
      const lines = data.toString().split('\n').filter(l => l.trim());
      for (const line of lines) {
        try {
          const msg = JSON.parse(line);
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('orchestrator-status', msg);
          }
        } catch {
          // Non-JSON line, forward as raw deploy-result for log display
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('deploy-result', {
              timestamp: new Date().toISOString(),
              output: line,
            });
          }
        }
      }
    });

    child.stderr.on('data', (data) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('deploy-result', {
          timestamp: new Date().toISOString(),
          error: data.toString(),
        });
      }
    });

    child.on('exit', (code) => {
      console.log(`[orchestrator] exited with code ${code}`);
      orchestratorProcess = null;
      // Auto-restart after 10s if app is still running
      if (mainWindow && !mainWindow.isDestroyed()) {
        const cfg = store.loadConfig();
        if (cfg.orchestrator_mode) {
          setTimeout(() => {
            if (store.loadConfig().orchestrator_mode) startOrchestrator();
          }, 10000);
        }
      }
    });

    orchestratorProcess = child;
    console.log(`[orchestrator] spawned pid=${child.pid}`);
  }

  function stopDeployMode() {
    if (deployInterval) { clearInterval(deployInterval); deployInterval = null; }
    if (orchestratorProcess) {
      orchestratorProcess.kill('SIGTERM');
      orchestratorProcess = null;
    }
  }

  startDeployInterval();

}

function stopBackgroundTasks() {
  if (dashboardInterval) clearInterval(dashboardInterval);
  if (earningsInterval) clearInterval(earningsInterval);
  if (typeof stopDeployMode === 'function') stopDeployMode();
}

function setupHotReload() {
  const rendererFiles = ['index.html', 'styles.css', 'renderer.js', 'preload.js'];
  const mainFiles = ['main.js', 'vast.js', 'pool.js', 'session-store.js', 'profit-engine.js'];
  const debounceTimers = {};

  function debounced(file, delay, fn) {
    if (debounceTimers[file]) clearTimeout(debounceTimers[file]);
    debounceTimers[file] = setTimeout(fn, delay);
  }

  for (const file of rendererFiles) {
    const fp = path.join(__dirname, file);
    try {
      const w = fs.watch(fp, () => {
        debounced(file, 300, () => {
          if (mainWindow && !mainWindow.isDestroyed()) {
            console.log(`[hot-reload] renderer: ${file}`);
            mainWindow.webContents.reloadIgnoringCache();
          }
        });
      });
      watchers.push(w);
    } catch (_) {}
  }

  for (const file of mainFiles) {
    const fp = path.join(__dirname, file);
    try {
      const w = fs.watch(fp, () => {
        debounced(file, 500, () => {
          console.log(`[hot-reload] main: ${file} — restarting...`);
          stopBackgroundTasks();
          watchers.forEach(w => w.close());
          Object.values(debounceTimers).forEach(clearTimeout);
          const { spawn } = require('child_process');
          spawn(process.argv[0], process.argv.slice(1), { detached: true, stdio: 'inherit' });
          app.exit(0);
        });
      });
      watchers.push(w);
    } catch (_) {}
  }

  console.log('[hot-reload] watching', rendererFiles.length + mainFiles.length, 'files');
}

app.whenReady().then(() => {
  store.configureStateDir(path.join(app.getPath('userData'), 'state'));
  registerIPC();
  createWindow();
  startBackgroundTasks();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopBackgroundTasks();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackgroundTasks();
  watchers.forEach(w => w.close());
  watchers = [];
});
