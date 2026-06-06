"""Manage vast.ai instances — full lifecycle."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

MINING_DIR = Path(__file__).resolve().parent.parent
BLACKLIST_FILE = MINING_DIR / ".vast_blacklist"

WALLET = "REDACTED_WALLET"
API_URL = f"https://pearl.alphapool.tech/api/miner/{WALLET}"


def _state_dir() -> Path:
    """Return the state directory, checking env var first, then fallback."""
    env = os.environ.get("PEARL_STATE_DIR")
    if env:
        return Path(env)
    return MINING_DIR / "electron-app" / "state"


def _electron_config_path() -> Path:
    return _state_dir() / "config.json"


def _deployed_file() -> Path:
    return _state_dir() / "deployed.json"


def _bad_file() -> Path:
    return _state_dir() / "bad.json"


def _sessions_file() -> Path:
    return _state_dir() / "sessions.json"


# Legacy text-based state files (kept for read-only migration, never written to)
_LEGACY_DEPLOYED_FILE = MINING_DIR / ".vast_deployed"
_LEGACY_BAD_FILE = MINING_DIR / ".vast_bad"
_LEGACY_BLACKLIST_FILE = MINING_DIR / ".vast_blacklist"

# Reference hashrates per GPU model (TH/s) — Pearl mining on vast.ai
GPU_HASHRATES = {
    # Blackwell (RTX 50 series)
    "rtx_5090": 365,
    "rtx_5080": 185,
    "rtx_5070_ti": 150,
    "rtx_5070": 100,
    # Ada Lovelace (RTX 40 series)
    "rtx_4090": 255,
    "rtx_4080_super": 165,
    "rtx_4080": 155,
    "rtx_4070_ti_super": 120,
    "rtx_4070_ti": 110,
    "rtx_4070_super": 105,
    "rtx_4070": 100,
    "rtx_4060_ti": 68,
    "rtx_4060": 45,
    # Ampere (RTX 30 series)
    "rtx_3090_ti": 120,
    "rtx_3090": 110,
    "rtx_3080_ti": 100,
    "rtx_3080": 90,
    "rtx_3070_ti": 80,
    "rtx_3070": 70,
    "rtx_3060_ti": 65,
    "rtx_3060": 25,
    # Hopper / Blackwell datacenter
    "h100": 620,
    "h200": 650,
    "b200": 700,
    # Ampere datacenter
    "a100": 500,
    "a6000": 200,
    "a5000": 150,
    "a4000": 100,
    # Ada datacenter
    "l40s": 180,
    "l40": 140,
}

# Regex to extract GPU model prefix from worker names like "5090x4-9629.gpu0"
_GPU_MODEL_RE = re.compile(
    r"(\d{3,4}\s*(?:ti\s*super|ti|super)?)"  # e.g. 5090, 4090, 4060Ti, 4080Super, 4070TiSuper
    r"|((?:H100|H200|B200|A100|A6000|A5000|A4000|L40S?|L40))",  # e.g. H100, A100, L40S
    re.IGNORECASE,
)


def _parse_gpu_model(name: str) -> str | None:
    """Extract normalized GPU model key from a worker name.

    Worker names follow the format: {GPU_MODEL}x{COUNT}-{TAG}.gpu{INDEX}
    Examples:
        "5090x4-9629.gpu0"     -> "rtx_5090"
        "4090x2-a.gpu0"        -> "rtx_4090"
        "4060Tix4-b.gpu0"      -> "rtx_4060_ti"
        "H100x8-c.gpu0"        -> "h100"
    """
    m = _GPU_MODEL_RE.search(name)
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or "").strip().lower()
    if not raw:
        return None

    # Strip spaces
    clean = raw.replace(" ", "")

    # Datacenter GPUs: direct key lookup (e.g. "h100" → "h100", "a6000" → "a6000")
    if clean in GPU_HASHRATES:
        return clean
    # Try lowercase match for datacenter keys
    clean_lower = clean.lower()
    for key in GPU_HASHRATES:
        if key == clean_lower:
            return key
        # Handle "l40s" → "l40s"
        if not key.startswith("rtx_") and clean_lower == key:
            return key

    # Consumer GPUs: extract model number and suffixes
    m = re.match(r"(\d{3,4})(tisuper|super|ti)?$", clean, re.IGNORECASE)
    if not m:
        return None
    model_num, suffix = m.group(1), (m.group(2) or "").lower()

    # Build candidate keys in priority order (most specific first)
    candidates = []
    if suffix:
        if suffix == "tisuper":
            suffix_key = "_ti_super"
        elif suffix == "super":
            suffix_key = "_super"
        elif suffix == "ti":
            suffix_key = "_ti"
        else:
            suffix_key = ""
        if suffix_key:
            candidates.append(f"rtx_{model_num}{suffix_key}")
    candidates.append(f"rtx_{model_num}")

    # Check candidates against known keys (try most specific first)
    for cand in candidates:
        if cand in GPU_HASHRATES:
            return cand

    # Fallback: prefix match on model number
    for key in GPU_HASHRATES:
        if model_num in key.replace("rtx_", "").replace("_", ""):
            return key

    return None


def _min_th_for_model(gpu_model: str) -> float:
    """Return minimum TH/s threshold for a GPU model.

    Reads from electron config (key: ``min_th_{model_num}``),
    falls back to 70% of the reference hashrate.
    """
    cfg = _load_electron_config()
    # Config key is e.g. "min_th_5090" — strip the "rtx_" prefix
    clean = gpu_model.lower().replace("rtx_", "").replace(" ", "_").strip("_")
    config_key = f"min_th_{clean}"
    if config_key in cfg:
        return float(cfg[config_key])

    # Fallback: 70% of reference hashrate
    ref_th = GPU_HASHRATES.get(gpu_model, 300)
    return round(ref_th * 0.7, 1)

def _load_electron_config() -> dict:
    """Load the electron app's config and session data for cost calculations."""
    default = {"prl_price": 0.21, "earn_rate": 3.226}
    config_path = _electron_config_path()
    if config_path.exists():
        try:
            c = json.loads(config_path.read_text())
            return {**default, **c}
        except Exception:
            pass
    return default


def _gpu_break_even(gpu_model: str = "rtx_5090") -> float:
    """Calculate break-even $/hr for a GPU given its expected hashrate and PRL price."""
    cfg = _load_electron_config()
    prl = cfg.get("prl_price", 0.21)
    rate = cfg.get("earn_rate", 3.226)
    model_key = gpu_model.lower().replace(" ", "_").replace("nvidia", "").strip("_")
    th = GPU_HASHRATES.get(model_key, 300)  # fallback 300 if unknown model
    return (th / 1000) * rate * prl


def _calc_max_price_per_gpu(gpu_model: str = "rtx_5090") -> float:
    """Max viable rental $/GPU for a given model, based on PRL price.
    Threshold = break-even × 1.2 (20% buffer above break-even).
    This catches overpriced rentals while keeping reasonable fleet running.
    """
    be = _gpu_break_even(gpu_model)
    return round(be * 1.2, 4)


def _calc_min_th(gpu_model: str = "rtx_5090") -> float:
    """Return min TH/s threshold for a GPU model (electron config or fallback)."""
    return _min_th_for_model(gpu_model)


MAX_PRICE_PER_5090 = _calc_max_price_per_gpu()
MIN_TH_PER_5090 = _calc_min_th("rtx_5090")


def _snapshot_instances(instances: list[dict[str, Any]]) -> None:
    """Record instance snapshots from vast.ai instance list."""
    if not instances:
        return
    for entry in instances:
        if not isinstance(entry, dict):
            continue
        inst_id = str(entry.get("id", ""))
        num_gpus = entry.get("num_gpus", 0)
        try:
            dph_total = float(entry.get("dph_total", 0))
        except (TypeError, ValueError):
            dph_total = 0.0
        price_per_gpu = dph_total / num_gpus if num_gpus > 0 else dph_total
        record_instance_snapshot(
            instance_id=inst_id,
            status=entry.get("actual_status", str(entry.get("cur_state", ""))),
            gpu_name=entry.get("gpu_name", ""),
            num_gpus=num_gpus,
            dph_total=dph_total,
            price_per_gpu=price_per_gpu,
            machine_id=str(entry.get("machine_id", "")),
            geolocation=entry.get("geolocation", ""),
        )


from manager.audit import log_event
from manager.deploy import generate_deploy_script
from manager.locks import AutodeployLock, InstanceLock
from manager.recorder import (
    record_cycle_summary,
    record_instance_snapshot,
    record_instance_snapshots,
    record_kill_decision,
    record_worker_snapshot,
    record_worker_snapshots,
)


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except OSError as e:
        return -1, "", str(e)


