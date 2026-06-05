#!/bin/bash
# Pearl alpha-miner deployment for RTX 5090 instances
# Usage: curl -sL URL | bash -s WORKER_NAME
set -e

WORKER="${1:-auto}"
WALLET="prl1pyvv3nzlvyahzgdhsg4c4sm3z6ukv9zcc39genld24yw4thmet6asevn44h"

if [ "$WORKER" = "auto" ]; then
    WORKER="5090-$(hostname | md5sum | head -c 4)"
fi

echo "=== Pearl Miner Deploy ==="
echo "Worker: $WORKER"
echo "Wallet: ${WALLET:0:12}..."

# Kill old
pkill -9 alpha-miner 2>/dev/null || true
sleep 1

# Download miner
echo "[1/3] Downloading alpha-miner v1.7.6..."
curl -sL --connect-timeout 30 --retry 3 \
    -o /workspace/alpha-miner \
    https://github.com/AlphaMine-Tech/alpha-miner/releases/download/v1.7.6-beta/alpha-miner
chmod +x /workspace/alpha-miner
/workspace/alpha-miner --version

# Pick best pool
echo "[2/3] Picking best pool..."
BEST="eu2"
BEST_MS=999
for h in eu1 eu2 us1 us2 sg1; do
    ms=$(timeout 2 ping -c1 -W1 ${h}.alphapool.tech 2>/dev/null | grep -oP 'time=\K[0-9.]+' | head -1)
    if [ -n "$ms" ] && [ "$(echo "$ms < $BEST_MS" | bc 2>/dev/null)" = 1 ]; then
        BEST=$h
        BEST_MS=$ms
    fi
    printf "  %s: %s\n" "$h" "${ms:-timeout}ms"
done
echo "  => Best: $BEST (${BEST_MS}ms)"

# Detect GPU count
GPU_COUNT=$(nvidia-smi -L 2>/dev/null | wc -l)
DEVICES=$(seq -s, 0 $((GPU_COUNT - 1)))
echo "GPUs: $GPU_COUNT ($DEVICES)"

# Create startup script
echo "[3/3] Starting miner..."
cat > /workspace/mine.sh << SCRIPT
#!/bin/bash
cd /workspace
while true; do
    ./alpha-miner \
        --pool ${BEST}.alphapool.tech:5566 \
        --pool us1.alphapool.tech:5566 \
        --pool sg1.alphapool.tech:5566 \
        --address ${WALLET}.${WORKER} \
        --password "x;d=1048576" \
        --devices ${DEVICES} \
        --status-interval 60 \
        --color never
    sleep 10
done
SCRIPT
chmod +x /workspace/mine.sh

> /workspace/miner.log
nohup /workspace/mine.sh >> /workspace/miner.log 2>&1 &
sleep 8

CONNECTED=$(grep -c "connected" /workspace/miner.log 2>/dev/null || echo 0)
echo "=== Done: $CONNECTED GPUs connected ==="
echo "Log: /workspace/miner.log"
echo "Worker: $WORKER"
