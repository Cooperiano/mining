#!/bin/bash
# Pearl miner — lowest-latency-first with auto-return to primary
cd "$(dirname "$0")"

WALLET="${WALLET_ADDR:-REDACTED_WALLET.miner1}"
DIFF="${PEARL_DIFF:-262144}"

# Primary = lowest latency (eu2 = 193ms)
PRIMARY="eu2.alphapool.tech:5566"
BACKUPS=(
  "eu1.alphapool.tech:5566"
  "ru1.alphapool.tech:5566"
  "sg1.alphapool.tech:5566"
)

run_miner() {
    ./alpha-miner \
      --pool "$1" \
      --address "$WALLET" \
      --password "x;d=$DIFF" \
      --status-interval 60 \
      --color never
}

while true; do
    echo "[$(date '+%H:%M:%S')] Primary: $PRIMARY"
    run_miner "$PRIMARY"
    echo "[$(date '+%H:%M:%S')] Primary down, trying backups..."

    for pool in "${BACKUPS[@]}"; do
        echo "[$(date '+%H:%M:%S')] Backup: $pool (will retry primary after 5min)"
        run_miner "$pool" &
        PID=$!
        sleep 300  # 5 min on backup then retry primary
        kill $PID 2>/dev/null
        wait $PID 2>/dev/null
        echo "[$(date '+%H:%M:%S')] Retrying primary..."
        break  # always go back to primary after one backup attempt
    done
done
