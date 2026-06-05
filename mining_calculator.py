#!/usr/bin/env python3
"""GPU Mining Profitability Calculator

Supports RTX 3080 benchmarks for popular mineable coins.
Auto-fetches live prices when network is available, accepts manual input otherwise.
"""

import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "mining_config.json"

# Default coin prices (fallback when offline) - update periodically
DEFAULT_PRICES = {
    "ETC (Etchash)":      28.50,
    "ETHW (Ethash)":      3.20,
    "ERG (Autolykos2)":   1.15,
    "RVN (KawPow)":       0.022,
    "NEXA (NexaPow)":     0.00021,
    "CFX (Octopus)":      0.16,
    "KAS (kHeavyHash)":   0.12,
    "ALPH (Blake3)":      1.85,
    "ZEC (Equihash)":     32.00,
    "ZEN (Equihash)":     12.50,
    "CLORE (KawPow)":     0.045,
    "XMR (RandomX-monero)": 165.00,
}

# RTX 3080 hashrate benchmarks (MH/s for Ethash-like, Sol/s for others)
RTX3080_BENCHMARKS = {
    "ETC (Etchash)":       {"algo": "etchash",    "hashrate": 95.0,  "unit": "MH/s", "power": 240},
    "ETHW (Ethash)":       {"algo": "ethash",     "hashrate": 95.0,  "unit": "MH/s", "power": 240},
    "ERG (Autolykos2)":    {"algo": "autolykos2", "hashrate": 190.0, "unit": "MH/s", "power": 200},
    "RVN (KawPow)":        {"algo": "kawpow",     "hashrate": 48.0,  "unit": "MH/s", "power": 280},
    "NEXA (NexaPow)":      {"algo": "nexapow",    "hashrate": 95.0,  "unit": "MH/s", "power": 180},
    "CFX (Octopus)":       {"algo": "octopus",    "hashrate": 90.0,  "unit": "MH/s", "power": 230},
    "KAS (kHeavyHash)":    {"algo": "kheavyhash", "hashrate": 800.0, "unit": "MH/s", "power": 180},
    "ALPH (Blake3)":       {"algo": "blake3",     "hashrate": 2800.0,"unit": "MH/s", "power": 160},
    "ZEC (Equihash)":      {"algo": "equihash",   "hashrate": 100.0, "unit": "Sol/s","power": 240},
    "ZEN (Equihash)":      {"algo": "equihash",   "hashrate": 100.0, "unit": "Sol/s","power": 240},
    "CLORE (KawPow)":      {"algo": "kawpow",     "hashrate": 48.0,  "unit": "MH/s", "power": 280},
    "XMR (RandomX-monero)":{"algo": "rx/0",       "hashrate": 13500.0,"unit":"H/s",  "power": 120},  # CPU, not GPU
}


@dataclass
class MiningConfig:
    coin: str = "ETC (Etchash)"
    electricity_cost: float = 0.10  # USD per kWh
    gpu_power_w: float = 240
    coin_price_usd: float = 0.0
    network_hashrate: float = 0.0  # total network hashrate
    block_reward: float = 0.0
    block_time: float = 0.0        # seconds
    gpu_count: int = 1
    manual_override: bool = True


def load_config() -> MiningConfig:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return MiningConfig(**{k: data.get(k, v) for k, v in MiningConfig.__dataclass_fields__.items()
                               if k in data or k in data})
    return MiningConfig()


def save_config(cfg: MiningConfig):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg.__dict__, f, indent=2)


def fetch_prices(coins: list[str]) -> dict[str, float]:
    """Try to fetch coin prices from CoinGecko. Falls back gracefully."""
    coin_ids = ["ethereum-classic", "ethereum-pow", "ergo", "ravencoin", "nexa",
                "conflux-token", "kaspa", "alephium", "zcash", "horizen", "bitcoin",
                "monero"]
    name_to_id = {
        "ETC (Etchash)": "ethereum-classic",
        "ETHW (Ethash)": "ethereum-pow",
        "ERG (Autolykos2)": "ergo",
        "RVN (KawPow)": "ravencoin",
        "NEXA (NexaPow)": "nexa",
        "CFX (Octopus)": "conflux-token",
        "KAS (kHeavyHash)": "kaspa",
        "ALPH (Blake3)": "alephium",
        "ZEC (Equihash)": "zcash",
        "ZEN (Equihash)": "horizen",
        "CLORE (KawPow)": "clore-ai",
        "XMR (RandomX-monero)": "monero",
    }
    relevant = [name_to_id[c] for c in coins if c in name_to_id]
    if not relevant:
        return {}
    try:
        ids_str = ",".join(relevant)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        prices = {}
        for name, cgid in name_to_id.items():
            if cgid in data:
                prices[name] = data[cgid]["usd"]
        return prices
    except Exception:
        return {}


