# Pearl Mining — Operations Pipeline

> Wallet: `REDACTED_WALLET`  
> Pool: AlphaPool (pearl.alphapool.tech) | Dashboard: https://pearl.alphapool.tech  
> Miner: alpha-miner v1.7.6-beta | API: `curl -s https://pearl.alphapool.tech/api/miner/WALLET`

## Pipeline Overview

```
vast.ai rent → autodeploy.sh → deploy_5090.sh → alpha-miner → API → dashboard.sh
                    ↓ bad instance? → kill
```

### Files

| File | Purpose |
|---|---|
| `dashboard.sh` | Real-time dashboard (pool API, no SSH) |
| `autodeploy.sh` | Cron job: deploy new + kill bad instances |
| `deploy_5090.sh` | Standardized deploy script (auto-detect GPUs) |
| `check_instance.py` | Manual profitability calculator |
| `mine_pearl.sh` | Local launcher with lowest-latency-first pool cycling |
| `MINING_NOTES.md` | This document |

### Quick Commands

```bash
./dashboard.sh -w 10         # Live monitor
bash autodeploy.sh            # Manual deploy run
tail -f autodeploy.log        # Watch cron activity
python3 check_instance.py --th 300 --price 0.56  # Check profitability
```

## Profitability Formula

```
Earnings($/hr) = GPU_TH_s / 1000 × 3.226 × $0.80
Break-even:   GPU_TH_s > cost_per_gpu_hr / 0.80 × 1000 / 3.226
```

| GPU | Expected TH/s | Min TH/s (breakeven) |
|---|---|---|
| RTX 5090 | 280–360 | **217** |
| H100/H200 | 550–650 | **430+** (unprofitable at current rental rates) |
| RTX 4090 | 220–280 | **170** |

## Vast.ai Pipeline

### Rent → Deploy → Monitor → Kill

**Cron:** `*/5 * * * * ~/projects/mining/autodeploy.sh >> ~/projects/mining/autodeploy.log 2>&1`

Auto-actions every 5 min:
- **New instance detected** → `deploy_5090.sh` (download alpha-miner, pick best pool, start mining)
- **No outbound network** → `vastai destroy`
- **≥2 GPUs below 150 TH/s** → `vastai destroy`
- **Already killed** → skip (tracked in `.vast_bad`)

### Deploy Script (`deploy_5090.sh`)

Auto-handles:
1. Download alpha-miner v1.7.6
2. Ping all 5 pool nodes → pick lowest latency
3. Auto-detect GPU count (no hardcoded device list)
4. Static difficulty d=1048576 for 5090
5. 3-pool failover (primary + us1 + sg1)

### Common Instance Failures (60%+ of interruptible rentals)

| Symptom | Cause | Action |
|---|---|---|
| `connect() failed` | No outbound network | Auto-kill by cron |
| `stratum connection closed` | Pool rejecting IP range | Kill manually |
| `CUDA_ERROR_INVALID_DEVICE` | Wrong GPU count | Fixed: auto-detect |
| SSH dead / key denied | Instance unstable | Kill via web console |
| <150 TH/s on 5090 | PCIe bottleneck / power cap | Auto-kill by cron |

## Vast.ai CLI Reference — Full Command Guide

> API key stored at `~/.config/vastai/vast_api_key`  
> Global flags: `--raw` (JSON output), `--explain` (show API mapping), `--curl` (show curl equivalent)

### TL;DR — Check All Instances Fast

```bash
# Show all instances (ID, GPU, status, cost)
vastai show instances

# Show just IDs and statuses
vastai show instances --raw | python3 -c "
import json,sys
for i in json.load(sys.stdin).get('instances',[]):
    print(f\"{i['id']} | {i.get('gpu_name','?'):>8} | {i['status']:<10} | \${i.get('dph_total',0):.3f}/hr | {i.get('label','')}\")
"

# Check GPU health on a specific instance
vastai execute INSTANCE_ID "nvidia-smi"

# Check if miner is running on an instance
vastai execute INSTANCE_ID "ps aux | grep alpha-miner"

# Destroy everything (WARNING — all instances)
vastai show instances --raw | python3 -c "
import json,sys
for i in json.load(sys.stdin).get('instances',[]):
    print(i['id'])
" | xargs -n1 vastai destroy instance
```

### Search & Discovery

