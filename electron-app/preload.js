const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  // Dashboard
  getDashboard: () => ipcRenderer.invoke('get-dashboard'),

  // Sessions (read-only)
  getAllSessions: () => ipcRenderer.invoke('session-all'),

  // Profit (read-only snapshot)
  profitabilitySnapshot: () => ipcRenderer.invoke('profit-snapshot'),
  getConfig: () => ipcRenderer.invoke('config-get'),
  saveConfig: (updates) => ipcRenderer.invoke('config-save', updates),

  // Deploy management
  deployNow: () => ipcRenderer.invoke('deploy-now'),
  getStatus: () => ipcRenderer.invoke('get-status'),
  getBlacklist: () => ipcRenderer.invoke('get-blacklist'),
  addToBlacklist: (entry) => ipcRenderer.invoke('add-to-blacklist', entry),
  getDeployLog: () => ipcRenderer.invoke('get-deploy-log'),
  getAuditLog: (opts) => ipcRenderer.invoke('get-audit-log', opts),

  // JSONL record queries
  getKillDecisions: (opts) => ipcRenderer.invoke('get-kill-decisions', opts),
  getCycleLog: (opts) => ipcRenderer.invoke('get-cycle-log', opts),
  getWorkerSnapshots: (opts) => ipcRenderer.invoke('get-worker-snapshots', opts),
  getInstanceSnapshots: (opts) => ipcRenderer.invoke('get-instance-snapshots', opts),
  getConfigLog: (opts) => ipcRenderer.invoke('get-config-log', opts),
  getEarningsLog: (opts) => ipcRenderer.invoke('get-earnings-log', opts),
  readJsonlRaw: (filename, limit) => ipcRenderer.invoke('read-jsonl-raw', filename, limit),
  exportHistoryCSV: () => ipcRenderer.invoke('export-history-csv'),

  // Instances (manual deploy)
  listInstances: (force) => ipcRenderer.invoke('list-instances', force),
  refreshInstanceHealth: (force) => ipcRenderer.invoke('refresh-instance-health', force),
  deployToInstance: (instanceId) => ipcRenderer.invoke('deploy-instance', instanceId),

  // Interruptible offers
  scanInterruptible: () => ipcRenderer.invoke('scan-interruptible'),
  getInterruptibleOffers: () => ipcRenderer.invoke('get-interruptible-offers'),

  // Event listeners
  onDashboardUpdate: (callback) => {
    ipcRenderer.on('dashboard-update', (_event, data) => callback(data));
  },

  onDeployResult: (callback) => {
    ipcRenderer.on('deploy-result', (_event, data) => callback(data));
  },

  onInstanceDeployStart: (callback) => {
    ipcRenderer.on('instance-deploy-start', (_event, instanceId) => callback(instanceId));
  },

  onInstanceDeployOutput: (callback) => {
    ipcRenderer.on('instance-deploy-output', (_event, data) => callback(data));
  },

  onInstanceDeployResult: (callback) => {
    ipcRenderer.on('instance-deploy-result', (_event, data) => callback(data));
  },

  onInstanceHealthUpdate: (callback) => {
    ipcRenderer.on('instance-health-update', (_event, data) => callback(data));
  },
});
