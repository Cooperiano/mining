"""Dynamic bid adjuster for interruptible vast.ai instances (V1).

V1 scope: profit-aware bid adjustment ONLY.
  - Raises bids on profitable instances to improve survival.
  - Lowers bids on stable SAFE instances to reduce cost.
  - Never destroys, creates, or deploys replacements.
  - Never bids above max_bid = earnings/hr - min_margin/hr.

Verified vast.ai instance fields (2026-06-06):
  - is_bid: bool — True if instance is interruptible/spot
  - min_bid: float — current bid price ($/hr)
  - dph_total: float — current total cost ($/hr), may differ from bid
  - dlperf_per_dphtotal: float — DLPerf/$ metric
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────
# Margin calculation
# ──────────────────────────────────────────────

def calc_margin_per_hr(inst: dict[str, Any], workers: list[dict[str, Any]],
                       cfg: dict[str, Any]) -> float:
    """Calculate margin per hour using pool h1_th hashrate.

    Returns 0.0 if no online workers found (skip bid check).
    """
    earn_rate = float(cfg.get("earn_rate", 3.226))
    prl_price = float(cfg.get("prl_price", 0.80))

    # Sum h1_th from online workers
    total_h1 = 0.0
    has_online = False
    for w in workers:
        if not w.get("online"):
            continue
        has_online = True
        try:
            h1_str = w.get("hashrate_1h") or "0"
            h1 = float(str(h1_str).split()[0])
        except (ValueError, KeyError, AttributeError):
            h1 = 0.0
        total_h1 += h1

    if not has_online:
        return 0.0

    earnings = (total_h1 / 1000) * earn_rate * prl_price
    try:
        dph_total = float(inst.get("dph_total", 0))
    except (TypeError, ValueError):
        dph_total = 0.0

    return earnings - dph_total


def calc_max_bid(inst: dict[str, Any], workers: list[dict[str, Any]],
                 cfg: dict[str, Any]) -> float:
    """Calculate maximum bid: earnings/hr - min_margin/hr.

    This is the ONLY hard ceiling for bids.
    NOT _calc_max_price_per_gpu() — that is break-even * 1.2 and can exceed profit line.
    """
    earn_rate = float(cfg.get("earn_rate", 3.226))
    prl_price = float(cfg.get("prl_price", 0.80))
    min_margin_hr = float(cfg.get("bid_min_margin_hr", 0.08))

    total_h1 = 0.0
    for w in workers:
        if not w.get("online"):
            continue
        try:
            h1_str = w.get("hashrate_1h") or "0"
            h1 = float(str(h1_str).split()[0])
        except (ValueError, KeyError, AttributeError):
            h1 = 0.0
        total_h1 += h1

    earnings = (total_h1 / 1000) * earn_rate * prl_price
    return max(0.0, earnings - min_margin_hr)


# ──────────────────────────────────────────────
# Tier classification
# ──────────────────────────────────────────────

TIER_SAFE = "SAFE"
TIER_WATCH = "WATCH"
TIER_NO_CHASE = "NO_CHASE"
TIER_NO_ACTION_REPLACE_RECOMMENDED = "NO_ACTION_REPLACE_RECOMMENDED"


def classify_margin(margin: float, cfg: dict[str, Any]) -> str:
    """Classify margin into a tier for bid decision."""
    safe_hr = float(cfg.get("bid_safe_margin_hr", 0.10))
    watch_hr = float(cfg.get("bid_watch_margin_hr", 0.03))

    if margin > safe_hr:
        return TIER_SAFE
    if margin > watch_hr:
        return TIER_WATCH
    if margin > 0:
        return TIER_NO_CHASE
    return TIER_NO_ACTION_REPLACE_RECOMMENDED


# ──────────────────────────────────────────────
# Bid adjustment with hysteresis
# ──────────────────────────────────────────────

def calc_bid_adjustment(current_bid: float, max_bid: float,
                        tier: str, history_entry: dict[str, Any] | None,
                        cfg: dict[str, Any], *,
                        dlperf_per_dollar: float | None = None) -> float | None:
    """Calculate new bid price, or None if no change needed.

    Hysteresis rules:
      - Minimum adjustment: < bid_min_adjustment_usd -> skip
      - Cooldown: bid_cooldown_sec since last adjustment
      - Consecutive same-tier count required before adjusting
      - DLPerf/$ gate: < min_dlperf_per_dollar -> no raises
      - Lower bids require more consecutive checks than raises
    """
    now = time.time()
    cooldown = float(cfg.get("bid_cooldown_sec", 300))
    min_adj = float(cfg.get("bid_min_adjustment_usd", 0.01))
    consecutive_raise = int(cfg.get("bid_consecutive_before_adjust", 2))
    consecutive_lower = int(cfg.get("bid_consecutive_before_lower", 3))
    min_dlperf = float(cfg.get("min_dlperf_per_dollar", 350))
    raise_max_pct = float(cfg.get("bid_raise_max_pct", 10))
    lower_pct = float(cfg.get("bid_lower_pct", 3))

    # ── Hysteresis: cooldown ──
    if history_entry:
        last_adj = history_entry.get("last_adjustment", 0)
        if last_adj and (now - last_adj) < cooldown:
            return None

    # ── Hysteresis: consecutive tier count ──
    if history_entry:
        ct = history_entry.get("consecutive_tier", {})
        cons_tier = ct.get("tier", "")
        cons_count = ct.get("count", 0)
    else:
        cons_tier = ""
        cons_count = 0

    if cons_tier != tier:
        return None  # tier changed, reset count

    # ── DLPerf/$ gate ──
    low_quality = dlperf_per_dollar is not None and dlperf_per_dollar < min_dlperf

    # ── Tier rules ──
    if tier == TIER_NO_ACTION_REPLACE_RECOMMENDED:
        # V1: log only, no action
        return None

    if tier == TIER_NO_CHASE:
        return None

    if tier == TIER_WATCH:
        # Raise bid, but cautiously
        if cons_count < consecutive_raise:
            return None
        if low_quality:
            return None  # DLPerf/$ gate: don't raise on low quality
        new_bid = min(current_bid * (1 + raise_max_pct / 200), max_bid * 0.9)
        if abs(new_bid - current_bid) < min_adj:
            return None
        return round(max(new_bid, 0.0001), 4)

    if tier == TIER_SAFE:
        # Two sub-cases: raise if preempted recently, lower if stable
        # Check for recent preemption (within 2h)
        preemption_recent = False
        if history_entry:
            hist = history_entry.get("history", [])
            for h in reversed(hist[-10:]):
                if h.get("action") == "raise" and h.get("reason") == "preempted_recently":
                    if now - h.get("ts", 0) < 7200:  # 2 hours
                        preemption_recent = True
                        break

        if preemption_recent:
            # Raise to defend against preemption
            if cons_count < consecutive_raise:
                return None
            if low_quality:
                return None
            new_bid = min(current_bid * (1 + raise_max_pct / 100), max_bid)
            if abs(new_bid - current_bid) < min_adj:
                return None
            return round(max(new_bid, 0.0001), 4)
        else:
            # Lower bid to save cost (stable SAFE)
            if cons_count < consecutive_lower:
                return None  # Lower requires more consecutive checks
            new_bid = current_bid * (1 - lower_pct / 100)
            if abs(new_bid - current_bid) < min_adj:
                return None
            # Don't lower below a reasonable floor (50% of max_bid)
            floor = max_bid * 0.5 if max_bid > 0 else 0
            if new_bid < floor:
                return None
            return round(max(new_bid, 0.0001), 4)

    return None


# ──────────────────────────────────────────────
# Bid history persistence
# ──────────────────────────────────────────────

def load_bid_history(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load bid history from state/bid_history.json."""
    path = Path(state_dir) / "bid_history.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_bid_history(state_dir: str | Path, data: dict[str, dict[str, Any]]) -> None:
    """Save bid history to state/bid_history.json."""
    path = Path(state_dir) / "bid_history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def record_bid_action(state_dir: str | Path, instance_id: str,
                      entry: dict[str, Any]) -> None:
    """Append a bid action to history and update current state.

    entry should contain: ts, bid_before, bid_after, action, tier,
                          margin_per_hr, reason
    """
    data = load_bid_history(state_dir)
    rec = data.get(instance_id, {
        "instance_id": instance_id,
        "gpu_model": "",
        "current_bid": 0.0,
        "last_adjustment": 0.0,
        "last_seen_running": 0.0,
        "consecutive_tier": {"tier": "", "count": 0},
        "explicitly_killed": False,
        "intended_action": None,
        "preemption_count": 0,
        "history": [],
    })

    # Update current state
    rec["current_bid"] = entry.get("bid_after", rec.get("current_bid", 0))
    rec["last_adjustment"] = entry.get("ts", time.time())

    # Append to history (keep last 200 entries per instance)
    hist = rec.get("history", [])
    hist.append(entry)
    rec["history"] = hist[-200:]

    data[instance_id] = rec
    save_bid_history(state_dir, data)


