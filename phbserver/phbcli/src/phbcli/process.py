"""PID file-based process management for the phbcli server and local gateway.

Supports Windows (taskkill) and Unix (SIGTERM).
All functions are workspace-scoped — they accept workspace_path: Path.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def workspace_pid_file(workspace_path: Path) -> Path:
    return workspace_path / "phbcli.pid"


def workspace_gateway_pid_file(workspace_path: Path) -> Path:
    return workspace_path / "gateway.pid"


# ---------------------------------------------------------------------------
# Server PID
# ---------------------------------------------------------------------------

def write_pid(workspace_path: Path, pid: int | None = None) -> None:
    pid = pid or os.getpid()
    workspace_pid_file(workspace_path).write_text(str(pid), encoding="utf-8")


def read_pid(workspace_path: Path) -> int | None:
    pid_file = workspace_pid_file(workspace_path)
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_pid(workspace_path: Path) -> None:
    try:
        workspace_pid_file(workspace_path).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Gateway PID
# ---------------------------------------------------------------------------

def write_gateway_pid(workspace_path: Path, pid: int) -> None:
    workspace_gateway_pid_file(workspace_path).write_text(str(pid), encoding="utf-8")


def read_gateway_pid(workspace_path: Path) -> int | None:
    pid_file = workspace_gateway_pid_file(workspace_path)
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_gateway_pid(workspace_path: Path) -> None:
    try:
        workspace_gateway_pid_file(workspace_path).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Process utilities
# ---------------------------------------------------------------------------

def is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def kill_process(pid: int) -> bool:
    """Send termination signal. Returns True if the signal was sent."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                check=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# High-level stop helpers
# ---------------------------------------------------------------------------

def stop_server(workspace_path: Path) -> bool:
    """Stop the server for the given workspace. Returns True if stopped."""
    pid = read_pid(workspace_path)
    if pid is None:
        return False
    if not is_running(pid):
        remove_pid(workspace_path)
        return False
    killed = kill_process(pid)
    if killed:
        remove_pid(workspace_path)
    return killed


def stop_gateway(workspace_path: Path) -> bool:
    """Stop the local gateway for the given workspace. Returns True if stopped."""
    pid = read_gateway_pid(workspace_path)
    if pid is None:
        return False
    if not is_running(pid):
        remove_gateway_pid(workspace_path)
        return False
    killed = kill_process(pid)
    if killed:
        remove_gateway_pid(workspace_path)
    return killed
