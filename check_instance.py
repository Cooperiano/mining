#!/usr/bin/env python3
"""Check if a rented GPU is profitable for Pearl mining.

Formula: Earnings($/hr) = TH/s / 1000 * 3.226 * PRICE

Usage:
    python3 check_instance.py --th 300 --price 0.56
    python3 check_instance.py --th 105,90,53,68 --total-price 2.24
    python3 check_instance.py --api  # scan all running vast.ai workers
"""

import argparse
import json
import subprocess
import sys

EARN_RATE = 3.226    # PRL per hour per 1000 TH/s (1 PH/s)
PRL_PRICE = 0.80     # USD per PRL

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
BOLD = "\033[1m"


def earnings(th_s):
    return th_s / 1000 * EARN_RATE * PRL_PRICE


def fmt(usd):
    if usd >= 0.01:
        return f"${usd:.2f}/hr"
    return f"${usd:.4f}/hr"


def check_gpu(th_s, cost_per_gpu):
    earn = earnings(th_s)
    profit = earn - cost_per_gpu
    if profit > 0:
        tag = f"{GREEN}PROFIT{RESET}"
    elif profit > -0.05:
        tag = f"{YELLOW}MARGINAL{RESET}"
    else:
        tag = f"{RED}LOSS{RESET}"
    return earn, profit, tag


def print_gpu(name, th_s, cost, earn, profit, tag):
    print(f"  {BOLD}{name:<16}{RESET}"
          f" {th_s:>7.0f} TH/s"
          f"  earn {fmt(earn):>10}"
          f"  cost {fmt(cost):>10}"
          f"  net {fmt(profit):>10}"
          f"  [{tag}]")


def check_instance(per_gpu_th, per_gpu_cost, label=""):
    print(f"\n{BOLD}=== {label or 'Instance'} ==={RESET}")
    total_earn = 0
    total_cost = 0

    for i, (th, cost) in enumerate(zip(per_gpu_th, per_gpu_cost)):
        earn, profit, tag = check_gpu(th, cost)
        total_earn += earn
        total_cost += cost
        print_gpu(f"GPU #{i}", th, cost, earn, profit, tag)

    total_profit = total_earn - total_cost
    tag = GREEN + "PROFIT" + RESET if total_profit > 0 else RED + "LOSS" + RESET
    print(f"  {'─' * 60}")
    print(f"  {BOLD}{'TOTAL':<16}{RESET}"
          f" {'—':>7}"
          f"  earn {fmt(total_earn):>10}"
          f"  cost {fmt(total_cost):>10}"
          f"  net {fmt(total_profit):>10}"
          f"  [{tag}]")
    return total_profit


def scan_vast():
    """Query AlphaPool API for all workers, cross-ref with vast.ai instances."""
    import urllib.request

    wallet = "prl1pyvv3nzlvyahzgdhsg4c4sm3z6ukv9zcc39genld24yw4thmet6asevn44h"
    url = f"https://pearl.alphapool.tech/api/miner/{wallet}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"API error: {e}")
        return

    # Get vast.ai instances
    try:
        out = subprocess.check_output(
            ["vastai", "show", "instances"], timeout=10, text=True
        )
    except Exception:
        out = ""

    # Parse vast instances: id -> price/hr
    vast_prices = {}
    for line in out.split("\n"):
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            inst_id = parts[1]
            price = float(parts[7])
            gpu_count = int(parts[4].rstrip("x"))
            num_gpus = int(parts[5])
            vast_prices[inst_id] = (price, gpu_count * int(parts[5]))
        except (ValueError, IndexError):
            continue

    workers = data.get("workers", [])
    online = [w for w in workers if w.get("online")]

    print(f"\n{BOLD}Online workers: {len(online)}  |  "
          f"Balance: {data.get('balance_prl', 0):.2f} PRL  |  "
          f"Paid: {data.get('total_paid_prl', 0):.2f} PRL{RESET}\n")

    # Group workers by machine
    groups = {}
    for w in online:
        name = w["name"]
        live = float(w["hashrate_live"].split()[0])
        h1 = float(w["hashrate_1h"].split()[0])

        if "5090x4-2" in name:
            group = "vast-b"
        elif "5090x4" in name:
            group = "vast-a"
        elif "miner2" in name:
            group = "lab1"
        elif "miner1" in name:
            group = "station"
        elif "miner3" in name:
            group = "laptop"
        else:
            group = "other"

        if group not in groups:
            groups[group] = []
        groups[group].append((live, h1, name))

    for group, gpus in sorted(groups.items()):
        th_values = [g[0] for g in gpus]
        avg_th = sum(th_values) / len(th_values)
        total_th = sum(th_values)
        earn = earnings(total_th)

        if group in ("station", "lab1", "laptop"):
            cost = 0  # owned
        else:
            cost = 0  # unknown rental price

        tag = GREEN + "OWN" + RESET if cost == 0 else ""
        print(f"  {BOLD}{group:<10}{RESET} {len(gpus)} GPUs  "
              f"Σ {total_th:.0f} TH/s  avg {avg_th:.0f}  ",
              end="")
        if cost > 0:
            profit = earn - cost
            tag = GREEN + f"PROFIT +${profit:.2f}" + RESET if profit > 0 else RED + f"LOSS -${abs(profit):.2f}" + RESET
        print(f"earn {fmt(earn)}  [{tag}]")

    # highlight bad GPUs
    print(f"\n{BOLD}{RED}⚠  Low performers (< 200 TH/s on 5090):{RESET}")
    for w in online:
        name = w["name"]
        if "5090" not in name:
            continue
        live = float(w["hashrate_live"].split()[0])
        if live < 200:
            h1 = float(w["hashrate_1h"].split()[0])
            print(f"  {name:<24} live {live:.0f} TH/s  1h {h1:.0f} TH/s  →  KILL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pearl mining profitability checker")
    parser.add_argument("--th", type=str, help="Comma-separated TH/s per GPU, e.g. '300,290,310'")
    parser.add_argument("--price", type=float, help="Cost per GPU per hour")
    parser.add_argument("--total-price", type=float, help="Total instance cost per hour (divided by GPU count)")
    parser.add_argument("--gpus", type=int, default=1, help="Number of GPUs")
    parser.add_argument("--api", action="store_true", help="Scan AlphaPool API for all workers")
    parser.add_argument("--min-th", type=float, default=200, help="Minimum TH/s for 5090 (default: 200)")
    parser.add_argument("--prl-price", type=float, default=0.80, help="PRL price in USD")

    args = parser.parse_args()

    if args.prl_price:
        PRL_PRICE = args.prl_price

    if args.api:
        scan_vast()
        sys.exit(0)

    if not args.th:
        parser.error("--th is required (or use --api)")

    th_list = [float(x.strip()) for x in args.th.split(",")]

    if args.total_price:
        cost_per = args.total_price / len(th_list)
    elif args.price:
        cost_per = args.price
    else:
        parser.error("--price or --total-price required")

    costs = [cost_per] * len(th_list)
    profit = check_instance(th_list, costs, "Manual Check")

    if profit < 0:
        print(f"\n{RED}VERDICT: KILL — losing ${abs(profit):.2f}/hr{RESET}\n")
    else:
        print(f"\n{GREEN}VERDICT: KEEP — earning ${profit:.2f}/hr{RESET}\n")
