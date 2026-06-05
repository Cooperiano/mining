#!/usr/bin/env python3
"""Enhanced autodeploy cron — Phase 2 integration: manage + discover + bid.

Cron schedule recommendations:
- Fast mode (interruptible heavy): every 30 seconds
- Normal mode: every 1-2 minutes
- Discovery mode: every hour (embedded check)

Usage:
  python3 autodeploy_enhanced.py          # Full cycle (manage + discover)
  python3 autodeploy_enhanced.py --no-discover  # Management only
"""

from __future__ import annotations

import sys
import traceback
import time
from datetime import datetime
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR))

# Core modules
from manager import vast

# Phase 2: Offer discovery
try:
    from offer_discovery import scan_market, calculate_optimal_bid, place_bid, TARGET_GPUS, HISTORY_DB, MIN_PFD, OPTIMAL_PFD
    OFFER_DISCOVERY_AVAILABLE = True
except ImportError:
    OFFER_DISCOVERY_AVAILABLE = False

FAIL_FLAG = Path("/tmp/.autodeploy_fail")
LAST_DISCOVER_FILE = MINING_DIR / ".last_discovery"
DISCOVER_INTERVAL = 3600  # 1 hour between market scans


def _should_discover() -> bool:
    """Check if it's time for a market discovery cycle."""
    if not LAST_DISCOVER_FILE.exists():
        return True

    try:
        last_time = float(LAST_DISCOVER_FILE.read_text().strip())
        return time.time() - last_time > DISCOVER_INTERVAL
    except (ValueError, OSError):
        return True


def _update_discovery_timestamp() -> None:
    """Update the last discovery timestamp."""
    LAST_DISCOVER_FILE.write_text(str(time.time()))


def discover_and_bid_cycle(dry_run: bool = False, max_bids: int = 3) -> list[str]:
    """Phase 2: Discover profitable offers and place bids."""
    if not OFFER_DISCOVERY_AVAILABLE:
        return ["Offer discovery not available (offer_discovery.py not found)"]

    log = [f"\n=== Market Discovery @ {datetime.now().strftime('%H:%M:%S')} ==="]

    # Scan market for all target GPUs
    log.append("Scanning market...")
    offers = scan_market()

    if not offers:
        log.append("No profitable offers found.")
        return log

    # Top offers summary
    top_5 = offers[:5]
    log.append(f"Found {len(offers)} offers, top 5:")
    for o in top_5:
        log.append(f"  {o['id'][:8]} | {o['gpu_name']:12} | ${o['min_bid']:.3f}/hr | "
                   f"score={o['score']:.1f} | ratio={o['bid_ratio']:.2f}x")

    # Place bids on top offers
    bids_to_place = min(max_bids, len(top_5))
    log.append(f"\nPlacing bids on top {bids_to_place} offers...")

    for offer in top_5[:bids_to_place]:
        bid_rec = calculate_optimal_bid(offer["gpu_name"])
        if bid_rec["optimal_bid"] == 0:
            continue

        result = place_bid(offer["id"], bid_rec["optimal_bid"], dry_run=dry_run)
        log.append(result)

    # Save to history
    from offer_discovery import save_to_history
    save_to_history(offers)
    log.append(f"Saved scan results to {HISTORY_DB}")

    _update_discovery_timestamp()
    return log


def enhanced_autodeploy_cycle(
    skip_discovery: bool = False,
    dry_run_discovery: bool = False,
) -> str:
    """Enhanced autodeploy: management + optional discovery + bidding."""
    log: list[str] = []

    # Phase 2: Market discovery (every hour)
    if not skip_discovery and _should_discover():
        discovery_log = discover_and_bid_cycle(dry_run=dry_run_discovery, max_bids=3)
        log.extend(discovery_log)

    # Phase 1: Instance management (every cycle)
    log.append(f"\n=== Instance Management @ {datetime.now().strftime('%H:%M:%S')} ===")
    management_log = vast.autodeploy_cycle()
    log.append(management_log)

    return "\n".join(log)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced autodeploy with offer discovery")
    parser.add_argument("--no-discover", action="store_true", help="Skip market discovery")
    parser.add_argument("--dry-run", action="store_true", help="Dry run discovery (no actual bids)")

    args = parser.parse_args()

    try:
        result = enhanced_autodeploy_cycle(
            skip_discovery=args.no_discover,
            dry_run_discovery=args.dry_run,
        )
        print(result)

        # Clear fail flag on success
        if FAIL_FLAG.exists():
            FAIL_FLAG.unlink()

        sys.exit(0)
    except Exception as e:
        traceback.print_exc()
        # Touch fail flag so you know something broke
        FAIL_FLAG.write_text(f"{datetime.now()} {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()