"""AlphaPool API monitoring dashboard."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Any

WALLET = "REDACTED_WALLET"
API_URL = f"https://pearl.alphapool.tech/api/miner/{WALLET}"
EARN_RATE = 3.226
PRL_PRICE = 0.80

SEP = "│"
BAR = "─"

TOP = "┌" + BAR * 12 + "┬" + BAR * 17 + "┬" + BAR * 10 + "┬" + BAR * 9 + "┬" + BAR * 7 + "┐"
MID = "├" + BAR * 12 + "┼" + BAR * 17 + "┼" + BAR * 10 + "┼" + BAR * 9 + "┼" + BAR * 7 + "┤"
BOT = "├" + BAR * 12 + "┴" + BAR * 17 + "┴" + BAR * 10 + "┴" + BAR * 9 + "┴" + BAR * 7 + "┤"
END = "└" + BAR * 59 + "┘"

WORKER_MAP: dict[str, tuple[str, str]] = {
    "miner1": ("station", "RTX 3080"),
    "miner2": ("lab1", "4060Ti"),
    "miner3": ("laptop", "RTX 3060"),
}

GPU_POWER: dict[str, str] = {
    "RTX 3080": "320W",
    "4060Ti": "160W",
    "RTX 3060": "95W",
    "RTX 5090": "575W",
    "RTX 4090": "450W",
    "RTX 5080": "360W",
}


def _fetch_api() -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _parse_worker(w: dict[str, Any]) -> tuple[str, str, float, float] | None:
    if not w.get("online"):
        return None
    live = float(w["hashrate_live"].split()[0])
    h1 = float(w["hashrate_1h"].split()[0])
    name = w["name"]

    machine, gpu_label = _classify_worker(name)
    return machine, gpu_label, live, h1


def _classify_worker(name: str) -> tuple[str, str]:
    if name == "miner1":
        return "station", "RTX 3080"
    if "miner2" in name:
        return "lab1", "4060Ti"
    if name == "miner3":
        return "laptop", "RTX 3060"
    if "5090x4" in name:
        gpu_num = ""
        m = re.search(r"gpu(\d+)", name)
        if m:
            gpu_num = f" #{m.group(1)}"
        tag = re.search(r"5090x4[^.]*", name)
        machine = tag.group(0) if tag else name[:14]
        return machine, f"5090{gpu_num}"
    return name[:12], name[:16]


def get_dashboard() -> str:
    """Generate a single dashboard frame."""
    data = _fetch_api()
    if not data:
        return "API unreachable"

    now = time.strftime("%H:%M:%S")
    balance = data.get("balance_prl", 0)
    paid = data.get("total_paid_prl", 0)
    est_1h = data.get("estHash1h", 0)

    lines: list[str] = []
    lines.append(f"{TOP}")
    lines.append(f"{SEP}  PEARL Mining Dashboard{' ' * 20}{now:>20} {SEP}")
    lines.append(f"{MID}")
    lines.append(f"{SEP} {'Machine':<10} {SEP} {'GPU':<15} {SEP} {'Live TH/s':>8} {SEP} {'1h TH/s':>7} {SEP} {'W':>5} {SEP}")
    lines.append(f"{MID}")

    total_live = 0.0

    for w in data.get("workers", []):
        parsed = _parse_worker(w)
        if not parsed:
            continue
        machine, gpu_label, live, h1 = parsed
        power = GPU_POWER.get(gpu_label.rstrip(" #0123456789"), "?")

        lines.append(
            f"{SEP} {machine:<10} {SEP} {gpu_label:<15} {SEP} {live:>8.1f} {SEP} {h1:>7.1f} {SEP} {power:>5} {SEP}"
        )
        total_live += live

    lines.append(f"{BOT}")
    lines.append(
        f"{SEP} {'TOTAL':<10} {SEP} {'—':<15} {SEP} {total_live:>8.1f} {SEP} {est_1h:>7} {SEP} {'—':>5} {SEP}"
    )
    lines.append(f"{BOT}")
    lines.append(
        f"{SEP}  Balance: {balance:.2f} PRL  |  Total Paid: {paid:.2f} PRL{' ' * 9} {SEP}"
    )
    lines.append(f"{END}")

    return "\n".join(lines)


def get_worker_data() -> list[dict[str, Any]]:
    """Get raw worker data for programmatic use."""
    data = _fetch_api()
    if not data:
        return []
    return [
        {
            "name": w["name"],
            "online": w.get("online", False),
            "live_th": float(w["hashrate_live"].split()[0]),
            "h1_th": float(w["hashrate_1h"].split()[0]),
            "difficulty": w.get("difficulty", 0),
        }
        for w in data.get("workers", [])
    ]


def get_balance() -> dict[str, float]:
    data = _fetch_api()
    if not data:
        return {}
    est_str = str(data.get("estHash1h", "0"))
    try:
        est_val = float(est_str.split()[0])
    except (ValueError, IndexError):
        est_val = 0.0
    return {
        "balance": float(data.get("balance_prl", 0)),
        "paid": float(data.get("total_paid_prl", 0)),
        "est_1h": est_val,
    }


def earnings(th_s: float) -> float:
    return th_s / 1000 * EARN_RATE * PRL_PRICE
