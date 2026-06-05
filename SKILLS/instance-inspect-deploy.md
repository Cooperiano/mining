# Instance Inspect & Deploy

Handle new instance inspection, SSH connection, and Pearl miner deployment for both vast.ai cloud instances and self-hosted machines.

## Trigger

Use this skill when the user asks to:
- Check a new instance's IP, GPU, or other info
- Connect to / SSH into an instance
- Deploy a miner to a specific instance
- Get SSH/IP details for any instance
- Inspect the status of a newly rented vast.ai machine

## Tools Available

All commands below should be run from `mining/` project root:

| Command | Purpose |
|---------|---------|
| `python3 minerctl.py list` | List all miners (hosted + vast.ai) |
| `python3 minerctl.py vast list` | List only vast.ai instances |
| `python3 minerctl.py vast ssh <id>` | Get SSH URL for a vast.ai instance |
| `python3 minerctl.py vast wait <id>` | Wait for instance to reach running state |
| `python3 minerctl.py vast deploy <id>` | Deploy Pearl miner to vast.ai instance |
| `python3 minerctl.py vast kill <id> [reason]` | Destroy a vast.ai instance |
| `python3 minerctl.py vast autodeploy` | Run one autodeploy scan cycle |
| `python3 cost_report.py` | Profit/cost report |
| `python3 minerctl.py dashboard [-w SEC]` | Live mining dashboard |

## Workflow: New vast.ai Instance

### 1. Check instance state

```bash
python3 minerctl.py vast list
```

Or use `--raw` format for machine-readable data:
```bash
vastai show instances --raw | python3 -m json.tool
```

### 2. Get connection info (IP + Port)

```bash
python3 minerctl.py vast ssh <INSTANCE_ID>
```

### 3. Inspect the instance (GPUs, specs)

```bash
vastai ssh-url <INSTANCE_ID>
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@<IP> -p <PORT> "nvidia-smi"
```

Full inspection:
```bash
ssh -o StrictHostKeyChecking=no root@<IP> -p <PORT> "echo '=== CPU ===' && nproc && echo '=== RAM ===' && free -h && echo '=== GPUs ===' && nvidia-smi && echo '=== Disk ===' && df -h /workspace && echo '=== Network ===' && curl -s --connect-timeout 3 https://api.ipify.org"
```

### 4. Deploy the Pearl miner

```bash
python3 minerctl.py vast deploy <INSTANCE_ID>
```

This executes:
1. Gets SSH URL for the instance
2. Verifies outbound network connectivity
3. Detects GPU count and type via SSH
4. Pings all pool nodes (eu1, eu2, us1, us2, sg1) to pick lowest latency
5. Generates deploy script via `manager/deploy.py:generate_deploy_script()`
6. Pipes script over SSH, auto-downloads alpha-miner v1.7.6
7. Starts miner via nohup

### 5. Quick SSH session

```bash
vastai ssh-url <INSTANCE_ID> | xargs -I {} sh -c 'ssh -o StrictHostKeyChecking=no "{}"'
```

## Autodeploy Pipeline

Runs every 5 min via OpenClaw cron (`spearl-autodeploy`) in isolated session.

### Autodeploy Cycle Steps:

1. **Cost check** — Kill instances where price/GPU exceeds model-specific threshold
2. **Underperformer check** — Kill GPU workers below 150 TH/s (with warm-up grace: skips if 1h avg < 30% of threshold)
3. **Deploy new** — Auto-deploy to any undepolyed, non-bad instances

### Threshold Calculation (per GPU model):

| GPU | TH/s | At $0.73/PRL |
|-----|------|--------------|
| RTX 5090 | 365 | $1.03/GPU |
| RTX 4090 | 255 | $0.72/GPU |
| RTX 5080 | 185 | $0.52/GPU |
| RTX 5070 Ti | 150 | $0.42/GPU |
| RTX 3080 | 90 | $0.25/GPU |
| RTX 3060 Ti | 65 | $0.18/GPU |

Formula: `(expected_th / 1000) × 3.226 × prl_price × 1.2`

PRL price read from `electron-app/state/config.json` (`prl_price` field). Currently $0.73.

## Pricing Model

- **All instances must be interruptible (bid)** — no on-demand
- Prices set via vast.ai bid system
- `.vast_saved` contains known good machines with max bid prices
- `re_rent.py` re-rents saved machines at bid pricing

## Profitability & Calculation Reference

### Core Formulas

```
Earnings ($/hr) = (th_s / 1000) × earn_rate × prl_price
Net Profit ($/hr) = Earnings - Rental_Cost - Electricity_Cost
Break-even TH/s = (cost_per_hour / prl_price) × 1000 / earn_rate
```

**Constants:**
| Param | Value | Source |
|-------|-------|--------|
| `earn_rate` | 3.226 PRL/hr per PH/s | AlphaPool |
| `prl_price` | $0.73 | `electron-app/state/config.json` (manual) |
| `electricity_price` | $0.085/kWh | `config.json` |
| `owned_total_watts` | 500 W | `config.json` (station + lab1 + laptop) |

### GPU Hashrates (Reference)

