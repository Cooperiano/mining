#!/usr/bin/env python3
"""Generate cost/profit report for running vast.ai instances."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
WALLET = "prl1pyvv3nzlvyahzgdhsg4c4sm3z6ukv9zcc39genld24yw4thmet6asevn44h"
API_URL = f"https://pearl.alphapool.tech/api/miner/{WALLET}"

EARN_RATE = 3.226  # PRL/hr per TH/s

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def main():
    # Get instances
    raw = _run(["vastai", "show", "instances"], timeout=15)
    clean = _strip_ansi(raw)

    instances = []
    for line in clean.split("\n"):
        parts = line.split()
        if len(parts) < 12 or not parts[1].isdigit():
            continue
        if parts[3] != "running":
            continue
        inst_id = parts[1]
        machine = parts[2]
        gpu_count = int(parts[4].rstrip("x"))
        gpu_model = parts[5]
        try:
            price = float(parts[8])
        except ValueError:
            price = 0.0
        uptime = int(parts[12]) if len(parts) > 12 and parts[12].isdigit() else 0
        instances.append({
            "id": inst_id,
            "machine": machine,
            "gpus": gpu_count,
            "model": gpu_model,
            "price": price,
            "uptime": uptime,
        })

    # Get pool data
    try:
        import urllib.request
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            pool_data = json.loads(resp.read())
    except Exception as e:
        pool_data = {"workers": [], "hashrate": "0", "balance": "0", "paid": "0"}

    # Build worker hashrate map
    worker_th: dict[str, float] = {}
    total_th = 0.0
    for w in pool_data.get("workers", []):
        try:
            live = float(w["hashrate_live"].split()[0])
            name = w["name"]
            worker_th[name] = live
            total_th += live
        except (ValueError, KeyError):
            pass

    # Summary
    total_cost = sum(i["price"] for i in instances)
    total_gpus = sum(i["gpus"] for i in instances)
    earnings_prl = total_th / 1000 * EARN_RATE

    print(f"{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  PEARL MINING — COST REPORT @ {time.strftime('%Y-%m-%d %H:%M')}{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    # Per-instance breakdown
    print(f"\n{BOLD}Instances:{RESET}")
    print(f"  {'ID':<10} {'Machine':<8} {'GPUs':>4} {'Cost/hr':>9} {'Cost/GPU':>9} {'TH/s':>8} {'$/hr':>8} {'Profit':>8}")
    print(f"  {'─'*10} {'─'*8} {'─'*4} {'─'*9} {'─'*9} {'─'*8} {'─'*8} {'─'*8}")

    for inst in instances:
        inst_id = inst["id"]
        # Estimate this instance's TH/s from pool data by matching worker name suffix
        suffix = inst_id[-4:]
        inst_th = sum(v for k, v in worker_th.items() if suffix in k)
        inst_earnings = inst_th / 1000 * EARN_RATE
        # Rough PRL price
        prl_price = 0.80
        inst_usd = inst_earnings * prl_price
        profit = inst_usd - inst["price"]
        color = GREEN if profit > 0 else RED

        print(f"  {inst_id:<10} {inst['machine']:<8} {inst['gpus']:>4} "
              f"${inst['price']:<7.3f} ${inst['price']/inst['gpus']:<7.3f} "
              f"{color}{inst_th:>7.0f} ${inst_usd:<6.2f} ${profit:<+.3f}{RESET}")

    # Totals
    total_earnings_usd = earnings_prl * 0.80
    net = total_earnings_usd - total_cost

    print(f"  {'─'*69}")
    print(f"  {'TOTAL':<18} {total_gpus:>4}  ${total_cost:<7.3f}          "
          f"{BOLD}{total_th:>7.0f} ${total_earnings_usd:<6.2f} {GREEN if net > 0 else RED}${net:<+.3f}{RESET}")
    print()

    # Pool summary
    balance = pool_data.get("balance", "?")
    paid = pool_data.get("paid", "?")
    unpaid = pool_data.get("payments_count", 0)
    print(f"  Pool balance: {balance} PRL  |  Total paid: {paid} PRL  |  Unpaid shares: {unpaid}")
    print(f"  Hashrate: {total_th:.0f} TH/s  |  Est: {earnings_prl:.1f} PRL/hr (${total_earnings_usd:.2f}/hr)")
    print(f"  Rental cost: ${total_cost:.3f}/hr (${total_cost*24:.2f}/day)")

    daily = pool_data.get("payments_by_day", [])
    if daily:
        print(f"\n  Recent earnings:")
        for d in daily[-5:]:
            print(f"    {d['day']}: {d['amount_prl']:.2f} PRL (${d['amount_prl']*0.80:.2f})")

    print(f"\n{BOLD}{'='*70}{RESET}")


if __name__ == "__main__":
    main()
