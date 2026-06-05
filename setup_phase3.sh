#!/bin/bash
# Quick setup script for Phase 3 deployment

set -e

cd "$(dirname "$0")"

echo "=== Pearl Mining - Phase 3 Setup ==="
echo

# 1. Make scripts executable
echo "[1/4] Making scripts executable..."
chmod +x offer_discovery.py
chmod +x autodeploy_enhanced.py
chmod +x automated_profit_system.py
chmod +x autodeploy_phase3.sh

# 2. Initialize state files
echo "[2/4] Initializing state files..."
touch .vast_deployed .vast_bad .vast_blacklist .vast_saved
touch .last_discovery
touch .profit_state .optimization_state

# 3. Test profitability report
echo "[3/4] Testing profitability report..."
if python3 automated_profit_system.py --report 2>&1 | grep -q "PROFITABILITY REPORT"; then
    echo "  ✓ Profitability report working"
else
    echo "  ⚠ Profitability report may have issues (check vast.ai/AlphaPool connectivity)"
fi

# 4. Show cron command
echo "[4/4] Cron installation command:"
echo
echo "  # Add to your crontab (crontab -e):"
echo "  */2 * * * * $PWD/autodeploy_phase3.sh"
echo
echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. Review IMPLEMENTATION_ROADMAP.md"
echo "  2. Run: python3 automated_profit_system.py --report"
echo "  3. Run: python3 automated_profit_system.py --dry-run"
echo "  4. Install cron if satisfied"
echo
echo "For monitoring:"
echo "  tail -f autodeploy.log"
echo