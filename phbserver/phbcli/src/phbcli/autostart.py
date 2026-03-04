"""Auto-start registration for phbcli — workspace-aware.

Each workspace gets its own task/registry entry so that multiple workspaces
can independently auto-start at login.

Entry names:
  Task Scheduler task:  phbcli-<workspace_name>
  Registry Run key:     phbcli-<workspace_name>

Windows strategy (in order):
  1. schtasks /Create /SC ONLOGON /RL LIMITED  — preferred; user-scoped task.
     If this fails (Access Denied on some Win10/11 configs) →
  2. Registry HKCU\\...\\Run key — always works, no elevation required.

Stubs for macOS (launchd) and Linux (systemd) are provided for future use.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from typing import Literal

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore[assignment]

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

AutostartMethod = Literal["schtasks", "registry", "none"]


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

def _task_name(workspace_name: str) -> str:
    return f"phbcli-{workspace_name}"


def _reg_run_key(workspace_name: str) -> str:
    return f"phbcli-{workspace_name}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _phbcli_executable() -> str:
    """Resolve the full path to the phbcli executable."""
    exe = shutil.which("phbcli")
    if exe is None:
        raise RuntimeError(
            "phbcli executable not found on PATH. "
            "Make sure it is installed (e.g. via 'uv tool install phbcli')."
        )
    return exe


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Windows — Task Scheduler
# ---------------------------------------------------------------------------

def _schtasks_create(exe: str, workspace_name: str, run_level: str = "LIMITED") -> bool:
    task = _task_name(workspace_name)
    cmd = [
        "schtasks", "/Create",
        "/TN", task,
        "/TR", f'"{exe}" start --workspace {workspace_name}',
        "/SC", "ONLOGON",
        "/RL", run_level,
        "/F",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def _schtasks_delete(workspace_name: str) -> bool:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", _task_name(workspace_name), "/F"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 or "does not exist" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Windows — Registry Run key
# ---------------------------------------------------------------------------

def _registry_create(exe: str, workspace_name: str) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        REG_RUN_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(
            key,
            _reg_run_key(workspace_name),
            0,
            winreg.REG_SZ,
            f'"{exe}" start --workspace {workspace_name}',
        )


def _registry_delete(workspace_name: str) -> None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REG_RUN_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, _reg_run_key(workspace_name))
    except FileNotFoundError:
        pass


def _registry_exists(workspace_name: str) -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, _reg_run_key(workspace_name))
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Windows — UAC-elevated schtasks
# ---------------------------------------------------------------------------

def _elevate_schtasks_create(exe: str, workspace_name: str) -> bool:
    task = _task_name(workspace_name)
    args = (
        f'/Create /TN "{task}" '
        f'/TR "\\"{exe}\\" start --workspace {workspace_name}" '
        f"/SC ONLOGON /RL HIGHEST /F"
    )
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "schtasks", args, None, 1)
    return int(ret) > 32


def _elevate_schtasks_delete(workspace_name: str) -> bool:
    args = f'/Delete /TN "{_task_name(workspace_name)}" /F'
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "schtasks", args, None, 1)
    return int(ret) > 32


# ---------------------------------------------------------------------------
# Windows — main register/unregister with fallback chain
# ---------------------------------------------------------------------------

def _register_windows(exe: str, workspace_name: str) -> AutostartMethod:
    if _schtasks_create(exe, workspace_name, run_level="LIMITED"):
        return "schtasks"
    _registry_create(exe, workspace_name)
    return "registry"


def _unregister_windows(workspace_name: str) -> None:
    _schtasks_delete(workspace_name)
    _registry_delete(workspace_name)


# ---------------------------------------------------------------------------
# macOS (stub)
# ---------------------------------------------------------------------------

def _register_macos(_exe: str, _workspace_name: str) -> AutostartMethod:
    raise NotImplementedError("macOS launchd auto-start is not yet implemented.")


def _unregister_macos(_workspace_name: str) -> None:
    raise NotImplementedError("macOS launchd auto-start is not yet implemented.")


# ---------------------------------------------------------------------------
# Linux (stub)
# ---------------------------------------------------------------------------

def _register_linux(_exe: str, _workspace_name: str) -> AutostartMethod:
    raise NotImplementedError("Linux systemd auto-start is not yet implemented.")


def _unregister_linux(_workspace_name: str) -> None:
    raise NotImplementedError("Linux systemd auto-start is not yet implemented.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_autostart(workspace_name: str) -> AutostartMethod:
    """Register phbcli to start automatically on user login for the given workspace."""
    exe = _phbcli_executable()
    if sys.platform == "win32":
        return _register_windows(exe, workspace_name)
    elif sys.platform == "darwin":
        return _register_macos(exe, workspace_name)
    else:
        return _register_linux(exe, workspace_name)


def register_autostart_elevated(workspace_name: str) -> bool:
    """Windows only: register a /RL HIGHEST task via UAC prompt."""
    if sys.platform != "win32":
        raise RuntimeError("Elevated auto-start is only supported on Windows.")
    exe = _phbcli_executable()
    return _elevate_schtasks_create(exe, workspace_name)


def unregister_autostart(workspace_name: str) -> None:
    """Remove auto-start registrations for the given workspace."""
    if sys.platform == "win32":
        _unregister_windows(workspace_name)
    elif sys.platform == "darwin":
        _unregister_macos(workspace_name)
    else:
        _unregister_linux(workspace_name)


def unregister_autostart_elevated(workspace_name: str) -> bool:
    """Windows only: delete the Task Scheduler task via UAC prompt."""
    if sys.platform != "win32":
        raise RuntimeError("Elevated teardown is only supported on Windows.")
    accepted = _elevate_schtasks_delete(workspace_name)
    if accepted:
        _registry_delete(workspace_name)
    return accepted
