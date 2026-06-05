"""Shared deployment scripts for Pearl alpha-miner."""

import shlex
from typing import Any

WALLET = "REDACTED_WALLET"

ALPHA_MINER_URL = (
    "https://github.com/AlphaMine-Tech/alpha-miner/releases/download/"
    "v1.7.6-beta/alpha-miner"
)

POOL_NODES = ["eu1", "eu2", "us1", "us2", "sg1"]
POOL_PORT = 5566

DIFFICULTY: dict[str, int] = {
    "5090": 1048576,
    "h100": 1048576,
    "h200": 1048576,
    "4090": 524288,
    "5080": 524288,
    "3080": 262144,
    "3090": 262144,
    "4060ti": 262144,
    "4070": 262144,
    "4080": 262144,
    "3070": 131072,
    "3060ti": 131072,
    "3060": 131072,
}


def gpu_difficulty(gpu_type: str) -> int:
    return DIFFICULTY.get(gpu_type.lower(), 262144)


def generate_deploy_script(
    worker: str,
    gpu_type: str = "auto",
    mining_dir: str = "$HOME/mining",
) -> str:
    """Generate the bash deploy script to be piped over SSH."""
    difficulty = gpu_difficulty(gpu_type)

    pools = " ".join(f'"{node}.alphapool.tech:{POOL_PORT}"' for node in POOL_NODES)

    return f"""#!/bin/bash
set -e
WORKER="{worker}"
WALLET="{WALLET}"
MINING_DIR="{mining_dir}"

echo "=== Pearl Miner Deploy ==="
echo "Worker: $WORKER"
echo "GPU type: {gpu_type}"
echo "Difficulty: {difficulty}"

mkdir -p "$MINING_DIR"

# Kill any existing miner processes (both alpha-miner and mine.sh wrappers)
pkill -9 alpha-miner 2>/dev/null || true
pkill -9 mine.sh 2>/dev/null || true
sleep 2

# Double check: ensure no alpha-miner processes remain
if pgrep -f alpha-miner > /dev/null 2>&1; then
    echo "WARNING: Still detecting alpha-miner processes, forcing kill..."
    pkill -9 -f alpha-miner
    sleep 1
fi

echo "[1/3] Downloading alpha-miner v1.7.6..."
curl -sL --connect-timeout 30 --retry 3 \\
    -o "$MINING_DIR/alpha-miner" \\
    "{ALPHA_MINER_URL}"
chmod +x "$MINING_DIR/alpha-miner"
$MINING_DIR/alpha-miner --version 2>&1 || true

echo "[2/3] Using selected pool..."
BEST="eu2"
BEST_MS=999
echo "  => Best: $BEST"

GPU_COUNT=$(nvidia-smi -L 2>/dev/null | wc -l)
DEVICES=$(seq -s, 0 $((GPU_COUNT - 1)))
echo "GPUs: $GPU_COUNT ($DEVICES)"

echo "[3/3] Starting miner..."

# Check if miner is already running before starting new one
if pgrep -f alpha-miner > /dev/null 2>&1; then
    echo "WARNING: alpha-miner already running, skipping start"
    CONNECTED=$(grep -c "connected" $MINING_DIR/miner.log 2>/dev/null || echo 0)
    echo "=== Already running: $CONNECTED GPUs connected ==="
    echo "Log: $MINING_DIR/miner.log"
    echo "Worker: $WORKER"
    exit 0
fi

cat > $MINING_DIR/mine.sh << SCRIPT
#!/bin/bash
cd "\\$(dirname "\\$0")"
while true; do
    for pool in $BEST.alphapool.tech:{POOL_PORT} \\
               eu2.alphapool.tech:{POOL_PORT} \\
               us1.alphapool.tech:{POOL_PORT} \\
               sg1.alphapool.tech:{POOL_PORT} \\
               eu1.alphapool.tech:{POOL_PORT}; do
        echo "[\\$(date '+%H:%M:%S')] Connecting to \\$pool..."
        ./alpha-miner \\
            --pool "\\$pool" \\
            --address {WALLET}.$WORKER \\
            --password "x;d={difficulty}" \\
            --devices $DEVICES \\
            --status-interval 60 \\
            --color never
        echo "[\\$(date '+%H:%M:%S')] Disconnected, retrying in 10s..."
        sleep 10
    done
done
SCRIPT
chmod +x $MINING_DIR/mine.sh

> $MINING_DIR/miner.log
nohup $MINING_DIR/mine.sh >> $MINING_DIR/miner.log 2>&1 &
sleep 8
CONNECTED=$(grep -c "connected" $MINING_DIR/miner.log 2>/dev/null || echo 0)
echo "=== Done: $CONNECTED GPUs connected ==="
echo "Log: $MINING_DIR/miner.log"
echo "Worker: $WORKER"
"""


def generate_stop_script(mining_dir: str = "$HOME/mining") -> str:
    """Generate script to stop the miner on a remote host."""
    return f"""#!/bin/bash
if pkill -9 alpha-miner 2>/dev/null; then
    echo "Miner stopped."
else
    echo "No miner running."
fi
"""


def generate_status_script(mining_dir: str = "$HOME/mining") -> str:
    """Generate script to check miner status on a remote host."""
    return f"""#!/bin/bash
if pgrep -f alpha-miner > /dev/null 2>&1; then
    echo "RUNNING (PID: $(pgrep -f alpha-miner | head -1))"
    tail -5 {mining_dir}/miner.log 2>/dev/null
else
    echo "NOT RUNNING"
fi
"""


def generate_start_script(mining_dir: str = "$HOME/mining") -> str:
    """Generate script to start an already-deployed miner."""
    return f"""#!/bin/bash
cd {mining_dir}
if [ ! -f mine.sh ]; then
    echo "ERROR: Miner not deployed. Run deploy first."
    exit 1
fi
if pgrep -f alpha-miner > /dev/null 2>&1; then
    echo "Miner already running (PID: $(pgrep -f alpha-miner | head -1))"
    exit 0
fi
nohup ./mine.sh >> miner.log 2>&1 &
sleep 5
if pgrep -f alpha-miner > /dev/null 2>&1; then
    echo "Miner started (PID: $(pgrep -f alpha-miner | head -1))"
else
    echo "ERROR: Miner failed to start. Check {mining_dir}/miner.log"
    exit 1
fi
"""
