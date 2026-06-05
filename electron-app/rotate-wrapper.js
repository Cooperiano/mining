/** Thread-safe JSONL writer with file rotation (JavaScript counterpart to manager/rotate.py).

Each line is a JSON object — no read-modify-write needed.
On macOS, fs.appendFileSync is atomic for writes under PIPE_BUF (~512 bytes).
Files rotate at 50 MB, keeping up to 10 rotated copies.
*/

const fs = require('fs');
const path = require('path');

const MAX_BYTES = 50 * 1024 * 1024; // 50 MB
const MAX_ROTATIONS = 10;

/** @returns {string} state directory path */
function stateDir() {
  const env = process.env.PEARL_STATE_DIR;
  if (env) return env;
  return path.join(__dirname, 'state');
}

/**
 * Resolve full path for a JSONL file, creating parent dirs if needed.
 * @param {string} filename
 * @returns {string}
 */
function logPath(filename) {
  const d = stateDir();
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  return path.join(d, filename);
}

/**
 * Rotate a JSONL file: shift .N → .N+1, rename current → .1.
 * Assumes no concurrent writers during rotation.
 * @param {string} filename
 */
function rotate(filename) {
  const base = logPath(filename);
  if (!fs.existsSync(base)) return;

  // Remove oldest rotation
  const oldest = logPath(`${filename}.${MAX_ROTATIONS}.jsonl`);
  if (fs.existsSync(oldest)) fs.unlinkSync(oldest);

  // Shift: .9 → .10, .8 → .9, ... .1 → .2
  for (let n = MAX_ROTATIONS - 1; n >= 1; n--) {
    const src = logPath(`${filename}.${n}.jsonl`);
    const dst = logPath(`${filename}.${n + 1}.jsonl`);
    if (fs.existsSync(src)) fs.renameSync(src, dst);
  }

  // Rename current → .1
  const first = logPath(`${filename}.1.jsonl`);
  fs.renameSync(base, first);
}

/**
 * Append one JSON record to a JSONL file.
 * Auto-adds `ts` (ISO 8601) and `epoch_ms` (Unix ms) if missing.
 * Rotates at 50 MB, keeping up to 10 rotated copies.
 *
 * @param {string} filename - Base filename (e.g. "earnings_log.jsonl")
 * @param {object} record - Dictionary to write as a JSON line
 */
function writeRecord(filename, record) {
  if (!record.ts) record.ts = new Date().toISOString().replace('Z', '').split('.')[0];
  if (!record.epoch_ms) record.epoch_ms = Date.now();

  const line = JSON.stringify(record) + '\n';
  const filepath = logPath(filename);

  // Check size and rotate if needed
  if (fs.existsSync(filepath)) {
    const stat = fs.statSync(filepath);
    if (stat.size >= MAX_BYTES) {
      rotate(filename);
      // File was renamed away — new one will be created by appendFileSync
    }
  }

  fs.appendFileSync(filepath, line, 'utf8');
}

/**
 * Read records from a JSONL file, newest first.
 *
 * @param {string} filename - Base filename
 * @param {object} [opts]
 * @param {number} [opts.limit=500] - Max records to return
 * @param {number} [opts.beforeEpochMs] - Only records before this timestamp
 * @param {number} [opts.afterEpochMs] - Only records after this timestamp
 * @returns {object[]}
 */
function readRecords(filename, opts = {}) {
  const { limit = 500, beforeEpochMs, afterEpochMs } = opts;
  const filepath = logPath(filename);
  if (!fs.existsSync(filepath)) return [];

  /** @type {object[]} */
  const results = [];
  try {
    const content = fs.readFileSync(filepath, 'utf8');
    const lines = content.trim().split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const record = JSON.parse(line);
        const epoch = record.epoch_ms || 0;
        if (beforeEpochMs != null && epoch >= beforeEpochMs) continue;
        if (afterEpochMs != null && epoch <= afterEpochMs) continue;
        results.push(record);
      } catch (_) {
        // skip malformed lines
      }
    }
  } catch (_) {
    return [];
  }

  results.reverse();
  return results.slice(0, limit);
}

/**
 * Return the last N records, newest first.
 * @param {string} filename
 * @param {number} [lines=100]
 * @returns {object[]}
 */
function tailRecords(filename, lines = 100) {
  return readRecords(filename, { limit: lines });
}

/**
 * Read raw JSON lines, newest first (for log viewing).
 * @param {string} filename
 * @param {number} [limit=500]
 * @returns {string[]}
 */
function readRawLines(filename, limit = 500) {
  const filepath = logPath(filename);
  if (!fs.existsSync(filepath)) return [];

  /** @type {string[]} */
  const lines = [];
  try {
    const content = fs.readFileSync(filepath, 'utf8');
    for (const line of content.trim().split('\n')) {
      if (line.trim()) lines.push(line.trim());
    }
  } catch (_) {
    return [];
  }

  lines.reverse();
  return lines.slice(0, limit);
}

module.exports = {
  stateDir,
  logPath,
  writeRecord,
  readRecords,
  tailRecords,
  readRawLines,
  MAX_BYTES,
  MAX_ROTATIONS,
};
