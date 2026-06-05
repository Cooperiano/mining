#!/bin/bash
# ============================================================
#  Pearl (PRL) Mining Setup — one-command deployment
#  Works on: Ubuntu/Debian with NVIDIA GPU + CUDA drivers
# ============================================================
set -e

# --- CONFIG (edit these) ------------------------------------
WALLET="prl1pyvv3nzlvyahzgdhsg4c4sm3z6ukv9zcc39genld24yw4thmet6asevn44h"
WORKER="miner1"
POOL="eu2.alphapool.tech:5566"   # lowest ping from tested regions
# --- END CONFIG --------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "=============================================="
echo "  Pearl Mining Setup"
echo "=============================================="
echo ""

# 1. Check NVIDIA GPU
echo -n "Checking GPU... "
if ! command -v nvidia-smi &>/dev/null; then
    echo -e "${RED}FAIL${NC} — nvidia-smi not found. Install NVIDIA drivers first."
    exit 1
fi
GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
if [ -z "$GPU" ]; then
    echo -e "${RED}FAIL${NC} — No NVIDIA GPU detected."
    exit 1
fi
echo -e "${GREEN}$GPU${NC}"

# 2. Check CUDA
echo -n "Checking CUDA... "
if ! nvidia-smi 2>/dev/null | grep -q "CUDA"; then
    echo -e "${RED}FAIL${NC} — CUDA not available."
    exit 1
fi
CUDA_VER=$(nvidia-smi | grep -oP 'CUDA Version: \K[0-9.]+')
echo -e "${GREEN}$CUDA_VER${NC}"

# 3. Download alpha-miner
ALPHA_URL="https://api.github.com/repos/AlphaMine-Tech/alpha-miner/releases/latest"
echo ""
echo "Fetching latest alpha-miner version..."
RELEASE=$(curl -s --connect-timeout 15 "$ALPHA_URL" 2>/dev/null)
VERSION=$(echo "$RELEASE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tag_name','unknown'))" 2>/dev/null)
echo "Latest: $VERSION"

# Get download asset ID
ASSET_ID=$(echo "$RELEASE" | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('assets',[]):
    if a['name'] == 'alpha-miner' and 'linux' not in a['name'].lower():
        print(a['id']); break
" 2>/dev/null)

if [ -z "$ASSET_ID" ]; then
    echo "Looking for binary in release assets..."
    ASSET_ID=$(echo "$RELEASE" | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('assets',[]):
    if 'miner' in a['name'].lower() and 'setup' not in a['name'].lower():
        print(a['id']); break
" 2>/dev/null)
fi

if [ -z "$ASSET_ID" ]; then
    echo -e "${RED}FAIL${NC} — Could not find alpha-miner binary in release."
    # Show available assets for debugging
    echo "$RELEASE" | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('assets',[]):
    print(f\"  {a['name']} ({a['size']} bytes)\")
" 2>/dev/null
    exit 1
fi

echo "Downloading alpha-miner (asset $ASSET_ID)..."
curl -s -L -H "Accept: application/octet-stream" \
    -o alpha-miner \
    "https://api.github.com/repos/AlphaMine-Tech/alpha-miner/releases/assets/$ASSET_ID" \
    -w "  Downloaded: %{size_download} bytes\n" 2>/dev/null
chmod +x alpha-miner
echo -e "${GREEN}alpha-miner downloaded${NC}"

# 4. Verify miner works
echo ""
echo "Verifying miner..."
./alpha-miner --list-devices 2>&1 || {
    echo -e "${RED}Miner verification failed${NC}"
    exit 1
}

# 5. Create mining start script
cat > mine_pearl.sh << SCRIPT
#!/bin/bash
cd "\$(dirname "\$0")"

WALLET="${WALLET}.\${WORKER:-miner1}"
POOLS=(
  "eu2.alphapool.tech:5566"
  "eu1.alphapool.tech:5566"
  "ru1.alphapool.tech:5566"
  "sg1.alphapool.tech:5566"
  "us1.alphapool.tech:5566"
  "us2.alphapool.tech:5566"
)

echo "Starting Pearl miner on RTX 3080..."
echo "Wallet: \$WALLET"
echo "Pools: \${POOLS[*]}"
echo ""

while true; do
  for pool in "\${POOLS[@]}"; do
    echo "[\$(date '+%H:%M:%S')] Connecting to \$pool..."
    ./alpha-miner \
      --pool "\$pool" \
      --address "\$WALLET" \
      --status-interval 120 \
      --color always
    echo "[\$(date '+%H:%M:%S')] Disconnected from \$pool, retrying in 10s..."
    sleep 10
  done
done
SCRIPT
chmod +x mine_pearl.sh
echo -e "${GREEN}Start script created: mine_pearl.sh${NC}"

# 6. Summary
echo ""
echo "=============================================="
echo "  Setup Complete"
echo "=============================================="
echo ""
echo "  To start mining:"
echo "    ./mine_pearl.sh                    # foreground"
echo "    screen -S pearl ./mine_pearl.sh    # detachable"
echo "    tmux new -s pearl ./mine_pearl.sh  # detachable"
echo ""
echo "  Dashboard: https://pearl.alphapool.tech/#dashboard"
echo "  Wallet:    $WALLET"
echo "=============================================="