| GPU | Architecture | VRAM | Expected TH/s |
|-----|-------------|------|--------------|
| RTX 5090 | Blackwell SM_120 | 32 GB | ~365 |
| RTX 5080 | Blackwell SM_120 | 16 GB | ~185 |
| RTX 5070 Ti | Blackwell SM_120 | 16 GB | ~150 |
| RTX 4090 | Ada SM_89 | 24 GB | ~255 |
| RTX 3090 | Ampere SM_86 | 24 GB | ~110 |
| RTX 3080 | Ampere SM_86 | 10 GB | ~90 |
| RTX 3070 | Ampere SM_86 | 8 GB | ~70 |
| RTX 3060 Ti | Ampere SM_86 | 8 GB | ~65 |
| RTX 4060 Ti | Ada SM_89 | 8 GB | ~68 |
| H100 | Hopper SM_90 | 80 GB | ~620 |

### Dynamic Cost Thresholds

Calculated live in `manager/vast.py` from config, per GPU model:

```
break_even($/hr) = (gpu_th / 1000) × 3.226 × prl_price
max_price($/hr)  = break_even × 1.2  (20% buffer)
```

**At PRL=$0.73:**
| GPU | Break-even | Kill threshold |
|-----|-----------|---------------|
| RTX 5090 | $0.86/hr | **$1.03/hr** |
| RTX 4090 | $0.60/hr | **$0.72/hr** |
| RTX 5080 | $0.44/hr | **$0.52/hr** |
| RTX 3080 | $0.21/hr | **$0.25/hr** |
| RTX 3060 Ti | $0.15/hr | **$0.18/hr** |

### Min TH/s Thresholds (Underperformer Kill)

From `electron-app/state/config.json`:
| GPU | Min TH/s |
|-----|---------|
| RTX 5090 | 250 |
| RTX 4090 | 100 |
| RTX 4060 Ti | 40 |

Underperformer check has a **warm-up buffer**: skips workers where 1h avg hashrate < 30% of threshold (just deployed, hasn't accumulated pool data yet).

### Self-Hosted Hardware

| Machine | GPU(s) | Watts | Est TH/s |
|---------|--------|-------|---------|
| station | RTX 3080 | 320W | ~86 |
| lab1 | 2× RTX 4060 Ti | 160W | ~115 |
| laptop | RTX 3060 | 95W | ~21 |
| **Total** | | **500W** | **~222 TH/s** |

Electricity cost: `(500/1000) × $0.085 = $0.0425/hr` for owned fleet.

### Session P&L Tracking

The electron app (`profit-engine.js` + `session-store.js`) tracks every rental as a session:

1. Created → Searching → Renting → Deploying → Mining → Completed/Killed
2. Each session records: worker_name, gpu_type, rental_cost_per_hour, electricity_cost_per_hour, hashrate_samples (up to 1000)
3. Historical data persists in `state/sessions.json`
4. Dashboard shows per-session P&L in History tab

### Vast.ai Pricing Model

- **All instances must be interruptible (bid)** — no on-demand
- Current spot prices (from `vastai show instances --raw`):
  - 2×5090: $1.14-1.41/hr ($0.57-0.71/GPU)
  - 4×5090: ~$1.79/hr ($0.45/GPU)
- Saved machines (`vast_saved`) tracked with max bid prices for re-rental

### Electron App Config Reference

File: `electron-app/state/config.json`

| Key | Current | Description |
|-----|---------|-------------|
| `prl_price` | 0.73 | PRL price override |
| `electricity_price_usd_kwh` | 0.085 | Electricity rate |
| `owned_total_watts` | 500 | Self-hosted power draw |
| `min_th_5090` | 250 | Kill threshold for 5090 |
| `min_th_4090` | 100 | Kill threshold for 4090 |
| `min_th_4060ti` | 40 | Kill threshold for 4060 Ti |
| `kill_threshold_gpu_count` | 2 | Min GPUs below threshold to trigger kill |
| `earn_rate` | 3.226 | Pool earn rate |
| `api_url` | https://pearl.alphapool.tech/api/miner/ | Pool API |

### Key Files

| File | Purpose |
|------|---------|
| `electron-app/state/config.json` | User configuration |
| `electron-app/state/sessions.json` | Session history (P&L) |
| `electron-app/state/price_cache.json` | Cached exchange prices |
| `.vast_deployed` | Instance IDs with deployed miners |
| `.vast_bad` | Instance IDs that failed or were killed |
| `.vast_saved` | Known good machines for re-rental |
| `.vast_blacklist` | Problem hosts to avoid |

## Troubleshooting

| Problem | Check |
|---------|-------|
| Instance won't SSH | Run `minerctl.py vast wait <id>` — may still be booting |
| Deploy fails (network) | Instance has no outbound access — kill it: `minerctl.py vast kill <id> "no network"` |
| Miner not appearing on dashboard | SSH in: `tail -50 /root/mining/miner.log` |
| Low hashrate | Auto-killed below 250 TH/s per 5090 with warm-up buffer |
| Worker name wrong | Format: `{gpu_type}x{gpu_count}-{last4_of_instance_id}.gpuN` |

## Key Config Reference

- **Wallet**: `REDACTED_WALLET`
- **Pool**: AlphaPool (`*.alphapool.tech:5566`)
- **Earn rate**: 3.226 PRL/hr per PH/s
- **PRL price**: $0.73 (from config, adjustable)
- **Config**: `electron-app/state/config.json`
- **Sessions**: `electron-app/state/sessions.json`
- **Deployed state**: `.vast_deployed`
- **Bad instances**: `.vast_bad`
- **Saved machines**: `.vast_saved`
- **Blacklist**: `.vast_blacklist`