def calc_daily_earnings(cfg: MiningConfig, benchmark: dict) -> dict:
    """Calculate daily earnings based on hashrate and network stats."""
    hr = benchmark["hashrate"] * cfg.gpu_count

    # Network-based estimate (if we have network data)
    if cfg.network_hashrate > 0 and cfg.block_reward > 0 and cfg.block_time > 0:
        blocks_per_day = 86400 / cfg.block_time
        daily_coins = (hr / cfg.network_hashrate) * blocks_per_day * cfg.block_reward
    else:
        # Fallback: rough estimate based on whattomine-like ratios
        # These are approximate daily earnings per RTX 3080 at mid-2024 levels
        fallback = {
            "ETC (Etchash)":     0.022,
            "ETHW (Ethash)":     0.005,
            "ERG (Autolykos2)":  0.38,
            "RVN (KawPow)":      28.0,
            "NEXA (NexaPow)":    1200.0,
            "CFX (Octopus)":     5.0,
            "KAS (kHeavyHash)":  120.0,
            "ALPH (Blake3)":     5.5,
            "ZEC (Equihash)":    0.005,
            "ZEN (Equihash)":    0.018,
            "CLORE (KawPow)":    14.0,
            "XMR (RandomX-monero)": 0.005,
        }
        daily_coins = fallback.get(cfg.coin, 0.0) * cfg.gpu_count

    price = cfg.coin_price_usd if cfg.coin_price_usd > 0 else 0.0
    daily_usd = daily_coins * price
    daily_power_kwh = (benchmark["power"] * cfg.gpu_count * 24) / 1000
    daily_electric_cost = daily_power_kwh * cfg.electricity_cost
    daily_profit = daily_usd - daily_electric_cost

    return {
        "hashrate": hr,
        "hashrate_unit": benchmark["unit"],
        "power_w": benchmark["power"] * cfg.gpu_count,
        "daily_coins": daily_coins,
        "daily_usd": daily_usd,
        "daily_electric_cost": daily_electric_cost,
        "daily_profit": daily_profit,
        "weekly_profit": daily_profit * 7,
        "monthly_profit": daily_profit * 30,
        "yearly_profit": daily_profit * 365,
    }


def color(val: float, unit: str = "$") -> str:
    if val > 0:
        return f"\033[32m+{val:.4f} {unit}\033[0m"
    elif val < 0:
        return f"\033[31m{val:.4f} {unit}\033[0m"
    return f"{val:.4f} {unit}"


