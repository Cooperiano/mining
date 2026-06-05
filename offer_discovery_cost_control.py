#!/usr/bin/env python3
"""Phase 2 Enhanced - Cost-Controlled Offer Discovery.

Integrates:
- Market scanning with PFD > 300 filter
- Cost control ($10/hr limit)
- Auto-bidding with budget checking

Usage:
  python3 offer_discovery_cost_control.py          # Scan + show
  python3 offer_discovery_cost_control.py --bid    # Show bids with cost check
  python3 offer_discovery_cost_control.py --auto   # Auto-bid with cost control
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from datetime import datetime

MINING_DIR = Path(__file__).resolve().parent
HISTORY_DB = MINING_DIR / "market_history.json"

# Import from vast module
sys.path.insert(0, str(MINING_DIR / "manager"))
from vast import _vastai, _strip_ansi, GPU_HASHRATES, _gpu_break_even

# Import cost control
from cost_control import check_cost_limit, get_current_cost, MAX_TOTAL_COST_USD_HR, print_cost_status

# Configuration - SUPPORTED GPUs
# RTX 50 Series (Blackwell)
TARGET_GPUS = [
    "RTX_5090", "RTX_5080", "RTX_5070_TI", "RTX_5070",
    # RTX 40 Series (Ada)
    "RTX_4090", "RTX_4080", "RTX_4070_TI", "RTX_4070",
    "RTX_4060_TI", "RTX_4060",
    # RTX 30 Series (Ampere)
    "RTX_3090_TI", "RTX_3090", "RTX_3080_TI", "RTX_3080",
    "RTX_3070_TI", "RTX_3070", "RTX_3060_TI", "RTX_3060",
    # Data Center Cards
    "H100", "H200", "B100", "B200", "A100",
    "L40", "L40S", "L4", "RTX_6000_ADA", "RTX_A6000", "RTX_A5000", "RTX_A4000",
]

# Discount from break-even (0.8 = 80% of break-even price)
DISCOUNT_FACTOR = 0.7

# Maximum bid as ratio to break-even (1.2 = max 120%)
MAX_BID_RATIO = 1.2

# Performance thresholds (PFLOPS per dollar)
# User preference: PFD > 330 minimum, > 360 preferred, > 400 optimal
MIN_PFD = 330.0  # Minimum acceptable (raised from 300 based on user feedback)
OPTIMAL_PFD = 400.0  # Target/optimal (400+ as requested)


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


def _vastai(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    return _run(["vastai"] + args, timeout=timeout)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _search_offers(gpu_name: str, max_price: float | None = None) -> list[dict]:
    """Search vast.ai for offers and parse into structured data."""
    query = f"gpu_name={gpu_name} rentable=true verified=true direct_port_count>=1"
    if max_price is not None:
        query += f" max_price<={max_price}"

    rc, stdout, stderr = _vastai(["search", "offers", query, "-o", "dlperf_per_dphtotal-", "--raw"])
    if rc != 0:
        return []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    offers = []
    for item in data:
        if not isinstance(item, dict):
            continue

        try:
            offers.append({
                "id": str(item.get("id", "")),
                "gpu_name": item.get("gpu_name", ""),
                "num_gpus": int(item.get("num_gpus", 1)),
                # PFD = dlperf per dollar per hour (correct field name)
                "dlperf_usd": float(item.get("dlperf_per_dphtotal", 0) or 0),
                "dlperf": float(item.get("dlperf", 0) or 0),
                "flops_per_dphtotal": float(item.get("flops_per_dphtotal", 0) or 0),
                "min_bid": float(item.get("min_bid", 0) or 0),
                "dph_total": float(item.get("dph_total", 0) or 0),
                "cuda_max_good": item.get("cuda_max_good", ""),
                "inet_up": float(item.get("inet_up", 0) or 0),
                "inet_down": float(item.get("inet_down", 0) or 0),
                "reliability2": float(item.get("reliability2", 0) or 0),
                "direct_port_count": int(item.get("direct_port_count", 0) or 0),
                "storage_total_cost": float(item.get("storage_total_cost", 0) or 0),
                "geolocation": item.get("geolocation", ""),
                "gpu_ram": int(item.get("gpu_total_ram", 0) or 0),
                "verification": item.get("verification", ""),
            })
        except (ValueError, TypeError):
            continue

    return offers


def _score_offer(offer: dict) -> float:
    """Score an offer based on multiple factors.

    CRITICAL: dlperf_usd (PFLOPS/$) must be > 300, 400+ is optimal.
    """
    score = 0.0
    pfd = offer["dlperf_usd"]

    # PRIMARY: PFLOPS per dollar (CRITICAL metric)
    # Below 300 = hard penalty, 400+ = bonus
    if pfd < MIN_PFD:
        return 0  # Reject offers below threshold

    # Linear bonus: 330 = base, 360 = +50 bonus, 400+ = +100 bonus
    pfd_score = ((pfd - MIN_PFD) / (OPTIMAL_PFD - MIN_PFD)) * 50
    score += min(pfd_score + 50, 100)  # Base 50 for meeting minimum

    # Network bandwidth (higher is better for mining)
    # Normalize: 1000 Mbps = 10 points
    score += min(offer["inet_up"] / 1000 * 10, 10)

    # Reliability score (0-1 scale)
    score += offer["reliability2"] * 20

    # Direct ports (for low-latency pool)
    score += min(offer["direct_port_count"] * 5, 15)

    # Storage cost penalty
    score -= min(offer["storage_total_cost"] * 2, 10)

    # Minimum bid price penalty (too high = bad)
    gpu_type = offer["gpu_name"].lower().replace(" ", "_")
    be = _gpu_break_even(gpu_type)
    if be > 0:
        bid_ratio = offer["min_bid"] / be
        if bid_ratio > 0.8:
            score -= (bid_ratio - 0.8) * 50  # Penalty for overpriced

    return max(score, 0)


def calculate_optimal_bid(gpu_model: str) -> dict:
    """Calculate optimal bid based on break-even and market factors.

    Also checks PFLOPS/$ of available offers to ensure quality.
    """
    gpu_type = gpu_model.lower().replace(" ", "_")

    break_even = _gpu_break_even(gpu_type)
    if break_even == 0:
        return {"gpu_model": gpu_model, "break_even": 0, "optimal_bid": 0, "reason": "unknown GPU"}

    # Base bid: discount factor below break-even
    base_bid = break_even * DISCOUNT_FACTOR

    # Max bid: ratio above break-even
    max_bid = break_even * MAX_BID_RATIO

    # Current market adjustment (scan for recent prices)
    offers = _search_offers(gpu_model, max_price=max_bid)

    # Filter offers by PFLOPS/$ threshold
    quality_offers = [o for o in offers if o["dlperf_usd"] >= MIN_PFD]

    if quality_offers:
        avg_price = sum(o["min_bid"] for o in quality_offers[:5]) / min(len(quality_offers), 5)
        avg_pfd = sum(o["dlperf_usd"] for o in quality_offers[:5]) / min(len(quality_offers), 5)
        # Adjust towards market average (but stay aggressive)
        adjusted_bid = (base_bid + avg_price * 0.3) / 1.3
    else:
        adjusted_bid = base_bid
        avg_pfd = 0

    optimal_bid = min(max(adjusted_bid, 0.01), max_bid)

    return {
        "gpu_model": gpu_model,
        "break_even": round(break_even, 4),
        "base_bid": round(base_bid, 4),
        "market_avg": round(quality_offers[0]["min_bid"], 4) if quality_offers else None,
        "avg_pfd": round(avg_pfd, 1) if quality_offers else 0,
        "optimal_bid": round(optimal_bid, 4),
        "max_bid": round(max_bid, 4),
        "expected_th": GPU_HASHRATES.get(gpu_type, 0),
        "expected_profit": round(optimal_bid * -1 + (GPU_HASHRATES.get(gpu_type, 0) / 1000 * 3.226 * 0.80), 3),
        "quality_offers": len(quality_offers),
    }


def scan_market(gpu_name: str | None = None) -> list[dict]:
    """Scan market for all target GPUs or specific GPU."""
    if gpu_name:
        targets = [gpu_name]
    else:
        targets = TARGET_GPUS

    all_offers = []
    for gpu in targets:
        break_even = _gpu_break_even(gpu.lower().replace(" ", "_"))
        max_price = break_even * MAX_BID_RATIO if break_even else 1.0

        offers = _search_offers(gpu, max_price=max_price)

        for offer in offers:
            offer["score"] = _score_offer(offer)
            offer["break_even"] = break_even
            offer["bid_ratio"] = offer["min_bid"] / break_even if break_even > 0 else 0
            offer["scan_time"] = datetime.now().isoformat()

        all_offers.extend(offers)

    # Sort by score
    all_offers.sort(key=lambda x: x["score"], reverse=True)

    return all_offers


def save_to_history(offers: list[dict]) -> None:
    """Save scan results to history database."""
    history = {"offers": offers, "scan_time": datetime.now().isoformat()}

    # Load existing history
    if HISTORY_DB.exists():
        try:
            existing = json.loads(HISTORY_DB.read_text())
            if isinstance(existing, dict) and "history" in existing:
                # Append to history array (max 1000 entries)
                history["history"] = existing["history"][-999:] + [history]
            else:
                history["history"] = [history]
        except (json.JSONDecodeError, KeyError):
            history["history"] = [history]
    else:
        history["history"] = [history]

    HISTORY_DB.write_text(json.dumps(history, indent=2))


def place_bid(offer_id: str, bid_price: float, dry_run: bool = False) -> str:
    """Place a bid on an offer."""
    if dry_run:
        return f"[DRY-RUN] Would bid ${bid_price:.4f}/hr on offer {offer_id}"

    cmd = ["create", "instance", str(offer_id), "--min-bid", str(bid_price)]
    rc, stdout, stderr = _vastai(cmd, timeout=60)

    if rc != 0:
        return f"Failed to bid on {offer_id}: {stderr or stdout[:200]}"

    try:
        result = json.loads(stdout)
        contract_id = result.get("new_contract")
        return f"Bid placed: ${bid_price:.4f}/hr on {offer_id} → contract {contract_id}"
    except json.JSONDecodeError:
        return f"Bid placed: ${bid_price:.4f}/hr on {offer_id} (response: {stdout[:100]})"


def print_top_offers(offers: list[dict], limit: int = 20) -> None:
    """Print top offers in formatted table.

    Shows PFLOPS/$ prominently - > 300 is minimum, > 400 is optimal.
    """
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{'='*115}{RESET}")
    print(f"{BOLD}  TOP OFFERS (PFD > {int(MIN_PFD)}, optimal > {int(OPTIMAL_PFD)}) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'='*115}{RESET}\n")

    print(f"  {'ID':<10} {'GPU':<12} {'GPUs':>4} {'Score':>6} {'$/hr':>7} {'Ratio':>6} {'PFD':>6} {'Quality':>10} {'Rel':>4} {'Net Up':>8}")
    print(f"  {'─'*10} {'─'*12} {'─'*4} {'─'*6} {'─'*7} {'─'*6} {'─'*6} {'─'*10} {'─'*4} {'─'*8}")

    for offer in offers[:limit]:
        id_str = offer["id"][:8]
        gpu = offer["gpu_name"][:10]
        gpus = offer["num_gpus"]
        score = offer["score"]
        price = offer["min_bid"]
        ratio = offer["bid_ratio"]
        pfd = offer["dlperf_usd"]
        rel = offer["reliability2"]
        net = offer["inet_up"]

        # Color code PFD
        if pfd >= OPTIMAL_PFD:
            pfd_color = GREEN
            quality = "EXCELLENT"
        elif pfd >= 360.0:
            pfd_color = YELLOW
            quality = "GOOD"
        elif pfd >= MIN_PFD:
            pfd_color = YELLOW
            quality = "OK"
        else:
            pfd_color = RED
            quality = "POOR"

        # Color code price ratio
        price_color = GREEN if ratio < 0.7 else (YELLOW if ratio < 0.9 else RED)

        print(f"  {id_str:<10} {gpu:<12} {gpus:>4} {score:>6.1f} ${price:<6.3f} {price_color}{ratio:>5.2f}x{RESET} "
              f"{pfd_color}{pfd:>6.1f}{RESET} {pfd_color}{quality:<10}{RESET} {rel:>3.0f} {net:>6} Mbps")

    print(f"\n{BOLD}{'='*115}{RESET}")
    print(f"  PFD = PFLOPS per Dollar. {YELLOW}PFD < {int(MIN_PFD)} = rejected{RESET} | {GREEN}PFD > {int(OPTIMAL_PFD)} = optimal{RESET}")


def print_bid_table(gpu_name: str | None = None) -> None:
    """Print optimal bid recommendations."""
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    targets = [gpu_name] if gpu_name else TARGET_GPUS

    print(f"\n{BOLD}{'='*110}{RESET}")
    print(f"{BOLD}  OPTIMAL BID RECOMMENDATIONS (PFD > {int(MIN_PFD)}, optimal > {int(OPTIMAL_PFD)})  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'='*110}{RESET}\n")

    print(f"  {'GPU':<15} {'Break-even':>12} {'Base Bid':>10} {'Market':>10} {'Optimal':>10} {'Max':>10} {'PFD':>6} {'Quality':>8} {'Exp Profit':>12} {'TH/s':>8}")
    print(f"  {'─'*15} {'─'*12} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*6} {'─'*8} {'─'*12} {'─'*8}")

    for gpu in targets:
        rec = calculate_optimal_bid(gpu)
        if rec["break_even"] == 0:
            continue

        market_str = f"${rec['market_avg']:>9.3f}" if rec['market_avg'] else f"{'N/A':>9}"
        pfd_str = f"{rec['avg_pfd']:>6.1f}" if rec['avg_pfd'] > 0 else "N/A"

        # Color based on quality
        if rec['avg_pfd'] >= OPTIMAL_PFD:
            quality_str = f"{GREEN}EXCELLENT{RESET}"
        elif rec['avg_pfd'] >= 360.0:
            quality_str = f"{YELLOW}GOOD{RESET}"
        elif rec['avg_pfd'] >= MIN_PFD:
            quality_str = f"{CYAN}OK{RESET}"
        else:
            quality_str = f"{RED}POOR{RESET}"

        print(f"  {gpu:<15} ${rec['break_even']:>10.3f} ${rec['base_bid']:>9.3f} "
              f"{market_str} {GREEN}${rec['optimal_bid']:>9.3f}{RESET} "
              f"${rec['max_bid']:>9.3f} {CYAN}{pfd_str}{RESET} {quality_str:<8} "
              f"${rec['expected_profit']:>11.3f} {CYAN}{rec['expected_th']:>7.0f}{RESET}")

    print(f"\n{BOLD}{'='*110}{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Vast.ai Market Intelligence with Cost Control")
    parser.add_argument("--gpu", help="Target specific GPU model")
    parser.add_argument("--bid", action="store_true", help="Show optimal bid recommendations")
    parser.add_argument("--auto", action="store_true", help="Auto-bid on top offers")
    parser.add_argument("--limit", type=int, default=20, help="Number of offers to show")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no actual bids)")
    parser.add_argument("--no-save", action="store_true", help="Don't save to history")
    parser.add_argument("--cost-status", action="store_true", help="Show current cost status")

    args = parser.parse_args()

    # Show cost status
    if args.cost_status:
        print_cost_status()
        return

    # Bid recommendation mode
    if args.bid:
        print_bid_table(args.gpu)
        return

    # Discovery mode
    print(f"Scanning market...")
    offers = scan_market(args.gpu)

    if not offers:
        print("No profitable offers found.")
        return

    print_top_offers(offers, args.limit)

    # Save to history
    if not args.no_save:
        save_to_history(offers)
        print(f"\nSaved {len(offers)} offers to {HISTORY_DB}")

    # Auto-bid mode with cost control
    if args.auto:
        # Check cost limit before bidding
        current_cost = get_current_cost()
        remaining_budget = MAX_TOTAL_COST_USD_HR - current_cost

        if remaining_budget <= 0:
            print(f"\n[STOP] Cost limit reached: ${current_cost:.3f}/hr >= ${MAX_TOTAL_COST_USD_HR}/hr")
            print("No new bids will be placed until some instances are killed.")
            return

        print(f"\n[Cost Control] Current: ${current_cost:.3f}/hr | Budget: ${MAX_TOTAL_COST_USD_HR}/hr | Remaining: ${remaining_budget:.3f}/hr")

        top_n = min(3, len(offers))
        print(f"\nAuto-bidding on top {top_n} offers...")
        bid_count = 0
        for offer in offers[:top_n]:
            gpu_type = offer["gpu_name"].lower().replace(" ", "_")
            bid_rec = calculate_optimal_bid(offer["gpu_name"])
            if bid_rec["optimal_bid"] == 0:
                continue

            # Check cost limit for this instance
            allowed, current_cost, remaining = check_cost_limit(bid_rec["optimal_bid"])
            if not allowed:
                print(f"  [SKIP] {offer['gpu_name']} - would exceed $10/hr limit (current: ${current_cost:.3f}/hr)")
                continue

            result = place_bid(offer["id"], bid_rec["optimal_bid"], dry_run=args.dry_run)
            print(result)
            bid_count += 1

            # Update current cost estimate
            current_cost = get_current_cost()
            remaining = MAX_TOTAL_COST_USD_HR - current_cost
            if remaining <= 0:
                print(f"  [STOP] Cost limit reached after {bid_count} bid(s)")
                break


if __name__ == "__main__":
    main()