def _vastai(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    return _run(["vastai"] + args, timeout=timeout)


def _vastai_yes(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run vastai command with 'y' piped to stdin (for destroy, etc)."""
    try:
        r = subprocess.run(
            ["vastai"] + args, input="y\n", capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except OSError as e:
        return -1, "", str(e)


def change_bid(instance_id: str, price: float) -> tuple[int, str, str]:
    """Change bid price for a spot/interruptible instance.

    Returns (rc, stdout, stderr) from vastai CLI.
    """
    return _vastai(["change", "bid", str(instance_id), "--price", f"{price:.4f}"])


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def list_instances() -> str:
    """List all running vast.ai instances."""
    rc, stdout, stderr = _vastai(["show", "instances"], timeout=15)
    if rc != 0:
        return f"vastai error: {stderr or stdout}"

    clean = _strip_ansi(stdout)
    lines = clean.strip().split("\n")
    if len(lines) <= 1:
        return "No instances found."

    deployed_ids = _deployed_ids()
    bad_ids = _bad_ids()

    out = ["vast.ai instances:"]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        inst_id = parts[1]
        status = parts[3] if len(parts) > 3 else "?"
        tag = ""
        if inst_id in deployed_ids:
            tag = " [DEPLOYED]"
        elif inst_id in bad_ids:
            tag = " [BAD]"
        out.append(f"  {inst_id}  {status}  {line[50:90].strip()}{tag}")
    return "\n".join(out)


def search_offers(
    gpu_name: str = "RTX_5090",
    num_gpus: int = 1,
    max_price: float | None = None,
    verified: bool = True,
    limit: int = 20,
) -> str:
    """Search vast.ai for available GPU offers."""
    query_parts = [
        f"gpu_name={gpu_name}",
        f"num_gpus>={num_gpus}",
        "rentable=true",
        "direct_port_count>=1",
    ]
    if verified:
        query_parts.append("verified=true")

    query = " ".join(query_parts)
    if max_price is not None:
        query += f" max_price<={max_price}"

    args = ["search", "offers", query, "-o", "dlperf_usd-"]
    if limit:
        args += ["--limit", str(limit)]

    rc, stdout, stderr = _vastai(args, timeout=30)
    if rc != 0:
        return f"vastai error: {stderr or stdout}"

    clean = _strip_ansi(stdout)
    lines = clean.strip().split("\n")
    if len(lines) <= 1:
        return "No offers found."

    out = [f"Offers for {gpu_name}:"]
    for line in lines[1:limit + 1]:
        parts = line.split()
        if len(parts) < 5:
            continue
        out.append(f"  {line.strip()}")
    return "\n".join(out)


def create_instance(
    offer_id: str,
    image: str = "nvidia/cuda:12.4.0-devel-ubuntu22.04",
    disk: int = 20,
    onstart_cmd: str = "nvidia-smi",
    direct: bool = True,
) -> str:
    """Create (rent) a vast.ai instance from an offer."""
    args = [
        "create", "instance", str(offer_id),
        "--image", image,
        "--disk", str(disk),
        "--onstart-cmd", onstart_cmd,
    ]
    if direct:
        args.append("--direct")

    rc, stdout, stderr = _vastai(args, timeout=60)
    if rc != 0:
        return f"vastai error: {stderr or stdout}"

    try:
        result = json.loads(stdout)
        contract_id = result.get("new_contract")
        if contract_id:
            return f"Instance created: {contract_id}"
    except json.JSONDecodeError:
        pass
    return stdout.strip()


# ── State persistence (JSON format, unified under PEARL_STATE_DIR) ──


def _read_state_json(filepath: Path) -> set[str]:
    """Read a JSON array of strings into a set."""
    if not filepath.exists():
        return set()
    try:
        data = json.loads(filepath.read_text())
        return set(str(x) for x in data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, ValueError):
        return set()


def _write_state_json(filepath: Path, ids: set[str]) -> None:
    """Write a set of strings as a sorted JSON array."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(sorted(ids), indent=2))


def _read_state(filepath: Path) -> set[str]:
    """Legacy text-file reader — kept for migration and backward compat."""
    if not filepath.exists():
        return set()
    text = filepath.read_text().strip()
    if not text:
        return set()
    return set(text.split("\n"))


def _migrate_legacy_state() -> None:
    """One-time migration of .vast_deployed/.vast_bad text files to deployed.json/bad.json.
    Never deletes the legacy files — only copies data into the new JSON format.
    """
    deployed_path = _deployed_file()
    bad_path = _bad_file()

    # Only migrate if new files don't exist yet (or are empty)
    if deployed_path.exists() and deployed_path.stat().st_size > 0:
        return

    legacy_deployed = _read_state(_LEGACY_DEPLOYED_FILE)
    legacy_bad = _read_state(_LEGACY_BAD_FILE)

    if legacy_deployed:
        _write_state_json(deployed_path, legacy_deployed)
    if legacy_bad:
        _write_state_json(bad_path, legacy_bad)
    # Create empty files so future calls skip migration
    if not deployed_path.exists():
        _write_state_json(deployed_path, set())
    if not bad_path.exists():
        _write_state_json(bad_path, set())


def _deployed_ids() -> set[str]:
    """Return the set of deployed instance IDs (from unified state)."""
    _migrate_legacy_state()
    return _read_state_json(_deployed_file())


def _bad_ids() -> set[str]:
    """Return the set of bad instance IDs (from unified state)."""
    _migrate_legacy_state()
    return _read_state_json(_bad_file())


def _add_to_state(filepath: Path, inst_id: str) -> None:
    """Add an instance ID to a JSON state file."""
    ids = _read_state_json(filepath)
    ids.add(inst_id)
    _write_state_json(filepath, ids)


def _remove_from_state(filepath: Path, inst_id: str) -> None:
    """Remove an instance ID from a JSON state file."""
    ids = _read_state_json(filepath)
    ids.discard(inst_id)
    _write_state_json(filepath, ids)


def _mark_deployed(inst_id: str) -> None:
    """Mark an instance as deployed in unified state."""
    _add_to_state(_deployed_file(), inst_id)


def _mark_bad(inst_id: str) -> None:
    """Mark an instance as bad in unified state."""
    _add_to_state(_bad_file(), inst_id)


def _unmark_deployed(inst_id: str) -> None:
    """Remove an instance from deployed state."""
    _remove_from_state(_deployed_file(), inst_id)


# ── Safety: rate limiter, protection period, dry-run ──


def _destroy_tracker_path() -> Path:
    return _state_dir() / "destroy_tracker.json"


def _deploy_times_path() -> Path:
    return _state_dir() / "deploy_times.json"


def _can_destroy(cfg: dict) -> bool:
    """Check if we're under the hourly destroy limit."""
    max_per_hour = int(cfg.get("max_destroys_per_hour", 2))
    if max_per_hour <= 0:
        return False

    tracker_path = _destroy_tracker_path()
    if not tracker_path.exists():
        return True

    try:
        timestamps = json.loads(tracker_path.read_text())
        if not isinstance(timestamps, list):
            return True
    except (json.JSONDecodeError, ValueError):
        return True

    now = time.time()
    one_hour_ago = now - 3600
    recent = [t for t in timestamps if t > one_hour_ago]
    return len(recent) < max_per_hour


def _record_destroy() -> None:
    """Record a destroy timestamp for rate limiting."""
    tracker_path = _destroy_tracker_path()
    tracker_path.parent.mkdir(parents=True, exist_ok=True)

    timestamps: list[float] = []
    if tracker_path.exists():
        try:
            timestamps = json.loads(tracker_path.read_text())
            if not isinstance(timestamps, list):
                timestamps = []
        except (json.JSONDecodeError, ValueError):
            timestamps = []

    now = time.time()
    timestamps.append(now)
    # Keep only last hour
    one_hour_ago = now - 3600
    timestamps = [t for t in timestamps if t > one_hour_ago]
    tracker_path.write_text(json.dumps(timestamps))


def _is_protected(inst_id: str, cfg: dict) -> bool:
    """Check if an instance is still in its protection period."""
    protection_minutes = int(cfg.get("new_instance_protection_minutes", 15))
    if protection_minutes <= 0:
        return False

    deploy_times_path = _deploy_times_path()
    if not deploy_times_path.exists():
        return False

    try:
        deploy_times = json.loads(deploy_times_path.read_text())
        if not isinstance(deploy_times, dict):
            return False
    except (json.JSONDecodeError, ValueError):
        return False

    deploy_time = deploy_times.get(str(inst_id))
    if deploy_time is None:
        return False

    elapsed = time.time() - deploy_time
    return elapsed < protection_minutes * 60


def _record_deploy_time(inst_id: str) -> None:
    """Record the deploy time for an instance."""
    deploy_times_path = _deploy_times_path()
    deploy_times_path.parent.mkdir(parents=True, exist_ok=True)

    deploy_times: dict[str, float] = {}
    if deploy_times_path.exists():
        try:
            deploy_times = json.loads(deploy_times_path.read_text())
            if not isinstance(deploy_times, dict):
                deploy_times = {}
        except (json.JSONDecodeError, ValueError):
            deploy_times = {}

    deploy_times[str(inst_id)] = time.time()
    deploy_times_path.write_text(json.dumps(deploy_times))


def _check_costs_dry(
    max_price_per_gpu: float | None = None,
    instances: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Dry-run variant of _check_costs — logs what would be killed, doesn't kill.

    Args:
        max_price_per_gpu: Optional override for price threshold.
        instances: Optional pre-fetched instance list.  If None, fetches fresh.
    """
    log: list[str] = []
    log.append("[DRY RUN] Cost check (no destroys will be made)")
    if instances is not None:
        data = instances
    else:
        rc, stdout, _ = _vastai(["show", "instances", "--raw"], timeout=15)
        if rc != 0:
            log.append("cost check failed: vastai error")
            return log
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            log.append(f"cost check failed: JSON parse error: {e}")
            return log

    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("actual_status") != "running":
            continue
        inst_id = str(entry["id"])
        num_gpus = entry.get("num_gpus", 1)
        gpu_name = entry.get("gpu_name", "RTX 5090")
        try:
            price_total = float(entry.get("dph_total", 0))
        except (TypeError, ValueError):
            continue
        price_per_gpu = price_total / num_gpus if num_gpus > 0 else price_total

        threshold = max_price_per_gpu if max_price_per_gpu else _calc_max_price_per_gpu(gpu_name)

        if price_per_gpu > threshold:
            log.append(
                f"DRY: Would destroy {inst_id} ${price_per_gpu:.2f}/GPU "
                f"({gpu_name}) > max ${threshold:.2f}"
            )
        elif price_per_gpu > threshold * 0.8:
            log.append(
                f"WARN: {inst_id} ${price_per_gpu:.2f}/GPU ({gpu_name}) "
                f"near threshold ${threshold:.2f}"
            )
    return log


def _check_and_kill_dry() -> list[str]:
    """Dry-run variant of _check_and_kill — logs underperformers, doesn't kill."""
    log: list[str] = []
    log.append("[DRY RUN] Performance check (no kills will be made)")

    try:
        import urllib.request
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log.append(f"API error: {e}")
        return log

    flagged: dict[tuple[str, str], list[tuple[float, str, float]]] = {}
    unknown_gpu_count = 0

    for w in data.get("workers", []):
        if not w.get("online"):
            continue
        try:
            live = float(w["hashrate_live"].split()[0])
            h1 = float(w.get("hashrate_1h", "0").split()[0]) if w.get("hashrate_1h") else 0
        except (ValueError, KeyError):
            continue
        name = w["name"]

        gpu_model = _parse_gpu_model(name)
        if gpu_model is None:
            unknown_gpu_count += 1
            continue

        min_th = _min_th_for_model(gpu_model)

        if h1 >= min_th:
            continue
        if live >= min_th:
            continue

        m = re.match(r"\w+x\d+-([a-z0-9]+)\.gpu\d+", name, re.IGNORECASE)
        inst_tag = m.group(1) if m else None
        if not inst_tag:
            continue

        key = (inst_tag, gpu_model)
        if key not in flagged:
            flagged[key] = []
        flagged[key].append((live, name, h1))

    if unknown_gpu_count:
        log.append(f"INFO: {unknown_gpu_count} workers with unrecognized GPU model (skipped)")

    if not flagged:
        return log

    for (tag, gpu_model), gpus in flagged.items():
        avg_live = sum(g[0] for g in gpus) / len(gpus)
        avg_h1 = sum(g[2] for g in gpus) / len(gpus) if gpus else 0
        min_th = _min_th_for_model(gpu_model)
        log.append(
            f"DRY: Would destroy instance with tag {tag} — "
            f"{len(gpus)} {gpu_model} GPUs below {min_th} TH/s "
            f"(avg live {avg_live:.0f}, h1={avg_h1:.0f})"
        )

    return log


def _pick_best_pool(host: str, port: str) -> str:
    """SSH into instance and pick the pool with the fastest TCP connection."""
    pools = ["eu1", "eu2", "us1", "us2", "sg1"]
    results = {}
    for pool in pools:
        probe = (
            "python3 -c \"import socket,time; "
            f"t=time.time(); s=socket.create_connection(('{pool}.alphapool.tech',5566),3); "
            "print(round((time.time()-t)*1000,1)); s.close()\" 2>/dev/null || echo 999"
        )
        cmd = [
            "ssh", "-q", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
            f"root@{host}", "-p", port,
            probe,
        ]
        _, out, _ = _run(cmd, timeout=12)
        ms = out.strip()
        try:
            results[pool] = float(ms)
        except ValueError:
            results[pool] = 999
    best = min(results, key=results.get)
    return f"{best}.alphapool.tech:5566"


def _get_instance_gpu_info(host: str, port: str) -> tuple[int, str]:
    """SSH in and get gpu count and type."""
    cmd = [
        "ssh", "-q", "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
        f"root@{host}", "-p", port,
        "nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1",
    ]
    _, out, _ = _run(cmd, timeout=12)
    raw_gpu = out.strip().lower()
    match = re.search(r"(rtx|h|a|b)\s*(pro\s*)?(\d{3,4})(\s*ti)?", raw_gpu)
    if match:
        prefix = match.group(1)
        number = match.group(3)
        suffix = "ti" if match.group(4) else ""
        gpu_type = f"{prefix}_{number}{suffix}" if prefix == "rtx" else f"{prefix}{number}"
    else:
        gpu_type = re.sub(r"[^a-z0-9]+", "_", raw_gpu).strip("_") or "gpu"

    cmd2 = [
        "ssh", "-q", "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
        f"root@{host}", "-p", port,
        "nvidia-smi -L 2>/dev/null | wc -l",
    ]
    _, out2, _ = _run(cmd2, timeout=12)
    try:
        gpu_count = int(out2.strip())
    except ValueError:
        gpu_count = 1
    return gpu_count, gpu_type


def deploy_instance(inst_id: str, log: Callable[[str], None] | None = None) -> str:
    """Deploy Pearl miner to a vast.ai instance."""
    lock = InstanceLock(inst_id)
    if not lock.acquire():
        log_event("lock_timeout", instance_id=inst_id, trigger="manual",
                  details="deploy_instance lock acquire failed")
        return f"SKIP: {inst_id} — locked (another deploy or kill in progress)"

    try:
        return _deploy_instance_inner(inst_id, log)
    finally:
        lock.release()


def _deploy_instance_inner(inst_id: str, log: Callable[[str], None] | None = None) -> str:
    """Inner deploy logic — lock already held."""
    emit = log or (lambda _message: None)
    log_event("deploy_start", instance_id=inst_id, trigger="manual")

    # Get SSH URL
    emit(f"[1/5] Resolving SSH endpoint for {inst_id}...")
    rc, stdout, stderr = _vastai(["ssh-url", str(inst_id)], timeout=15)
    if rc != 0:
        return f"Failed to get SSH URL: {stderr or stdout}"

    url = stdout.strip()
    m = re.search(r"@([^:]+):(\d+)", url)
    if not m:
        return f"Could not parse SSH URL: {url}"

    host, port = m.group(1), m.group(2)
    emit(f"      SSH: {host}:{port}")

    # Verify the actual mining endpoint, not only general HTTPS connectivity.
    emit("[2/5] Checking pool connectivity...")
    test_cmd = [
        "ssh", "-q", "-o", "ConnectTimeout=8", "-o", "LogLevel=QUIET",
        f"root@{host}", "-p", port,
        "for h in eu1 eu2 us1 us2 sg1; do "
        "timeout 4 bash -c \"</dev/tcp/$h.alphapool.tech/5566\" 2>/dev/null "
        "&& echo OK && exit 0; done; echo FAIL; exit 1",
    ]
    rc2, out2, _ = _run(test_cmd, timeout=15)
    if rc2 != 0 or "OK" not in out2:
        return f"FAIL: {inst_id} — pool port 5566 unreachable"
    emit("      Pool TCP OK")

    # Detect GPU count and type, pick best pool
    emit("[3/5] Detecting GPUs...")
    gpu_count, gpu_type = _get_instance_gpu_info(host, port)
    emit(f"      GPUs: {gpu_count} x {gpu_type}")
    emit("[4/5] Measuring pool latency...")
    best_pool = _pick_best_pool(host, port)
    emit(f"      Best pool: {best_pool}")

    # Build worker name
    worker = f"{gpu_type.replace('rtx_','')}x{gpu_count}-{inst_id[-4:]}"

    # Generate deploy script on the fly
    script = generate_deploy_script(worker=worker, gpu_type=gpu_type)
    # Override the ping-based pool picking: set BEST to our measured best,
    # and set BEST_MS=0 so the ping loop never overwrites it
    best_node = best_pool.rsplit(".", 2)[0]  # "us1.alphapool.tech:5566" -> "us1"
    script = script.replace('BEST="eu2"', f'BEST="{best_node}"')
    script = script.replace('BEST_MS=999', 'BEST_MS=0')

    b64 = base64.b64encode(script.encode()).decode()

    deploy_cmd = [
        "ssh", "-q", "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=QUIET",
        f"root@{host}", "-p", port,
        f"echo '{b64}' | base64 -d | bash",
    ]
    emit("[5/5] Cleaning old processes, downloading and starting miner...")
    rc3, out, err = _run(deploy_cmd, timeout=120)
    if out.strip():
        emit(out.strip())
    if err.strip():
        emit(err.strip())
    # Wait-and-retry verification — Blackwell GPUs need more init time.
    # Try up to 3 times with a 5s gap between each.
    miner_count, connected_count = 0, 0
    for _attempt in range(3):
        import time as _t
        _t.sleep(5)
        verify_cmd = [
            "ssh", "-q", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no",
            "-o", "LogLevel=QUIET", f"root@{host}", "-p", port,
            "p=$(pgrep -c alpha-miner 2>/dev/null || true); "
            "c=$(grep -c 'pool connected' /root/mining/miner.log 2>/dev/null || true); "
            "echo \"$p $c\"",
        ]
        _, verify_out, _ = _run(verify_cmd, timeout=12)
        try:
            miner_count, connected_count = [int(value) for value in verify_out.strip().split()[:2]]
        except (ValueError, IndexError):
            miner_count, connected_count = 0, 0
        if miner_count > 0 and connected_count > 0:
            break

    if rc3 == 0 and miner_count > 0 and connected_count > 0:
        _mark_deployed(inst_id)
        _record_deploy_time(inst_id)
        log_event("deploy_success", instance_id=inst_id, trigger="manual",
                  details=f"{worker} ({host}:{port}) via {best_pool}")
        return f"Deployed: {inst_id} -> {worker} ({host}:{port}) via {best_pool}\n\n{out.strip()}"
    reason = "miner not running" if miner_count <= 0 else "miner has not connected to pool"
    log_event("deploy_fail", instance_id=inst_id, trigger="manual", details=reason)
    return f"FAIL: {inst_id} — {reason} after deploy\n{out}\n{err}"


def kill_instance(inst_id: str, reason: str = "") -> str:
    """Destroy a vast.ai instance and add machine to blacklist."""
    lock = InstanceLock(inst_id)
    if not lock.acquire():
        log_event("lock_timeout", instance_id=inst_id, trigger="manual",
                  details="kill_instance lock acquire failed")
        return f"SKIP: {inst_id} — locked (another deploy or kill in progress)"

    try:
        return _kill_instance_inner(inst_id, reason)
    finally:
        lock.release()


def _kill_instance_inner(inst_id: str, reason: str = "", *, blacklist: bool = True) -> str:
    """Inner kill logic — lock already held.

    Args:
        inst_id: The instance ID to destroy.
        reason: Human-readable reason for the kill decision.
        blacklist: If False, skip adding the machine_id to the blacklist file
                   (e.g. for manual kills or one-off issues)."""
    cfg = _load_electron_config()
    trigger = "autodeploy" if reason else "manual"
    log_event("kill_start", instance_id=inst_id, trigger=trigger, details=reason)

    # Safety: check protection period
    if _is_protected(str(inst_id), cfg):
        log_event("protection_skip", instance_id=inst_id, trigger=trigger,
                  details=f"deployed < {cfg.get('new_instance_protection_minutes', 15)} min ago")
        return (
            f"SKIP: {inst_id} — protected "
            f"(deployed < {cfg.get('new_instance_protection_minutes', 15)} min ago)"
        )

    # Safety: check destroy rate limit
    if not _can_destroy(cfg):
        log_event("rate_limit_skip", instance_id=inst_id, trigger=trigger,
                  details=f"destroy rate limit reached ({cfg.get('max_destroys_per_hour', 2)}/hr)")
        return f"SKIP: {inst_id} — destroy rate limit reached ({cfg.get('max_destroys_per_hour', 2)}/hr)"

    # Get machine ID before destroying
    machine_id = ""
    rc, stdout, _ = _vastai(["show", "instances", "--raw"], timeout=15)
    if rc == 0:
        try:
            data = json.loads(stdout)
            for entry in data:
                if str(entry.get("id")) == str(inst_id):
                    machine_id = str(entry.get("machine_id", ""))
                    break
        except (json.JSONDecodeError, KeyError):
            pass

    rc, stdout, stderr = _vastai_yes(["destroy", "instance", str(inst_id)], timeout=15)
    if rc != 0:
        return f"FAILED to destroy {inst_id}: {stderr or stdout[:200]}"

    # Verify it's actually gone — show command returns error when instance deleted
    rc2, out2, _ = _vastai(["show", "instance", str(inst_id)], timeout=10)
    if rc2 == 0 and ("running" in _strip_ansi(out2).lower() or inst_id in out2):
        return f"FAILED to destroy {inst_id}: instance still exists after destroy command"

    _unmark_deployed(inst_id)
    _mark_bad(inst_id)
    _record_destroy()
    log_event("kill_success", instance_id=inst_id, trigger=trigger,
              details=f"{reason} [machine {machine_id}]" if machine_id else reason)

    # Add to blacklist with machine ID and reason (when enabled)
    if blacklist and machine_id and reason:
        from datetime import datetime as dt
        blacklist_entry = f"{machine_id} {reason} {dt.now().strftime('%Y-%m-%d')}\n"
        with open(BLACKLIST_FILE, "a") as f:
            f.write(blacklist_entry)
        log_event("blacklist_add", instance_id=inst_id, trigger=trigger,
                  details=f"machine={machine_id} reason={reason[:80]}")

    msg = f"Destroyed: {inst_id}"
    if reason:
        msg += f" ({reason})"
    if machine_id:
        msg += f" [machine {machine_id}]"
    return msg


def wait_ready(inst_id: str, timeout_sec: int = 300) -> str:
    """Wait for an instance to reach 'running' state."""
    start = time.time()
    while time.time() - start < timeout_sec:
        rc, stdout, _ = _vastai(["show", "instance", str(inst_id)], timeout=15)
        if rc != 0:
            time.sleep(10)
            continue

        clean = _strip_ansi(stdout)
        for line in clean.split("\n"):
            if "status" in line.lower():
                if "running" in line.lower():
                    return f"Instance {inst_id} is running."
                if any(s in line.lower() for s in ("exited", "offline", "unknown")):
                    return f"Instance {inst_id} is {line.strip()} — won't reach running."

        time.sleep(10)
    return f"Timeout waiting for {inst_id} after {timeout_sec}s"


def autodeploy_cycle(
    max_price_per_gpu: float | None = None,
) -> str:
    """Run one full autodeploy cycle with global lock."""
    lock = AutodeployLock()
    if not lock.acquire():
        log_event("lock_timeout", trigger="autodeploy",
                  details="autodeploy_cycle lock acquire failed")
        return "=== autodeploy SKIPPED — another cycle is running ==="

    try:
        return _autodeploy_cycle_inner(max_price_per_gpu)
    finally:
        lock.release()


def _autodeploy_cycle_inner(
    max_price_per_gpu: float | None = None,
) -> str:
    """Inner autodeploy logic — global lock already held.

    Respects safety config from electron app:
      - ``automation_enabled``: false → skip entire cycle
      - ``dry_run``: true → log actions only, no destroys or deploys
      - ``auto_destroy_enabled``: false → dry-run cost/perf checks (log only)
      - ``auto_deploy_enabled``: false → skip deploying new instances

    Optimizations vs the original sequential flow:

    1. Fetches ``vastai show instances --raw`` **once** and reuses the JSON
       data across cost check, performance check, and deploy phases (was 3
       separate calls).
    2. Runs cost check and performance check **concurrently** via
       :class:`~concurrent.futures.ThreadPoolExecutor` (both are I/O-bound
       and independent — cost checks pricing, perf checks hashrate).
    3. Deploy loop iterates over the same cached JSON instead of parsing
       text output.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cycle_start_time = time.time()
    cfg = _load_electron_config()
    log: list[str] = []

    prl = cfg.get("prl_price", "?")
    ref_max = _calc_max_price_per_gpu("rtx_5090")
    ref_min = _min_th_for_model("rtx_5090")

    # Master kill switch
    if not cfg.get("automation_enabled", True):
        log.append(
            f"=== autodeploy @ {time.strftime('%H:%M:%S')} | "
            f"SKIPPED (automation_enabled=false) ==="
        )
        return "\n".join(log)

    dry_run = bool(cfg.get("dry_run", False))
    auto_destroy = bool(cfg.get("auto_destroy_enabled", False))
    auto_deploy = bool(cfg.get("auto_deploy_enabled", True))

    log_event("cycle_start", trigger="autodeploy",
              details=f"PRL=${prl} max=${ref_max:.4f}/GPU min={ref_min}TH/s"
                      f"{' DRY' if dry_run else ''}"
                      f"{' destroy=OFF' if not auto_destroy else ''}"
                      f"{' deploy=OFF' if not auto_deploy else ''}")

    header = f"=== autodeploy @ {time.strftime('%H:%M:%S')} | PRL=${prl} | 5090 max ${ref_max:.4f}/GPU | min {ref_min} TH/s"
    if dry_run:
        header += " | DRY RUN"
    elif not auto_destroy:
        header += " | destroy=OFF"
    log.append(header + " ===")

    # ── Fetch instances ONCE (shared across all phases) ──
    instances: list[dict[str, Any]] = []
    if not dry_run or auto_deploy:
        rc, raw_stdout, _ = _vastai(["show", "instances", "--raw"], timeout=15)
        if rc == 0:
            try:
                instances = json.loads(raw_stdout)
                if not isinstance(instances, list):
                    instances = []
            except json.JSONDecodeError:
                log.append("WARN: could not parse vastai instances JSON")
        else:
            log.append(f"WARN: vastai instances fetch failed — checks will fetch individually")

    # ── Record instance snapshots (every cycle) ──
    _snapshot_instances(instances)

    # ── 1+2. Cost check + Performance check IN PARALLEL ──
    real_checks_allowed = auto_destroy and not dry_run

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Cost check future
        if real_checks_allowed:
            cost_future = executor.submit(_check_costs, max_price_per_gpu, instances or None)
        else:
            cost_future = executor.submit(_check_costs_dry, max_price_per_gpu, instances or None)

        # Performance check future
        if real_checks_allowed:
            pf_kwargs: dict[str, Any] = {}
            if instances:
                pf_kwargs["instances"] = instances
            perf_future = executor.submit(_check_and_kill, **pf_kwargs)
        else:
            perf_future = executor.submit(_check_and_kill_dry)

        # Collect results as they complete (order doesn't matter)
        for future in as_completed([cost_future, perf_future]):
            try:
                log.extend(future.result())
            except Exception as e:
                log.append(f"ERROR in check phase: {e}")

    # ── 3. Deploy to new (undeployed, non-bad) instances ──
    if dry_run:
        log.append("[DRY RUN] Would search for instances to deploy")
    elif not auto_deploy:
        log.append("SKIP: auto_deploy_enabled=false — no new deploys")
    elif instances:
        deployed_ids = _deployed_ids()
        bad_ids = _bad_ids()

        # Collect candidates
        deploy_candidates: list[str] = []
        for entry in instances:
            if not isinstance(entry, dict):
                continue
            if entry.get("actual_status") != "running":
                continue
            inst_id = str(entry["id"])
            if inst_id in deployed_ids or inst_id in bad_ids:
                continue
            deploy_candidates.append(inst_id)

        # Deploy candidates in parallel (each instance gets its own thread)
        if deploy_candidates:
            deploy_max = int(cfg.get("max_concurrent_deploys", 3))
            workers = min(len(deploy_candidates), deploy_max)
            log.append(f"Deploying to {len(deploy_candidates)} instances ({workers} concurrent)...")
            with ThreadPoolExecutor(max_workers=workers) as deploy_executor:
                deploy_futures = {
                    deploy_executor.submit(deploy_instance, inst_id): inst_id
                    for inst_id in deploy_candidates
                }
                for future in as_completed(deploy_futures):
                    try:
                        log.append(future.result())
                    except Exception as e:
                        log.append(f"ERROR deploying {deploy_futures[future]}: {e}")
    else:
        # Fallback: no cached instances — fetch inline (original text-based path)
        rc, stdout, _ = _vastai(["show", "instances"], timeout=15)
        if rc == 0:
            clean = _strip_ansi(stdout)
            deployed_ids = _deployed_ids()
            bad_ids = _bad_ids()
            for line in clean.split("\n"):
                parts = line.split()
                if len(parts) < 8:
                    continue
                inst_id = parts[1]
                if not inst_id.isdigit():
                    continue
                if parts[3] != "running":
                    continue
                if inst_id in deployed_ids or inst_id in bad_ids:
                    continue
                result = deploy_instance(inst_id)
                log.append(result)

    actual_kills = sum(1 for l in log if l.startswith("Destroyed:"))
    dry_kills = sum(1 for l in log if l.startswith("DRY: Would destroy"))
    summary = f"=== done ({actual_kills} killed"
    if dry_kills:
        summary += f", {dry_kills} dry-run"
    summary += ") ==="
    log.append(summary)
    duration = time.time() - cycle_start_time

    # Count cost-related results
    cost_killed = sum(1 for l in log if l.startswith("Destroyed:") and "exceeds max" in l)
    cost_warnings = sum(1 for l in log if l.startswith("WARN:") and "near threshold" in l)
    perf_killed = actual_kills - cost_killed
    perf_skipped = sum(1 for l in log if "warming up" in l)

    # Count deploy results
    deploys_attempted = sum(1 for l in log if l.startswith("Deploying to"))
    deploys_succeeded = sum(
        1 for l in log
        if l.startswith("Deployed:") or l.startswith("OK: deployed")
    )
    deploys_failed = sum(
        1 for l in log
        if l.startswith("FAIL:") or l.startswith("FAILED to deploy")
    )

    instances_running = sum(1 for e in instances if isinstance(e, dict) and e.get("actual_status") == "running")
    deploy_candidate_count = sum(
        1 for e in instances
        if isinstance(e, dict) and e.get("actual_status") == "running"
        and str(e.get("id", "")) not in _deployed_ids()
        and str(e.get("id", "")) not in _bad_ids()
    )

    record_cycle_summary(
        prl_price=float(prl) if isinstance(prl, (int, float)) else 0.0,
        max_price_per_gpu=max_price_per_gpu if max_price_per_gpu else ref_max,
        min_th_ref=ref_min,
        dry_run=dry_run,
        auto_destroy=auto_destroy,
        auto_deploy=auto_deploy,
        automation_enabled=bool(cfg.get("automation_enabled", True)),
        instances_fetched=len(instances),
        instances_running=instances_running,
        cost_killed=cost_killed,
        cost_warnings=cost_warnings,
        perf_killed=perf_killed,
        perf_skipped_warming=perf_skipped,
        deploy_candidates=deploy_candidate_count,
        deploys_attempted=deploys_attempted,
        deploys_succeeded=deploys_succeeded,
        deploys_failed=deploys_failed,
        duration_seconds=duration,
    )

    log_event("cycle_end", trigger="autodeploy",
              details=f"{actual_kills} killed"
                      f"{f', {dry_kills} dry-run' if dry_kills else ''}")
    return "\n".join(log)


def _check_costs(
    max_price_per_gpu: float | None = None,
    instances: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Kill instances where price per GPU exceeds model-specific threshold.
    Threshold is based on expected hashrate of the GPU model x PRL price.

    Args:
        max_price_per_gpu: Optional override for price threshold.
        instances: Optional pre-fetched instance list from ``vastai show
                   instances --raw``.  If None, fetches fresh data.
    """
    log: list[str] = []
    if instances is not None:
        data = instances
    else:
        rc, stdout, _ = _vastai(["show", "instances", "--raw"], timeout=15)
        if rc != 0:
            log.append("cost check failed: vastai error")
            return log
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            log.append(f"cost check failed: JSON parse error: {e}")
            return log

    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("actual_status") != "running":
            continue
        inst_id = str(entry["id"])
        num_gpus = entry.get("num_gpus", 1)
        gpu_name = entry.get("gpu_name", "RTX 5090")
        try:
            price_total = float(entry.get("dph_total", 0))
        except (TypeError, ValueError):
            continue
        price_per_gpu = price_total / num_gpus if num_gpus > 0 else price_total

        # Get model-specific threshold
        threshold = max_price_per_gpu if max_price_per_gpu else _calc_max_price_per_gpu(gpu_name)

        if price_per_gpu > threshold:
            result = kill_instance(
                inst_id,
                f"${price_per_gpu:.2f}/GPU ({gpu_name}) exceeds max ${threshold:.2f}"
            )
            log.append(result)
            executed = result.startswith("Destroyed:")
            record_kill_decision(
                instance_id=inst_id,
                machine_id=str(entry.get("machine_id", "")),
                trigger="autodeploy",
                reason_type="too_expensive",
                executed=executed,
                gpu_model=_parse_gpu_model(gpu_name) or gpu_name.lower().replace(" ", "_"),
                num_gpus=num_gpus,
                price_per_gpu=price_per_gpu,
                max_price_per_gpu=threshold,
                dph_total=price_total,
                details=f"${price_per_gpu:.2f}/GPU ({gpu_name}) exceeds max ${threshold:.2f}",
            )
        elif price_per_gpu > threshold * 0.8:
            log.append(f"WARN: {inst_id} ${price_per_gpu:.2f}/GPU ({gpu_name}) near threshold ${threshold:.2f}")
            record_kill_decision(
                instance_id=inst_id,
                machine_id=str(entry.get("machine_id", "")),
                trigger="autodeploy",
                reason_type="too_expensive",
                executed=False,
                gpu_model=_parse_gpu_model(gpu_name) or gpu_name.lower().replace(" ", "_"),
                num_gpus=num_gpus,
                price_per_gpu=price_per_gpu,
                max_price_per_gpu=threshold,
                dph_total=price_total,
                details=f"WARNING near threshold: ${price_per_gpu:.2f}/GPU ({gpu_name})",
            )
    return log


def _check_and_kill(
    instances: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Query AlphaPool API, find underperforming workers, kill their instances.

    Applies per-GPU-model thresholds from electron config (or fallback to 70% of
    reference hashrate).  Uses 1-hour average hashrate for the kill decision
    (more stable than live), with a warm-up grace period for newly deployed
    instances (avg_h1 < 30% of threshold → skip).

    Args:
        instances: Optional pre-fetched instance list from ``vastai show
                   instances --raw``.  If None, fetches fresh data.
    """
    log: list[str] = []

    try:
        import urllib.request
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log.append(f"API error: {e}")
        return log

    # Group underperforming workers by (instance_tag, gpu_model)
    # structure: {(tag, gpu_model): [(live_th, worker_name, h1_th)]}
    flagged: dict[tuple[str, str], list[tuple[float, str, float]]] = {}
    unknown_gpu_count = 0

    for w in data.get("workers", []):
        if not w.get("online"):
            continue
        try:
            live = float(w["hashrate_live"].split()[0])
            h1 = float(w.get("hashrate_1h", "0").split()[0]) if w.get("hashrate_1h") else 0
        except (ValueError, KeyError):
            continue
        name = w["name"]

        # Parse GPU model from worker name
        gpu_model = _parse_gpu_model(name)
        if gpu_model is None:
            unknown_gpu_count += 1
            continue

        # Extract instance tag from worker name (needed for snapshot)
        inst_tag = ""
        m = re.match(r"\w+x\d+-([a-z0-9]+)\.gpu\d+", name, re.IGNORECASE)
        if m:
            inst_tag = m.group(1)

        # Record worker snapshot (every cycle, regardless of performance)
        record_worker_snapshot(
            worker_name=name,
            online=True,
            live_th=live,
            h1_th=h1,
            instance_tag=inst_tag,
            gpu_model=gpu_model,
        )

        min_th = _min_th_for_model(gpu_model)

        # Use 1h average for stable kill decisions
        if h1 >= min_th:
            continue

        # Harsh drop check: live hashrate AND 1h avg are both below threshold
        if live >= min_th:
            continue  # recovering — let it stay

        # Extract instance tag from worker name
        # Formats: "5090x4-9629.gpu0" -> ("9629", gpu0), "4090x2-a.gpu0" -> ("a", gpu0)
        if not inst_tag:
            continue

        key = (inst_tag, gpu_model)
        if key not in flagged:
            flagged[key] = []
        flagged[key].append((live, name, h1))

    if unknown_gpu_count:
        log.append(f"INFO: {unknown_gpu_count} workers with unrecognized GPU model (skipped)")

    if not flagged:
        return log

    # For each flagged tag, find the matching instance and kill
    if instances is not None:
        inst_data = instances
    else:
        rc, stdout, _ = _vastai(["show", "instances", "--raw"], timeout=15)
        if rc != 0:
            return log
        try:
            inst_data = json.loads(stdout)
        except json.JSONDecodeError:
            return log

    for (tag, gpu_model), gpus in flagged.items():
        avg_live = sum(g[0] for g in gpus) / len(gpus)
        avg_h1 = sum(g[2] for g in gpus) / len(gpus) if gpus else 0
        min_th = _min_th_for_model(gpu_model)
        num_gpus = len(gpus)

        # Warm-up protection: skip if 1h average is < 30% of threshold
        if avg_h1 < min_th * 0.3:
            log.append(
                f"SKIP: {num_gpus} {gpu_model} GPUs low on tag {tag} "
                f"(avg live {avg_live:.0f} TH/s, h1={avg_h1:.0f} — warming up)"
            )
            record_kill_decision(
                instance_id=tag,
                trigger="autodeploy",
                reason_type="underperforming",
                executed=False,
                gpu_model=gpu_model,
                num_gpus=num_gpus,
                live_th=avg_live,
                h1_th=avg_h1,
                min_th_conf=min_th,
                threshold_used="config",
                warmup_skipped=True,
                details=f"warming up: avg_h1={avg_h1:.0f} < 30% min_th={min_th:.0f}",
            )
            continue

        found_match = False
        for entry in inst_data:
            if not isinstance(entry, dict):
                continue
            if entry.get("actual_status") != "running":
                continue
            inst_id = str(entry["id"])
            # Exact match: instance ID must END with the tag
            if not inst_id.endswith(tag):
                continue

            found_match = True
            entry_num_gpus = entry.get("num_gpus", num_gpus)
            try:
                dph_total = float(entry.get("dph_total", 0))
            except (TypeError, ValueError):
                dph_total = 0.0
            price_per_gpu = dph_total / entry_num_gpus if entry_num_gpus > 0 else dph_total
            machine_id = str(entry.get("machine_id", ""))

            result = kill_instance(
                inst_id,
                f"{num_gpus} {gpu_model} GPUs below {min_th} TH/s "
                f"(avg live {avg_live:.0f}, h1={avg_h1:.0f})"
            )
            log.append(result)
            executed = result.startswith("Destroyed:")
            record_kill_decision(
                instance_id=inst_id,
                machine_id=machine_id,
                trigger="autodeploy",
                reason_type="underperforming",
                executed=executed,
                gpu_model=gpu_model,
                num_gpus=entry_num_gpus,
                live_th=avg_live,
                h1_th=avg_h1,
                min_th_conf=min_th,
                threshold_used="config",
                price_per_gpu=price_per_gpu,
                dph_total=dph_total,
                warmup_skipped=False,
                details=f"avg live={avg_live:.0f}, h1={avg_h1:.0f}, min_th={min_th:.0f}",
            )
            break

        if not found_match:
            record_kill_decision(
                instance_id=tag,
                trigger="autodeploy",
                reason_type="underperforming",
                executed=False,
                gpu_model=gpu_model,
                num_gpus=num_gpus,
                live_th=avg_live,
                h1_th=avg_h1,
                min_th_conf=min_th,
                threshold_used="config",
                warmup_skipped=False,
                details="no matching running instance found",
            )

    return log


# ── Cost-effective GPU whitelist ──

_COST_EFFECTIVE_OFFERS_FILE = "cost_effective_offers.json"

_COUNTRY_TO_REGION: dict[str, str] = {
    # North America
    "US": "North America",
    "CA": "North America",
    "MX": "North America",
    # Europe
    "DE": "Europe", "NL": "Europe", "GB": "Europe", "FR": "Europe",
    "FI": "Europe", "PL": "Europe", "NO": "Europe", "SE": "Europe",
    "IT": "Europe", "ES": "Europe", "AT": "Europe", "BE": "Europe",
    "CH": "Europe", "IE": "Europe", "CZ": "Europe", "DK": "Europe",
    "PT": "Europe", "RO": "Europe", "HU": "Europe", "GR": "Europe",
    "BG": "Europe", "SK": "Europe", "LT": "Europe", "LV": "Europe",
    "EE": "Europe", "IS": "Europe", "UA": "Europe",
    # Asia
    "JP": "Asia", "SG": "Asia", "HK": "Asia", "KR": "Asia",
    "IN": "Asia", "TW": "Asia", "AE": "Asia", "IL": "Asia",
    "SA": "Asia", "TR": "Asia", "CN": "Asia",
    # Oceania
    "AU": "Oceania", "NZ": "Oceania",
    # South America
    "BR": "South America", "AR": "South America", "CL": "South America",
    "CO": "South America",
    # Africa
    "ZA": "Africa", "NG": "Africa", "EG": "Africa",
}


def _geolocation_to_region(geolocation: str) -> str:
    """Map vast.ai geolocation to a canonical region name.

    vast.ai returns strings like ``"Ukraine, UA"``, ``"US-CA"``, or
    ``"US"``. This function extracts the country code and maps it.

    Returns ``"Other"`` for unrecognized codes and ``"Unknown"`` for
    empty input.
    """
    if not geolocation:
        return "Unknown"
    code = geolocation.strip()
    # Format: "City/Country, CODE" → extract CODE
    if "," in code:
        country = code.split(",")[-1].strip().upper()
    # Format: "US-CA" → extract "US"
    elif "-" in code:
        country = code.split("-")[0].strip().upper()
    else:
        country = code.upper()
    return _COUNTRY_TO_REGION.get(country, "Other")


def _normalize_offer_gpu_name(gpu_name: str) -> str | None:
    """Normalize a vast.ai offer GPU name to a ``GPU_HASHRATES`` key.

    Handles the variety of formats vast.ai returns::

        'RTX 5090'               -> 'rtx_5090'
        'NVIDIA GeForce RTX 4090' -> 'rtx_4090'
        'NVIDIA RTX 4070 Ti SUPER' -> 'rtx_4070_ti_super'
        'Tesla H100'             -> 'h100'
        'NVIDIA A100-SXM4-80GB'  -> 'a100'
        'RTX A6000'              -> 'a6000'
        'NVIDIA L40S'            -> 'l40s'

    Returns None if no match is found.
    """
    raw = gpu_name.strip().lower()
    if not raw:
        return None

    # Remove noise words
    cleaned = raw.replace("-", " ").replace("_", " ")
    for prefix in ["nvidia ", "geforce ", "tesla ", "nvidia geforce "]:
        cleaned = cleaned.replace(prefix, "")

    # Pass 1: datacenter GPU keys (non-rtx_)
    compact = cleaned.replace(" ", "")
    for key in GPU_HASHRATES:
        if not key.startswith("rtx_"):
            if key in compact:
                return key

    # Pass 2: consumer GPU keys (rtx_)
    normalized = "_".join(cleaned.split())
    for key in GPU_HASHRATES:
        if key.startswith("rtx_"):
            suffix = key[4:]  # e.g. "5090", "4070_ti_super"
            if suffix in normalized:
                return key

    # Pass 3: fallback by model number
    m = re.search(r"(?:\b|_)(\d{3,4})\b", normalized)
    if m:
        model_num = m.group(1)
        for key in GPU_HASHRATES:
            if model_num in key:
                return key

    return None


def _gpu_display_name(gpu_key: str) -> str:
    """Convert an internal GPU key to a vast.ai searchable display name."""
    if gpu_key.startswith("rtx_"):
        # rtx_5090 -> RTX 5090, rtx_4070_ti_super -> RTX 4070 Ti SUPER
        base = gpu_key[4:].replace("_", " ").upper()
        return f"RTX {base}"
    # Datacenter GPUs: uppercase the key
    return gpu_key.upper()


def _parse_search_json(text: str) -> list[dict[str, Any]] | None:
    """Try to parse vastai search offers --raw JSON output."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return None


def _parse_search_text(text: str) -> list[dict[str, Any]]:
    """Fallback: parse tabular text output from vastai search offers."""
    clean = _strip_ansi(text)
    lines = clean.strip().split("\n")
    if len(lines) <= 1:
        return []

    # Try to parse header row for column indices
    header = lines[0].split()
    offers: list[dict[str, Any]] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        # Heuristic column mapping for vastai text output
        # Typical columns: ID  Machine  Status  GPU  Num  DPH  ...
        try:
            offer: dict[str, Any] = {
                "id": parts[1] if len(parts) > 1 else "",
                "gpu_name": parts[3] if len(parts) > 3 else "",
                "num_gpus": int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1,
                "dph_total": float(parts[5]) if len(parts) > 5 else 0.0,
                "geolocation": parts[2] if len(parts) > 2 else "",
                "verified": len(header) > 0,
            }
            offers.append(offer)
        except (ValueError, IndexError):
            continue
    return offers


def scan_cost_effective_offers() -> str:
    """Scan vast.ai marketplace for cost-effective GPU offers.

    Queries the vast.ai search offers API for all supported GPU models,
    calculates **TH per dollar per hour** (reference hashrate / price
    per GPU per hour), filters by the ``th_per_dollar_hr_threshold``
    and ``whitelist_regions`` config values, and saves matching offers
    to ``state/cost_effective_offers.json``.

    Returns a formatted report string for CLI display.
    """
    cfg = _load_electron_config()
    threshold = float(cfg.get("th_per_dollar_hr_threshold", 400))
    whitelist_regions: list[str] = cfg.get(
        "whitelist_regions", ["North America", "Asia", "Europe"]
    )
    # Handle both string (comma-separated) and list forms from config
    if isinstance(whitelist_regions, str):
        whitelist_regions = [
            r.strip() for r in whitelist_regions.split(",") if r.strip()
        ]
    if not isinstance(whitelist_regions, list) or not whitelist_regions:
        whitelist_regions = ["North America", "Asia", "Europe"]

    verified = bool(cfg.get("vast_verified_only", True))
    max_price = cfg.get("vast_max_price")
    max_price = float(max_price) if max_price is not None else None

    matching_offers: list[dict[str, Any]] = []
    errors: list[str] = []
    total_checked = 0

    for gpu_key, ref_th in GPU_HASHRATES.items():
        display_name = _gpu_display_name(gpu_key)

        query_parts = [
            f"gpu_name={display_name}",
            "num_gpus>=1",
            "rentable=true",
            "direct_port_count>=1",
        ]
        if verified:
            query_parts.append("verified=true")

        query = " ".join(query_parts)
        if max_price is not None:
            query += f" max_price<={max_price}"

        # Try --raw for JSON; fall back to text parsing
        args = [
            "search", "offers", query,
            "-o", "dph_total-",
            "--limit", "30",
            "--raw",
        ]

        rc, stdout, stderr = _vastai(args, timeout=30)
        if rc != 0:
            # Retry without --raw (some vastai versions don't support it)
            args_no_raw = [a for a in args if a != "--raw"]
            rc, stdout, stderr = _vastai(args_no_raw, timeout=30)
            if rc != 0:
                errors.append(f"  [{gpu_key}] search failed: {stderr[:100]}")
                continue

        offers = _parse_search_json(stdout)
        if offers is None:
            offers = _parse_search_text(stdout)

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            total_checked += 1

            offer_gpu_name = str(offer.get("gpu_name", ""))
            matched_key = _normalize_offer_gpu_name(offer_gpu_name)
            if matched_key is None:
                continue
            actual_ref_th = GPU_HASHRATES.get(matched_key, ref_th)

            try:
                dph_total = float(offer.get("dph_total", 0))
                num_gpus = int(offer.get("num_gpus", 1))
            except (TypeError, ValueError):
                continue
            if dph_total <= 0 or num_gpus <= 0:
                continue

            price_per_gpu = dph_total / num_gpus
            th_per_dollar_hr = actual_ref_th / price_per_gpu if price_per_gpu > 0 else 0.0

            geography = str(offer.get("geolocation", ""))
            region = _geolocation_to_region(geography)

            if th_per_dollar_hr >= threshold and region in whitelist_regions:
                matching_offers.append({
                    "offer_id": str(offer.get("id", "")),
                    "gpu_name": offer_gpu_name,
                    "gpu_model_key": matched_key,
                    "num_gpus": num_gpus,
                    "dph_total": round(dph_total, 4),
                    "price_per_gpu_hr": round(price_per_gpu, 4),
                    "ref_th_per_gpu": actual_ref_th,
                    "th_per_dollar_hr": round(th_per_dollar_hr, 1),
                    "geolocation": geography,
                    "region": region,
                    "verified": bool(offer.get("verified", False)),
                    "machine_id": str(offer.get("machine_id", "")),
                    "rentable": bool(offer.get("rentable", False)),
                    "inet_up": offer.get("inet_up", 0),
                    "inet_down": offer.get("inet_down", 0),
                    "cuda_vers": str(offer.get("cuda_max_good", "")),
                    "disk_space": offer.get("disk_space", 0),
                    "ram": offer.get("ram", 0),
                })

    # Sort by TH/$/hr descending (best value first)
    matching_offers.sort(key=lambda o: o["th_per_dollar_hr"], reverse=True)

    # Persist to file
    output_path = _state_dir() / _COST_EFFECTIVE_OFFERS_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(matching_offers, indent=2))

    # Build report
    lines: list[str] = []
    lines.append("=== Cost-Effective GPU Scan ===")
    lines.append(f"  Threshold: {threshold:.0f} TH/$/hr")
    lines.append(f"  Regions:  {', '.join(sorted(whitelist_regions))}")
    lines.append(f"  Offers checked: {total_checked}")
    lines.append(f"  Matches: {len(matching_offers)}")
    lines.append(f"  Saved to: {output_path}")
    lines.append("")

    if errors:
        lines.append("Warnings:")
        lines.extend(errors)
        lines.append("")

    if matching_offers:
        header = (
            f"{'GPU':<22} {'$/GPU':<9} {'TH/$/hr':<10} "
            f"{'Region':<16} {'Loc':<5} {'ID':<10}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for o in matching_offers[:50]:
            loc = o["geolocation"][:5]
            lines.append(
                f"{o['gpu_model_key']:<22}"
                f"${o['price_per_gpu_hr']:<8.4f} "
                f"{o['th_per_dollar_hr']:<10.1f} "
                f"{o['region']:<16} "
                f"{loc:<5} "
                f"{o['offer_id']:<10}"
            )
        if len(matching_offers) > 50:
            lines.append(f"  ... and {len(matching_offers) - 50} more matches")
    else:
        lines.append("No cost-effective offers found matching the current criteria.")

    return "\n".join(lines)


_INTERRUPTIBLE_OFFERS_FILE = "interruptible_offers.json"


def scan_interruptible_offers() -> str:
    """Scan vast.ai for **interruptible** offers with high DLPerf efficiency.

    Filters offers where:
    - ``interruptible=true``
    - DLPerf per dollar per hour > ``min_dlperf_per_dollar`` (default 350)

    Results are saved to ``state/interruptible_offers.json`` for the
    Electron UI to display as a real-time list.

    Returns a formatted report string for CLI display.
    """
    cfg = _load_electron_config()
    min_dlperf_usd = float(cfg.get("min_dlperf_per_dollar", 350))
    whitelist_regions: list[str] = cfg.get(
        "whitelist_regions", ["North America", "Asia", "Europe"]
    )
    if isinstance(whitelist_regions, str):
        whitelist_regions = [
            r.strip() for r in whitelist_regions.split(",") if r.strip()
        ]
    if not isinstance(whitelist_regions, list) or not whitelist_regions:
        whitelist_regions = ["North America", "Asia", "Europe"]

    verified = bool(cfg.get("vast_verified_only", True))

    matching_offers: list[dict[str, Any]] = []
    errors: list[str] = []
    total_checked = 0

    for gpu_key, ref_th in GPU_HASHRATES.items():
        display_name = _gpu_display_name(gpu_key)

        query_parts = [
            f"gpu_name={display_name}",
            "num_gpus>=1",
            "rentable=true",
            "direct_port_count>=1",
            "interruptible=true",
        ]
        if verified:
            query_parts.append("verified=true")

        query = " ".join(query_parts)

        args = [
            "search", "offers", query,
            "-o", "dlperf_usd-",
            "--limit", "30",
            "--raw",
        ]

        rc, stdout, stderr = _vastai(args, timeout=30)
        if rc != 0:
            args_no_raw = [a for a in args if a != "--raw"]
            rc, stdout, stderr = _vastai(args_no_raw, timeout=30)
            if rc != 0:
                errors.append(f"  [{gpu_key}] search failed: {stderr[:100]}")
                continue

        offers = _parse_search_json(stdout)
        if offers is None:
            offers = _parse_search_text(stdout)

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            total_checked += 1

            # Only interruptible offers
            if not offer.get("interruptible"):
                continue

            offer_gpu_name = str(offer.get("gpu_name", ""))
            matched_key = _normalize_offer_gpu_name(offer_gpu_name)
            if matched_key is None:
                continue

            try:
                dph_total = float(offer.get("dph_total", 0))
                num_gpus = int(offer.get("num_gpus", 1))
                dlperf = float(offer.get("dlperf", 0))
            except (TypeError, ValueError):
                continue
            if dph_total <= 0 or num_gpus <= 0 or dlperf <= 0:
                continue

            price_per_gpu = dph_total / num_gpus
            dlperf_per_dollar_hr = dlperf / dph_total if dph_total > 0 else 0.0

            geography = str(offer.get("geolocation", ""))
            region = _geolocation_to_region(geography)

            if dlperf_per_dollar_hr >= min_dlperf_usd and region in whitelist_regions:
                matching_offers.append({
                    "offer_id": str(offer.get("id", "")),
                    "gpu_name": offer_gpu_name,
                    "gpu_model_key": matched_key,
                    "num_gpus": num_gpus,
                    "dph_total": round(dph_total, 4),
                    "price_per_gpu_hr": round(price_per_gpu, 4),
                    "dlperf": round(dlperf, 2),
                    "dlperf_per_dollar_hr": round(dlperf_per_dollar_hr, 1),
                    "ref_th_per_gpu": ref_th,
                    "geolocation": geography,
                    "region": region,
                    "verified": bool(offer.get("verified", False)),
                    "machine_id": str(offer.get("machine_id", "")),
                    "rentable": bool(offer.get("rentable", False)),
                    "inet_up": offer.get("inet_up", 0),
                    "inet_down": offer.get("inet_down", 0),
                    "cuda_vers": str(offer.get("cuda_max_good", "")),
                    "disk_space": offer.get("disk_space", 0),
                    "ram": offer.get("ram", 0),
                })

    # Sort by DLPerf/$ descending (best efficiency first)
    matching_offers.sort(key=lambda o: o["dlperf_per_dollar_hr"], reverse=True)

    # Persist to file for Electron UI
    output_path = _state_dir() / _INTERRUPTIBLE_OFFERS_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(matching_offers, indent=2))

    # Build report
    lines: list[str] = []
    lines.append("=== Interruptible Offers (DLPerf Efficiency) ===")
    lines.append(f"  Threshold: DLPerf/$ >= {min_dlperf_usd:.0f}")
    lines.append(f"  Regions:   {', '.join(sorted(whitelist_regions))}")
    lines.append(f"  Offers checked: {total_checked}")
    lines.append(f"  Matches: {len(matching_offers)}")
    lines.append(f"  Saved to: {output_path}")
    lines.append("")

    if errors:
        lines.append("Warnings:")
        lines.extend(errors)
        lines.append("")

    if matching_offers:
        header = (
            f"{'GPU':<22} {'DLPerf':<9} {'DLPerf/$':<10} "
            f"{'$/GPU/hr':<10} {'Region':<16} {'ID':<10}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for o in matching_offers[:50]:
            lines.append(
                f"{o['gpu_model_key']:<22}"
                f"{o['dlperf']:<9.1f} "
                f"{o['dlperf_per_dollar_hr']:<10.1f} "
                f"${o['price_per_gpu_hr']:<9.4f} "
                f"{o['region']:<16} "
                f"{o['offer_id']:<10}"
            )
        if len(matching_offers) > 50:
            lines.append(f"  ... and {len(matching_offers) - 50} more matches")
    else:
        lines.append("No interruptible offers found matching DLPerf/$ criteria.")

    return "\n".join(lines)


def get_ssh_url(inst_id: str) -> str:
    """Get SSH connection URL for an instance."""
    rc, stdout, stderr = _vastai(["ssh-url", str(inst_id)], timeout=15)
    if rc != 0:
        return f"Error: {stderr or stdout}"
    return stdout.strip()
