"""High-level recording functions for mining operations.

Each function writes to a dedicated JSONL file via ``rotate.write_record()``.
All functions are thread/process-safe (fcntl locking in rotate.py).

Files written (all in ``electron-app/state/``):

- ``kill_decisions.jsonl``  — structured kill decision with all numeric inputs
- ``cycle_log.jsonl``        — autodeploy cycle summaries
- ``worker_snapshots.jsonl`` — periodic pool worker hashrate snapshots
- ``instance_snapshots.jsonl`` — periodic vast.ai instance state
- ``config_log.jsonl``       — config changes with before/after
"""

from __future__ import annotations

from manager.rotate import write_record

# ── Kill decision ────────────────────────────────────────────────────


def record_kill_decision(
    *,
    instance_id: str = "",
    machine_id: str = "",
    trigger: str = "autodeploy",
    reason_type: str = "underperforming",
    executed: bool = True,
    gpu_model: str = "",
    num_gpus: int = 0,
    live_th: float = 0.0,
    h1_th: float = 0.0,
    min_th_conf: float = 0.0,
    min_th_calc: float = 0.0,  # noqa: ARG001
    threshold_used: str = "config",
    price_per_gpu: float = 0.0,
    max_price_per_gpu: float = 0.0,
    dph_total: float = 0.0,
    warmup_skipped: bool = False,
    details: str = "",
) -> None:
    """Record a kill decision (executed or skipped).

    Args:
        reason_type: ``"underperforming"`` | ``"too_expensive"`` |
                     ``"no_workers_online"`` | ``"deploy_fail"`` | ``"manual"``
    """
    record: dict = {
        "instance_id": str(instance_id),
        "machine_id": str(machine_id),
        "trigger": trigger,
        "reason_type": reason_type,
        "executed": executed,
        "gpu_model": gpu_model,
        "num_gpus": num_gpus,
        "live_th": round(live_th, 2),
        "h1_th": round(h1_th, 2),
        "min_th_conf": round(min_th_conf, 2),
        "threshold_used": threshold_used,
        "price_per_gpu": round(price_per_gpu, 4),
        "max_price_per_gpu": round(max_price_per_gpu, 4),
        "dph_total": round(dph_total, 4),
        "warmup_skipped": warmup_skipped,
        "details": details,
    }
    write_record("kill_decisions.jsonl", record)


# ── Cycle summary ────────────────────────────────────────────────────


def record_cycle_summary(
    *,
    prl_price: float = 0.0,
    max_price_per_gpu: float = 0.0,
    min_th_ref: float = 0.0,
    dry_run: bool = False,
    auto_destroy: bool = True,
    auto_deploy: bool = True,
    automation_enabled: bool = True,
    instances_fetched: int = 0,
    instances_running: int = 0,
    cost_killed: int = 0,
    cost_warnings: int = 0,
    perf_killed: int = 0,
    perf_skipped_warming: int = 0,
    deploy_candidates: int = 0,
    deploys_attempted: int = 0,
    deploys_succeeded: int = 0,
    deploys_failed: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    """Record an autodeploy cycle summary."""
    record: dict = {
        "prl_price": round(prl_price, 4),
        "max_price_per_gpu": round(max_price_per_gpu, 4),
        "min_th_ref": round(min_th_ref, 2),
        "dry_run": dry_run,
        "auto_destroy": auto_destroy,
        "auto_deploy": auto_deploy,
        "automation_enabled": automation_enabled,
        "instances_fetched": instances_fetched,
        "instances_running": instances_running,
        "cost_killed": cost_killed,
        "cost_warnings": cost_warnings,
        "perf_killed": perf_killed,
        "perf_skipped_warming": perf_skipped_warming,
        "deploy_candidates": deploy_candidates,
        "deploys_attempted": deploys_attempted,
        "deploys_succeeded": deploys_succeeded,
        "deploys_failed": deploys_failed,
        "duration_seconds": round(duration_seconds, 2),
    }
    write_record("cycle_log.jsonl", record)


# ── Worker snapshots (batch) ─────────────────────────────────────────


def record_worker_snapshot(
    *,
    worker_name: str,
    online: bool = True,
    live_th: float = 0.0,
    h1_th: float = 0.0,
    instance_tag: str = "",
    gpu_model: str = "",
) -> None:
    """Record a single pool worker's hashrate snapshot."""
    record: dict = {
        "worker_name": worker_name,
        "online": online,
        "live_th": round(live_th, 2),
        "h1_th": round(h1_th, 2),
        "instance_tag": str(instance_tag),
        "gpu_model": gpu_model,
    }
    write_record("worker_snapshots.jsonl", record)


def record_worker_snapshots(workers: list[dict]) -> None:
    """Record a batch of pool worker snapshots."""
    for w in workers:
        record_worker_snapshot(
            worker_name=w.get("worker_name", ""),
            online=w.get("online", True),
            live_th=w.get("live_th", 0.0),
            h1_th=w.get("h1_th", 0.0),
            instance_tag=w.get("instance_tag", ""),
            gpu_model=w.get("gpu_model", ""),
        )


# ── Instance snapshots (batch) ───────────────────────────────────────


def record_instance_snapshot(
    *,
    instance_id: str = "",
    status: str = "",
    gpu_name: str = "",
    num_gpus: int = 0,
    dph_total: float = 0.0,
    price_per_gpu: float = 0.0,
    machine_id: str = "",
    geolocation: str = "",
) -> None:
    """Record a single vast.ai instance snapshot."""
    record: dict = {
        "instance_id": str(instance_id),
        "status": status,
        "gpu_name": gpu_name,
        "num_gpus": num_gpus,
        "dph_total": round(dph_total, 4),
        "price_per_gpu": round(price_per_gpu, 4),
        "machine_id": str(machine_id),
        "geolocation": geolocation,
    }
    write_record("instance_snapshots.jsonl", record)


def record_instance_snapshots(instances: list[dict]) -> None:
    """Record a batch of vast.ai instance snapshots.

    Each dict in *instances* should have: instance_id, status, gpu_name,
    num_gpus, dph_total, machine_id, geolocation.
    """
    for inst in instances:
        record_instance_snapshot(
            instance_id=inst.get("instance_id", ""),
            status=inst.get("status", ""),
            gpu_name=inst.get("gpu_name", ""),
            num_gpus=inst.get("num_gpus", 0),
            dph_total=inst.get("dph_total", 0.0),
            price_per_gpu=inst.get("price_per_gpu", 0.0),
            machine_id=inst.get("machine_id", ""),
            geolocation=inst.get("geolocation", ""),
        )


# ── Config change ────────────────────────────────────────────────────


def record_config_change(
    *,
    trigger: str = "python_detect",
    changed_keys: list[str] | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Record a configuration change with before/after values.

    Args:
        trigger: ``"electron_ui"`` | ``"python_detect"``
        changed_keys: List of keys that were changed.
        before: Config dict before the change.
        after: Config dict after the change.
    """
    record: dict = {
        "trigger": trigger,
        "changed_keys": changed_keys or [],
    }
    if before is not None:
        # Only include changed values in before/after for compactness
        keys = changed_keys or []
        record["before"] = {k: before[k] for k in keys if k in before}
    if after is not None:
        keys = changed_keys or []
        record["after"] = {k: after[k] for k in keys if k in after}
    write_record("config_log.jsonl", record)
