#!/usr/bin/env python3
"""Autodeploy cron entrypoint — runs every minute, self-contained."""
import sys
import traceback
from datetime import datetime
from pathlib import Path

MINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MINING_DIR))

FAIL_FLAG = Path("/tmp/.autodeploy_fail")

try:
    from manager import vast
    result = vast.autodeploy_cycle()
    print(result)
    # Clear fail flag on success
    if FAIL_FLAG.exists():
        FAIL_FLAG.unlink()
except Exception as e:
    traceback.print_exc()
    # Touch fail flag so you know something broke
    FAIL_FLAG.write_text(f"{datetime.now()} {e}\n")
    sys.exit(1)
