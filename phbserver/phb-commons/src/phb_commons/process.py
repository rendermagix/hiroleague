"""Shared PID file-based process management utilities."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def pid_file(base_path: Path, pid_filename: str) -> Path:
    return base_path / pid_filename


def channel_pid_file(
    base_path: Path, channel_name: str, channels_dir: str = "channels"
) -> Path:
    return base_path / channels_dir / f"{channel_name}.pid"


def write_pid(base_path: Path, pid_filename: str, pid: int | None = None) -> None:
    pid = pid or os.getpid()
    pid_file(base_path, pid_filename).write_text(str(pid), encoding="utf-8")


def read_pid(base_path: Path, pid_filename: str) -> int | None:
    target = pid_file(base_path, pid_filename)
    if not target.exists():
        return None
    try:
        return int(target.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_pid(base_path: Path, pid_filename: str) -> None:
    try:
        pid_file(base_path, pid_filename).unlink(missing_ok=True)
    except OSError:
        pass


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


def write_channel_pid(
    base_path: Path, channel_name: str, pid: int, channels_dir: str = "channels"
) -> None:
    target = channel_pid_file(base_path, channel_name, channels_dir=channels_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(pid), encoding="utf-8")


def read_channel_pid(
    base_path: Path, channel_name: str, channels_dir: str = "channels"
) -> int | None:
    target = channel_pid_file(base_path, channel_name, channels_dir=channels_dir)
    if not target.exists():
        return None
    try:
        return int(target.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_channel_pid(
    base_path: Path, channel_name: str, channels_dir: str = "channels"
) -> None:
    try:
        channel_pid_file(base_path, channel_name, channels_dir=channels_dir).unlink(
            missing_ok=True
        )
    except OSError:
        pass


def stop_process(base_path: Path, pid_filename: str) -> bool:
    pid = read_pid(base_path, pid_filename)
    if pid is None:
        return False
    if not is_running(pid):
        remove_pid(base_path, pid_filename)
        return False
    killed = kill_process(pid)
    if killed:
        remove_pid(base_path, pid_filename)
    return killed