```bash
# Find cheapest RTX 5090s (interruptible, sorted by price)
vastai search offers 'gpu_name=RTX_5090 rentable=true verified=true' -o 'min_bid_usd'

# Find on-demand 5090s with direct ports
vastai search offers 'gpu_name=RTX_5090 rentable=true direct_port_count>=1' -o 'total_flops_usd-'

# Search by price ceiling (e.g. max $0.56/hr)
vastai search offers 'gpu_name=RTX_5090 rentable=true min_bid_usd<=0.56' -o 'total_flops_usd-'

# Search by datacenter location (lower latency to pool)
vastai search offers 'gpu_name=RTX_5090 rentable=true geolocation=US' -o 'total_flops_usd-'

# Find RTX 4090s (backup GPU when 5090 supply is tight)
vastai search offers 'gpu_name=RTX_4090 rentable=true verified=true' -o 'min_bid_usd'

# Search by DL performance per dollar (best value)
vastai search offers 'gpu_name=RTX_5090 rentable=true' -o 'dlperf_usd-'

# Multi-GPU search
vastai search offers 'gpu_name=RTX_4090 num_gpus>=2 rentable=true' -o 'total_flops_usd-'

# Search with multiple filters + output specific fields
vastai search offers 'gpu_name=RTX_5090 rentable=true verified=true min_bid_usd<=0.60' \
  -o 'total_flops_usd-' --raw
```

**Key filter fields:** `gpu_name`, `num_gpus`, `min_bid_usd`, `total_flops`, `dlperf`, `dlperf_usd`, `direct_port_count`, `inet_up`, `inet_down`, `geolocation`, `reliability2`, `rentable`, `verified`, `storage_total_cost`, `gpu_ram`, `cpu_ram`, `cuda_max_good`

**Sort with `-o`:** Append `-` for descending (best first). Examples: `dlperf_usd-` (best value first), `min_bid_usd` (cheapest first), `total_flops-` (most compute first)

### Instance Lifecycle

```bash
# Create on-demand instance (fixed price, reliable)
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct

# Create interruptible instance with max bid
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct --min-bid 0.56

# Create with on-start script (auto-deploy mining)
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct \
  --onstart-cmd "curl -L -o alpha-miner https://pearl.alphapool.tech/downloads/alpha-miner && chmod +x alpha-miner && ./alpha-miner --pool stratum+tcp://us1.alphapool.tech:5566 --address REDACTED_WALLET --worker vast-$(hostname)"

# Create with label for tracking
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct --label pearl-5090

# Launch (auto-select best offer matching filters)
vastai launch instance 'gpu_name=RTX_5090 rentable=true verified=true min_bid_usd<=0.56' \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct

# Show all your instances
vastai show instances

# Show single instance details (status, IP, GPU, cost)
vastai show instance INSTANCE_ID

# Show instances with raw JSON (parseable)
vastai show instances --raw

# Stop an instance (pause — disk charges continue, GPU charges stop)
vastai stop instance INSTANCE_ID

# Start a stopped instance
vastai start instance INSTANCE_ID

# Reboot an instance (stop + start)
vastai reboot instance INSTANCE_ID

# Destroy an instance (irreversible — stops all billing)
vastai destroy instance INSTANCE_ID

# Change bid price on an interruptible instance
vastai change bid INSTANCE_ID --price 0.50

# Accept a pending price increase from host
vastai accept price-increase INSTANCE_ID

# Recycle (destroy + re-create with same offer/template)
vastai recycle instance INSTANCE_ID

# Pre-pay deposit into reserved instance
vastai prepay instance INSTANCE_ID --amount 50
```

### SSH & Key Management

```bash
# Create SSH key on account (once)
vastai create ssh-key ~/.ssh/id_ed25519.pub

# List registered SSH keys
vastai show ssh-keys

# Delete an SSH key
vastai delete ssh-key KEY_ID

# Update an existing SSH key
vastai update ssh-key KEY_ID ~/.ssh/new_key.pub

# Attach SSH key to running instance (if you forgot at creation)
vastai attach ssh INSTANCE_ID KEY_ID

# Detach SSH key from instance
vastai detach ssh INSTANCE_ID KEY_ID

# Get SSH connection string
vastai ssh-url INSTANCE_ID

# Get SCP connection string (for rsync/scp)
vastai scp-url INSTANCE_ID
```

### Labels & Organization

```bash
# Label an instance (track purpose/GPU type)
vastai label instance INSTANCE_ID pearl-5090-us1

# Label is visible in show instances output — use for filtering
vastai show instances | grep pearl
```

