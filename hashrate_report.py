#!/usr/bin/env python3
"""Pull live hashrate from all running vast.ai instances."""

from __future__ import annotations

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"

SSH_OPTS = "-o StrictHostKeyChecking=no -o ConnectTimeout=8 -o LogLevel=QUIET"


def _ssh(host: str, port: str, cmd: str, timeout: int = 12) -> str:
    try:
        r = subprocess.run(
            f'ssh -q {SSH_OPTS} root@{host} -p {port} "{cmd}"',
            shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout
    except Exception:
        return ""


def main():
    # Get running instances
    result = subprocess.run(["vastai", "show", "instances"], capture_output=True, text=True, timeout=15)
    clean = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)

    instances = []
    for line in clean.split("\n"):
        parts = line.split()
        if len(parts) < 6 or not parts[1].isdigit():
            continue
        if parts[3] != "running":
            continue
        inst_id = parts[1]
        gpu_count = parts[4].rstrip("x")
        gpu_model = parts[5]
        instances.append((inst_id, f"{gpu_count}x {gpu_model}"))

    if not instances:
        print("No running instances.")
        return

    # Get all SSH URLs in parallel
    def _get_ssh_url(inst_id: str) -> tuple[str, str]:
        r = subprocess.run(["vastai", "ssh-url", inst_id], capture_output=True, text=True, timeout=10)
        return inst_id, r.stdout.strip()

    ssh_urls = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_get_ssh_url, inst_id) for inst_id, _ in instances]
        for f in as_completed(futures):
            inst_id, url = f.result()
            ssh_urls[inst_id] = url

    def _fetch_instance_data(inst_id: str, gpu_label: str) -> dict | None:
        url = ssh_urls.get(inst_id, "")
        m = re.search(r"@([^:]+):(\d+)", url)
        if not m:
            return None
        host, port = m.group(1), m.group(2)

        def _get_hashes():
            return _ssh(host, port,
                "grep 'hashrate_th_s=' /root/mining/miner.log 2>/dev/null | tail -8",
                timeout=15)

        def _get_power():
            return _ssh(host, port,
                "nvidia-smi --query-gpu=index,power.draw --format=csv,noheader 2>/dev/null")

        with ThreadPoolExecutor(max_workers=2) as inner:
            f_hash = inner.submit(_get_hashes)
            f_power = inner.submit(_get_power)
            hashes_raw = f_hash.result()
            power_raw = f_power.result()

        return {
            "inst_id": inst_id,
            "gpu_label": gpu_label,
            "hashes_raw": hashes_raw,
            "power_raw": power_raw,
        }

    print(f"{BOLD}{'='*75}{RESET}")
    print(f"{BOLD}  PEARL MINER HASHRATE REPORT  {time.strftime('%H:%M:%S')}{RESET}")
    print(f"{BOLD}{'='*75}{RESET}")
    print(f"  {'Instance':<12} {'GPU':>3} {'Model':<16} {'TH/s':>9}  {'Power':>8}")
    print(f"  {'─'*57}")

    grand_total = 0.0
    gpu_total = 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_fetch_instance_data, inst_id, gpu_label): inst_id
            for inst_id, gpu_label in instances
        }
        for f in as_completed(futures):
            data = f.result()
            if data is None:
                inst_id = futures[f]
                print(f"  {inst_id:<12} {RED}no SSH{RESET}")
                continue

            inst_id = data["inst_id"]
            gpu_label = data["gpu_label"]
            hashes_raw = data["hashes_raw"]
            power_raw = data["power_raw"]

            gpu_hashes: dict[int, float] = {}
            gpu_names: dict[int, str] = {}
            for line in hashes_raw.strip().split("\n"):
                mh = re.search(r"gpu=(\d+):(.+?) component.*hashrate_th_s=([\d.]+)", line)
                if mh:
                    gpu_id = int(mh.group(1))
                    gpu_name = mh.group(2).replace("NVIDIA_GeForce_", "").replace("_", " ")
                    th = float(mh.group(3))
                    if gpu_id not in gpu_hashes or th > gpu_hashes[gpu_id]:
                        gpu_hashes[gpu_id] = th
                        gpu_names[gpu_id] = gpu_name.replace("NVIDIA GeForce ", "").replace("NVIDIA", "").strip()

            power: dict[str, str] = {}
            for line in power_raw.strip().split("\n"):
                parts = line.split(", ")
                if len(parts) >= 2:
                    power[parts[0]] = parts[1].replace(" W", "")

            inst_total = 0
            if not gpu_hashes:
                print(f"  {inst_id:<12} {gpu_label:<10} {RED}no miner data{RESET}")
                continue

            for gpu_id in sorted(gpu_hashes.keys()):
                th = gpu_hashes[gpu_id]
                name = gpu_names.get(gpu_id, "?")
                pw = power.get(str(gpu_id), "?")

                if th >= 200:
                    color = GREEN
                elif th >= 80:
                    color = CYAN
                elif th > 0:
                    color = YELLOW
                else:
                    color = RED

                print(f"  {inst_id:<12} {gpu_id:>3} {name:<16} {color}{th:>9.1f}{RESET}  {pw:>6}W")
                inst_total += th
                gpu_total += 1

            grand_total += inst_total
            if len(gpu_hashes) > 1:
                print(f"  {'':<12} {'':>3} {'─'*16} {BOLD}{inst_total:>9.1f}{RESET}")
            print()

    print(f"  {BOLD}{'═'*57}{RESET}")
    print(f"  {BOLD}TOTAL: {grand_total:.1f} TH/s  |  {gpu_total} GPUs{RESET}")

    earn_rate = 3.226
    prl_price = 0.80
    prl_hr = grand_total / 1000 * earn_rate
    usd_hr = prl_hr * prl_price
    print(f"  Est earnings: {CYAN}{prl_hr:.2f} PRL/hr{RESET}  (${usd_hr:.2f}/hr)")
    print(f"  {BOLD}{'═'*57}{RESET}")


if __name__ == "__main__":
    main()
