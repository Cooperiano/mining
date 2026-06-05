#!/usr/bin/env python3
"""Per-instance agent: check status, deploy/redeploy miner, report.

Called by cron with instance ID as argument.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
os.environ["PATH"] = os.path.expanduser("~/miniconda3/bin:") + os.environ.get("PATH", "")

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR / "manager"))
from vast import deploy_instance, kill_instance, _add_to_state, DEPLOYED_FILE, BAD_FILE


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def get_instance_info(inst_id: str) -> dict | None:
    rc, stdout, _ = _run(["vastai", "show", "instances-v1", "--raw"], timeout=20)
    if rc != 0:
        return None
    data = json.loads(stdout)
    instances = data.get("instances", data) if isinstance(data, dict) else data
    for inst in instances:
        if str(inst.get("id")) == inst_id:
            return {
                "id": str(inst["id"]),
                "machine_id": str(inst.get("machine_id", "")),
                "gpu": str(inst.get("gpu_name", "?") or "?"),
                "num_gpus": int(inst.get("num_gpus", 1) or 1),
                "status": str(inst.get("actual_status", "unknown") or "unknown"),
                "dph": float(inst.get("dph_total", 0) or 0),
                "geo": str(inst.get("geolocation", "?") or "?"),
            }
    return None


def check_miner(inst_id: str) -> bool:
    rc, stdout, _ = _run(["vastai", "ssh-url", inst_id], timeout=15)
    m = re.search(r"@([^:]+):(\d+)", stdout.strip())
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


def main(inst_id: str):
    info = get_instance_info(inst_id)
    if not info:
        print(f"[{inst_id}] Instance not found — may have been destroyed.")
        return

    status = info["status"]
    gpu = info["gpu"]
    dph = info["dph"]
    geo = info["geo"]
    ts = time.strftime("%H:%M:%S")

    if status == "exited":
        print(f"[{ts}] [{inst_id}] {gpu} EXITED ${dph:.3f}/hr {geo} — interrupted, nothing to do.")
        return

    if status in ("loading", "creating"):
        print(f"[{ts}] [{inst_id}] {gpu} {status.upper()} ${dph:.3f}/hr {geo} — waiting.")
        return

    if status != "running":
        print(f"[{ts}] [{inst_id}] {gpu} {status.upper()} ${dph:.3f}/hr {geo} — unknown state.")
        return

    # Instance is running — check miner
    miner_ok = check_miner(inst_id)
    if miner_ok:
        print(f"[{ts}] [{inst_id}] {gpu} RUNNING ${dph:.3f}/hr {geo} — miner OK ⛏️")
        return

    # Miner not running — (re)deploy
    print(f"[{ts}] [{inst_id}] {gpu} RUNNING ${dph:.3f}/hr {geo} — miner NOT running, deploying...")
    result = deploy_instance(inst_id)
    if "FAIL" in result:
        print(f"[{ts}] [{inst_id}] Deploy FAILED: {result}")
    else:
        _add_to_state(DEPLOYED_FILE, inst_id)
        print(f"[{ts}] [{inst_id}] Deploy OK ✅")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 instance_agent.py <instance_id>")
        sys.exit(1)
    main(sys.argv[1])
