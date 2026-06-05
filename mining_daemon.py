#!/usr/bin/env python3
"""GPU miner management: start, stop, monitor, and auto-restart.

Usage:
  mining_daemon.py start <coin>     Start mining a specific coin
  mining_daemon.py stop             Stop all mining
  mining_daemon.py status           Show mining status
  mining_daemon.py benchmark        Run GPU benchmark
  mining_daemon.py profit           Show profitability of current coin
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

MINING_DIR = Path(__file__).parent
PID_FILE = MINING_DIR / ".miner.pid"
LOG_FILE = MINING_DIR / "miner.log"
STATS_FILE = MINING_DIR / "miner_stats.json"
START_TIME_FILE = MINING_DIR / ".start_time"

COIN_SCRIPTS = {
    "etc": "mine_etc.sh",
    "ethw": "mine_ethw.sh",
    "erg": "mine_erg.sh",
    "rvn": "mine_rvn.sh",
    "nexa": "mine_nexa.sh",
    "cfx": "mine_cfx.sh",
    "kas": "mine_kas.sh",
    "alph": "mine_alph.sh",
    "zec": "mine_zec.sh",
    "zen": "mine_zen.sh",
    "clore": "mine_clore.sh",
    "xmr": "mine_xmr.sh",
}


def is_miner_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def get_miner_pid() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except ValueError:
        return None


def start_mining(coin: str):
    if is_miner_running():
        print("Miner is already running. Stop it first with: mining_daemon.py stop")
        return

    coin_lower = coin.lower()
    if coin_lower not in COIN_SCRIPTS:
        print(f"Unknown coin '{coin}'. Available: {', '.join(COIN_SCRIPTS)}")
        return

    script = MINING_DIR / COIN_SCRIPTS[coin_lower]
    if not script.exists():
        print(f"Script not found: {script}")
        print("Run: python3 generate_miner_scripts.py")
        return

    os.chdir(MINING_DIR)

    with open(LOG_FILE, "a") as log:
        log.write(f"\n=== Started at {datetime.now()} ===\n")
        proc = subprocess.Popen(
            [str(script)],
            stdout=log,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setpgrp,
        )

    PID_FILE.write_text(str(proc.pid))
    START_TIME_FILE.write_text(str(time.time()))

    print(f"Miner started (PID: {proc.pid})")
    print(f"Coin: {coin}")
    print(f"Log: {LOG_FILE}")
    print()
    print("Monitor with: tail -f mining/miner.log")


def stop_mining():
    pid = get_miner_pid()
    if pid is None:
        print("No miner running.")
        return

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        time.sleep(2)
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass
    except OSError:
        pass

    PID_FILE.unlink(missing_ok=True)
    START_TIME_FILE.unlink(missing_ok=True)

    print("Miner stopped.")


def show_status():
    if not is_miner_running():
        print("Miner: NOT RUNNING")
        return

    pid = get_miner_pid()
    uptime_seconds = 0
    if START_TIME_FILE.exists():
        uptime_seconds = time.time() - float(START_TIME_FILE.read_text().strip())

    uptime_str = str(timedelta(seconds=int(uptime_seconds)))

    print(f"Miner: RUNNING")
    print(f"PID:   {pid}")
    print(f"Uptime: {uptime_str}")

    # Tail log
    if LOG_FILE.exists():
        try:
            last_lines = subprocess.check_output(
                ["tail", "-20", str(LOG_FILE)],
                text=True,
                timeout=5,
            )
            print(f"\n--- Last 20 log lines ---")
            print(last_lines)
        except Exception:
            pass


def benchmark_gpu():
    """Run a quick GPU benchmark to measure actual hashrate."""
    print("GPU Benchmark for RTX 3080")
    print("-" * 40)

    # Check NVIDIA status
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,power.draw,utilization.gpu,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 5:
                print(f"  GPU:     {parts[0]}")
                print(f"  Power:   {parts[1]} W")
                print(f"  Usage:   {parts[2]}%")
                print(f"  VRAM:    {parts[3]} MB")
                print(f"  Temp:    {parts[4]}°C")
    except Exception as e:
        print(f"  nvidia-smi error: {e}")

    print()
    print("For full hashrate benchmark, run the miner:")
    print("  python3 mining_daemon.py start kas")
    print("  (KAS uses kHeavyHash - good for quick testing)")
    print()


def systemd_template():
    """Print systemd service template for auto-start mining."""
    template = f"""[Unit]
Description=GPU Mining Service
After=network.target

[Service]
Type=simple
User={os.getenv('USER', 'miner')}
WorkingDirectory={MINING_DIR}
ExecStart={sys.executable} {MINING_DIR}/mining_daemon.py start kas
ExecStop={sys.executable} {MINING_DIR}/mining_daemon.py stop
Restart=always
RestartSec=30
StandardOutput=append:{LOG_FILE}
StandardError=append:{LOG_FILE}

# GPU power limits (optional)
Environment=GPU_MAX_POWER=250

[Install]
WantedBy=multi-user.target
"""
    print(template)
    print()
    print("To install:")
    print(f"  sudo cp {MINING_DIR}/mining.service /etc/systemd/system/")
    print("  sudo systemctl daemon-reload")
    print("  sudo systemctl enable mining")
    print("  sudo systemctl start mining")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "start":
        coin = sys.argv[2] if len(sys.argv) > 2 else "kas"
        start_mining(coin)
    elif cmd == "stop":
        stop_mining()
    elif cmd == "status":
        show_status()
    elif cmd == "benchmark":
        benchmark_gpu()
    elif cmd == "profit":
        from mining_calculator import interactive_mode
        interactive_mode()
    elif cmd == "service":
        systemd_template()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
