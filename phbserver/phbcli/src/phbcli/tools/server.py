"""Server lifecycle tools: setup, start, stop, status, teardown.

These tools own the logic for managing the phbcli server process and
auto-start registrations.  CLI commands in commands/root.py are thin
wrappers that parse flags, call execute(), and render the result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phb_commons.keys import public_key_to_b64
from phb_commons.process import is_running, read_pid, remove_pid, stop_process, write_pid
from phb_commons.constants.domain import MANDATORY_CHANNEL_NAME
from phb_commons.constants.timing import DEFAULT_PING_INTERVAL_SECONDS
from rich.console import Console

from ..autostart import (
    register_autostart,
    register_autostart_elevated,
    unregister_autostart,
    unregister_autostart_elevated,
)
from ..domain.channel_config import (
    ChannelConfig,
    find_workspace_root,
    load_channel_config,
    save_channel_config,
)
from ..domain.config import Config, load_config, load_state, master_key_path, resolve_log_dir, save_config
from ..domain.crypto import load_or_create_master_key
from ..domain.workspace import (
    WorkspaceError,
    WorkspaceRegistry,
    admin_port_for,
    create_workspace,
    http_port_for,
    load_registry,
    plugin_port_for,
    remove_workspace,
    resolve_workspace,
)
from ..constants import ENV_ADMIN_UI, ENV_WORKSPACE_PATH, PID_FILENAME
from .base import Tool, ToolParam


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SetupResult:
    workspace: str
    workspace_path: str
    device_id: str
    gateway_url: str
    http_port: int
    master_key: str
    desktop_pub: str
    autostart_registered: bool
    autostart_method: str  # "schtasks" | "registry" | "elevated" | "skipped" | "failed"
    server_started: bool


@dataclass
class StartResult:
    workspace: str
    workspace_path: str
    already_running: bool
    pid: int | None
    http_host: str
    http_port: int
    admin_port: int | None = None


@dataclass
class StopResult:
    workspace: str
    was_running: bool
    pid: int | None


@dataclass
class RestartResult:
    workspace: str
    workspace_path: str
    was_running: bool
    pid: int | None
    new_pid: int | None
    http_host: str
    http_port: int
    admin_port: int | None = None


@dataclass
class WorkspaceStatusEntry:
    id: str
    name: str
    is_default: bool
    server_running: bool
    pid: int | None
    ws_connected: bool
    last_connected: str | None
    gateway_url: str | None
    device_id: str
    http_host: str
    http_port: int


@dataclass
class StatusResult:
    workspaces: list[WorkspaceStatusEntry] = field(default_factory=list)


@dataclass
class TeardownResult:
    workspace: str
    workspace_path: str
    server_stopped: bool
    autostart_removed: bool
    purged: bool


@dataclass
class UninstallResult:
    teardown: TeardownResult


# ---------------------------------------------------------------------------
# Server process helpers (absorbed from services/server_control.py)
# ---------------------------------------------------------------------------


def _do_start(
    workspace_path: Path,
    config: Config,
    console: Console,
    *,
    foreground: bool = False,
    admin: bool = False,
) -> None:
    """Start the phbcli server for a workspace."""
    load_or_create_master_key(workspace_path, filename=config.master_key_file)
    _ensure_mandatory_devices_channel(workspace_path, config)

    pid = read_pid(workspace_path, PID_FILENAME)
    if pid and is_running(pid):
        console.print(f"[yellow]Server already running (PID {pid}).[/yellow]")
        return

    if foreground:
        import asyncio as _asyncio

        from phbcli.runtime.server_process import _main

        console.print(
            f"[green]Server starting[/green] in foreground. "
            f"HTTP: http://{config.http_host}:{config.http_port}/status  "
            "[dim](Ctrl+C to stop)[/dim]"
        )
        try:
            _asyncio.run(_main(foreground=True, workspace_path=workspace_path, admin=admin))
        except KeyboardInterrupt:
            pass
        console.print("[green]Server stopped.[/green]")
        return

    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        pythonw = str(Path(python).with_name("pythonw.exe"))
        if Path(pythonw).exists():
            python = pythonw

    script = str(Path(__file__).parents[1] / "runtime" / "server_process.py")
    env = {**os.environ, ENV_WORKSPACE_PATH: str(workspace_path)}
    if admin:
        env[ENV_ADMIN_UI] = "1"

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

    write_pid(workspace_path, PID_FILENAME, proc.pid)
    console.print(
        f"[green]Server started[/green] (PID {proc.pid}). "
        f"HTTP: http://{config.http_host}:{config.http_port}/status"
    )


def _graceful_http_stop(http_port: int, pid: int, workspace_path: Path, timeout: float = 10.0) -> bool:
    """POST /_shutdown to the server and wait for the process to exit.

    Returns True if the process exited gracefully within the timeout.
    This avoids Windows ``taskkill /F`` which bypasses signal handlers and
    orphans channel-plugin subprocesses.
    """
    import time
    import urllib.request

    try:
        url = f"http://127.0.0.1:{http_port}/_shutdown"
        req = urllib.request.Request(url, method="POST", data=b"")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(pid):
            remove_pid(workspace_path, PID_FILENAME)
            return True
        time.sleep(0.5)
    return False


def _do_stop(workspace_path: Path, console: Console) -> None:
    """Stop the server for a workspace."""
    pid = read_pid(workspace_path, PID_FILENAME)
    if pid is None or not is_running(pid):
        console.print("[yellow]Server is not running.[/yellow]")
        remove_pid(workspace_path, PID_FILENAME)
        return

    config = load_config(workspace_path)
    if _graceful_http_stop(config.http_port, pid, workspace_path):
        console.print(f"[green]Server stopped[/green] (was PID {pid}).")
        return

    stopped = stop_process(workspace_path, PID_FILENAME)
    if stopped:
        console.print(f"[green]Server stopped[/green] (was PID {pid}).")
    else:
        console.print("[red]Failed to stop server.[/red]")


# ---------------------------------------------------------------------------
# Bootstrap helper (absorbed from services/bootstrap.py)
# ---------------------------------------------------------------------------


def _ensure_mandatory_devices_channel(workspace_path: Path, config: Config) -> None:
    """Create/update the mandatory `devices` channel config inside the workspace."""
    existing = load_channel_config(workspace_path, MANDATORY_CHANNEL_NAME)
    uv_workspace = find_workspace_root()
    workspace_dir = str(uv_workspace) if uv_workspace else (
        existing.workspace_dir if existing else ""
    )
    channel_cfg = ChannelConfig(
        name=MANDATORY_CHANNEL_NAME,
        enabled=True,
        command=existing.command if existing and existing.command else [f"phb-channel-{MANDATORY_CHANNEL_NAME}"],
        config={
            **(existing.config if existing else {}),
            "gateway_url": config.gateway_url,
            "device_id": config.device_id,
            "master_key_path": str(master_key_path(workspace_path, config)),
            "ping_interval": (existing.config.get("ping_interval", DEFAULT_PING_INTERVAL_SECONDS) if existing else DEFAULT_PING_INTERVAL_SECONDS),
        },
        workspace_dir=workspace_dir,
    )
    save_channel_config(workspace_path, channel_cfg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_or_create(workspace: str | None) -> tuple[Any, WorkspaceRegistry, Path]:
    """Resolve a workspace entry, auto-creating 'default' if none exist."""
    try:
        entry, registry = resolve_workspace(workspace)
        return entry, registry, Path(entry.path)
    except WorkspaceError:
        if workspace is not None:
            raise
        entry, registry = create_workspace("default")
        return entry, registry, Path(entry.path)


def _register_autostart(workspace_id: str, elevated: bool) -> tuple[bool, str]:
    """Register auto-start using workspace id and return (success, method_label)."""
    if elevated and sys.platform == "win32":
        try:
            accepted = register_autostart_elevated(workspace_id)
        except RuntimeError:
            accepted = False
        if accepted:
            return True, "elevated"
    try:
        method = register_autostart(workspace_id)
        return True, str(method)
    except (NotImplementedError, Exception):
        return False, "failed"


def _unregister_autostart(workspace_id: str, stored_method: str | None) -> bool:
    # "elevated" was registered via UAC Task Scheduler (HIGHEST run-level) — needs elevated removal.
    # "schtasks" / "registry" use the standard path which tries both schtasks delete + registry delete.
    # "skipped" / "failed" / None — nothing was registered, nothing to remove.
    if stored_method in (None, "skipped", "failed"):
        return False
    if stored_method == "elevated" and sys.platform == "win32":
        try:
            accepted = unregister_autostart_elevated(workspace_id)
        except RuntimeError:
            accepted = False
        if accepted:
            return True
        # Fall through to standard removal if UAC was declined
    try:
        unregister_autostart(workspace_id)
        return True
    except (NotImplementedError, Exception):
        return False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SetupTool(Tool):
    name = "setup"
    description = (
        "One-time setup: save gateway config, generate device key, "
        "and optionally register auto-start and start the server"
    )
    params = {
        "gateway_url": ToolParam(str, "WebSocket gateway URL, e.g. ws://myhost:8765"),
        "workspace": ToolParam(str, "Workspace name or id to configure", required=False),
        "http_port": ToolParam(int, "Local HTTP server port override", required=False),
        "skip_autostart": ToolParam(bool, "Do not register auto-start", required=False),
        "start_server": ToolParam(
            bool,
            "Start the server after setup completes (default: false)",
            required=False,
        ),
        "elevated_task": ToolParam(
            bool,
            "(Windows) Request UAC elevation for Task Scheduler entry",
            required=False,
        ),
    }

    def execute(
        self,
        gateway_url: str,
        workspace: str | None = None,
        http_port: int | None = None,
        skip_autostart: bool = False,
        start_server: bool = False,
        elevated_task: bool = False,
    ) -> SetupResult:
        entry, registry, workspace_path = _resolve_or_create(workspace)
        existing = load_config(workspace_path)

        effective_http_port = http_port or http_port_for(registry, entry.port_slot)
        effective_plugin_port = plugin_port_for(registry, entry.port_slot)

        config = Config(
            device_id=existing.device_id,
            gateway_url=gateway_url,
            http_host=existing.http_host,
            http_port=effective_http_port,
            plugin_port=effective_plugin_port,
            admin_port=admin_port_for(registry, entry.port_slot),
            master_key_file=existing.master_key_file,
            pairing_code_length=existing.pairing_code_length,
            pairing_code_ttl_seconds=existing.pairing_code_ttl_seconds,
            attestation_expires_days=existing.attestation_expires_days,
        )
        save_config(workspace_path, config)
        private_key = load_or_create_master_key(workspace_path, filename=config.master_key_file)
        public_key_b64 = public_key_to_b64(private_key.public_key())
        _ensure_mandatory_devices_channel(workspace_path, config)

        autostart_registered = False
        autostart_method = "skipped"
        if not skip_autostart:
            # Autostart keyed by workspace id so renames don't break scheduled tasks
            autostart_registered, autostart_method = _register_autostart(
                entry.id, elevated_task
            )

        # Persist the autostart method in config.json so teardown can use it
        # without requiring the user to re-specify --elevated-task.
        config.autostart_method = autostart_method
        save_config(workspace_path, config)

        if start_server:
            _do_start(workspace_path, config, _NullConsole(), foreground=False)

        return SetupResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            device_id=config.device_id,
            gateway_url=config.gateway_url,
            http_port=config.http_port,
            master_key=str(master_key_path(workspace_path, config)),
            desktop_pub=public_key_b64,
            autostart_registered=autostart_registered,
            autostart_method=autostart_method,
            server_started=start_server,
        )


class StartTool(Tool):
    name = "start"
    description = "Start the phbcli server for a workspace (background by default)"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to start", required=False),
        "foreground": ToolParam(
            bool,
            "Run the server in the foreground with live log output",
            required=False,
        ),
        "admin": ToolParam(
            bool,
            "Also start the admin UI on its dedicated port",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        foreground: bool = False,
        admin: bool = False,
    ) -> StartResult:
        entry, registry, workspace_path = _resolve_or_create(workspace)

        if not (workspace_path / "config.json").exists():
            raise ValueError(
                f"Workspace '{entry.name}' is not configured. "
                f"Run 'phbcli setup --workspace {entry.name}' first."
            )

        config = load_config(workspace_path)

        pid = read_pid(workspace_path, PID_FILENAME)
        if pid and is_running(pid):
            return StartResult(
                workspace=entry.name,
                workspace_path=str(workspace_path),
                already_running=True,
                pid=pid,
                http_host=config.http_host,
                http_port=config.http_port,
                admin_port=config.admin_port if admin else None,
            )

        _do_start(workspace_path, config, _NullConsole(), foreground=foreground, admin=admin)

        new_pid = read_pid(workspace_path, PID_FILENAME)
        return StartResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            already_running=False,
            pid=new_pid,
            http_host=config.http_host,
            http_port=config.http_port,
            admin_port=config.admin_port if admin else None,
        )


class StopTool(Tool):
    name = "stop"
    description = "Stop the running phbcli server for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to stop", required=False),
    }

    def execute(self, workspace: str | None = None) -> StopResult:
        entry, _, workspace_path = _resolve_or_create(workspace)

        pid = read_pid(workspace_path, PID_FILENAME)
        was_running = pid is not None and is_running(pid)

        _do_stop(workspace_path, _NullConsole())
        return StopResult(workspace=entry.name, was_running=was_running, pid=pid)


class RestartTool(Tool):
    name = "restart"
    description = "Gracefully restart the phbcli server for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to restart", required=False),
        "foreground": ToolParam(
            bool,
            "Run the restarted server in the foreground with live log output",
            required=False,
        ),
        "admin": ToolParam(
            bool,
            "Also start the admin UI on its dedicated port",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        foreground: bool = False,
        admin: bool = False,
    ) -> RestartResult:
        entry, _, workspace_path = _resolve_or_create(workspace)

        if not (workspace_path / "config.json").exists():
            raise ValueError(
                f"Workspace '{entry.name}' is not configured. "
                f"Run 'phbcli setup --workspace {entry.name}' first."
            )

        config = load_config(workspace_path)
        pid = read_pid(workspace_path, PID_FILENAME)
        was_running = pid is not None and is_running(pid)

        if was_running:
            if os.getpid() == pid:
                from phbcli.runtime.http_server import request_restart

                request_restart(admin=admin)
                return RestartResult(
                    workspace=entry.name,
                    workspace_path=str(workspace_path),
                    was_running=True,
                    pid=pid,
                    new_pid=None,
                    http_host=config.http_host,
                    http_port=config.http_port,
                    admin_port=config.admin_port if admin else None,
                )

            _do_stop(workspace_path, _NullConsole())

        _do_start(workspace_path, config, _NullConsole(), foreground=foreground, admin=admin)

        new_pid = read_pid(workspace_path, PID_FILENAME)
        return RestartResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            was_running=was_running,
            pid=pid,
            new_pid=new_pid,
            http_host=config.http_host,
            http_port=config.http_port,
            admin_port=config.admin_port if admin else None,
        )


class StatusTool(Tool):
    name = "status"
    description = "Show server and WebSocket connection status for one or all workspaces"
    params = {
        "workspace": ToolParam(
            str,
            "Workspace name or id to query (omit to show all workspaces)",
            required=False,
        ),
    }

    def execute(self, workspace: str | None = None) -> StatusResult:
        registry = load_registry()

        if not registry.workspaces:
            return StatusResult(workspaces=[])

        if workspace is not None:
            entry, _ = resolve_workspace(workspace)
            ids = [entry.id]
        else:
            ids = list(registry.workspaces.keys())

        entries = []
        for ws_id in ids:
            ws_entry = registry.workspaces[ws_id]
            ws_path = Path(ws_entry.path)
            pid = read_pid(ws_path, "phbcli.pid")
            running = is_running(pid)
            state = load_state(ws_path)
            config = load_config(ws_path)
            entries.append(
                WorkspaceStatusEntry(
                    id=ws_id,
                    name=ws_entry.name,
                    is_default=ws_id == registry.default_workspace,
                    server_running=running,
                    pid=pid,
                    ws_connected=state.ws_connected,
                    last_connected=state.last_connected,
                    gateway_url=state.gateway_url or config.gateway_url or None,
                    device_id=config.device_id,
                    http_host=config.http_host,
                    http_port=config.http_port,
                )
            )
        return StatusResult(workspaces=entries)


class TeardownTool(Tool):
    name = "teardown"
    description = "Stop server and remove all auto-start registrations for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to tear down", required=False),
        "purge": ToolParam(
            bool,
            "Also delete the workspace folder (config, state, keys, logs…)",
            required=False,
        ),
    }

    def execute(
        self,
        workspace: str | None = None,
        purge: bool = False,
    ) -> TeardownResult:
        entry, registry, workspace_path = _resolve_or_create(workspace)

        _do_stop(workspace_path, _NullConsole())
        # Read the autostart method stored in config.json at setup time — no flag needed from caller.
        stored_config = load_config(workspace_path)
        autostart_removed = _unregister_autostart(entry.id, stored_config.autostart_method)

        if purge:
            if workspace_path.exists():
                shutil.rmtree(workspace_path, ignore_errors=True)
            try:
                remove_workspace(entry.id, purge=False)
            except WorkspaceError:
                pass

        return TeardownResult(
            workspace=entry.name,
            workspace_path=str(workspace_path),
            server_stopped=True,
            autostart_removed=autostart_removed,
            purged=purge,
        )


class UninstallTool(Tool):
    name = "uninstall"
    description = "Stop server, remove auto-start, and return package uninstall instructions"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to uninstall", required=False),
        "purge": ToolParam(bool, "Also delete the workspace folder", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        purge: bool = False,
    ) -> UninstallResult:
        teardown_result = TeardownTool().execute(
            workspace=workspace,
            purge=purge,
        )
        return UninstallResult(teardown=teardown_result)


# ---------------------------------------------------------------------------
# Internal: null console for _do_start / _do_stop (output handled by CLI layer)
# ---------------------------------------------------------------------------


class _NullConsole:
    """Drop-in for rich.Console that discards all output."""

    def print(self, *args: object, **kwargs: object) -> None:  # noqa: A003
        pass