### Billing & Cost Tracking

```bash
# Show your account info (balance, email, user ID)
vastai show user

# Show billing history (detailed)
vastai show invoices-v1

# Show billing history with filters (last 7 days)
vastai show invoices-v1 --start "$(date -v-7d +%Y-%m-%d)"

# Show machine earnings (if you're a host)
vastai show earnings

# Show reserve deposit info for an instance
vastai show deposit INSTANCE_ID

# Transfer credits to another account
vastai transfer credit RECIPIENT_USER_ID --amount 25

# Search invoices for specific instance
vastai search invoices 'instance_id=INSTANCE_ID'

# Show subaccounts
vastai show subaccounts

# Create a subaccount
vastai create subaccount --name mining-ops
```

### Logs & Debugging

```bash
# Get logs for an instance (on-start output, errors)
vastai logs INSTANCE_ID

# Execute a command remotely on an instance
vastai execute INSTANCE_ID "nvidia-smi"
vastai execute INSTANCE_ID "tail -50 /var/log/mining.log"
vastai execute INSTANCE_ID "ps aux | grep alpha-miner"

# Get user reports for a machine (if host)
vastai reports MACHINE_ID

# Show audit logs (account activity history)
vastai show audit-logs

# Show IP address history
vastai show ipaddrs
```

### Copy & Data Transfer

```bash
# Upload to instance
vastai copy local:./alpha-miner INSTANCE_ID:/root/

# Download from instance
vastai copy INSTANCE_ID:/var/log/mining.log local:./logs/

# Instance to instance copy
vastai copy INSTANCE_A:/workspace/ INSTANCE_B:/workspace/

# Cancel a copy in progress
vastai cancel copy DST_INSTANCE_ID
```

### Bulk Operations

```bash
# Create multiple instances from offer list
vastai create instances OFFER_ID_1 OFFER_ID_2 \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct

# Destroy multiple instances at once
vastai destroy instances INSTANCE_ID_1 INSTANCE_ID_2 INSTANCE_ID_3

# Stop multiple instances
vastai stop instances INSTANCE_ID_1 INSTANCE_ID_2

# Start multiple instances
vastai start instances INSTANCE_ID_1 INSTANCE_ID_2
```

### Market Intelligence

```bash
# GPU market metrics (current pricing, availability)
vastai metrics gpu

# GPU market trends over time
vastai metrics gpu-trends

# GPU availability by location
vastai metrics gpu-locations
```

### Templates

```bash
# Create a template (reuse image/config across instances)
vastai create template my-pearl-5090 \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct \
  --onstart-cmd "curl -L -o alpha-miner https://pearl.alphapool.tech/downloads/alpha-miner && chmod +x alpha-miner && ./alpha-miner --pool stratum+tcp://us1.alphapool.tech:5566 --address REDACTED_WALLET --worker vast-\$(hostname)"

# Search templates
vastai search templates 'pearl'

# Update a template
vastai update template TEMPLATE_ID --disk 40

# Delete a template
vastai delete template TEMPLATE_ID
```

### Environment Variables

```bash
# Set env var (available in on-start scripts + instance)
vastai create env-var PEARL_WALLET REDACTED_WALLET
vastai create env-var PEARL_POOL us1.alphapool.tech:5566

# Show env vars
vastai show env-vars

# Update an env var
vastai update env-var ENV_VAR_ID --value new_value

# Delete an env var
vastai delete env-var ENV_VAR_ID
```

### Interruptible vs On-Demand Strategy

| Type | Flag | Pricing | Risk | Best For |
|---|---|---|---|---|
| On-demand | (default) | Fixed $/hr | Low — rarely killed | Production mining |
| Interruptible | `--min-bid 0.56` | Bid-based, can be outbid | High — killed when outbid | Testing, overflow capacity |

```bash
# Check if instance is interruptible (shows in show instance output)
vastai show instance INSTANCE_ID | grep -i inter

# Change bid on interruptible instance (increase to avoid being outbid)
vastai change bid INSTANCE_ID --price 0.60
```

### Instance Auditing & Monitoring

How to check what's running, get instance IDs, and diagnose status.

