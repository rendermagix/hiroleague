"""Server start helpers used by root CLI commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console

from ..config import APP_DIR, Config
from ..crypto import load_or_create_master_key
from ..process import is_running, read_pid, write_pid
from .bootstrap import ensure_mandatory_devices_channel


def do_start(config: Config, console: Console, *, foreground: bool = False) -> None:
    """Start server either in foreground or as detached process."""
    load_or_create_master_key(APP_DIR, filename=config.master_key_file)
    ensure_mandatory_devices_channel(config)
    pid = read_pid()
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
            _asyncio.run(_main(foreground=True))
        except KeyboardInterrupt:
            pass
        console.print("[green]Server stopped.[/green]")
        return

    # Spawn a detached child process that runs the server loop.
    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        pythonw = str(Path(python).with_name("pythonw.exe"))
        if Path(pythonw).exists():
            python = pythonw
    script = str(Path(__file__).parents[1] / "_server_process.py")
    if sys.platform == "win32":
        proc = subprocess.Popen(
            [python, script],
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
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    write_pid(proc.pid)
    console.print(
        f"[green]Server started[/green] (PID {proc.pid}). "
        f"HTTP: http://{config.http_host}:{config.http_port}/status"
    )
