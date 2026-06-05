#!/usr/bin/env python3
"""Generate miner batch scripts and configuration files for GPU mining.

Supports lolMiner, rigel, gminer, and t-rex.
Creates ready-to-run shell scripts for each supported coin/algorithm.
"""

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MINING_DIR = Path(__file__).parent

# Pool configuration for each algorithm
POOLS = {
    "etchash": {
        "pool": "stratum+tcp://etc.2miners.com:1010",
        "backup": "stratum+tcp://etc.viabtc.com:3001",
    },
    "ethash": {
        "pool": "stratum+tcp://ethw.2miners.com:2020",
        "backup": "stratum+tcp://ethw.viabtc.com:3002",
    },
    "autolykos2": {
        "pool": "stratum+tcp://erg.2miners.com:8888",
        "backup": "stratum+tcp://erg.f2pool.com:5800",
    },
    "kawpow": {
        "pool": "stratum+tcp://rvn.2miners.com:6060",
        "backup": "stratum+tcp://rvn.viabtc.com:3003",
    },
    "nexapow": {
        "pool": "stratum+tcp://nexa.2miners.com:7070",
        "backup": "stratum+tcp://nexa.vipor.net:5095",
    },
    "octopus": {
        "pool": "stratum+tcp://cfx.2miners.com:8080",
        "backup": "stratum+tcp://cfx.f2pool.com:6800",
    },
    "kheavyhash": {
        "pool": "stratum+tcp://kas.2miners.com:9090",
        "backup": "stratum+tcp://kas.f2pool.com:1500",
    },
    "blake3": {
        "pool": "stratum+tcp://alph.2miners.com:1100",
        "backup": "stratum+tcp://alph.vipor.net:5045",
    },
    "equihash": {
        "pool": "stratum+tcp://zec.2miners.com:1010",
        "backup": "stratum+tcp://zec.f2pool.com:5100",
    },
    "rx/0": {
        "pool": "xmr.2miners.com:2222",
        "backup": "pool.minexmr.com:4444",
    },
}

# Miner paths
MINER_PATHS = {
    "lolminer": MINING_DIR / "1.94" / "lolMiner",
    "rigel": MINING_DIR / "rigel-1.22.3-linux" / "rigel",
}

os.chdir(MINING_DIR)


@dataclass
class MinerConfig:
    name: str
    miner: str  # "lolminer", "rigel", "gminer", "trex"
    algo: str
    pool: str
    wallet: str
    worker: str = "worker1"
    password: str = "x"
    backup_pool: Optional[str] = None
    extra_args: str = ""
    gpu_devices: str = "0"


RGBENCH = {
    "ETC (Etchash)":      {"algo": "etchash",    "pool_key": "etchash"},
    "ETHW (Ethash)":      {"algo": "ethash",     "pool_key": "ethash"},
    "ERG (Autolykos2)":   {"algo": "autolykos2", "pool_key": "autolykos2"},
    "RVN (KawPow)":       {"algo": "kawpow",     "pool_key": "kawpow"},
    "NEXA (NexaPow)":     {"algo": "nexapow",    "pool_key": "nexapow"},
    "CFX (Octopus)":      {"algo": "octopus",    "pool_key": "octopus"},
    "KAS (kHeavyHash)":   {"algo": "kheavyhash", "pool_key": "kheavyhash"},
    "ALPH (Blake3)":      {"algo": "blake3",     "pool_key": "blake3"},
    "ZEC (Equihash)":     {"algo": "equihash",   "pool_key": "equihash"},
    "ZEN (Equihash)":     {"algo": "equihash",   "pool_key": "equihash"},
    "CLORE (KawPow)":     {"algo": "kawpow",     "pool_key": "kawpow"},
    "XMR (RandomX-monero)":{"algo": "rx/0",      "pool_key": "rx/0"},
}


def generate_lolminer_script(cfg: MinerConfig) -> str:
    """Generate lolMiner command with stratum connection."""
    pool = POOLS[cfg.algo]["pool"] if cfg.algo in POOLS else cfg.pool
    backup = cfg.backup_pool or (POOLS[cfg.algo]["backup"] if cfg.algo in POOLS else "")

    args = [
        f'./1.94/lolMiner',
        f'--algo {cfg.algo}',
        f'--pool {pool}',
        f'--user {cfg.wallet}.{cfg.worker}',
        f'--pass {cfg.password}',
    ]
    if backup:
        args.append(f'--pool {backup}')
        args.append(f'--user {cfg.wallet}.{cfg.worker}')
        args.append(f'--pass {cfg.password}')
    if cfg.extra_args:
        args.append(cfg.extra_args)

    return "#!/bin/bash\n\n" + " \\\n  ".join(args) + "\n"


