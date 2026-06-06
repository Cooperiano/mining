#!/usr/bin/env python3
"""Repackage alpha-miner binary with a new name, preserving protocol strings."""

import sys
import shutil

SRC = "alpha-miner"
DST = "CUDA-kernal"

REPLACEMENTS = [
    (b"alpha-miner", b"CUDA-kernal"),
]

def repack(src: str, dst: str) -> None:
    with open(src, "rb") as f:
        data = f.read()

    for old, new in REPLACEMENTS:
        assert len(old) == len(new), f"Length mismatch: {old!r} vs {new!r}"
        count = data.count(old)
        print(f"Replacing {old!r} -> {new!r}: {count} occurrences")
        data = data.replace(old, new)

    shutil.copy2(src, dst)
    with open(dst, "wb") as f:
        f.write(data)

    shutil.copymode(src, dst)
    print(f"\nWrote repackaged binary to {dst} ({len(data)} bytes)")

if __name__ == "__main__":
    repack(SRC, DST)
