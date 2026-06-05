#!/usr/bin/env python3
"""Cost Control Module - Ensure total rental cost stays within budget.

MAX_TOTAL_COST_USD_HR = 10.0

Usage:
  from cost_control import check_cost_limit, get_current_cost
  if check_cost_limit(new_instance_cost):
      # Safe to bid
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR))

# Maximum total rental cost per hour
MAX_TOTAL_COST_USD_HR = 10.0


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr)."""
    try:
        # Ensure miniconda3 is in PATH for vastai CLI
        env = os.environ.copy()
        env['PATH'] = f'{os.path.expanduser("~/miniconda3/bin")}:{env.get("PATH", "")}'
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except OSError as e:
        return -1, "", str(e)


def get_current_cost() -> float:
    """Get current total rental cost from vast.ai."""
    rc, stdout, _ = _run(["vastai", "show", "instances", "--raw"])
    if rc != 0:
        return 0.0

    try:
        data = json.loads(stdout)
        total_cost = 0.0
        for item in data:
            if item.get("actual_status") == "running":
                total_cost += float(item.get("dph_total", 0))
        return total_cost
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0.0


def check_cost_limit(new_cost: float, max_limit: float = MAX_TOTAL_COST_USD_HR) -> tuple[bool, float, float]:
    """Check if adding a new instance would exceed cost limit.

    Returns:
        (allowed, current_cost, remaining_budget)
    """
    current_cost = get_current_cost()
    total_cost = current_cost + new_cost
    allowed = total_cost <= max_limit
    remaining = max_limit - current_cost
    return allowed, current_cost, remaining


def print_cost_status() -> None:
    """Print current cost status."""
    current_cost = get_current_cost()
    remaining = MAX_TOTAL_COST_USD_HR - current_cost
    utilization = current_cost / MAX_TOTAL_COST_USD_HR

    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  COST CONTROL STATUS{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    color = GREEN if utilization < 0.8 else (YELLOW if utilization < 0.95 else RED)
    print(f"  Current cost: ${current_cost:.3f}/hr")
    print(f"  Budget limit: ${MAX_TOTAL_COST_USD_HR:.3f}/hr")
    print(f"  Remaining: ${remaining:.3f}/hr")
    print(f"  Utilization: {color}{utilization:.1%}{RESET}")

    if remaining <= 0:
        print(f"\n  {RED}[ALERT] Cost limit reached!{RESET}")
    elif remaining < 1.0:
        print(f"\n  {YELLOW}[WARNING] Budget almost exhausted (<$1.00 remaining){RESET}")

    print(f"\n{BOLD}{'='*60}{RESET}\n")


if __name__ == "__main__":
    print_cost_status()