```bash
# List all instances with key fields (ID, GPU, status, cost, label)
vastai show instances

# JSON format — parseable with jq/python
vastai show instances --raw

# Narrow to running only
vastai show instances --raw | python3 -c "
import json,sys
data=json.load(sys.stdin)
for i in data.get('instances',[]):
    if i['status']=='running':
        print(f\"{i['id']} | {i.get('gpu_name','?'):>8} | ${i.get('dph_total',0):.3f}/hr | {i.get('label','')}\")
"

# Check a specific instance
vastai show instance INSTANCE_ID

# Key status values:
#   loading  — pulling Docker image (1-5 min)
#   running  — healthy, ready to use
#   stopped  — paused by you (disk charges, no GPU charges)
#   exited   — container crashed (investigate logs)
#   offline  — host machine disconnected (destroy + retry)
#   unknown  — no heartbeat from host (destroy + retry)

# Check if instance is healthy via remote command
vastai execute INSTANCE_ID "nvidia-smi --query-gpu=name,utilization.gpu,temperature.gpu --format=csv,noheader"

# Check if miner is running
vastai execute INSTANCE_ID "ps aux | grep alpha-miner"

# Check miner hashrate from logs
vastai execute INSTANCE_ID "tail -30 /var/log/mining.log"

# Quick health sweep — check all running instances at once
vastai show instances --raw | python3 -c "
import json,sys
data=json.load(sys.stdin)
for i in data.get('instances',[]):
    print(f\"ID={i['id']} | {i.get('gpu_name','?'):>8} | status={i['status']} | cost=\${i.get('dph_total',0):.3f}/hr | label={i.get('label','')}\")
"
```

**Typical audit flow:**
```bash
# 1) List everything running
vastai show instances

# 2) For each instance, check GPU health
vastai execute INSTANCE_ID "nvidia-smi"

# 3) Check mining process
vastai execute INSTANCE_ID "ps aux | grep alpha-miner"

# 4) Get logs if something is wrong
vastai logs INSTANCE_ID

# 5) Kill unprofitable/failed instances
vastai destroy instance INSTANCE_ID
```

### Quick Profitability Check (Manual)

```bash
# 1. Search for best current 5090 price
vastai search offers 'gpu_name=RTX_5090 rentable=true verified=true' -o 'min_bid_usd' --raw | head -5

# 2. Estimate earnings at 300 TH/s:
#    Earnings/hr = 300 / 1000 * 3.226 * $0.80 = ~$0.77/hr

# 3. Profit/hr = earnings - rental_cost
#    E.g. $0.77 - $0.56 = $0.21/hr profit per 5090

# 4. Check running costs across all instances
vastai show instances --raw | python3 -c "
import json,sys
data=json.load(sys.stdin)
for i in data.get('instances',[]):
    print(f\"{i['id']}: {i.get('gpu_name','?')} @ \${i.get('min_bid',i.get('dph_total',0))}/hr status={i['status']}\")
"
```

## Owned Hardware

| Machine | GPU | TH/s | W | Management |
|---|---|---|---|---|
| station | RTX 3080 | ~90 | 320W | `systemctl --user restart pearl-miner` |
| lab1 | 2× RTX 4060 Ti | ~135 | 320W | `systemctl --user restart pearl-miner` |
| laptop | RTX 3060 | ~25 | 95W | Docker `pearl-miner` (restart=always) |

### Service Management

```bash
# station & lab1: systemd user services
systemctl --user status pearl-miner
systemctl --user restart pearl-miner
journalctl --user -fu pearl-miner

# laptop: Docker
ssh Julian-laptop "docker logs -f pearl-miner"
ssh Julian-laptop "docker restart pearl-miner"
```

## Static Difficulty

| GPU | d= |
|---|---|
| RTX 3060 Ti / 3070 | 131072 |
| RTX 3080 / 3090 / 4060 Ti | 262144 |
| RTX 4070 / 4080 | 262144 |
| RTX 4090 / 5080 | 524288 |
| RTX 5090 / H100 / H200 | **1048576** |

## AlphaPool Nodes (pick lowest ping)

| Region | Host | Port |
|---|---|---|
| Europe 1 | eu1.alphapool.tech | 5566 |
| Europe 2 | eu2.alphapool.tech | 5566 |
| US East | us1.alphapool.tech | 5566 |
| US West | us2.alphapool.tech | 5566 |
| Asia | sg1.alphapool.tech | 5566 |

## Kaspa Mining (DEPRECATED — GPU unprofitable)

KAS mining via bzminer on Kryptex pool was shut down. GPU Kaspa mining is not viable due to ASIC dominance.
