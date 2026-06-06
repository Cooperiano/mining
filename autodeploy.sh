#!/bin/bash
# Autodeploy cron wrapper — checks costs, kills bad instances, deploys new ones
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python)"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] autodeploy start" >> "$DIR/autodeploy.log"
$PYTHON minerctl.py vast autodeploy >> "$DIR/autodeploy.log" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] autodeploy end" >> "$DIR/autodeploy.log"
