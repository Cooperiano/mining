#!/usr/bin/env python3
"""Parallel deployment manager for multiple mining instances."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import sys

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR))

from manager.vast import (
    list_instances,
    deploy_instance,
    kill_instance,
    DEPLOYED_FILE,
    BAD_FILE,
    _read_state,
    _strip_ansi,
)
from manager import vast

def get_pending_instances() -> list[tuple[str, str]]:
    """Get instances that need deployment (not deployed, not bad)."""
    rc, stdout, _ = vast._vastai(["show", "instances"], timeout=15)
    if rc != 0:
        return []

    deployed_ids = _read_state(DEPLOYED_FILE)
    bad_ids = _read_state(BAD_FILE)

    pending = []
    for line in _strip_ansi(stdout).split("\n"):
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[1] == "ID" or not parts[1].isdigit():
            continue
        inst_id = parts[1]
        status = parts[3] if len(parts) > 3 else "?"
        if status == "running" and inst_id not in deployed_ids and inst_id not in bad_ids:
            gpu_name = parts[4] if len(parts) > 4 else "UNKNOWN"
            pending.append((inst_id, gpu_name))
    return pending


def deploy_single(inst_id: str, gpu_name: str) -> dict:
    """Deploy to a single instance, return result dict."""
    result = {
        "inst_id": inst_id,
        "gpu": gpu_name,
        "status": "unknown",
        "message": "",
    }

    try:
        output = deploy_instance(inst_id)
        if "FAIL:" in output or "no outbound network" in output:
            result["status"] = "failed"
            result["message"] = output
            # Auto-kill bad instances
            if "no outbound network" in output:
                kill_result = kill_instance(inst_id, "no outbound network")
                result["kill_result"] = kill_result
        elif "Deployed:" in output:
            result["status"] = "success"
            result["message"] = output
        else:
            result["status"] = "partial"
            result["message"] = output
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)

    return result


def parallel_deploy(max_workers: int = 4) -> dict:
    """Deploy to all pending instances in parallel."""
    pending = get_pending_instances()

    results = {
        "timestamp": datetime.now().isoformat(),
        "pending_count": len(pending),
        "results": [],
    }

    if not pending:
        results["message"] = "No pending instances to deploy"
        return results

    print(f"🚀 Parallel deploy: {len(pending)} instances, {max_workers} workers")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(deploy_single, inst_id, gpu_name): (inst_id, gpu_name)
            for inst_id, gpu_name in pending
        }

        for future in as_completed(futures):
            inst_id, gpu_name = futures[future]
            try:
                result = future.result()
                results["results"].append(result)

                # Print progress
                status_emoji = {"success": "✅", "failed": "❌", "partial": "⏳", "error": "⚠️"}.get(result["status"], "❓")
                print(f"{status_emoji} {inst_id} ({result['gpu']}) -> {result['status']}")

            except Exception as e:
                results["results"].append({
                    "inst_id": inst_id,
                    "gpu": gpu_name,
                    "status": "exception",
                    "message": str(e),
                })

    # Summary
    success = sum(1 for r in results["results"] if r["status"] == "success")
    failed = sum(1 for r in results["results"] if r["status"] in ("failed", "error"))
    results["summary"] = {"success": success, "failed": failed}

    print(f"\n📊 Summary: {success} succeeded, {failed} failed")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parallel mining deployment")
    parser.add_argument("--workers", type=int, default=4, help="Max parallel workers")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = parallel_deploy(max_workers=args.workers)

    if args.json:
        import json
        print(json.dumps(result, indent=2))
