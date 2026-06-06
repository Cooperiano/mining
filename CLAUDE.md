# Mining Management System — Development Guide

## Documentation Index

| 文档 | 路径 | 内容 |
|------|------|------|
| **GPU 算力参考表** | [docs/GPU_HASHRATE_REFERENCE.md](docs/GPU_HASHRATE_REFERENCE.md) | 所有 GPU 型号的 TH/s 算力、杀机阈值、TDP、性价比 |
| **运维手册** | [docs/OPERATIONS.md](docs/OPERATIONS.md) | 利润公式、Vast.ai CLI 速查、自动部署管道、故障排查 |
| **技能文档** | [docs/SKILLS.md](docs/SKILLS.md) | 实例检查部署流程、自动部署阈值计算、配置参考 |
| **自动化 & 依赖审计** | [docs/AUTOMATION_FALLBACK_AND_DEPENDENCIES.md](docs/AUTOMATION_FALLBACK_AND_DEPENDENCIES.md) | 自动修复策略、Fallback 设计、风险评估、实施路线 |

## Architecture

```
mining/
├── manager/                  # Python backend (mining logic)
│   ├── vast.py               # Core: autodeploy, check-and-kill, instance management
│   ├── minerctl.py           # CLI tool for manual operations
│   └── ...
├── electron-app/             # Electron desktop app (UI)
│   ├── main.js               # Electron main process (Python bridge via IPC)
│   ├── renderer.js            # Frontend rendering logic (all panels)
│   ├── index.html             # UI layout and table structures
│   ├── gpu.js                 # GPU model registry (frontend)
│   ├── styles.css             # Styling
│   └── state/
│       └── config.json        # Runtime configuration (thresholds, prices, etc.)
└── deploy.sh                  # Deployment script executed on vast.ai instances
```

**Communication**: Electron main process ↔ Python backend via child_process spawn. Renderer ↔ main process via IPC.

## Earnings & Profitability Formula

### Core Formula

```
earnings_per_hour = (hashrate_th_per_second / 1000) × EARN_RATE × PRL_PRICE
margin_per_hour   = earnings_per_hour - cost_per_hour
```

Where:
- `hashrate_th_per_second` = pool-reported hashrate in TH/s (use **1-hour average** `h1_th`, not live)
- `EARN_RATE` = 3.226 (PRL earned per TH/s per day equivalent, from AlphaPool)
- `PRL_PRICE` = current PRL token price in USD (from `config.json` `prl_price`, default $0.80)
- `cost_per_hour` = vast.ai rental price per hour

### Why 1-Hour Average

Live hashrate is volatile (pool luck, network jitter). The 1-hour average (`h1_th`) is the stable metric for kill decisions and profitability calculations. Always use `h1_th` for:
- Kill threshold comparisons
- Profit/margin estimates
- Worker earnings display

### Kill Decision Logic

```
if avg_h1 < min_threshold:
    → KILL (worker is underperforming)
if avg_h1 < min_threshold × 0.3:
    → SKIP (warm-up protection — worker just started)
```

Per-model thresholds are read from `config.json` as `min_th_{gpu_model}`. If not configured, fallback = `GPU_HASHRATES[model] × 0.7`.

## GPU Model Registry

### Adding a New GPU Model

1. **`manager/vast.py`** — Add to `GPU_HASHRATES` dict with reference hashrate (TH/s)
2. **`electron-app/state/config.json`** — Add `"min_th_{model}": <value>` (≈ 70% of reference)
3. **`electron-app/gpu.js`** — Add to:
   - `getMinThreshold()` — config key lookup with proper ordering (check Ti/Super variants first)
   - `powerMap` in `classifyWorker()` — TDP wattage
4. **`electron-app/index.html`** — If it's a major model, add a config field in Hashrate Thresholds card (optional)

### GPU Naming Convention

Vast.ai worker names follow the pattern: `{GPU_MODEL}x{COUNT}-{TAG}.gpu{INDEX}`

The backend parses GPU model with `_GPU_MODEL_RE` regex in `_parse_gpu_model()`. The regex extracts the leading GPU identifier (e.g., "5090", "H100", "A6000", "L40S").

### Normalized Keys

Keys in `GPU_HASHRATES` use lowercase with underscores:
- `rtx_5090`, `rtx_4080_super`, `rtx_4070_ti`
- `h100`, `h200`, `b200`
- `a100`, `a6000`, `a5000`, `a4000`
- `l40s`, `l40`

Config keys use the same normalization: `min_th_5090`, `min_th_4080_super`, etc.

## Key Files Reference

| File | Purpose | Critical Functions |
|------|---------|--------------------|
| `manager/vast.py` | Mining automation | `autodeploy_cycle()`, `_check_and_kill()`, `_parse_gpu_model()`, `_min_th_for_model()` |
| `manager/minerctl.py` | CLI commands | `cmd_vast_autodeploy()`, `cmd_vast_list_offers()` |
| `electron-app/main.js` | Electron backend bridge | Python process spawning, IPC handlers |
| `electron-app/renderer.js` | All UI rendering | `renderDashboard()`, `renderInstances()`, `renderHistory()` |
| `electron-app/index.html` | UI structure | Table headers, tab layout, config form |
| `electron-app/gpu.js` | GPU model utilities | `getMinThreshold()`, `classifyWorker()`, `normalizeGpuType()` |
| `electron-app/state/config.json` | Persistent config | All `min_th_*` entries, `prl_price`, `earn_rate`, automation flags |

## Configuration Keys

### Profitability
- `prl_price` — PRL token USD price (updated manually or via API)
- `earn_rate` — 3.226 (PRL per TH/s per day)
- `electricity_price_usd_kwh` — For owned hardware cost calculation

### Thresholds (per GPU model)
- `min_th_5090`, `min_th_4090`, `min_th_4060_ti`, etc.
- `kill_threshold_gpu_count` — Minimum GPU count before auto-kill triggers

### Automation
- `automation_enabled` — Master switch
- `auto_deploy_enabled` — Auto-deploy new instances
- `auto_destroy_enabled` — Auto-destroy underperforming instances (dangerous)
- `dry_run` — Log only, no actual kill/destroy
- `max_destroys_per_hour` — Rate limit for safety
- `consecutive_failures_before_destroy` — Retry threshold
- `new_instance_protection_minutes` — Warm-up grace period

## Future Optimization Directions

1. **Margin-based auto-kill**: Replace simple hashrate threshold with margin calculation. Kill if `margin_per_hour < 0` (costing money). More accurate than hashrate alone because it accounts for varying rental prices.

2. **Dynamic PRL price**: Currently PRL price is manually set in config. Integrate with a price API (CoinGecko, DexScreener) for real-time updates.

3. **Per-instance profitability history**: Track margin over time per instance to identify trends (degrading performance, price changes).

4. **Smart deployment**: Prioritize GPU models with the best historical margin, not just lowest price.

5. **Multi-pool support**: Currently hardcoded to AlphaPool. Support additional mining pools for failover.

## Code Style Notes

- Python: Follow PEP 8, use type annotations on all function signatures
- JavaScript (renderer): Vanilla JS, no framework. DOM manipulation via `setText()`, `setHtml()` helpers
- Config keys: snake_case in Python/config.json, camelCase in JS (mapped automatically)
- GPU model keys: lowercase with underscores (`rtx_5090`, `rtx_4080_super`)
