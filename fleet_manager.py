#!/usr/bin/env python3
"""Fleet manager: discover instances, spawn per-instance agents.

Usage:
  python3 fleet_manager.py              # Discover + dispatch agents
  python3 fleet_manager.py --status     # Just show fleet status
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
os.environ["PATH"] = os.path.expanduser("~/miniconda3/bin:") + os.environ.get("PATH", "")

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR / "manager"))
from vast import _read_state, _deployed_file, _bad_file, BLACKLIST_FILE

def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def get_all_instances() -> list[dict]:
    rc, stdout, _ = _run(["vastai", "show", "instances-v1", "--raw"], timeout=20)
    if rc != 0:
        return []
    try:
        data = json.loads(stdout)
        instances = data.get("instances", data) if isinstance(data, dict) else data
        result = []
        for inst in instances:
            status = str(inst.get("actual_status", "unknown") or "unknown")
            result.append({
                "id": str(inst["id"]),
                "machine_id": str(inst.get("machine_id", "") or ""),
                "gpu": str(inst.get("gpu_name", "?") or "?"),
                "num_gpus": int(inst.get("num_gpus", 1) or 1),
                "status": status,
                "dph": float(inst.get("dph_total", 0) or 0),
                "geo": str(inst.get("geolocation", "?") or "?"),
            })
        return result
    except (json.JSONDecodeError, KeyError, TypeError):
        # Fallback: parse plain text output
        lines = stdout.strip().split("\n")
        result = []
        for line in lines[1:]:  # skip header
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            try:
                inst = {
                    "id": parts[1],
                    "machine_id": parts[2],
                    "gpu": parts[3] if len(parts) > 3 else "?",
                    "num_gpus": int(parts[4]) if len(parts) > 4 else 1,
                    "status": parts[5],
                    "dph": float(parts[6]) if len(parts) > 6 else 0,
                    "geo": parts[7] if len(parts) > 7 else "?",
                }
                result.append(inst)
            except (ValueError, IndexError):
                continue
        return result


def show_status():
    instances = get_all_instances()
    if not instances:
        print("No instances.")
        return

    deployed = _read_state(_deployed_file())
    bad = _read_state(_bad_file())
    blacklisted = set()
    if BLACKLIST_FILE.exists():
        for line in BLACKLIST_FILE.read_text().splitlines():
            parts = line.strip().split()
            if parts and parts[0].isdigit():
                blacklisted.add(parts[0])

    total_cost = 0.0
    running = 0
    mining = 0

    print(f"\n  {'ID':<10} {'GPU':<18} {'Status':<10} {'$/hr':>7} {'State':<10} {'Location'}")
    print(f"  {'─'*10} {'─'*18} {'─'*10} {'─'*7} {'─'*10} {'─'*20}")

    for inst in instances:
        iid = inst["id"]
        mid = inst["machine_id"]
        status = inst["status"]
        dph = inst["dph"]

        emoji = {"running": "🟢", "loading": "🟡", "exited": "🔴"}.get(status, "⚪")

        if mid in blacklisted:
            state = "🚫 block"
        elif iid in bad:
            state = "❌ bad"
        elif status != "running":
            state = "—"
        elif iid in deployed:
            state = "⛏️ mining"
            mining += 1
        else:
            state = "⏳ todo"

        print(f"  {iid:<10} {inst['gpu']:<18} {emoji} {status:<8} ${dph:>6.3f} {state:<10} {inst['geo']}")

        if status == "running":
            total_cost += dph
            running += 1

    print(f"\n  ⛏️ Mining: {mining} | 🟢 Running: {running} | Total: {len(instances)} | Cost: ${total_cost:.3f}/hr")


if __name__ == "__main__":
    show_status()
