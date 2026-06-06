#!/usr/bin/env python3
"""Deploy Pearl miner to a single vast.ai instance via CLI."""
import sys
import json
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR))

from manager import vast


def _pool_hashrates() -> dict[str, float] | None:
    """Return instance-id suffix -> online pool hashrate."""
    try:
        req = urllib.request.Request(vast.API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    rates: dict[str, float] = {}
    for worker in data.get("workers", []):
        if not worker.get("online"):
            continue
        match = re.search(r"-([0-9]{4})", str(worker.get("name", "")))
        if not match:
            continue
        try:
            rate = float(str(worker.get("hashrate_live", "0")).split()[0])
        except (TypeError, ValueError):
            rate = 0
        rates[match.group(1)] = rates.get(match.group(1), 0) + rate
    return rates


def _inspect_running(entry: dict, deployed_ids: set[str], pool_rates: dict[str, float] | None) -> dict:
    inst_id = str(entry.get("id", ""))
    is_deployed = inst_id in deployed_ids
    result = {
        "deployment_state": "deployed" if is_deployed else "undeployed",
        "health": "pending",
        "issue": "Not deployed" if not is_deployed else "Checking...",
        "miner_running": False,
        "gpu_util": 0,
        "vram_used_mb": 0,
        "vram_total_mb": 0,
        "local_hashrate": 0,
        "pool_hashrate": round(pool_rates.get(inst_id[-4:], 0), 1) if pool_rates is not None else None,
    }

    # Vast's ssh_host/ssh_port proxy may be stale while `ssh-url` returns a
    # working direct endpoint, so always resolve the current URL.
    rc, ssh_url, _ = vast._vastai(["ssh-url", inst_id], timeout=10)
    match = re.search(r"@([^:]+):(\d+)", ssh_url.strip()) if rc == 0 else None
    if not match:
        if result["pool_hashrate"] and result["pool_hashrate"] > 0:
            result.update({"health": "degraded", "issue": "Pool online; SSH unavailable"})
        else:
            result.update({"health": "unhealthy", "issue": "SSH unavailable"})
        return result
    host, port = match.group(1), match.group(2)
    remote_cmd = (
        "echo MINER=$(pgrep -c alpha-miner 2>/dev/null || true); "
        "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total "
        "--format=csv,noheader,nounits 2>/dev/null | sed 's/^/GPU=/' ; "
        "grep 'hashrate_th_s=' /root/mining/miner.log 2>/dev/null | tail -32"
    )
    cmd = [
        "ssh", "-q", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no",
        "-o", "LogLevel=QUIET", f"root@{host}", "-p", port, remote_cmd,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = proc.stdout
    except Exception:
        output = ""
        proc = None

    if not proc or proc.returncode != 0 or "MINER=" not in output:
        if result["pool_hashrate"] and result["pool_hashrate"] > 0:
            result.update({"health": "degraded", "issue": "Pool online; SSH unavailable"})
        else:
            result.update({"health": "unhealthy", "issue": "SSH unavailable"})
        return result

    miner_match = re.search(r"MINER=(\d+)", output)
    result["miner_running"] = bool(miner_match and int(miner_match.group(1)) > 0)

    utils, used, total = [], [], []
    for gpu_match in re.finditer(r"GPU=\s*(\d+),\s*(\d+),\s*(\d+)", output):
        utils.append(int(gpu_match.group(1)))
        used.append(int(gpu_match.group(2)))
        total.append(int(gpu_match.group(3)))
    if utils:
        result["gpu_util"] = round(sum(utils) / len(utils))
        result["vram_used_mb"] = sum(used)
        result["vram_total_mb"] = sum(total)

    gpu_hashes: dict[str, float] = {}
    for hash_match in re.finditer(r"gpu=(\d+):.*?hashrate_th_s=([\d.]+)", output):
        gpu_hashes[hash_match.group(1)] = float(hash_match.group(2))
    # Miner logs persist after a crash; do not report stale hashrate as live.
    result["local_hashrate"] = round(sum(gpu_hashes.values()), 1) if result["miner_running"] else 0

    issues = []
    if not result["miner_running"]:
        issues.append("Miner not running")
    if not utils:
        issues.append("GPU metrics unavailable")
    elif result["gpu_util"] < 85:
        issues.append(f"Low GPU load ({result['gpu_util']}%)")
    if used and min(used) < 1000:
        issues.append("VRAM usage too low")
    if used and total and max(u / t for u, t in zip(used, total) if t > 0) > 0.5:
        issues.append("VRAM usage unusually high")
    if result["local_hashrate"] <= 0:
        issues.append("No local hashrate")
    else:
        normalized_gpu = str(entry.get("gpu_name", "")).lower().replace(" ", "_")
        expected_per_gpu = next(
            (rate for model, rate in vast.GPU_HASHRATES.items() if model in normalized_gpu),
            0,
        )
        expected_total = expected_per_gpu * int(entry.get("num_gpus", 1) or 1)
        if expected_total and result["local_hashrate"] < expected_total * 0.5:
            issues.append("Low local hashrate")
    if result["pool_hashrate"] is None:
        pass
    elif result["pool_hashrate"] <= 0:
        issues.append("Pool worker offline")
    elif result["local_hashrate"] > 0 and result["pool_hashrate"] < result["local_hashrate"] * 0.5:
        issues.append("Pool hashrate mismatch")

    result["health"] = "healthy" if not issues else "unhealthy"
    result["issue"] = "Healthy" if not issues else "; ".join(issues)
    return result


def list_instances(include_health: bool = False):
    """Return all instances, optionally with health metrics for running instances."""
    rc, stdout, _ = vast._vastai(["show", "instances", "--raw"], timeout=15)
    if rc != 0:
        print(json.dumps({"error": f"vastai error: {stdout}"}))
        return 1

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Failed to parse vastai output"}))
        return 1

    deployed_ids = vast._deployed_ids()
    pool_rates = _pool_hashrates() if include_health else None
    instances = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        status = entry.get("actual_status", entry.get("status", "unknown"))

        inst_id = str(entry.get("id", ""))
        gpu_name = entry.get("gpu_name", "?")
        num_gpus = entry.get("num_gpus", 1)
        try:
            price = float(entry.get("dph_total", entry.get("min_bid", 0)))
        except (TypeError, ValueError):
            price = 0

        machine_id = str(entry.get("machine_id", ""))
        ssh_host = entry.get("ssh_host", "") or entry.get("direct_port_host", "")
        ssh_port = str(entry.get("ssh_port", "") or entry.get("direct_port_start", "22"))

        instance = {
            "id": inst_id,
            "status": status,
            "gpu_name": gpu_name,
            "num_gpus": num_gpus,
            "price": round(price, 4),
            "is_bid": bool(entry.get("is_bid", False)),
            "min_bid": round(float(entry.get("min_bid", 0)), 4),
            "dlperf_per_dphtotal": round(float(entry.get("dlperf_per_dphtotal", 0)), 2),
            "machine_id": machine_id,
            "ssh_host": ssh_host,
            "ssh_port": ssh_port,
            "deployment_state": "unavailable",
            "health": "unavailable" if status != "running" else (
                "checking" if inst_id in deployed_ids else "pending"
            ),
            "issue": f"Instance is {status}" if status != "running" else (
                "Checking health..." if inst_id in deployed_ids else "Not deployed"
            ),
            "miner_running": False,
            "gpu_util": 0,
            "vram_used_mb": 0,
            "vram_total_mb": 0,
            "local_hashrate": 0,
            "pool_hashrate": round(pool_rates.get(inst_id[-4:], 0), 1) if pool_rates is not None else None,
        }
        instances.append(instance)

    if include_health:
        running = [inst for inst in instances if inst["status"] == "running"]
        entry_by_id = {str(entry.get("id")): entry for entry in data if isinstance(entry, dict)}
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(running)))) as executor:
            futures = {
                executor.submit(_inspect_running, entry_by_id[inst["id"]], deployed_ids, pool_rates): inst
                for inst in running
            }
            for future in as_completed(futures):
                futures[future].update(future.result())

    instances.sort(key=lambda inst: (inst["status"] != "running", inst["health"] != "unhealthy", inst["id"]))
    print(json.dumps(instances))
    return 0


def deploy(inst_id: str):
    """Deploy to a single instance."""
    result = vast.deploy_instance(inst_id, log=lambda message: print(message, flush=True))
    print(result)
    return 0 if result.startswith("Deployed:") else 1


def kill(inst_id: str, reason: str = "manual"):
    """Kill (destroy) a single instance."""
    result = vast.kill_instance(inst_id, reason=reason)
    print(result)
    return 0 if ("FAILED" not in result and "SKIP" not in result) else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 deploy_one.py [list|deploy|kill <instance_id>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        sys.exit(list_instances())
    elif cmd == "health":
        sys.exit(list_instances(include_health=True))
    elif cmd == "deploy":
        if len(sys.argv) < 3:
            print("Usage: python3 deploy_one.py deploy <instance_id>")
            sys.exit(1)
        sys.exit(deploy(sys.argv[2]))
    elif cmd == "kill":
        if len(sys.argv) < 3:
            print("Usage: python3 deploy_one.py kill <instance_id> [reason]")
            sys.exit(1)
        reason = sys.argv[3] if len(sys.argv) > 3 else "manual"
        sys.exit(kill(sys.argv[2], reason))
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python3 deploy_one.py [list|deploy|kill <instance_id>]")
        sys.exit(1)