def generate_rigel_script(cfg: MinerConfig) -> str:
    """Generate rigel miner command."""
    pool = POOLS[cfg.algo]["pool"] if cfg.algo in POOLS else cfg.pool

    args = [
        f'./rigel-1.22.3-linux/rigel',
        f'-a {cfg.algo}',
        f'-o {pool}',
        f'-u {cfg.wallet}',
        f'-w {cfg.worker}',
        f'-p {cfg.password}',
        f'--cclock 200,200',
        f'--lock-cclock 1500',
    ]
    if cfg.extra_args:
        args.append(cfg.extra_args)

    return "#!/bin/bash\n\n" + " \\\n  ".join(args) + "\n"


def interactive_setup():
    print()
    print("=" * 60)
    print("  GPU MINER CONFIGURATION GENERATOR")
    print("=" * 60)

    # Choose coin
    coins = list(RGBENCH.keys())
    print("\nAvailable algorithms:")
    for i, name in enumerate(coins, 1):
        print(f"  {i:2d}. {name}")

    try:
        choice = input(f"\nSelect coin [1-{len(coins)}]: ").strip()
        idx = int(choice) - 1
        coin = coins[idx]
    except (ValueError, IndexError, EOFError, KeyboardInterrupt):
        print("Invalid choice.")
        return

    info = RGBENCH[coin]

    # Wallet address
    wallet = input(f"\nYour {coin.split()[0]} wallet address: ").strip()
    if not wallet:
        print("Wallet address required!")
        return

    # Worker name
    worker = input("Worker name [worker1]: ").strip() or "worker1"

    # Miner choice
    print("\nMiner programs (install first):")
    print("  1. lolMiner (recommended)")
    print("  2. rigel")
    try:
        m = input("Choose miner [1]: ").strip() or "1"
        miner = "lolminer" if m == "1" else "rigel"
    except (EOFError, KeyboardInterrupt):
        return

    # Custom pool
    pool_key = info["pool_key"]
    pool_url = POOLS[pool_key]["pool"] if pool_key in POOLS else ""
    backup_url = POOLS[pool_key]["backup"] if pool_key in POOLS else ""

    print(f"\nDefault pool: {pool_url}")
    custom_pool = input("Custom pool URL [use default]: ").strip()

    if custom_pool:
        pool_url = custom_pool
        custom_backup = input("Backup pool URL [none]: ").strip()
        backup_url = custom_backup if custom_backup else ""

    # GPU selection
    gpus = input("GPU devices (comma-separated) [0]: ").strip() or "0"

    # Extra args
    extra = input("Extra miner arguments [none]: ").strip()

    cfg = MinerConfig(
        name=coin.replace(" ", "_"),
        miner=miner,
        algo=info["algo"],
        pool=pool_url,
        wallet=wallet,
        worker=worker,
        backup_pool=backup_url if backup_url else None,
        extra_args=extra,
        gpu_devices=gpus,
    )

    # Generate script
    if miner == "lolminer":
        script = generate_lolminer_script(cfg)
    else:
        script = generate_rigel_script(cfg)

    script_name = f"mine_{coin.split()[0].lower()}.sh"
    script_path = MINING_DIR / script_name
    script_path.write_text(script)
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    print(f"\n  Script created: {script_path}")
    print(f"  Run with:  cd mining && ./{script_name}")
    print()

    # Save wallet config
    wallet_config = {"wallet": wallet, "coin": coin, "worker": worker}
    with open(MINING_DIR / f"wallet_{coin.split()[0].lower()}.json", "w") as f:
        json.dump(wallet_config, f, indent=2)


def generate_all_scripts(wallet: str, miner: str = "lolminer"):
    """Generate scripts for all coins with a given wallet."""
    miner = miner.lower()
    count = 0
    for coin, info in RGBENCH.items():
        pool_key = info["pool_key"]
        pool_url = POOLS[pool_key]["pool"] if pool_key in POOLS else "stratum+tcp://pool.example.com:4444"
        backup_url = POOLS[pool_key]["backup"] if pool_key in POOLS else ""

        cfg = MinerConfig(
            name=coin.replace(" ", "_"),
            miner=miner,
            algo=info["algo"],
            pool=pool_url,
            wallet=wallet,
            worker="worker1",
            backup_pool=backup_url if backup_url else None,
        )

        if miner == "lolminer":
            script = generate_lolminer_script(cfg)
        else:
            script = generate_rigel_script(cfg)

        script_name = f"mine_{coin.split()[0].lower()}.sh"
        script_path = MINING_DIR / script_name
        script_path.write_text(script)
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
        count += 1

    print(f"Generated {count} mining scripts in {MINING_DIR}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        wallet = input("Wallet address: ").strip()
        if wallet:
            generate_all_scripts(wallet)
    else:
        interactive_setup()
