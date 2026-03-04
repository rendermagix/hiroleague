"""Server start/stop helpers used by root CLI commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from ..config import Config
from ..crypto import load_or_create_master_key
from ..process import (
    is_running,
    read_gateway_pid,
    read_pid,
    remove_gateway_pid,
    stop_gateway,  # used in _stop_local_gateway
    write_gateway_pid,
    write_pid,
)
from ..workspace import WorkspaceEntry, WorkspaceRegistry, gateway_port_for
from .bootstrap import ensure_mandatory_devices_channel


def do_start(
    workspace_path: Path,
    entry: WorkspaceEntry,
    registry: WorkspaceRegistry,
    config: Config,
    console: Console,
    *,
    foreground: bool = False,
) -> None:
    """Start the phbcli server (and optionally a local gateway) for a workspace."""
    load_or_create_master_key(workspace_path, filename=config.master_key_file)
    ensure_mandatory_devices_channel(workspace_path, config)

    pid = read_pid(workspace_path)
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

    write_pid(workspace_path, proc.pid)
    console.print(
        f"[green]Server started[/green] (PID {proc.pid}). "
        f"HTTP: http://{config.http_host}:{config.http_port}/status"
    )

    if entry.local_gateway:
        _start_local_gateway(workspace_path, entry, registry, console)


def do_stop(
    workspace_path: Path,
    entry: WorkspaceEntry,
    console: Console,
) -> None:
    """Stop the server (and local gateway if managed) for a workspace."""
    pid = read_pid(workspace_path)
    if pid is None or not is_running(pid):
        console.print("[yellow]Server is not running.[/yellow]")
        from ..process import remove_pid
        remove_pid(workspace_path)
    else:
        stopped = _stop_server_process(workspace_path)
        if stopped:
            console.print(f"[green]Server stopped[/green] (was PID {pid}).")
        else:
            console.print("[red]Failed to stop server.[/red]")

    if entry.local_gateway:
        _stop_local_gateway(workspace_path, console)


def _stop_server_process(workspace_path: Path) -> bool:
    from ..process import stop_server
    return stop_server(workspace_path)


def _start_local_gateway(
    workspace_path: Path,
    entry: WorkspaceEntry,
    registry: WorkspaceRegistry,
    console: Console,
) -> None:
    """Spawn a local phbgateway process for this workspace."""
    gw_pid = read_gateway_pid(workspace_path)
    if gw_pid and is_running(gw_pid):
        console.print(f"[yellow]Gateway already running (PID {gw_pid}).[/yellow]")
        return

    gw_exe = shutil.which("phbgateway")
    if not gw_exe:
        console.print(
            "[red]phbgateway not found on PATH. Cannot start local gateway.[/red]\n"
            "[dim]Install it with: uv tool install phbgateway[/dim]"
        )
        return

    gw_port = gateway_port_for(registry, entry.port_slot)
    log_dir = workspace_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        gw_exe,
        "--port", str(gw_port),
        "--state-dir", str(workspace_path),
        "--log-dir", str(log_dir),
    ]

    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
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
            cmd,
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    write_gateway_pid(workspace_path, proc.pid)
    console.print(
        f"[green]Gateway started[/green] (PID {proc.pid}) "
        f"on ws://localhost:{gw_port}"
    )


def _stop_local_gateway(workspace_path: Path, console: Console) -> None:
    gw_pid = read_gateway_pid(workspace_path)
    if gw_pid is None or not is_running(gw_pid):
        console.print("[dim]Gateway was not running.[/dim]")
        remove_gateway_pid(workspace_path)
        return

    stopped = stop_gateway(workspace_path)
    if stopped:
        console.print(f"[green]Gateway stopped[/green] (was PID {gw_pid}).")
    else:
        console.print("[red]Failed to stop gateway.[/red]")
