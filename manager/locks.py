"""File locks for safe concurrent operations across processes.

Provides per-instance locks (deploy/kill) and a global autodeploy singleton lock.
Process crash automatically releases locks — no stale lock files.
Cross-platform: uses fcntl on Unix, msvcrt on Windows.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def _lock_dir() -> Path:
    """Resolve the lock directory, checking PEARL_STATE_DIR first."""
    env = os.environ.get("PEARL_STATE_DIR")
    if env:
        return Path(env) / "locks"
    # Fallback for CLI usage without Electron
    mining = Path(__file__).resolve().parent.parent
    return mining / "electron-app" / "state" / "locks"


def _ensure_lock_dir() -> Path:
    d = _lock_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Platform-specific file locking ──────────────────────────

if sys.platform == 'win32':
    import msvcrt

    def _lock_nb(fd: int) -> None:
        """Non-blocking exclusive lock on Windows."""
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        """Release lock on Windows."""
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_nb(fd: int) -> None:
        """Non-blocking exclusive lock on Unix."""
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        """Release lock on Unix."""
        fcntl.flock(fd, fcntl.LOCK_UN)


class InstanceLock:
    """Per-instance advisory lock for deploy/kill operations.

    Usage::

        lock = InstanceLock("12345", timeout=5)
        if lock.acquire():
            try:
                deploy_instance("12345")
            finally:
                lock.release()
    """

    def __init__(self, instance_id: str, timeout: float = 5) -> None:
        self._id = str(instance_id)
        self._timeout = timeout
        self._lockfile = _ensure_lock_dir() / f"instance_{self._id}.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True on success, False on timeout."""
        deadline = time.monotonic() + self._timeout
        fd = os.open(self._lockfile, os.O_RDWR | os.O_CREAT, 0o644)
        while True:
            try:
                _lock_nb(fd)
                self._fd = fd
                return True
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    return False
                time.sleep(0.1)

    def release(self) -> None:
        """Release the lock and close the file descriptor."""
        if self._fd is not None:
            _unlock(self._fd)
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "InstanceLock":
        if not self.acquire():
            raise TimeoutError(f"Could not acquire lock for instance {self._id}")
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


class AutodeployLock:
    """Global singleton lock ensuring only one autodeploy cycle runs at a time.

    Usage::

        lock = AutodeployLock(timeout=10)
        if lock.acquire():
            try:
                autodeploy_cycle()
            finally:
                lock.release()
    """

    def __init__(self, timeout: float = 10) -> None:
        self._timeout = timeout
        self._lockfile = _ensure_lock_dir() / "autodeploy.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Try to acquire the global autodeploy lock."""
        deadline = time.monotonic() + self._timeout
        fd = os.open(self._lockfile, os.O_RDWR | os.O_CREAT, 0o644)
        while True:
            try:
                _lock_nb(fd)
                self._fd = fd
                return True
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    return False
                time.sleep(0.1)

    def release(self) -> None:
        """Release the lock and close the file descriptor."""
        if self._fd is not None:
            _unlock(self._fd)
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "AutodeployLock":
        if not self.acquire():
            raise TimeoutError("Could not acquire autodeploy lock (another cycle running?)")
        return self

    def __exit__(self, *args: object) -> None:
        self.release()
