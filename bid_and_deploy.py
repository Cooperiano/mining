#!/usr/bin/env python3
"""One-shot: bid → wait → deploy → verify → blacklist bad ones.

Usage:
  python3 bid_and_deploy.py                  # Bid on best available offers
  python3 bid_and_deploy.py --max-bids 5     # Limit number of bids
  python3 bid_and_deploy.py --dry-run        # Preview only
  python3 bid_and_deploy.py --pfd-threshold 220  # Override PFD threshold
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR / "manager"))

os.environ["PATH"] = os.path.expanduser("~/miniconda3/bin:") + os.environ.get("PATH", "")

from vast import deploy_instance, kill_instance, _read_state, _add_to_state, _write_state, BAD_FILE, BLACKLIST_FILE, DEPLOYED_FILE
from cost_control import check_cost_limit, get_current_cost, MAX_TOTAL_COST_USD_HR

BLACKLISTED_MACHINES: set[str] = set()
BAD_INSTANCES: set[str] = set()

TARGET_GPUS = [
    "RTX_5090", "RTX_5080", "RTX_5070_TI", "RTX_5070",
    "RTX_4090", "RTX_4080", "RTX_4070_TI", "RTX_4070",
    "RTX_4060_TI", "RTX_4060",
    "RTX_3090_TI", "RTX_3090", "RTX_3080_TI", "RTX_3080",
    "RTX_3070_TI", "RTX_3070", "RTX_3060_TI", "RTX_3060",
    "H100", "H200", "A100", "RTX_6000_ADA",
]

DEFAULT_PFD_THRESHOLD = 220.0


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _load_blacklisted_machines() -> set[str]:
    """Load blacklisted machine IDs."""
    machines = set()
    if BLACKLIST_FILE.exists():
        for line in BLACKLIST_FILE.read_text().splitlines():
            parts = line.strip().split()
            if parts and parts[0].isdigit():
                machines.add(parts[0])
    return machines


def _scan_all_gpus(pfd_threshold: float = DEFAULT_PFD_THRESHOLD) -> list[dict]:
    """Scan all target GPUs, return offers sorted by PFD."""
    BLACKLISTED_MACHINES.update(_load_blacklisted_machines())
    BAD_INSTANCES.update(_read_state(BAD_FILE))

    all_offers = []
    for gpu in TARGET_GPUS:
        try:
            r = subprocess.run(
                ["vastai", "search", "offers",
                 f"gpu_name={gpu} rentable=true num_gpus=1",
                 "-o", "dlperf_per_dphtotal-", "--raw"],
                capture_output=True, text=True, timeout=20,
            )
            data = json.loads(r.stdout)
            for o in data:
                machine_id = str(o.get("machine_id", ""))
                offer_id = str(o.get("id", ""))
                pfd = o.get("dlperf_per_dphtotal") or 0

                # Skip blacklisted machines
                if machine_id in BLACKLISTED_MACHINES:
                    continue
                # Skip bad instances
                if offer_id in BAD_INSTANCES:
                    continue
                # Skip low PFD
                if pfd < pfd_threshold:
                    continue

                all_offers.append({
                    "id": offer_id,
                    "machine_id": machine_id,
                    "gpu": o.get("gpu_name", "?"),
                    "pfd": pfd,
                    "min_bid": float(o.get("min_bid", 0) or 0),
                    "dph": float(o.get("dph_total", 0) or 0),
                    "geo": o.get("geolocation", "?"),
                    "inet_up": float(o.get("inet_up", 0) or 0),
                    "reliability": float(o.get("reliability2", 0) or 0),
                    "direct_ports": int(o.get("direct_port_count", 0) or 0),
                })
        except Exception:
            continue

    all_offers.sort(key=lambda x: x["pfd"], reverse=True)
    return all_offers


def _bid_and_deploy(offer: dict, dry_run: bool = False) -> str:
    """Bid on offer, wait for running, deploy, verify."""
    offer_id = offer["id"]
    gpu = offer["gpu"]
    dph = offer["dph"]

    if dry_run:
        return f"[DRY-RUN] Would bid on {offer_id} ({gpu} PFD={offer['pfd']:.0f} ${dph:.3f}/hr {offer['geo']})"

    # 1. Bid
    print(f"  [1/4] Bidding on {offer_id} ({gpu} PFD={offer['pfd']:.0f} ${dph:.3f}/hr {offer['geo']})...")
    rc, stdout, stderr = _run(
        ["vastai", "create", "instance", offer_id,
         "--image", "nvidia/cuda:12.4.0-devel-ubuntu22.04",
         "--disk", "20", "--ssh", "--direct",
         "--onstart-cmd", "echo ready"],
        timeout=60,
    )
    if rc != 0:
        return f"  FAIL bid {offer_id}: {stderr[:200]}"

    try:
        # vastai returns 'Started. {json}'
        json_str = stdout
        if 'Started.' in stdout:
            json_str = stdout[stdout.index('{'):]
        result = json.loads(json_str)
        inst_id = str(result.get("new_contract", ""))
    except (json.JSONDecodeError, KeyError) as e:
        return f"  FAIL parse bid response: {e} | stdout: {stdout[:200]}"

    if not inst_id:
        return f"  FAIL no contract ID in response"

    print(f"  [2/4] Instance {inst_id} created. Waiting for running...")

    # 2. Wait for running (max 5 min)
    for i in range(30):
        rc, stdout, _ = _run(["vastai", "show", "instance", inst_id], timeout=15)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", stdout)
        for line in clean.split("\n"):
            parts = line.split()
            if len(parts) >= 4 and parts[1] == inst_id:
                status = parts[3]
                if status == "running":
                    print(f"  ✅ Instance {inst_id} is running ({i * 10}s)")
                    break
                elif status in ("exited", "offline", "unknown"):
                    kill_instance(inst_id, f"stuck in {status}")
                    return f"  FAIL {inst_id}: stuck in {status}"
                else:
                    if i % 3 == 0:
                        print(f"  ... {status} ({i * 10}s)")
                break
        else:
            continue
        break
    else:
        kill_instance(inst_id, "timeout waiting for running")
        return f"  FAIL {inst_id}: timeout (5min)"

    # 3. Deploy miner
    print(f"  [3/4] Deploying miner to {inst_id}...")
    deploy_result = deploy_instance(inst_id)
    if "FAIL" in deploy_result:
        kill_instance(inst_id, deploy_result.split("FAIL:")[-1].strip())
        return f"  FAIL deploy {inst_id}: {deploy_result}"

    # 4. Verify (wait 30s, check if miner is running)
    print(f"  [4/4] Verifying miner on {inst_id}...")
    time.sleep(15)

    rc, stdout, _ = _run(["vastai", "ssh-url", inst_id], timeout=15)
    url = stdout.strip()
    m = re.search(r"@([^:]+):(\d+)", url)
    if m:
        host, port = m.group(1), m.group(2)
        rc2, out2, _ = _run(
            ["ssh", "-q", "-o", "ConnectTimeout=8",
             "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
             f"root@{host}", "-p", port,
             "pgrep -f alpha-miner && echo MINER_OK || echo MINER_NOT_FOUND"],
            timeout=15,
        )
        if "MINER_OK" in out2:
            return f"  ✅ {inst_id} ({gpu} ${dph:.3f}/hr) deployed & verified!"
        else:
            # Miner not running yet but deploy succeeded — might be warming up
            return f"  ⚠️ {inst_id} ({gpu} ${dph:.3f}/hr) deployed, miner warming up"

    return f"  ✅ {inst_id} ({gpu} ${dph:.3f}/hr) deployed (SSH verify skipped)"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bid → Wait → Deploy → Verify → Blacklist")
    parser.add_argument("--max-bids", type=int, default=5, help="Max bids to place")
    parser.add_argument("--pfd-threshold", type=float, default=DEFAULT_PFD_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  BID & DEPLOY @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  PFD threshold: >{args.pfd_threshold:.0f} | Max bids: {args.max_bids} | Budget: ${MAX_TOTAL_COST_USD_HR}/hr")
    print(f"{'='*70}\n")

    # Cost check
    current_cost = get_current_cost()
    remaining = MAX_TOTAL_COST_USD_HR - current_cost
    print(f"  Cost: ${current_cost:.3f}/hr | Remaining: ${remaining:.3f}/hr")
    if remaining <= 0:
        print(f"  [STOP] Budget exhausted!")
        return

    # Scan
    print(f"\n  Scanning {len(TARGET_GPUS)} GPU types (PFD > {args.pfd_threshold:.0f}, blacklisted machines excluded)...")
    offers = _scan_all_gpus(pfd_threshold=args.pfd_threshold)
    print(f"  Found {len(offers)} offers\n")

    if not offers:
        print("  No qualifying offers. Try lowering --pfd-threshold.")
        return

    # Show top offers
    print(f"  {'GPU':<15} {'PFD':>6} {'$/hr':>8} {'Location':<20}")
    print(f"  {'─'*15} {'─'*6} {'─'*8} {'─'*20}")
    for o in offers[:10]:
        print(f"  {o['gpu']:<15} {o['pfd']:>6.0f} ${o['dph']:>7.3f} {o['geo']:<20}")

    # Bid on top N
    bids_placed = 0
    print(f"\n  Bidding on top {min(args.max_bids, len(offers))} offers...\n")

    for offer in offers[:args.max_bids]:
        # Cost check
        allowed, current_cost, remaining = check_cost_limit(offer["dph"])
        if not allowed:
            print(f"  [SKIP] {offer['gpu']} — would exceed budget (${current_cost:.3f}+${offer['dph']:.3f} > ${MAX_TOTAL_COST_USD_HR})")
            continue

        result = _bid_and_deploy(offer, dry_run=args.dry_run)
        print(result)
        bids_placed += 1

    # Summary
    deployed = _read_state(DEPLOYED_FILE)
    bad = _read_state(BAD_FILE)
    blacklisted = _load_blacklisted_machines()

    print(f"\n{'='*70}")
    print(f"  SUMMARY: {bids_placed} bids placed")
    print(f"  Deployed: {len(deployed)} | Bad: {len(bad)} | Blacklisted machines: {len(blacklisted)}")
    print(f"  Current cost: ${get_current_cost():.3f}/hr")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
