"""Manage self-hosted miners via SSH."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .deploy import (
    generate_deploy_script,
    generate_start_script,
    generate_status_script,
    generate_stop_script,
    gpu_difficulty,
)

CONFIG_FILE = Path(os.path.expanduser("~/.config/minerctl/hosts.json"))


def _load() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {"hosts": []}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"hosts": []}


def _save(data: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _ssh_cmd(host: str, port: int, command: str) -> list[str]:
    return [
        "ssh", "-q",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=no",
        "-o", "LogLevel=QUIET",
        "root" if port != 22 else os.environ.get("USER", "root") + f"@{host}",
        "-p", str(port),
        command,
    ]


def _ssh_run(host: str, port: int, command: str) -> tuple[int, str]:
    cmd = _ssh_cmd(host, port, command)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except OSError as e:
        return -1, str(e)


def _pipe_script(host: str, port: int, script: str) -> tuple[int, str]:
    """Pipe a script over SSH and execute it."""
    b64 = base64.b64encode(script.encode()).decode()
    cmd = _ssh_cmd(host, port, f"echo '{b64}' | base64 -d | bash")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except OSError as e:
        return -1, str(e)


def add(ip: str, port: int, label: str | None = None,
        gpus: int = 1, gpu_type: str = "auto") -> str:
    data = _load()
    label = label or ip

    for h in data["hosts"]:
        if h["ip"] == ip and h["port"] == port:
            return f"Host {h['label']} ({ip}:{port}) already exists. Use 'remove' first."

    data["hosts"].append({
        "ip": ip,
        "port": port,
        "label": label,
        "gpus": gpus,
        "gpu_type": gpu_type,
    })
    _save(data)
    return f"Added: {label} ({ip}:{port}) [{gpus}x {gpu_type}]"


def remove(name: str) -> str:
    data = _load()
    for i, h in enumerate(data["hosts"]):
        if h["label"] == name or h["ip"] == name:
            removed = data["hosts"].pop(i)
            _save(data)
            return f"Removed: {removed['label']} ({removed['ip']}:{removed['port']})"
    return f"Host '{name}' not found."


def _find(name: str) -> dict[str, Any] | None:
    data = _load()
    for h in data["hosts"]:
        if h["label"] == name or h["ip"] == name:
            return h
    return None


def list_hosts() -> str:
    data = _load()
    if not data["hosts"]:
        return "No hosted miners configured. Use: minerctl host add <ip> <port>"

    lines = ["Hosted miners:"]
    for h in data["hosts"]:
        lines.append(
            f"  {h['label']:<12} {h['ip']}:{h['port']:<7}"
            f"  {h['gpus']}x {h['gpu_type']}"
        )
    return "\n".join(lines)


def deploy(name: str) -> str:
    h = _find(name)
    if not h:
        return f"Host '{name}' not found."

    worker = h["label"].replace(" ", "-")
    script = generate_deploy_script(
        worker=worker,
        gpu_type=h["gpu_type"],
    )
    rc, out = _pipe_script(h["ip"], h["port"], script)
    if rc == 0:
        return f"Deployed to {h['label']} ({h['ip']}:{h['port']})\n\n{out}"
    return f"FAILED ({rc}):\n{out}"


def start(name: str) -> str:
    h = _find(name)
    if not h:
        return f"Host '{name}' not found."
    script = generate_start_script()
    rc, out = _pipe_script(h["ip"], h["port"], script)
    return out.strip()


def stop(name: str) -> str:
    h = _find(name)
    if not h:
        return f"Host '{name}' not found."
    script = generate_stop_script()
    rc, out = _pipe_script(h["ip"], h["port"], script)
    return out.strip()


def restart(name: str) -> str:
    h = _find(name)
    if not h:
        return f"Host '{name}' not found."
    stop_out = stop(name)
    start_out = start(name)
    return f"{stop_out}\n{start_out}"


def status(name: str) -> str:
    h = _find(name)
    if not h:
        return f"Host '{name}' not found."
    script = generate_status_script()
    rc, out = _pipe_script(h["ip"], h["port"], script)

    d = gpu_difficulty(h["gpu_type"])
    return (
        f"{h['label']} ({h['ip']}:{h['port']}) [{h['gpus']}x {h['gpu_type']} d={d}]\n"
        f"{out.strip()}"
    )
