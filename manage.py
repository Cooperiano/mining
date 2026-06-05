#!/usr/bin/env python3
"""Deploy & manage Pearl mining instances on vast.ai.

You buy (bid) interruptible instances manually.
This script:
  1. Scans all your instances
  2. Deploys miner to any running instance that doesn't have it
  3. Monitors health, blacklists bad machines
  4. Reports status

Usage:
  python3 manage.py              # Full cycle: deploy + status
  python3 manage.py --status     # Just show status
  python3 manage.py --deploy     # Only deploy, no status table
  python3 manage.py --force ID   # Force re-deploy to instance ID
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR / "manager"))
os.environ["PATH"] = os.path.expanduser("~/miniconda3/bin:") + os.environ.get("PATH", "")

from vast import (
    deploy_instance, kill_instance,
    _read_state, _write_state,
    BAD_FILE, BLACKLIST_FILE, DEPLOYED_FILE,
)

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


def load_deployed() -> set[str]:
    return _read_state(DEPLOYED_FILE)


def get_instances() -> list[dict]:
    """Get all instances from vastai."""
    rc, stdout, _ = _run(["vastai", "show", "instances-v1", "--raw"], timeout=20)
    if rc != 0 or not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and "instances" in data:
            return data["instances"]
        return data if isinstance(data, list) else []
    except Exception:
        return []


def parse_instance(inst: dict) -> dict:
    """Extract key fields from instance."""
    return {
        "id": str(inst.get("id", inst.get("INSTANCE_ID", "")) or ""),
        "machine_id": str(inst.get("machine_id", "") or ""),
        "gpu": str(inst.get("gpu_name", "?") or "?"),
        "num_gpus": int(inst.get("num_gpus", 1) or 1),
        "status": str(inst.get("actual_status", inst.get("cur_state", "unknown")) or "unknown"),
        "dph": float(inst.get("dph_total", 0) or 0),
        "image": str(inst.get("image", "") or ""),
        "geo": str(inst.get("geolocation", "?") or "?"),
        "reliability": float(inst.get("reliability2", 0) or 0),
    }


def deploy_to_instance(inst_id: str) -> str:
    """Deploy miner to a running instance. Returns result string."""
    print(f"  🚀 Deploying miner to {inst_id}...", flush=True)
    result = deploy_instance(inst_id)
    return result


def check_miner_running(inst_id: str) -> bool:
    """SSH into instance and check if alpha-miner is running."""
    rc, stdout, _ = _run(["vastai", "ssh-url", inst_id], timeout=15)
    url = stdout.strip()
    m = re.search(r"@([^:]+):(\d+)", url)
    if not m:
        return False
    host, port = m.group(1), m.group(2)
    rc2, out2, _ = _run(
        ["ssh", "-q", "-o", "ConnectTimeout=8",
         "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
         f"root@{host}", "-p", port,
         "pgrep -f alpha-miner > /dev/null 2>&1 && echo RUNNING || echo STOPPED"],
        timeout=15,
    )
    return "RUNNING" in out2


def full_deploy_cycle():
    """Main loop: find undeployed running instances and deploy."""
    instances = get_instances()
    if not instances:
        print("  No instances found.", flush=True)
        return

    deployed = load_deployed()
    blacklisted = load_blacklist()
    bad = _read_state(BAD_FILE)

    new_deploys = 0
    failed = 0

    for inst in instances:
        info = parse_instance(inst)
        inst_id = info["id"]
        machine_id = info["machine_id"]
        status = info["status"]
        gpu = info["gpu"]
        dph = info["dph"]

        # Skip blacklisted
        if machine_id in blacklisted:
            print(f"  ⏭️  {inst_id} — machine {machine_id} blacklisted, skipping", flush=True)
            continue

        # Skip bad
        if inst_id in bad:
            print(f"  ⏭️  {inst_id} — marked bad, skipping", flush=True)
            continue

        # Only deploy to running instances
        if status != "running":
            print(f"  ⏳ {inst_id} ({gpu}) — {status}, waiting...", flush=True)
            continue

        # Already deployed? Check if miner still running
        if inst_id in deployed:
            if check_miner_running(inst_id):
                print(f"  ✅ {inst_id} ({gpu} ${dph:.3f}/hr) — miner OK", flush=True)
            else:
                print(f"  ⚠️  {inst_id} ({gpu}) — deployed but miner not running, re-deploying...", flush=True)
                result = deploy_to_instance(inst_id)
                if "FAIL" in result:
                    print(f"  ❌ {inst_id} re-deploy failed: {result}", flush=True)
                    failed += 1
                else:
                    print(f"  ✅ {inst_id} re-deployed OK", flush=True)
            continue

        # New instance — deploy!
        print(f"  🆕 {inst_id} ({gpu} ${dph:.3f}/hr) — new running instance, deploying...", flush=True)
        result = deploy_to_instance(inst_id)
        if "FAIL" in result:
            reason = result.split("FAIL:")[-1].strip() if "FAIL:" in result else result
            print(f"  ❌ {inst_id} deploy failed: {reason}", flush=True)
            # Auto-blacklist bad machines
            kill_instance(inst_id, reason)
            failed += 1
        else:
            print(f"  ✅ {inst_id} deployed successfully!", flush=True)
            _add_to_state(DEPLOYED_FILE, inst_id)
            new_deploys += 1

    print(f"\n  📊 New deploys: {new_deploys} | Failed: {failed}", flush=True)


def show_status():
    """Show all instances with status table."""
    instances = get_instances()
    if not instances:
        print("  No instances.", flush=True)
        return

    deployed = load_deployed()
    blacklisted = load_blacklist()
    bad = _read_state(BAD_FILE)

    total_cost = 0.0
    running_count = 0

    print(f"\n  {'ID':<10} {'GPU':<15} {'Status':<10} {'$/hr':>7} {'Miner':<8} {'Location'}", flush=True)
    print(f"  {'─'*10} {'─'*15} {'─'*10} {'─'*7} {'─'*8} {'─'*20}", flush=True)

    for inst in instances:
        info = parse_instance(inst)
        inst_id = info["id"]
        status = info["status"]
        dph = info["dph"] or 0.0

        # Determine miner status
        if inst_id in bad:
            miner = "❌ BAD"
        elif status != "running":
            miner = "—"
        elif inst_id in deployed:
            miner = "⛏️ mining"
        else:
            miner = "⏳ todo"

        emoji = {"running": "🟢", "loading": "🟡", "exited": "🔴"}.get(status, "⚪")

        print(f"  {inst_id:<10} {info['gpu']:<15} {emoji} {status:<8} ${info.get('dph', 0) or 0:>6.3f} {miner:<8} {info['geo']}", flush=True)

        if status == "running":
            total_cost += info["dph"]
            running_count += 1

    print(f"\n  Running: {running_count} | Total cost: ${total_cost:.3f}/hr | Budget: $10.000/hr", flush=True)
    print(f"  Deployed: {len(deployed)} | Bad: {len(bad)} | Blacklisted machines: {len(blacklisted)}", flush=True)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Deploy & manage Pearl mining instances")
    p.add_argument("--status", action="store_true", help="Only show status")
    p.add_argument("--deploy", action="store_true", help="Only deploy, no status")
    p.add_argument("--force", type=str, help="Force re-deploy to instance ID")
    args = p.parse_args()

    print(f"\n{'='*70}", flush=True)
    print(f"  PEARL MINING — DEPLOY & MANAGE", flush=True)
    print(f"{'='*70}\n", flush=True)

    if args.force:
        print(f"  🔄 Force re-deploy to {args.force}...", flush=True)
        result = deploy_to_instance(args.force)
        print(f"  Result: {result}", flush=True)
        return

    if args.status:
        show_status()
        return

    # Default: deploy cycle + status
    if not args.deploy:
        show_status()
        print(flush=True)

    full_deploy_cycle()

    if not args.deploy:
        print(flush=True)
        show_status()


if __name__ == "__main__":
    main()
