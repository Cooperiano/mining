#!/usr/bin/env python3
"""Re-rent saved good instances at interruptible (bid) pricing.

Reads .vast_saved to find matching offers, rents them,
then deploys Pearl miner automatically.

Usage:
    python3 re_rent.py                 # rent all saved machines
    python3 re_rent.py 58921           # rent specific machine only
    python3 re_rent.py --dry-run       # search only, don't rent
    python3 re_rent.py --deploy-only   # deploy to currently running instances
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

SAVED_FILE = Path(__file__).resolve().parent / ".vast_saved"

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def load_saved() -> list[dict]:
    """Parse .vast_saved into list of {machine_id, gpu_count, gpu_model, max_price, label}."""
    if not SAVED_FILE.exists():
        print(f"{RED}.vast_saved not found{RESET}")
        return []
    saved = []
    for line in SAVED_FILE.read_text().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 5:
            saved.append({
                "machine_id": parts[0],
                "gpu_count": int(parts[1]),
                "gpu_model": parts[2],
                "max_price": float(parts[3]),
                "label": parts[4],
            })
    return saved


def search_offer(machine_id: str, gpu_model: str, gpu_count: int) -> dict | None:
    """Search for interruptible offer on a specific machine. Returns offer dict or None."""
    query = f"gpu_name={gpu_model} num_gpus={gpu_count} machine_id={machine_id} inet_up>=1"
    result = subprocess.run(
        ["vastai", "search", "offers", query, "--type", "on-demand", "--raw", "--limit", "3"],
        capture_output=True, text=True, timeout=30,
    )
    if not result.stdout.strip():
        return None
    try:
        offers = __import__("json").loads(result.stdout)
    except Exception:
        # Try non-raw
        result2 = subprocess.run(
            ["vastai", "search", "offers", query, "--type", "on-demand", "--limit", "3"],
            capture_output=True, text=True, timeout=30,
        )
        # Parse text output
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result2.stdout)
        for line in clean.split("\n"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return {"offer_id": parts[1], "price": "?"}
        return None

    if isinstance(offers, list) and offers:
        return offers[0]
    if isinstance(offers, dict) and "offers" in offers and offers["offers"]:
        return offers["offers"][0]
    return None


def search_offer_interruptible(machine_id: str, gpu_model: str, gpu_count: int) -> dict | None:
    """Search for interruptible (bid) offer on a specific machine."""
    query = f"gpu_name={gpu_model} num_gpus={gpu_count} machine_id={machine_id} inet_up>=1"
    result = subprocess.run(
        ["vastai", "search", "offers", query, "--type", "bid", "--limit", "3", "--raw"],
        capture_output=True, text=True, timeout=30,
    )
    if not result.stdout.strip():
        return None
    try:
        offers = __import__("json").loads(result.stdout)
    except Exception:
        return None

    if isinstance(offers, list) and offers:
        return offers[0]
    if isinstance(offers, dict) and "offers" in offers and offers["offers"]:
        return offers["offers"][0]
    return None


def rent_instance(offer: dict, label: str, interruptible: bool = False) -> str | None:
    """Rent an offer and return instance_id or None."""
    offer_id = offer.get("id") or offer.get("offer_id") or offer.get("contract_id")
    if not offer_id:
        return None

    args = [
        "vastai", "create", "instance", str(offer_id),
        "--image", "nvidia/cuda:12.4.0-devel-ubuntu22.04",
        "--disk", "20",
        "--onstart-cmd", "nvidia-smi",
        "--direct",
    ]
    if interruptible:
        args.append("--bid")

    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    try:
        data = __import__("json").loads(result.stdout)
        contract = data.get("new_contract") or data.get("contract_id")
        if contract:
            print(f"  {GREEN}Rented: {contract} (offer {offer_id}){RESET}")
            return str(contract)
    except Exception:
        pass

    # Try parsing text output
    m = re.search(r"new_contract[:\s]+(\d+)", result.stdout)
    if m:
        print(f"  {GREEN}Rented: {m.group(1)}{RESET}")
        return m.group(1)
    return None


def deploy_to(inst_id: str, worker_label: str, gpu_type: str) -> bool:
    """Deploy Pearl miner to instance."""
    from manager.deploy import generate_deploy_script
    import base64

    # Get SSH URL
    r = subprocess.run(["vastai", "ssh-url", inst_id], capture_output=True, text=True, timeout=15)
    url = r.stdout.strip()
    m = re.search(r"@([^:]+):(\d+)", url)
    if not m:
        print(f"  {RED}No SSH URL for {inst_id}{RESET}")
        return False
    host, port = m.group(1), m.group(2)

    script = generate_deploy_script(worker=worker_label, gpu_type=gpu_type)
    b64 = base64.b64encode(script.encode()).decode()

    cmd = [
        "ssh", "-q",
        "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=no",
        "-o", "LogLevel=QUIET",
        f"root@{host}", "-p", port,
        f"echo '{b64}' | base64 -d | bash",
    ]
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r2.returncode == 0:
        print(f"  {GREEN}Deployed: {inst_id} -> {worker_label}{RESET}")
        # Record
        deployed = Path(__file__).resolve().parent / ".vast_deployed"
        ids = set(deployed.read_text().strip().split("\n")) if deployed.exists() else set()
        ids.add(inst_id)
        deployed.write_text("\n".join(sorted(ids)) + "\n")
        return True
    else:
        print(f"  {RED}Deploy failed: {inst_id}{RESET}")
        return False


def wait_and_deploy(inst_id: str, worker_label: str, gpu_type: str, timeout: int = 300) -> bool:
    """Wait for instance to reach running, then deploy."""
    start = time.time()
    while time.time() - start < timeout:
        r = subprocess.run(
            ["vastai", "show", "instance", inst_id], capture_output=True, text=True, timeout=15
        )
        clean = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)
        if "running" in clean and inst_id in clean:
            print(f"  Instance ready, deploying...")
            return deploy_to(inst_id, worker_label, gpu_type)
        if any(s in clean.lower() for s in ["exited", "offline", "unknown"]):
            print(f"  {RED}Instance {inst_id} failed to boot{RESET}")
            return False
        time.sleep(10)
    print(f"  {YELLOW}Timeout waiting for {inst_id}{RESET}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Re-rent saved instances at bid pricing")
    parser.add_argument("machine_ids", nargs="*", help="Machine IDs to re-rent (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Search only, don't rent")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for boot after renting")
    args = parser.parse_args()

    all_saved = load_saved()
    if not all_saved:
        return

    # Filter by machine_id if specified
    if args.machine_ids:
        all_saved = [s for s in all_saved if s["machine_id"] in args.machine_ids]
        if not all_saved:
            print(f"No saved entries match: {args.machine_ids}")
            return

    print(f"{BOLD}Re-rent saved instances{RESET}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'RENT + DEPLOY'}")
    print()

    total_rented = 0
    for entry in all_saved:
        mid = entry["machine_id"]
        gpu = entry["gpu_model"]
        count = entry["gpu_count"]
        max_p = entry["max_price"]
        label = entry["label"]

        print(f"  [{mid}] {count}x {gpu} (max ${max_p:.2f}/hr)")

        # Search interruptible first
        offer = search_offer_interruptible(mid, gpu, count)
        is_interruptible = True
        if not offer:
            offer = search_offer(mid, gpu, count)
            is_interruptible = False

        if not offer:
            print(f"    {YELLOW}No offers found for machine {mid}{RESET}")
            continue

        price = offer.get("min_bid") or offer.get("dph_total") or offer.get("price") or "?"
        bid_type = "INT" if is_interruptible else "on-demand"
        print(f"    Found: offer {offer.get('id', '?')} | ${price} [{bid_type}]")

        if float(str(price).replace("$", "")) > max_p * 1.1:
            print(f"    {YELLOW}Price ${price} exceeds max ${max_p:.2f}/hr, skipping{RESET}")
            continue

        if args.dry_run:
            continue

        # Rent
        print(f"    Renting...")
        inst_id = rent_instance(offer, label, interruptible=is_interruptible)
        if not inst_id:
            print(f"    {RED}Rent failed{RESET}")
            continue

        total_rented += 1

        # Wait and deploy
        if not args.no_wait:
            wait_and_deploy(inst_id, label, gpu_type=gpu.lower().replace("rtx_", ""))
        print()

    print(f"\n{BOLD}Rented: {total_rented} instances{RESET}")


if __name__ == "__main__":
    main()
