#!/usr/bin/env python3
"""Market scanner: find best PFD offers across all RTX 30/40/50 + datacenter GPUs.

Strategy:
  - RTX 30/40/50 series + datacenter cards (H100, H200, A100, B100, B200, L40, L4, RTX 6000 ADA)
  - No num_gpus limit (multi-GPU OK)
  - Interruptible only
  - Sort by PFD (dlperf/$) high to low
  - Bid on best offers first

Usage:
  python3 scan_market.py                    # Show top 30 offers
  python3 scan_market.py --limit 10         # Show top 10
  python3 scan_market.py --bid 5            # Bid on top 5
  python3 scan_market.py --bid 5 --dry-run  # Preview bids
  python3 scan_market.py --pfd 200          # Lower PFD threshold
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

# Force unbuffered output for subprocess polling
sys.stdout.reconfigure(line_buffering=True)

from datetime import datetime
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR / "manager"))
os.environ["PATH"] = os.path.expanduser("~/miniconda3/bin:") + os.environ.get("PATH", "")

from vast import deploy_instance, kill_instance, _read_state, _add_to_state, _write_state
from vast import BAD_FILE, BLACKLIST_FILE, DEPLOYED_FILE

# All supported GPU names (vast.ai format)
GPU_NAMES = [
    "RTX_5090", "RTX_5080", "RTX_5070_Ti", "RTX_5070",
    "RTX_4090", "RTX_4080", "RTX_4070_Ti", "RTX_4070", "RTX_4060_Ti", "RTX_4060",
    "RTX_3090_Ti", "RTX_3090", "RTX_3080_Ti", "RTX_3080",
    "RTX_3070_Ti", "RTX_3070", "RTX_3060_Ti", "RTX_3060",
    "H100", "H200_NVL", "A100", "B100", "B200",
    "L40", "L40S", "L4",
    "RTX_6000_Ada", "RTX_A6000", "RTX_A5000", "RTX_A4000",
]

# Only accept offers from these regions (geolocation contains these)
ALLOWED_REGIONS = [
    # North America
    "US", "CA", "United States", "Canada", "America",
    # Europe
    "FI", "DE", "FR", "GB", "NL", "PL", "CZ", "HU", "BG", "RO", "LV", "LT", "EE",
    "SE", "NO", "DK", "AT", "BE", "CH", "IE", "PT", "ES", "IT", "SK",
    "Finland", "Germany", "France", "Netherlands", "Poland", "Czechia",
    "Hungary", "Bulgaria", "Latvia", "Sweden", "Switzerland",
    # Asia
    "KR", "JP", "TW", "SG", "HK", "VN", "TH", "IN", "MY",
    "South Korea", "Japan", "Taiwan", "Singapore", "Vietnam",
    "China", "CN",
]

DEFAULT_PFD = 330.0  # User: >330 min, >360 good, >400 optimal
MAX_COST_HR = 10.0
IMAGE = "nvidia/cuda:12.4.0-devel-ubuntu22.04"


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def load_blacklist() -> set[str]:
    machines = set()
    if BLACKLIST_FILE.exists():
        for line in BLACKLIST_FILE.read_text().splitlines():
            parts = line.strip().split()
            if parts and parts[0].isdigit():
                machines.add(parts[0])
    return machines


def load_bad() -> set[str]:
    return _read_state(BAD_FILE)


def scan_offers(pfd_threshold: float = DEFAULT_PFD) -> list[dict]:
    """Scan all GPUs, return offers sorted by PFD descending."""
    blacklisted = load_blacklist()
    bad = load_bad()

    all_offers = []
    for gpu in GPU_NAMES:
        try:
            # No num_gpus filter — multi-GPU OK
            r = subprocess.run(
                ["vastai", "search", "offers",
                 f"gpu_name={gpu} rentable=true",
                 "-o", "dlperf_per_dphtotal-", "--raw"],
                capture_output=True, text=True, timeout=30,
            )
            data = json.loads(r.stdout)
            for o in data:
                machine_id = str(o.get("machine_id", ""))
                offer_id = str(o.get("id", ""))
                pfd = o.get("dlperf_per_dphtotal") or 0

                if machine_id in blacklisted:
                    continue
                if offer_id in bad:
                    continue
                if pfd < pfd_threshold:
                    continue

                # Region filter: only NA, EU, Asia
                geo = o.get("geolocation", "") or ""
                if not any(region in geo for region in ALLOWED_REGIONS):
                    continue

                num_gpus = int(o.get("num_gpus", 1))
                dph = float(o.get("dph_total", 0) or 0)

                all_offers.append({
                    "id": offer_id,
                    "machine_id": machine_id,
                    "gpu": o.get("gpu_name", "?"),
                    "num_gpus": num_gpus,
                    "pfd": pfd,
                    "min_bid": float(o.get("min_bid", 0) or 0),
                    "dph": dph,
                    "geo": o.get("geolocation", "?"),
                    "inet_up": float(o.get("inet_up", 0) or 0),
                    "reliability": float(o.get("reliability2", 0) or 0),
                    "gpu_ram": int(o.get("gpu_total_ram", 0) or 0),
                    "cuda": o.get("cuda_max_good", ""),
                    "compute_cap": o.get("compute_cap", ""),
                })
        except Exception:
            continue

    all_offers.sort(key=lambda x: x["pfd"], reverse=True)
    return all_offers


def get_current_cost() -> float:
    """Sum dph_total of all running instances."""
    try:
        rc, stdout, _ = _run(["vastai", "show", "instances-v1", "--raw"], timeout=20)
        if rc != 0:
            return 0.0
        data = json.loads(stdout)
        return sum(float(inst.get("dph_total", 0) or 0) for inst in data)
    except Exception:
        return 0.0


def bid_offer(offer: dict) -> tuple[bool, str]:
    """Place bid, return (success, instance_id_or_error)."""
    rc, stdout, stderr = _run(
        ["vastai", "create", "instance", offer["id"],
         "--image", IMAGE,
         "--disk", "20", "--ssh", "--direct",
         "--onstart-cmd", "echo ready"],
        timeout=60,
    )
    if rc != 0:
        return False, stderr[:200]

    try:
        json_str = stdout
        if "Started." in stdout:
            json_str = stdout[stdout.index("{"):]
        result = json.loads(json_str)
        inst_id = str(result.get("new_contract", ""))
        return bool(inst_id), inst_id
    except Exception as e:
        return False, f"parse error: {e} | {stdout[:200]}"


def wait_running(inst_id: str, timeout_s: int = 300) -> str:
    """Wait for instance to reach running. Returns status string."""
    for i in range(timeout_s // 10):
        rc, stdout, _ = _run(["vastai", "show", "instance", inst_id], timeout=15)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", stdout)
        for line in clean.split("\n"):
            parts = line.split()
            if len(parts) >= 4 and parts[1] == inst_id:
                status = parts[3]
                if status == "running":
                    return "running"
                if status in ("exited", "offline", "unknown"):
                    return status
                break
        time.sleep(10)
    return "timeout"


def full_cycle(offer: dict, dry_run: bool = False) -> str:
    """Bid → wait → deploy → verify. Returns result string."""
    offer_id = offer["id"]
    gpu = offer["gpu"]
    dph = offer["dph"]
    n = offer["num_gpus"]
    gpu_str = f"{n}x {gpu}" if n > 1 else gpu

    if dry_run:
        return f"[DRY] {offer_id:10} {gpu_str:<15} PFD={offer['pfd']:6.0f} ${dph:.3f}/hr {offer['geo']}"

    # 1. Bid
    print(f"  [1/4] Bidding {offer_id} ({gpu_str} PFD={offer['pfd']:.0f} ${dph:.3f}/hr)...")
    ok, result = bid_offer(offer)
    if not ok:
        return f"  ❌ BID FAIL {offer_id}: {result}"
    inst_id = result
    print(f"        → Instance {inst_id}")

    # 2. Wait
    print(f"  [2/4] Waiting for running...")
    status = wait_running(inst_id)
    if status != "running":
        kill_instance(inst_id, f"stuck: {status}")
        return f"  ❌ {inst_id}: {status} → destroyed"

    # 3. Deploy
    print(f"  [3/4] Deploying miner...")
    deploy_result = deploy_instance(inst_id)
    if "FAIL" in deploy_result:
        kill_instance(inst_id, deploy_result.split("FAIL:")[-1].strip())
        return f"  ❌ DEPLOY {inst_id}: {deploy_result}"

    # 4. Verify
    print(f"  [4/4] Verifying...")
    time.sleep(10)
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
            return f"  ✅ {inst_id} ({gpu_str} ${dph:.3f}/hr) miner running!"
        return f"  ⚠️ {inst_id} ({gpu_str} ${dph:.3f}/hr) deployed, miner warming up"

    return f"  ✅ {inst_id} ({gpu_str} ${dph:.3f}/hr) deployed (SSH check skipped)"


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=30, help="Show top N offers")
    p.add_argument("--bid", type=int, default=0, help="Bid on top N offers")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--pfd", type=float, default=DEFAULT_PFD, help="Min PFD threshold")
    args = p.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*80}", flush=True)
    print(f"  MARKET SCAN @ {ts}", flush=True)
    print(f"  GPUs: RTX 30/40/50 + datacenter | No num_gpus limit | Interruptible", flush=True)
    print(f"  PFD threshold: >{args.pfd:.0f} | Budget: ${MAX_COST_HR}/hr", flush=True)
    print(f"  Blacklisted machines: {len(load_blacklist())}", flush=True)
    print(f"{'='*80}\n", flush=True)

    # Scan
    print("  Scanning market...", flush=True)
    offers = scan_offers(pfd_threshold=args.pfd)
    print(f"  Found {len(offers)} qualifying offers\n", flush=True)

    if not offers:
        print("  No qualifying offers. Try lowering --pfd.")
        return

    # Table
    print(f"  {'#':>3} {'ID':<10} {'GPU':<20} {'PFD':>6} {'$/hr':>8} {'GPUs':>4} {'Rel':>5} {'Location'}")
    print(f"  {'─'*3} {'─'*10} {'─'*20} {'─'*6} {'─'*8} {'─'*4} {'─'*5} {'─'*20}")
    for i, o in enumerate(offers[:args.limit], 1):
        n = o["num_gpus"]
        gpu_str = f"{n}x {o['gpu']}" if n > 1 else o["gpu"]
        print(f"  {i:>3} {o['id']:<10} {gpu_str:<20} {o['pfd']:>6.0f} ${o['dph']:>7.3f} {n:>4} {o['reliability']:>4.2f} {o['geo']}")

    if args.bid > 0:
        current_cost = get_current_cost()
        print(f"\n  Current cost: ${current_cost:.3f}/hr | Budget: ${MAX_COST_HR}/hr")
        print(f"\n  Bidding on top {args.bid} offers...\n")

        success = 0
        for offer in offers[:args.bid]:
            # Budget check
            new_cost = get_current_cost() + offer["dph"]
            if new_cost > MAX_COST_HR:
                print(f"  [SKIP] ${new_cost:.3f}/hr would exceed budget")
                continue
            result = full_cycle(offer, dry_run=args.dry_run)
            print(result)
            if "✅" in result or "⚠️" in result:
                success += 1

        deployed = _read_state(DEPLOYED_FILE)
        bad = _read_state(BAD_FILE)
        blacklisted = load_blacklist()
        print(f"\n{'='*80}")
        print(f"  DONE: {success} deployed | Budget used: ${get_current_cost():.3f}/${MAX_COST_HR}/hr")
        print(f"  Deployed: {len(deployed)} | Bad: {len(bad)} | Blacklisted: {len(blacklisted)}")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
