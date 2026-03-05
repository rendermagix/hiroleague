"""Root CLI command registrations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from phb_commons.keys import public_key_to_b64
from phb_commons.process import is_running, read_pid

from ..config import Config, load_config, load_state, master_key_path, save_config
from ..crypto import load_or_create_master_key
from ..services.autostart_feedback import (
    register_autostart_with_feedback,
    unregister_autostart_with_feedback,
)
from ..services.bootstrap import ensure_mandatory_devices_channel
from ..services.server_control import do_start, do_stop
from ..workspace import (
    WorkspaceError,
    WorkspaceRegistry,
    create_workspace,
    http_port_for,
    load_registry,
    plugin_port_for,
    resolve_workspace,
)


def _resolve_or_create_default(
    workspace: str | None,
    console: Console,
) -> tuple[object, WorkspaceRegistry, Path]:
    """Resolve a workspace entry and return (entry, registry, workspace_path).

    If no workspaces exist and workspace is None, auto-creates 'default'.
    Calls typer.Exit(1) on unresolvable errors.
    """
    try:
        entry, registry = resolve_workspace(workspace)
        return entry, registry, Path(entry.path)
    except WorkspaceError:
        if workspace is not None:
            # Caller asked for a specific workspace that does not exist.
            console.print(
                f"[red]Workspace '{workspace}' not found. "
                "Run [bold]phbcli workspace list[/bold] to see available workspaces.[/red]"
            )
            raise typer.Exit(1)

        # No workspaces at all — auto-create 'default'.
        console.print(
            "[dim]No workspaces found. Creating workspace '[bold]default[/bold]'…[/dim]"
        )
        try:
            entry, registry = create_workspace("default")
        except WorkspaceError as exc:
            console.print(f"[red]Failed to create default workspace: {exc}[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]Workspace 'default' created[/green] at {entry.path}"
        )
        return entry, registry, Path(entry.path)


def register(app: typer.Typer, console: Console) -> None:
    """Register root-level commands on the provided app."""

    @app.command()
    def setup(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace name to configure (default: registry default).",
        ),
        gateway_url: Optional[str] = typer.Option(
            None, "--gateway-url", "-g",
            help="WebSocket gateway URL (e.g. ws://myhost:8765)",
        ),
        http_port: Optional[int] = typer.Option(
            None, "--port", "-p", help="Local HTTP server port (default: from workspace slot)"
        ),
        skip_autostart: bool = typer.Option(
            False, "--skip-autostart", help="Do not register auto-start"
        ),
        elevated_task: bool = typer.Option(
            False, "--elevated-task",
            help="(Windows) Request UAC elevation to create a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """One-time setup: configure gateway, generate device ID, register auto-start."""
        console.print("[bold cyan]phbcli setup[/bold cyan]")

        entry, registry, workspace_path = _resolve_or_create_default(workspace, console)

        existing = load_config(workspace_path)

        effective_gateway_url = gateway_url
        if effective_gateway_url is None:
            default_gw = existing.gateway_url
            effective_gateway_url = typer.prompt(
                "Gateway WebSocket URL",
                default=default_gw,
            )

        effective_http_port = http_port or http_port_for(registry, entry.port_slot)
        effective_plugin_port = plugin_port_for(registry, entry.port_slot)

        config = Config(
            device_id=existing.device_id,
            gateway_url=effective_gateway_url,
            http_host=existing.http_host,
            http_port=effective_http_port,
            plugin_port=effective_plugin_port,
            master_key_file=existing.master_key_file,
            pairing_code_length=existing.pairing_code_length,
            pairing_code_ttl_seconds=existing.pairing_code_ttl_seconds,
            attestation_expires_days=existing.attestation_expires_days,
        )
        save_config(workspace_path, config)
        private_key = load_or_create_master_key(workspace_path, filename=config.master_key_file)
        public_key_b64 = public_key_to_b64(private_key.public_key())
        ensure_mandatory_devices_channel(workspace_path, config)

        console.print(f"[green]Config saved to[/green] {workspace_path / 'config.json'}")
        console.print(f"  workspace  : [bold]{entry.name}[/bold]")
        console.print(f"  device_id  : [bold]{config.device_id}[/bold]")
        console.print(f"  gateway_url: [bold]{config.gateway_url}[/bold]")
        console.print(f"  http_port  : [bold]{config.http_port}[/bold]")
        console.print(f"  master_key : [bold]{master_key_path(workspace_path, config)}[/bold]")
        console.print(f"  desktop_pub: [bold]{public_key_b64}[/bold]")
        console.print("  channel    : [bold]devices[/bold] (mandatory)")

        if not skip_autostart:
            register_autostart_with_feedback(console, entry.name, elevated=elevated_task)

        console.print("\nStarting server…")
        do_start(workspace_path, entry, registry, config, console, foreground=False)

    @app.command()
    def start(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to start (default: registry default).",
        ),
        foreground: bool = typer.Option(
            False, "--foreground", "-f",
            help=(
                "Run the server in the foreground with live log output. "
                "Press Ctrl+C to stop."
            ),
        ),
    ) -> None:
        """Start the phbcli server (background by default, foreground with -f)."""
        entry, registry, workspace_path = _resolve_or_create_default(workspace, console)

        if not (workspace_path / "config.json").exists():
            console.print(
                "[red]Workspace not configured. "
                f"Run [bold]phbcli setup --workspace {entry.name}[/bold] first.[/red]"
            )
            raise typer.Exit(1)

        config = load_config(workspace_path)
        do_start(workspace_path, entry, registry, config, console, foreground=foreground)

    @app.command()
    def stop(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to stop (default: registry default).",
        ),
    ) -> None:
        """Stop the running phbcli server."""
        entry, registry, workspace_path = _resolve_or_create_default(workspace, console)
        do_stop(workspace_path, entry, console)

    @app.command()
    def status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to query (omit to show all workspaces).",
        ),
    ) -> None:
        """Show server and WebSocket connection status."""
        registry = load_registry()

        if not registry.workspaces:
            console.print("[dim]No workspaces configured.[/dim]")
            return

        # If --workspace is given, show just that one in detail.
        if workspace is not None:
            if workspace not in registry.workspaces:
                console.print(f"[red]Workspace '{workspace}' not found.[/red]")
                raise typer.Exit(1)
            _print_workspace_status(console, registry, workspace)
            return

        # No --workspace: show a summary of all workspaces.
        if len(registry.workspaces) == 1:
            only = next(iter(registry.workspaces))
            _print_workspace_status(console, registry, only)
        else:
            for name in registry.workspaces:
                _print_workspace_status(console, registry, name)
                console.print()

    @app.command()
    def teardown(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to tear down (default: registry default).",
        ),
        purge: bool = typer.Option(
            False, "--purge",
            help="Also delete the workspace folder (config, state, keys, logs…).",
        ),
        elevated_task: bool = typer.Option(
            False, "--elevated-task",
            help="(Windows) Request UAC elevation to delete a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """Stop server and remove all auto-start registrations for a workspace."""
        console.print("[bold cyan]phbcli teardown[/bold cyan]")

        try:
            entry, registry, workspace_path = _resolve_or_create_default(workspace, console)
        except SystemExit:
            return

        do_stop(workspace_path, entry, console)
        unregister_autostart_with_feedback(console, entry.name, elevated=elevated_task)

        if purge:
            import shutil as _shutil
            if workspace_path.exists():
                _shutil.rmtree(workspace_path, ignore_errors=True)
                console.print(f"[green]Workspace folder removed:[/green] {workspace_path}")

            # Also remove from registry.
            from ..workspace import remove_workspace
            try:
                remove_workspace(entry.name, purge=False)
                console.print(f"[green]Workspace '{entry.name}' removed from registry.[/green]")
            except WorkspaceError:
                pass

        console.print("\n[green]Teardown complete.[/green]")

    @app.command()
    def uninstall(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to uninstall (default: registry default).",
        ),
        purge: bool = typer.Option(False, "--purge", help="Also delete the workspace folder."),
        elevated_task: bool = typer.Option(
            False, "--elevated-task",
            help="(Windows) Request UAC elevation to delete a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """Stop server, remove auto-start, then print package uninstall commands."""
        import click
        ctx = click.get_current_context()
        ctx.invoke(teardown, workspace=workspace, purge=purge, elevated_task=elevated_task)

        console.print(
            "\n[bold]To fully remove phbcli, run one of:[/bold]\n"
            "  [cyan]uv tool uninstall phbcli[/cyan]       (if installed via uv tool)\n"
            "  [cyan]pip uninstall phbcli[/cyan]            (if installed via pip)\n"
        )


def _print_workspace_status(
    console: Console,
    registry: WorkspaceRegistry,
    name: str,
) -> None:
    entry = registry.workspaces[name]
    workspace_path = Path(entry.path)
    pid = read_pid(workspace_path, "phbcli.pid")
    running = is_running(pid)
    state = load_state(workspace_path)
    config = load_config(workspace_path)

    title = f"phbcli status — {name}"
    if name == registry.default_workspace:
        title += " [cyan](default)[/cyan]"

    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Server running", "[green]yes[/green]" if running else "[red]no[/red]")
    table.add_row("PID", str(pid) if pid else "—")
    table.add_row(
        "WS connected",
        "[green]yes[/green]" if state.ws_connected else "[red]no[/red]",
    )
    table.add_row("Last connected", state.last_connected or "—")
    table.add_row("Gateway URL", state.gateway_url or config.gateway_url or "—")
    table.add_row("Device ID", config.device_id)
    table.add_row(
        "HTTP API",
        f"http://{config.http_host}:{config.http_port}/status" if running else "—",
    )

    console.print(table)
