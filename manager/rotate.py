"""Thread-safe JSONL writer with file rotation.

Each line is a JSON object — no read-modify-write needed.
Thread/process-safe via advisory lock on every append.
Files rotate at 50 MB, keeping up to 10 rotated copies.
Cross-platform: uses fcntl on Unix, msvcrt on Windows.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ── Platform-specific file locking ──────────────────────────

if sys.platform == 'win32':
    import msvcrt

    def _flock_ex(fd: int) -> None:
        """Acquire exclusive lock (blocking) on Windows."""
        import time as _t
        deadline = _t.monotonic() + 30
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if _t.monotonic() >= deadline:
                    raise
                _t.sleep(0.05)

    def _flock_un(fd: int) -> None:
        """Release lock on Windows."""
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _flock_ex(fd: int) -> None:
        """Acquire exclusive lock (blocking) on Unix."""
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _flock_un(fd: int) -> None:
        """Release lock on Unix."""
        fcntl.flock(fd, fcntl.LOCK_UN)

MAX_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ROTATIONS = 10


def _state_dir() -> Path:
    """Resolve the state directory from PEARL_STATE_DIR or fallback."""
    env = os.environ.get("PEARL_STATE_DIR")
    if env:
        return Path(env)
    mining = Path(__file__).resolve().parent.parent
    return mining / "electron-app" / "state"


def _log_path(filename: str) -> Path:
    """Resolve full path for a JSONL file, creating parent dirs if needed."""
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / filename


def _rotate(filename: str) -> None:
    """Rotate a JSONL file: shift .N → .N+1, rename current → .1, create fresh.

    Must be called while holding the fcntl lock on the file.
    """
    base = _log_path(filename)
    if not base.exists():
        return

    # Remove oldest rotation if it exists
    oldest = _log_path(f"{filename}.{MAX_ROTATIONS}.jsonl")
    if oldest.exists():
        oldest.unlink()

    # Shift existing rotations: .9 → .10, .8 → .9, ... .1 → .2
    for n in range(MAX_ROTATIONS - 1, 0, -1):
        src = _log_path(f"{filename}.{n}.jsonl")
        dst = _log_path(f"{filename}.{n + 1}.jsonl")
        if src.exists():
            src.rename(dst)

    # Rename current file to .1
    first = _log_path(f"{filename}.1.jsonl")
    base.rename(first)


def write_record(filename: str, record: dict) -> None:
    """Append one JSON record to a JSONL file (thread/process-safe).

    Automatically adds ``ts`` (ISO 8601) and ``epoch_ms`` (Unix ms) if
    the record doesn't already contain them.

    When the file exceeds 50 MB, rotates it before appending.
    Keeps up to 10 rotated copies (``filename.1.jsonl`` through
    ``filename.10.jsonl``).

    Args:
        filename: Base filename (e.g. ``"kill_decisions.jsonl"``).
        record: Dictionary to write as a JSON line.
    """
    if "ts" not in record:
        record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if "epoch_ms" not in record:
        record["epoch_ms"] = int(time.time() * 1000)

    line = json.dumps(record, ensure_ascii=False) + "\n"
    path = _log_path(filename)

    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _flock_ex(fd)
        try:
            stat = os.fstat(fd)
            if stat.st_size >= MAX_BYTES:
                # Close the fd temporarily so rename works on the same inode
                os.close(fd)
                fd = -1
                _rotate(filename)
                # Re-open — _rotate renamed the old file away
                fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
                _flock_ex(fd)

            os.lseek(fd, 0, os.SEEK_END)
            os.write(fd, line.encode("utf-8"))
        finally:
            _flock_un(fd)
    finally:
        if fd >= 0:
            os.close(fd)


def read_records(
    filename: str,
    *,
    limit: int = 500,
    before_epoch_ms: int | None = None,
    after_epoch_ms: int | None = None,
) -> list[dict]:
    """Read records from a JSONL file, newest first.

    Args:
        filename: Base filename (e.g. ``"kill_decisions.jsonl"``).
        limit: Max number of records to return.
        before_epoch_ms: Only return records before this timestamp.
        after_epoch_ms: Only return records after this timestamp.

    Returns:
        List of record dicts, newest first.
    """
    path = _log_path(filename)
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

                epoch = record.get("epoch_ms", 0)
                if before_epoch_ms is not None and epoch >= before_epoch_ms:
                    continue
                if after_epoch_ms is not None and epoch <= after_epoch_ms:
                    continue
                results.append(record)
    except (OSError, IOError):
        return []

    results.reverse()
    return results[:limit]


def tail_records(filename: str, lines: int = 100) -> list[dict]:
    """Return the last N records from a JSONL file, newest first."""
    return read_records(filename, limit=lines)


def read_raw_lines(filename: str, limit: int = 500) -> list[str]:
    """Read raw JSON lines from a JSONL file, newest first.

    Useful for display/log viewing where you want the exact text.
    """
    path = _log_path(filename)
    if not path.exists():
        return []

    lines: list[str] = []
    try:
        with open(path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
    except (OSError, IOError):
        return []

    lines.reverse()
    return lines[:limit]