def update_consecutive_tier(state_dir: str | Path, instance_id: str,
                            tier: str) -> dict[str, Any]:
    """Update the consecutive tier counter for an instance.

    Returns the updated history entry for the instance.
    """
    data = load_bid_history(state_dir)
    rec = data.get(instance_id, {
        "instance_id": instance_id,
        "gpu_model": "",
        "current_bid": 0.0,
        "last_adjustment": 0.0,
        "last_seen_running": 0.0,
        "consecutive_tier": {"tier": "", "count": 0},
        "explicitly_killed": False,
        "intended_action": None,
        "preemption_count": 0,
        "history": [],
    })

    ct = rec.get("consecutive_tier", {"tier": "", "count": 0})
    if ct.get("tier") == tier:
        ct["count"] = ct.get("count", 0) + 1
    else:
        ct = {"tier": tier, "count": 1}
    rec["consecutive_tier"] = ct
    rec["last_seen_running"] = time.time()

    data[instance_id] = rec
    save_bid_history(state_dir, data)
    return rec


def mark_explicitly_killed(state_dir: str | Path, instance_id: str) -> None:
    """Mark an instance as explicitly killed (not preempted)."""
    data = load_bid_history(state_dir)
    if instance_id in data:
        data[instance_id]["explicitly_killed"] = True
        save_bid_history(state_dir, data)


def increment_preemption(state_dir: str | Path, instance_id: str) -> None:
    """Increment preemption count for an instance (record only in V1)."""
    data = load_bid_history(state_dir)
    if instance_id in data:
        data[instance_id]["preemption_count"] = data[instance_id].get("preemption_count", 0) + 1
        save_bid_history(state_dir, data)


def get_or_create_entry(state_dir: str | Path, instance_id: str,
                        gpu_model: str = "", current_bid: float = 0.0) -> dict[str, Any]:
    """Get existing bid history entry or create a new one."""
    data = load_bid_history(state_dir)
    if instance_id not in data:
        data[instance_id] = {
            "instance_id": instance_id,
            "gpu_model": gpu_model,
            "current_bid": current_bid,
            "last_adjustment": 0.0,
            "last_seen_running": time.time(),
            "consecutive_tier": {"tier": "", "count": 0},
            "explicitly_killed": False,
            "intended_action": None,
            "preemption_count": 0,
            "history": [],
        }
        save_bid_history(state_dir, data)
    return data[instance_id]
