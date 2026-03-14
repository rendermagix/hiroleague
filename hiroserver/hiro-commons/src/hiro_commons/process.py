"""Shared PID file-based process management utilities.

Design principles:
  - Only the child process writes its own PID (it knows its real PID).
  - The parent never writes the PID — it polls for the PID file to appear.
  - Only stop_process() removes the PID file — the child never deletes it.
  - stderr goes to a log file so crashes are diagnosable.
  - Always spawn via ``uv run --directory`` so the correct venv and all
    workspace packages are guaranteed regardless of sys.executable quirks
    (debugpy, entry-point stubs, etc.).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


_workspace_root_cache: Path | None = None


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (defaults to this file) to find the uv workspace
    root — the directory containing ``pyproject.toml`` with ``[tool.uv.workspace]``.

    Returns None if no workspace root is found.
    The result is cached after the first successful lookup.
    """
    global _workspace_root_cache
    if _workspace_root_cache is not None:
        return _workspace_root_cache

    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        toml = candidate / "pyproject.toml"
        if toml.exists():
            try:
                data = tomllib.loads(toml.read_text(encoding="utf-8"))
                if "workspace" in data.get("tool", {}).get("uv", {}):
                    _workspace_root_cache = candidate
                    return candidate
            except Exception:
                pass
    return None


def uv_python_cmd() -> list[str]:
    """Return the command prefix ``["uv", "run", "--directory", <root>, "python"]``
    that spawns Python inside the uv workspace venv.

    This is the only reliable way to get the correct interpreter + all
    workspace packages, regardless of how the parent process was launched
    (debugpy, entry-point scripts, Task Scheduler, etc.).
    """
    root = find_workspace_root()
    if root is None:
        raise FileNotFoundError(
            "Could not find uv workspace root (pyproject.toml with [tool.uv.workspace])"
        )
    return ["uv", "run", "--directory", str(root), "python"]


def spawn_detached(
    cmd: list[str],
    env: dict[str, str] | None = None,
    stderr_log: Path | None = None,
) -> None:
    """Spawn a fully detached background process.

    The caller should NOT try to use the returned PID — the child writes its
    own PID via write_pid().  Use wait_for_pid() to wait for it.
    """
    effective_env = env if env is not None else dict(os.environ)
    stderr_target = open(stderr_log, "a") if stderr_log else subprocess.DEVNULL  # noqa: SIM115
    if sys.platform == "win32":
        subprocess.Popen(
            cmd,
            env=effective_env,
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            ),
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
        )
    else:
        subprocess.Popen(
            cmd,
            env=effective_env,
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
        )


def wait_for_pid(
    base_path: Path,
    pid_filename: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.15,
) -> int:
    """Wait for a child process to write its PID file and confirm it is alive.

    Raises RuntimeError if the PID file doesn't appear within *timeout*
    seconds or the process is not running when checked.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = read_pid(base_path, pid_filename)
        if pid is not None and is_running(pid):
            return pid
        time.sleep(poll_interval)

    pid = read_pid(base_path, pid_filename)
    if pid is not None and is_running(pid):
        return pid
    raise RuntimeError(
        f"Child process did not start within {timeout}s "
        f"(pid_file={base_path / pid_filename}, last_pid={pid})"
    )


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
                # Suppress the console window that Windows would otherwise flash
                # briefly for each tasklist.exe invocation.
                creationflags=subprocess.CREATE_NO_WINDOW,
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
                creationflags=subprocess.CREATE_NO_WINDOW,
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
