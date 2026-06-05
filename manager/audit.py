"""Append-only JSONL audit log for all state-changing operations.

Each line is a JSON object — no read-modify-write needed.
Thread-safe via ``fcntl`` advisory lock on every append.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path


def _state_dir() -> Path:
    """Resolve the state directory from PEARL_STATE_DIR or fallback."""
    env = os.environ.get("PEARL_STATE_DIR")
    if env:
        return Path(env)
    mining = Path(__file__).resolve().parent.parent
    return mining / "electron-app" / "state"


def _audit_path() -> Path:
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "audit.jsonl"


def log_event(
    event: str,
    instance_id: str = "",
    trigger: str = "manual",
    actor: str = "",
    details: str = "",
    old_state: str = "",
    new_state: str = "",
    extra: dict | None = None,
) -> None:
    """Append one event to the audit log (thread/process-safe).

    Args:
        event: Event type — ``deploy_start``, ``deploy_success``, ``deploy_fail``,
               ``kill_start``, ``kill_success``, ``kill_skip``, ``config_change``,
               ``cycle_start``, ``cycle_end``, ``protection_skip``,
               ``rate_limit_skip``, ``dry_run``, ``lock_timeout``
        instance_id: vast.ai instance ID (if applicable)
        trigger: What initiated the action — ``autodeploy``, ``manual``, ``config``
        actor: Username or process identifier
        details: Human-readable description
        old_state: Previous state before the change
        new_state: New state after the change
        extra: Arbitrary extra fields to include in the record
    """
    record: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event,
        "instance_id": str(instance_id),
        "trigger": trigger,
    }
    if actor:
        record["actor"] = actor
    if details:
        record["details"] = details
    if old_state:
        record["old_state"] = old_state
    if new_state:
        record["new_state"] = new_state
    if extra:
        record["extra"] = extra

    line = json.dumps(record, ensure_ascii=False) + "\n"
    path = _audit_path()

    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def query_events(
    instance_id: str = "",
    event_type: str = "",
    limit: int = 100,
) -> list[dict]:
    """Return recent audit events, newest first.

    Args:
        instance_id: Filter by instance ID (empty = all)
        event_type: Filter by event type (empty = all)
        limit: Max number of events to return
    """
    path = _audit_path()
    if not path.exists():
        return []

    results: list[dict] = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if instance_id and record.get("instance_id") != str(instance_id):
                    continue
                if event_type and record.get("event") != event_type:
                    continue
                results.append(record)
    except (OSError, IOError):
        return []

    # Return newest first
    results.reverse()
    return results[:limit]


def tail_events(lines: int = 50) -> list[dict]:
    """Return the last N audit events, newest first."""
    return query_events(limit=lines)
