"""Shared auto-start registration helpers for PHB executables."""

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


def _task_name(entry_name_prefix: str, target_name: str) -> str:
    return f"{entry_name_prefix}-{target_name}"


def _reg_run_key(entry_name_prefix: str, target_name: str) -> str:
    return f"{entry_name_prefix}-{target_name}"


def _resolve_executable(executable_name: str) -> str:
    exe = shutil.which(executable_name)
    if exe is None:
        raise RuntimeError(
            f"{executable_name} executable not found on PATH. "
            f"Make sure it is installed (e.g. via 'uv tool install {executable_name}')."
        )
    return exe


def _command_line(exe: str, launch_args: list[str]) -> str:
    return subprocess.list2cmdline([exe, *launch_args])


def _schtasks_create(task_name: str, command_line: str, run_level: str = "LIMITED") -> bool:
    cmd = [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        command_line,
        "/SC",
        "ONLOGON",
        "/RL",
        run_level,
        "/F",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def _schtasks_delete(task_name: str) -> bool:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 or "does not exist" in result.stderr.lower()


def _registry_create(reg_key: str, command_line: str) -> None:
    with winreg.OpenKey(  # type: ignore[union-attr]
        winreg.HKEY_CURRENT_USER,  # type: ignore[union-attr]
        REG_RUN_PATH,
        0,
        winreg.KEY_SET_VALUE,  # type: ignore[union-attr]
    ) as key:
        winreg.SetValueEx(  # type: ignore[union-attr]
            key,
            reg_key,
            0,
            winreg.REG_SZ,  # type: ignore[union-attr]
            command_line,
        )


def _registry_delete(reg_key: str) -> None:
    try:
        with winreg.OpenKey(  # type: ignore[union-attr]
            winreg.HKEY_CURRENT_USER,  # type: ignore[union-attr]
            REG_RUN_PATH,
            0,
            winreg.KEY_SET_VALUE,  # type: ignore[union-attr]
        ) as key:
            winreg.DeleteValue(key, reg_key)  # type: ignore[union-attr]
    except FileNotFoundError:
        pass


def _elevate_schtasks_create(task_name: str, command_line: str) -> bool:
    tr = command_line.replace('"', '\\"')
    args = (
        f'/Create /TN "{task_name}" '
        f'/TR "{tr}" '
        "/SC ONLOGON /RL HIGHEST /F"
    )
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "schtasks", args, None, 1)
    return int(ret) > 32


def _elevate_schtasks_delete(task_name: str) -> bool:
    args = f'/Delete /TN "{task_name}" /F'
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "schtasks", args, None, 1)
    return int(ret) > 32


def _register_windows(task_name: str, reg_key: str, command_line: str) -> AutostartMethod:
    if _schtasks_create(task_name, command_line, run_level="LIMITED"):
        return "schtasks"
    _registry_create(reg_key, command_line)
    return "registry"


def _unregister_windows(task_name: str, reg_key: str) -> None:
    _schtasks_delete(task_name)
    _registry_delete(reg_key)


def register_autostart(
    target_name: str,
    *,
    entry_name_prefix: str,
    executable_name: str,
    launch_args: list[str],
) -> AutostartMethod:
    exe = _resolve_executable(executable_name)
    task_name = _task_name(entry_name_prefix, target_name)
    reg_key = _reg_run_key(entry_name_prefix, target_name)
    command_line = _command_line(exe, launch_args)
    if sys.platform == "win32":
        return _register_windows(task_name, reg_key, command_line)
    if sys.platform == "darwin":
        raise NotImplementedError("macOS launchd auto-start is not yet implemented.")
    raise NotImplementedError("Linux systemd auto-start is not yet implemented.")


def register_autostart_elevated(
    target_name: str,
    *,
    entry_name_prefix: str,
    executable_name: str,
    launch_args: list[str],
) -> bool:
    if sys.platform != "win32":
        raise RuntimeError("Elevated auto-start is only supported on Windows.")
    exe = _resolve_executable(executable_name)
    task_name = _task_name(entry_name_prefix, target_name)
    command_line = _command_line(exe, launch_args)
    return _elevate_schtasks_create(task_name, command_line)


def unregister_autostart(target_name: str, *, entry_name_prefix: str) -> None:
    task_name = _task_name(entry_name_prefix, target_name)
    reg_key = _reg_run_key(entry_name_prefix, target_name)
    if sys.platform == "win32":
        _unregister_windows(task_name, reg_key)
    elif sys.platform == "darwin":
        raise NotImplementedError("macOS launchd auto-start is not yet implemented.")
    else:
        raise NotImplementedError("Linux systemd auto-start is not yet implemented.")


def unregister_autostart_elevated(target_name: str, *, entry_name_prefix: str) -> bool:
    if sys.platform != "win32":
        raise RuntimeError("Elevated teardown is only supported on Windows.")
    task_name = _task_name(entry_name_prefix, target_name)
    reg_key = _reg_run_key(entry_name_prefix, target_name)
    accepted = _elevate_schtasks_delete(task_name)
    if accepted:
        _registry_delete(reg_key)
    return accepted
