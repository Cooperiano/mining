#!/bin/bash
# Phase 3 Cron — Fully automated profitability system
# Recommended schedule: every 1-2 minutes for interruptible-heavy ops
# For testing: comment out discovery (use --no-discover flag)

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd /home/julian/projects/mining || exit 1

LOG_FILE="/home/julian/projects/mining/autodeploy.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] phase3 cycle start" >> "$LOG_FILE"

# Full automated cycle: discovery + management + profitability + optimization
python3 automated_profit_system.py >> "$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] phase3 cycle end" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"