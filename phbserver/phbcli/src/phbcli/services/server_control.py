"""Server start/stop helpers used by root CLI commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from phb_commons.process import is_running, read_pid, remove_pid, stop_process, write_pid
from rich.console import Console

from ..config import Config
from ..crypto import load_or_create_master_key
from ..workspace import WorkspaceEntry, WorkspaceRegistry
from .bootstrap import ensure_mandatory_devices_channel

PHBCLI_PID_FILENAME = "phbcli.pid"


def do_start(
    workspace_path: Path,
    _entry: WorkspaceEntry,
    _registry: WorkspaceRegistry,
    config: Config,
    console: Console,
    *,
    foreground: bool = False,
) -> None:
    """Start the phbcli server for a workspace."""
    load_or_create_master_key(workspace_path, filename=config.master_key_file)
    ensure_mandatory_devices_channel(workspace_path, config)

    pid = read_pid(workspace_path, PHBCLI_PID_FILENAME)
    if pid and is_running(pid):
        console.print(f"[yellow]Server already running (PID {pid}).[/yellow]")
        return

    if foreground:
        import asyncio as _asyncio

        from phbcli._server_process import _main

        console.print(
            f"[green]Server starting[/green] in foreground. "
            f"HTTP: http://{config.http_host}:{config.http_port}/status  "
            "[dim](Ctrl+C to stop)[/dim]"
        )
        try:
            _asyncio.run(_main(foreground=True, workspace_path=workspace_path))
        except KeyboardInterrupt:
            pass
        console.print("[green]Server stopped.[/green]")
        return

    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        pythonw = str(Path(python).with_name("pythonw.exe"))
        if Path(pythonw).exists():
            python = pythonw

    script = str(Path(__file__).parents[1] / "_server_process.py")
    env = {**os.environ, "PHB_WORKSPACE_PATH": str(workspace_path)}

    if sys.platform == "win32":
        proc = subprocess.Popen(
            [python, script],
            env=env,
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            ),
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            [python, script],
            env=env,
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    write_pid(workspace_path, PHBCLI_PID_FILENAME, proc.pid)
    console.print(
        f"[green]Server started[/green] (PID {proc.pid}). "
        f"HTTP: http://{config.http_host}:{config.http_port}/status"
    )

def do_stop(
    workspace_path: Path,
    _entry: WorkspaceEntry,
    console: Console,
) -> None:
    """Stop the server for a workspace."""
    pid = read_pid(workspace_path, PHBCLI_PID_FILENAME)
    if pid is None or not is_running(pid):
        console.print("[yellow]Server is not running.[/yellow]")
        remove_pid(workspace_path, PHBCLI_PID_FILENAME)
    else:
        stopped = _stop_server_process(workspace_path)
        if stopped:
            console.print(f"[green]Server stopped[/green] (was PID {pid}).")
        else:
            console.print("[red]Failed to stop server.[/red]")

def _stop_server_process(workspace_path: Path) -> bool:
    return stop_process(workspace_path, PHBCLI_PID_FILENAME)
