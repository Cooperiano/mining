#!/usr/bin/env python3
"""Phase 3: Fully automated profitability system.

Integration of:
- Phase 1: Instance management (vast.py autodeploy_cycle)
- Phase 2: Market discovery + bid optimization (offer_discovery.py)
- Phase 3: Real-time profitability tracking + dynamic optimization

Architecture:
  Cron (1 min) → enhanced_autodeploy_cycle
                  ├── Market discovery (every hour)
                  │   ├── Scan market
                  │   ├── Score offers
                  │   ├── Auto-bid top 3
                  │   └── Save to history
                  ├── Instance management (every cycle)
                  │   ├── Cost check → kill high-cost
                  │   ├── Performance check → kill low-hashrate
                  │   └── Deploy to new running instances
                  └── Profitability analysis (every cycle)
                      ├── Real-time cost/earnings
                      ├── Per-GPU profitability
                      └── Dynamic threshold adjustment

Key Metrics:
  - Net profit = earnings - rental_cost
  - Profit margin = net_profit / earnings
  - Fleet utilization = running GPUs / total GPUs bid

Auto-optimization:
  - If fleet utilization < 50% → increase bid aggression
  - If net profit < 0 for 1 hour → reduce bid prices 20%
  - If profit margin > 40% → increase bid prices 10% (capture more offers)
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR))

# Core modules
from manager import vast
from offer_discovery import scan_market, calculate_optimal_bid, save_to_history, HISTORY_DB

# State files
PROFIT_STATE_FILE = MINING_DIR / ".profit_state"
OPTIMIZATION_FILE = MINING_DIR / ".optimization_state"

# Profitability thresholds (will be auto-adjusted)
DEFAULT_CONFIG = {
    "min_profit_margin": 0.15,      # 15% minimum profit margin
    "max_fleet_utilization": 0.8,   # 80% max utilization (avoid over-expansion)
    "bid_aggression": 0.7,          # 70% of break-even (lower = more conservative)
    "profit_history_hours": 24,     # Track 24h profit history
    "optimization_interval": 3600,  # Re-optimize every hour
}


def _load_profit_state() -> dict:
    """Load profitability state."""
    if PROFIT_STATE_FILE.exists():
        try:
            return json.loads(PROFIT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"history": [], "current": {}}


def _save_profit_state(state: dict) -> None:
    """Save profitability state."""
    PROFIT_STATE_FILE.write_text(json.dumps(state, indent=2))


def _load_optimization_state() -> dict:
    """Load optimization state."""
    if OPTIMIZATION_FILE.exists():
        try:
            return json.loads(OPTIMIZATION_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_CONFIG.copy()


def _save_optimization_state(state: dict) -> None:
    """Save optimization state."""
    OPTIMIZATION_FILE.write_text(json.dumps(state, indent=2))


def calculate_real_time_profitability() -> dict:
    """Calculate real-time profitability from vast.ai and AlphaPool."""
    wallet = "REDACTED_WALLET"
    api_url = f"https://pearl.alphapool.tech/api/miner/{wallet}"

    # Get instances
    rc, stdout, _ = vast._vastai(["show", "instances", "--raw"])
    if rc != 0:
        return {"error": "Failed to get instances"}

    try:
        instances = json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "Failed to parse instances"}

    running_instances = [i for i in instances if i.get("actual_status") == "running"]

    # Get pool data
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            pool_data = json.loads(resp.read())
    except Exception as e:
        return {"error": f"Failed to get pool data: {e}"}

    # Build worker hashrate map
    worker_th: dict[str, float] = {}
    total_th = 0.0
    for w in pool_data.get("workers", []):
        try:
            live = float(w["hashrate_live"].split()[0])
            name = w["name"]
            worker_th[name] = live
            total_th += live
        except (ValueError, KeyError):
            pass

    # Calculate per-instance profitability
    earn_rate = 3.226  # PRL/hr per TH/s
    prl_price = 0.80  # Hardcoded for now, could be dynamic from API

    instance_profits = []
    total_cost = 0.0
    total_earnings = 0.0

    for inst in running_instances:
        inst_id = str(inst["id"])
        gpu_count = inst.get("num_gpus", 1)
        gpu_model = inst.get("gpu_name", "Unknown")
        try:
            price_total = float(inst.get("dph_total", 0))
        except (ValueError, TypeError):
            price_total = 0.0

        # Match instance to worker by ID suffix
        suffix = inst_id[-4:]
        inst_th = sum(v for k, v in worker_th.items() if suffix in k)
        inst_earnings_prl = inst_th / 1000 * earn_rate
        inst_earnings_usd = inst_earnings_prl * prl_price

        profit = inst_earnings_usd - price_total
        profit_margin = profit / inst_earnings_usd if inst_earnings_usd > 0 else -1

        instance_profits.append({
            "id": inst_id,
            "gpu_model": gpu_model,
            "gpu_count": gpu_count,
            "cost_usd_hr": price_total,
            "th_s": inst_th,
            "earnings_usd_hr": inst_earnings_usd,
            "profit_usd_hr": profit,
            "profit_margin": profit_margin,
        })

        total_cost += price_total
        total_earnings += inst_earnings_usd

    net_profit = total_earnings - total_cost
    fleet_utilization = sum(i["gpu_count"] for i in instance_profits) / (sum(i.get("num_gpus", 0) for i in instances) or 1)

    return {
        "timestamp": datetime.now().isoformat(),
        "running_instances": len(running_instances),
        "total_gpus": sum(i["gpu_count"] for i in instance_profits),
        "total_th_s": total_th,
        "total_cost_usd_hr": total_cost,
        "total_earnings_usd_hr": total_earnings,
        "net_profit_usd_hr": net_profit,
        "profit_margin": net_profit / total_earnings if total_earnings > 0 else -1,
        "fleet_utilization": fleet_utilization,
        "instances": instance_profits,
    }


def optimize_parameters(profitability: dict) -> list[str]:
    """Auto-optimize bidding parameters based on profitability trends."""
    log = []
    state = _load_optimization_state()

    # Check if it's time to re-optimize
    if not profitability.get("instances"):
        return log

    net_profit = profitability["net_profit_usd_hr"]
    profit_margin = profitability["profit_margin"]
    utilization = profitability["fleet_utilization"]

    log.append(f"Current: net_profit=${net_profit:.3f}/hr, margin={profit_margin:.1%}, utilization={utilization:.1%}")

    # Optimization logic
    changes = []

    # If profit margin too low → reduce bids
    if profit_margin < state["min_profit_margin"] * 0.5:
        new_aggression = max(state["bid_aggression"] * 0.8, 0.4)  # Reduce by 20%, min 40%
        state["bid_aggression"] = new_aggression
        changes.append(f"Reduced bid aggression to {new_aggression:.1%} (low profit margin)")
    # If profit margin high → increase bids to capture more offers
    elif profit_margin > state["min_profit_margin"] * 2:
        new_aggression = min(state["bid_aggression"] * 1.1, 0.9)  # Increase by 10%, max 90%
        state["bid_aggression"] = new_aggression
        changes.append(f"Increased bid aggression to {new_aggression:.1%} (high profit margin)")

    # If utilization too low → check if we need more aggressive bidding
    if utilization < 0.5 and profit_margin > 0:
        log.append("WARNING: Low fleet utilization (<50%) but profitable - consider manual review")

    # Apply changes
    if changes:
        log.extend(changes)
        _save_optimization_state(state)

    return log


def record_profit_history(profitability: dict) -> None:
    """Record profitability to history."""
    state = _load_profit_state()

    # Add current snapshot
    snapshot = {
        "timestamp": profitability["timestamp"],
        "net_profit_usd_hr": profitability["net_profit_usd_hr"],
        "profit_margin": profitability["profit_margin"],
        "fleet_utilization": profitability["fleet_utilization"],
        "running_instances": profitability["running_instances"],
    }
    state["history"].append(snapshot)

    # Trim to last N hours
    cutoff = datetime.now() - timedelta(hours=state.get("max_hours", 24))
    state["history"] = [
        h for h in state["history"]
        if datetime.fromisoformat(h["timestamp"]) > cutoff
    ]

    state["current"] = snapshot
    _save_profit_state(state)


def generate_profitability_report() -> str:
    """Generate comprehensive profitability report."""
    profitability = calculate_real_time_profitability()

    if "error" in profitability:
        return f"Error: {profitability['error']}"

    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    lines = [
        f"\n{BOLD}{'='*90}{RESET}",
        f"{BOLD}  PROFITABILITY REPORT @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}",
        f"{BOLD}{'='*90}{RESET}\n",
    ]

    # Summary
    net = profitability["net_profit_usd_hr"]
    margin = profitability["profit_margin"]
    util = profitability["fleet_utilization"]

    color = GREEN if net > 0 else RED
    lines.append(f"  {BOLD}Summary:{RESET}")
    lines.append(f"    Running instances: {profitability['running_instances']}")
    lines.append(f"    Total GPUs: {profitability['total_gpus']}")
    lines.append(f"    Total TH/s: {profitability['total_th_s']:.1f}")
    lines.append(f"    Rental cost: ${profitability['total_cost_usd_hr']:.3f}/hr")
    lines.append(f"    Earnings: ${profitability['total_earnings_usd_hr']:.3f}/hr")
    lines.append(f"    {BOLD}Net profit: {color}${net:.3f}/hr{RESET}")
    lines.append(f"    Profit margin: {color}{margin:.1%}{RESET}")
    lines.append(f"    Fleet utilization: {CYAN}{util:.1%}{RESET}")

    # Per-instance breakdown
    if profitability["instances"]:
        lines.append(f"\n  {BOLD}Instance Breakdown:{RESET}")
        lines.append(f"    {'ID':<10} {'GPU':<12} {'GPUs':>4} {'Cost':>9} {'TH/s':>8} {'Earn':>8} {'Profit':>8}")
        lines.append(f"    {'─'*10} {'─'*12} {'─'*4} {'─'*9} {'─'*8} {'─'*8} {'─'*8}")

        for inst in profitability["instances"]:
            inst_color = GREEN if inst["profit_usd_hr"] > 0 else RED
            lines.append(
                f"    {inst['id'][-8:]:<10} {inst['gpu_model'][:10]:<12} {inst['gpu_count']:>4} "
                f"${inst['cost_usd_hr']:>8.3f} {inst['th_s']:>8.1f} "
                f"${inst['earnings_usd_hr']:>7.3f} {inst_color}${inst['profit_usd_hr']:>7.3f}{RESET}"
            )

    lines.append(f"\n{BOLD}{'='*90}{RESET}")
    return "\n".join(lines)


def full_automated_cycle(skip_discovery: bool = False, dry_run_discovery: bool = False) -> str:
    """Full automated cycle: discovery + management + profitability + optimization."""
    log = []

    # Phase 2: Market discovery
    if not skip_discovery and vast._should_discover():
        log.append("=== Market Discovery ===")
        from autodeploy_enhanced import discover_and_bid_cycle
        discovery_log = discover_and_bid_cycle(dry_run=dry_run_discovery, max_bids=3)
        log.extend(discovery_log)
        log.append("")

    # Phase 1: Instance management
    log.append("=== Instance Management ===")
    management_log = vast.autodeploy_cycle()
    log.append(management_log)
    log.append("")

    # Phase 3: Profitability analysis
    log.append("=== Profitability Analysis ===")
    profitability = calculate_real_time_profitability()

    if "error" not in profitability:
        record_profit_history(profitability)
        log.append(f"Net profit: ${profitability['net_profit_usd_hr']:.3f}/hr "
                   f"(margin: {profitability['profit_margin']:.1%})")

        # Optimization
        optimization_log = optimize_parameters(profitability)
        if optimization_log:
            log.append("\n=== Optimization ===")
            log.extend(optimization_log)
    else:
        log.append(f"Error: {profitability['error']}")

    return "\n".join(log)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Phase 3: Fully automated profitability system")
    parser.add_argument("--report", action="store_true", help="Generate profitability report")
    parser.add_argument("--no-discover", action="store_true", help="Skip market discovery")
    parser.add_argument("--dry-run", action="store_true", help="Dry run discovery")
    parser.add_argument("--optimize", action="store_true", help="Run optimization only")

    args = parser.parse_args()

    if args.report:
        print(generate_profitability_report())
    elif args.optimize:
        profitability = calculate_real_time_profitability()
        if "error" not in profitability:
            record_profit_history(profitability)
            log = optimize_parameters(profitability)
            print("\n".join(log))
        else:
            print(f"Error: {profitability['error']}")
    else:
        result = full_automated_cycle(
            skip_discovery=args.no_discover,
            dry_run_discovery=args.dry_run,
        )
        print(result)


if __name__ == "__main__":
    main()