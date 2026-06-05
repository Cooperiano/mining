#!/bin/bash
# Autodeploy cron wrapper — checks costs, kills bad instances, deploys new ones
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd /Users/juliancooper/Desktop/projects/mining || exit 1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] autodeploy start" >> /Users/juliancooper/Desktop/projects/mining/autodeploy.log
python3 minerctl.py vast autodeploy >> /Users/juliancooper/Desktop/projects/mining/autodeploy.log 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] autodeploy end" >> /Users/juliancooper/Desktop/projects/mining/autodeploy.log
