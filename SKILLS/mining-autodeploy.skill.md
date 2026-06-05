# Mining Autodeploy

Automated vast.ai mining deployment and management.

## Usage

Run anytime to check and deploy mining instances:

```
/mining-autodeploy
```

## What It Does

1. **Cost check** — Kills instances above max price threshold
2. **Performance check** — Kills GPUs below minimum hashrate
3. **Auto deploy** — Deploys Pearl miner to new instances
4. **Status report** — Shows running instances and hashrates

## Files

- `manage.sh` — Main management script
- `manager/vast.py` — Vast.ai instance management
- `.vast_deployed` — Deployed instance IDs
- `.vast_bad` — Bad instance blacklist

## Thresholds

Dynamic thresholds based on PRL price:
- Max price per GPU = break-even × 1.2
- Min hashrate for 5090 = 250 TH/s (configurable)

## Troubleshooting

If instances show "no miner":
1. Check network connectivity
2. Verify AlphaPool API access
3. Instance may be blacklisted — check `.vast_bad`

If vastai errors occur:
1. Temporary network issues — will retry next cycle
2. API rate limits — wait a few minutes