def print_summary(cfg: MiningConfig, results: dict, prices: dict):
    bench = RTX3080_BENCHMARKS[cfg.coin]
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print(f"║  MINING PROFITABILITY REPORT                             ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Coin:      {cfg.coin:<42} ║")
    print(f"║  Algorithm: {bench['algo']:<42} ║")
    print(f"║  GPUs:      {cfg.gpu_count}x RTX 3080 ({bench['power']*cfg.gpu_count}W total) {'':>17}║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Hashrate:      {results['hashrate']:>8.1f} {results['hashrate_unit']} {'':>21}║")
    print(f"║  Power:         {results['power_w']:>8.0f} W {'':>25}║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Coin Price:    ${cfg.coin_price_usd:>9.4f} {'':>27}║")
    print(f"║  Daily Coins:   {results['daily_coins']:>8.4f} {'':>29}║")

    daily_str = f"${results['daily_usd']:.4f}" if results['daily_usd'] > 0 else "N/A"
    print(f"║  Daily Revenue:  {daily_str:>9} {'':>26}║")
    print(f"║  Daily Electric: ${results['daily_electric_cost']:>8.4f} {'':>27}║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Daily Profit:   {color(results['daily_profit']):>33}    ║")
    print(f"║  Weekly Profit:  {color(results['weekly_profit']):>32}   ║")
    print(f"║  Monthly Profit: {color(results['monthly_profit']):>31}  ║")
    print(f"║  Yearly Profit:  {color(results['yearly_profit'], ''):>29}   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Profitability judgment
    if results["daily_profit"] > 2:
        print("  ==> \033[32mPROFITABLE ✓\033[0m - Good daily returns")
    elif results["daily_profit"] > 0:
        print("  ==> \033[33mMARGINAL ~\033[0m - Barely profitable")
    else:
        print("  ==> \033[31mNOT PROFITABLE ✗\033[0m - Losing money at current prices")


def print_all_coins(cfg: MiningConfig, prices: dict):
    """Compare profitability across all supported coins."""

    rows = []
    for coin, bench in RTX3080_BENCHMARKS.items():
        coin_price = prices.get(coin, DEFAULT_PRICES.get(coin, 0.0))
        temp_cfg = MiningConfig(
            coin=coin,
            electricity_cost=cfg.electricity_cost,
            coin_price_usd=coin_price,
            gpu_count=cfg.gpu_count,
        )
        r = calc_daily_earnings(temp_cfg, bench)
        rows.append((coin, r["daily_usd"], r["daily_electric_cost"], r["daily_profit"], bench["algo"]))

    rows.sort(key=lambda x: x[3], reverse=True)

    print()
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║  ALL COINS COMPARISON (RTX 3080, 1 GPU)                                  ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    print(f"║ {'Coin':<20} {'Algo':<15} {'Daily$':>9} {'Cost$':>9} {'Profit$':>10} ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    for coin, daily_usd, cost, profit, algo in rows:
        ps = f"+${profit:.4f}" if profit >= 0 else f"${profit:.4f}"
        print(f"║ {coin:<20} {algo:<15} ${daily_usd:>7.4f}  ${cost:>7.4f} {ps:>10} ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print()


def interactive_mode():
    cfg = load_config()

    print()
    print("=" * 60)
    print("  GPU MINING PROFITABILITY CALCULATOR")
    print("=" * 60)

    # Select coin
    coins = list(RTX3080_BENCHMARKS.keys())
    print(f"\nSupported coins ({len(coins)}):")
    for i, name in enumerate(coins, 1):
        bench = RTX3080_BENCHMARKS[name]
        print(f"  {i:2d}. {name:<22} ({bench['algo']:<12} {bench['hashrate']:>7.0f} {bench['unit']}, {bench['power']}W)")

    try:
        choice = input(f"\nSelect coin [1-{len(coins)}, default=1]: ").strip()
        if choice and choice.isdigit() and 1 <= int(choice) <= len(coins):
            cfg.coin = coins[int(choice) - 1]
        elif choice:
            print(f"  Using: {cfg.coin}")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    bench = RTX3080_BENCHMARKS[cfg.coin]

    # Electricity cost
    try:
        ec = input(f"Electricity cost $/kWh [default={cfg.electricity_cost}]: ").strip()
        if ec:
            cfg.electricity_cost = float(ec)
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    # GPU count
    try:
        gc = input(f"Number of GPUs [default={cfg.gpu_count}]: ").strip()
        if gc:
            cfg.gpu_count = int(gc)
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    # Fetch prices or use defaults
    print("\nFetching live prices...")
    prices = fetch_prices(coins)

    if prices and cfg.coin in prices:
        cfg.coin_price_usd = float(prices[cfg.coin])
        print(f"  {cfg.coin}: ${cfg.coin_price_usd:.4f} (live)")
    elif cfg.coin in DEFAULT_PRICES and cfg.coin_price_usd == 0:
        cfg.coin_price_usd = DEFAULT_PRICES[cfg.coin]
        print(f"  {cfg.coin}: ${cfg.coin_price_usd:.4f} (cached)")
    else:
        print(f"  Using price: ${cfg.coin_price_usd:.4f}")

    try:
        cp = input(f"  Override {cfg.coin} price USD [enter to keep]: ").strip()
        if cp:
            cfg.coin_price_usd = float(cp)
    except (EOFError, KeyboardInterrupt):
        pass

    # Network difficulty (optional)
    try:
        nh = input(f"\nTotal network hashrate in {bench['unit']} (0 to use fallback) [0]: ").strip()
        if nh:
            cfg.network_hashrate = float(nh)
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if cfg.network_hashrate > 0:
        try:
            br = input("Block reward [0]: ").strip()
            if br:
                cfg.block_reward = float(br)
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        try:
            bt = input("Block time in seconds [0]: ").strip()
            if bt:
                cfg.block_time = float(bt)
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    save_config(cfg)

    # Calculate and display
    results = calc_daily_earnings(cfg, bench)
    print_summary(cfg, results, prices)

    # Show all coins comparison
    show_all = input("Show comparison of all coins? [y/N]: ").strip().lower()
    if show_all == "y":
        print_all_coins(cfg, prices)


def cmdline_mode():
    import argparse
    parser = argparse.ArgumentParser(description="GPU Mining Profitability Calculator")
    parser.add_argument("--coin", type=str, help="Coin to mine")
    parser.add_argument("--price", type=float, help="Coin price in USD")
    parser.add_argument("--electricity", type=float, default=0.10, help="Electricity cost $/kWh")
    parser.add_argument("--gpus", type=int, default=1, help="Number of GPUs")
    parser.add_argument("--all", action="store_true", help="Show all coins comparison")
    args = parser.parse_args()

    cfg = load_config()

    if args.electricity:
        cfg.electricity_cost = args.electricity
    if args.gpus:
        cfg.gpu_count = args.gpus

    coins = list(RTX3080_BENCHMARKS.keys())
    prices = fetch_prices(coins)

    if args.all:
        if prices:
            print("Live prices loaded.\n")
        print_all_coins(cfg, prices)
        return

    if args.coin:
        # Find best match
        matches = [c for c in coins if args.coin.lower() in c.lower()]
        if matches:
            cfg.coin = matches[0]
        else:
            print(f"Coin '{args.coin}' not found. Available: {', '.join(coins)}")
            sys.exit(1)

    if args.price:
        cfg.coin_price_usd = args.price
    elif cfg.coin in prices:
        cfg.coin_price_usd = float(prices[cfg.coin])
        print(f"Using live price for {cfg.coin}: ${cfg.coin_price_usd:.4f}\n")
    elif cfg.coin in DEFAULT_PRICES:
        cfg.coin_price_usd = DEFAULT_PRICES[cfg.coin]
        print(f"Using cached price for {cfg.coin}: ${cfg.coin_price_usd:.4f}\n")

    bench = RTX3080_BENCHMARKS[cfg.coin]
    results = calc_daily_earnings(cfg, bench)
    print_summary(cfg, results, prices)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmdline_mode()
    else:
        interactive_mode()
