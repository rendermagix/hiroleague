"""Root CLI command registrations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..tools.server import (
    RestartTool,
    SetupTool,
    StartTool,
    StatusTool,
    StopTool,
    TeardownTool,
    UninstallTool,
)
from ..domain.workspace import WorkspaceError


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
        start_server: bool = typer.Option(
            False, "--start-server",
            help="Start the server immediately after setup completes.",
        ),
        elevated_task: bool = typer.Option(
            False, "--elevated-task",
            help="(Windows) Request UAC elevation to create a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """One-time setup: configure gateway, generate device ID, register auto-start."""
        console.print("[bold cyan]phbcli setup[/bold cyan]")

        from ..domain.workspace import WorkspaceError as _WE, resolve_workspace as _resolve
        from ..domain.config import load_config as _load_config

        try:
            entry, _ = _resolve(workspace)
            existing = _load_config(Path(entry.path))
            default_gw = existing.gateway_url
        except _WE:
            default_gw = "ws://localhost:8765"

        effective_gateway_url = gateway_url
        if effective_gateway_url is None:
            effective_gateway_url = typer.prompt(
                "Gateway WebSocket URL",
                default=default_gw,
            )

        try:
            result = SetupTool().execute(
                gateway_url=effective_gateway_url,
                workspace=workspace,
                http_port=http_port,
                skip_autostart=skip_autostart,
                start_server=start_server,
                elevated_task=elevated_task,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Config saved to[/green] {result.workspace_path}/config.json")
        console.print(f"  workspace  : [bold]{result.workspace}[/bold]")
        console.print(f"  device_id  : [bold]{result.device_id}[/bold]")
        console.print(f"  gateway_url: [bold]{result.gateway_url}[/bold]")
        console.print(f"  http_port  : [bold]{result.http_port}[/bold]")
        console.print(f"  master_key : [bold]{result.master_key}[/bold]")
        console.print(f"  desktop_pub: [bold]{result.desktop_pub}[/bold]")
        console.print("  channel    : [bold]devices[/bold] (mandatory)")

        if result.autostart_registered:
            method = result.autostart_method
            if method == "elevated":
                console.print(
                    "[green]Auto-start registered[/green] via Task Scheduler "
                    "(elevated, run-level: HIGHEST)."
                )
            elif method == "schtasks":
                console.print(
                    "[green]Auto-start registered[/green] via Task Scheduler "
                    "(run-level: LIMITED, no elevation needed)."
                )
            elif method == "registry":
                console.print(
                    "[green]Auto-start registered[/green] via Registry Run key "
                    "[dim](Task Scheduler was unavailable — registry fallback used)[/dim]."
                )
        elif result.autostart_method == "failed":
            console.print("[yellow]Auto-start registration failed.[/yellow]")

        if result.server_started:
            console.print("\n[green]Server started.[/green]")
        else:
            console.print(
                f"\nRun [bold]phbcli start --workspace {result.workspace}[/bold] to start the server."
            )

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
        admin: bool = typer.Option(
            False, "--admin",
            help="Also start the admin UI on its dedicated port (localhost only).",
        ),
    ) -> None:
        """Start the phbcli server (background by default, foreground with -f)."""
        try:
            result = StartTool().execute(workspace=workspace, foreground=foreground, admin=admin)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.already_running:
            console.print(f"[yellow]Server already running (PID {result.pid}).[/yellow]")
        else:
            console.print(
                f"[green]Server started[/green] (PID {result.pid}). "
                f"HTTP: http://{result.http_host}:{result.http_port}/status"
            )
            if result.admin_port:
                console.print(
                    f"  Admin UI: [cyan]http://127.0.0.1:{result.admin_port}[/cyan]"
                )

    @app.command()
    def stop(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to stop (default: registry default).",
        ),
    ) -> None:
        """Stop the running phbcli server."""
        try:
            result = StopTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.was_running:
            console.print(f"[green]Server stopped[/green] (was PID {result.pid}).")
        else:
            console.print("[yellow]Server is not running.[/yellow]")

    @app.command()
    def restart(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to restart (default: registry default).",
        ),
        foreground: bool = typer.Option(
            False, "--foreground", "-f",
            help=(
                "Run the restarted server in the foreground with live log output. "
                "Press Ctrl+C to stop."
            ),
        ),
        admin: bool = typer.Option(
            False, "--admin",
            help="Also start the admin UI on its dedicated port (localhost only).",
        ),
    ) -> None:
        """Gracefully restart the phbcli server (stop + start)."""
        try:
            result = RestartTool().execute(
                workspace=workspace, foreground=foreground, admin=admin,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.was_running:
            console.print(
                f"[green]Server restarted[/green] "
                f"(was PID {result.pid}, now PID {result.new_pid})."
            )
        else:
            console.print(
                f"[green]Server started[/green] (was not running, PID {result.new_pid})."
            )
        console.print(
            f"  HTTP: http://{result.http_host}:{result.http_port}/status"
        )
        if result.admin_port:
            console.print(
                f"  Admin UI: [cyan]http://127.0.0.1:{result.admin_port}[/cyan]"
            )

    @app.command()
    def status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to query (omit to show all workspaces).",
        ),
    ) -> None:
        """Show server and WebSocket connection status."""
        try:
            result = StatusTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.workspaces:
            console.print("[dim]No workspaces configured.[/dim]")
            return

        for ws in result.workspaces:
            _print_workspace_status_entry(console, ws)
            if len(result.workspaces) > 1:
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
    ) -> None:
        """Stop server and remove all auto-start registrations for a workspace."""
        console.print("[bold cyan]phbcli teardown[/bold cyan]")

        try:
            result = TeardownTool().execute(
                workspace=workspace,
                purge=purge,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            return

        if result.autostart_removed:
            console.print("[green]Auto-start removed[/green] (Task Scheduler + Registry).")
        else:
            console.print("[yellow]Auto-start removal failed or skipped.[/yellow]")

        if purge:
            console.print(f"[green]Workspace folder removed:[/green] {result.workspace_path}")
            console.print(f"[green]Workspace '{result.workspace}' removed from registry.[/green]")

        console.print("\n[green]Teardown complete.[/green]")

    @app.command()
    def uninstall(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W",
            help="Workspace to uninstall (default: registry default).",
        ),
        purge: bool = typer.Option(False, "--purge", help="Also delete the workspace folder."),
    ) -> None:
        """Stop server, remove auto-start, then print package uninstall commands."""
        console.print("[bold cyan]phbcli teardown[/bold cyan]")

        try:
            result = UninstallTool().execute(
                workspace=workspace,
                purge=purge,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            return

        td = result.teardown
        if td.autostart_removed:
            console.print("[green]Auto-start removed[/green] (Task Scheduler + Registry).")
        else:
            console.print("[yellow]Auto-start removal failed or skipped.[/yellow]")

        if purge:
            console.print(f"[green]Workspace folder removed:[/green] {td.workspace_path}")
            console.print(f"[green]Workspace '{td.workspace}' removed from registry.[/green]")

        console.print(
            "\n[bold]To fully remove phbcli, run one of:[/bold]\n"
            "  [cyan]uv tool uninstall phbcli[/cyan]       (if installed via uv tool)\n"
            "  [cyan]pip uninstall phbcli[/cyan]            (if installed via pip)\n"
        )


def _print_workspace_status_entry(
    console: Console,
    ws: object,
) -> None:
    from ..tools.server import WorkspaceStatusEntry
    assert isinstance(ws, WorkspaceStatusEntry)

    title = f"phbcli status — {ws.name}"
    if ws.is_default:
        title += " [cyan](default)[/cyan]"

    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("ID", f"[dim]{ws.id}[/dim]")
    table.add_row("Server running", "[green]yes[/green]" if ws.server_running else "[red]no[/red]")
    table.add_row("PID", str(ws.pid) if ws.pid else "—")
    table.add_row(
        "WS connected",
        "[green]yes[/green]" if ws.ws_connected else "[red]no[/red]",
    )
    table.add_row("Last connected", ws.last_connected or "—")
    table.add_row("Gateway URL", ws.gateway_url or "—")
    table.add_row("Device ID", ws.device_id)
    table.add_row(
        "HTTP API",
        f"http://{ws.http_host}:{ws.http_port}/status" if ws.server_running else "—",
    )

    console.print(table)
