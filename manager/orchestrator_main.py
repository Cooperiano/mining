"""Persistent orchestrator process — entry point for the actor-model autodeploy.

Run directly::

    python3 manager/orchestrator_main.py

Or via Electron's main.js when ``orchestrator_mode`` is enabled.

Outputs status lines to stdout (JSON) for Electron to consume.  Handles
SIGTERM / SIGINT for graceful shutdown.
"""

from __future__ import annotations

import json
import signal
import sys
import time


def main() -> None:
    # Ensure project root is on sys.path
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from manager.instance_manager import InstanceOrchestrator

    orch = InstanceOrchestrator()

    # Graceful shutdown on signals
    def _shutdown(signum: int, _frame: object) -> None:
        _emit("shutdown", signal=signum)
        orch.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _emit("starting", pid=os.getpid())
    orch.start()

    # Keep alive — emit status heartbeat every 30s
    try:
        while True:
            time.sleep(30)
            status = orch.status()
            _emit("heartbeat", **status)
    except KeyboardInterrupt:
        pass
    finally:
        orch.stop()
        _emit("stopped")


def _emit(event: str, **kwargs: object) -> None:
    """Write a JSON status line to stdout (one object per line)."""
    msg = {"event": event, "ts": time.time(), **kwargs}
    print(json.dumps(msg, default=str), flush=True)


import os  # noqa: E402 — needed after sys.path adjustment


if __name__ == "__main__":
    main()
