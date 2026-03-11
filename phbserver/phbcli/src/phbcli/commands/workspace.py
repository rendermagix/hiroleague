"""Workspace management subcommands — thin CLI layer over workspace tools.

phbcli workspace list
phbcli workspace create <name> [--path P] [--set-default]
phbcli workspace remove <name-or-id> [--purge] [--yes]
phbcli workspace update <name-or-id> [--name N] [--set-default] [--gateway-url URL]
phbcli workspace show [<name-or-id>]
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from phb_commons.process import is_running, read_pid
from rich.console import Console
from rich.table import Table

from ..domain.workspace import WorkspaceError
from ..tools.workspace import (
    WorkspaceCreateTool,
    WorkspaceListTool,
    WorkspaceRemoveTool,
    WorkspaceShowTool,
    WorkspaceUpdateTool,
)


def register(workspace_app: typer.Typer, console: Console) -> None:
    """Register workspace management commands."""

    @workspace_app.command("list")
    def workspace_list() -> None:
        """List all configured workspaces."""
        result = WorkspaceListTool().execute()

        if not result.workspaces:
            console.print(
                "[dim]No workspaces configured. "
                "Run [bold]phbcli workspace create <name>[/bold] to get started.[/dim]"
            )
            return

        table = Table(title="Workspaces", show_header=True)
        table.add_column("", width=2, no_wrap=True)
        table.add_column("Name", style="bold")
        table.add_column("ID", style="dim")
        table.add_column("Setup")
        table.add_column("Server")
        table.add_column("Autostart")
        table.add_column("HTTP")
        table.add_column("Admin")
        table.add_column("Gateway URL")
        table.add_column("Path")

        for ws in result.workspaces:
            workspace_path = Path(ws["path"])
            pid = read_pid(workspace_path, "phbcli.pid")
            running = is_running(pid)

            default_marker = "[cyan]*[/cyan]" if ws["is_default"] else ""
            setup_str = "[green]configured[/green]" if ws["is_configured"] else "[yellow]needs setup[/yellow]"
            server_str = "[green]running[/green]" if running else "[dim]stopped[/dim]"
            method = ws.get("autostart_method")
            autostart_str = {
                "elevated": "[magenta]elevated[/magenta]",
                "schtasks": "[blue]schtasks[/blue]",
                "registry": "[cyan]registry[/cyan]",
                "skipped": "[dim]skipped[/dim]",
                "failed": "[red]failed[/red]",
            }.get(method or "", "[dim]—[/dim]")
            http_str = f":{ws['http_port']}"
            admin_str = f":{ws['admin_port']}"
            gw_str = ws.get("gateway_url") or "[dim]—[/dim]"
            short_id = ws["id"][:8]
            table.add_row(
                default_marker, ws["name"], short_id, setup_str, server_str,
                autostart_str, http_str, admin_str, gw_str, ws["path"],
            )

        console.print(table)
        console.print("\n[cyan]*[/cyan] = default workspace")

    @workspace_app.command("create")
    def workspace_create(
        name: str = typer.Argument(..., help="Workspace name (e.g. 'default', 'work')"),
        path: Optional[str] = typer.Option(
            None, "--path", "-p",
            help="Custom folder path. Defaults to the platform data dir.",
        ),
        make_default: bool = typer.Option(
            False, "--set-default",
            help="Set this workspace as the default after creation.",
        ),
    ) -> None:
        """Create a new workspace."""
        try:
            result = WorkspaceCreateTool().execute(
                name=name,
                path=path,
                set_default=make_default,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Workspace '[bold]{result.name}[/bold]' created.[/green]")
        console.print(f"  id          : [dim]{result.id}[/dim]")
        console.print(f"  path        : [bold]{result.path}[/bold]")
        console.print(f"  http_port   : [bold]{result.http_port}[/bold]")
        console.print(f"  plugin_port : [bold]{result.plugin_port}[/bold]")
        console.print(f"  admin_port  : [bold]{result.admin_port}[/bold]")

        if result.is_default:
            console.print("  [cyan]Set as default workspace.[/cyan]")

        console.print(f"\nNext: [bold]phbcli setup --workspace {result.name}[/bold]")

    @workspace_app.command("remove")
    def workspace_remove(
        workspace: str = typer.Argument(..., help="Workspace name or id to remove"),
        purge: bool = typer.Option(
            False, "--purge",
            help="Also delete the workspace folder from disk.",
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ) -> None:
        """Remove a workspace from the registry."""
        if not yes:
            action = "remove and DELETE the folder of" if purge else "remove"
            typer.confirm(
                f"Are you sure you want to {action} workspace '{workspace}'?", abort=True
            )
        try:
            result = WorkspaceRemoveTool().execute(workspace=workspace, purge=purge)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Workspace '[bold]{result.name}[/bold]' removed.[/green]")
        if result.purged:
            console.print("  Workspace folder deleted from disk.")

    @workspace_app.command("update")
    def workspace_update(
        workspace: str = typer.Argument(..., help="Workspace name or id to update"),
        new_name: Optional[str] = typer.Option(
            None, "--name", "-n",
            help="New display name for the workspace.",
        ),
        make_default: bool = typer.Option(
            False, "--set-default",
            help="Set this workspace as the default.",
        ),
        gateway_url: Optional[str] = typer.Option(
            None, "--gateway-url", "-g",
            help="New gateway WebSocket URL (light update — no key regen). "
                 "For full reconfiguration use 'phbcli setup'.",
        ),
    ) -> None:
        """Update workspace name, default flag, and/or gateway URL."""
        if new_name is None and not make_default and gateway_url is None:
            console.print("[yellow]Nothing to update. Pass --name, --set-default, or --gateway-url.[/yellow]")
            raise typer.Exit(0)
        try:
            result = WorkspaceUpdateTool().execute(
                workspace=workspace,
                name=new_name,
                set_default=make_default,
                gateway_url=gateway_url,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.renamed:
            console.print(f"  [green]Renamed[/green] → '[bold]{result.name}[/bold]'")
        if result.default_changed:
            console.print(f"  [green]Default workspace set to[/green] '[bold]{result.name}[/bold]'")
        if result.gateway_updated:
            console.print(f"  [green]Gateway URL updated.[/green]")
        if not any([result.renamed, result.default_changed, result.gateway_updated]):
            console.print("[dim]No changes made (values were already the same).[/dim]")

    @workspace_app.command("show")
    def workspace_show(
        workspace: Optional[str] = typer.Argument(
            None, help="Workspace name or id (omit to show the default)"
        ),
    ) -> None:
        """Show details of a workspace."""
        try:
            result = WorkspaceShowTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        workspace_path = Path(result.path)
        pid = read_pid(workspace_path, "phbcli.pid")
        running = is_running(pid)

        table = Table(
            title=f"Workspace: {result.name}",
            show_header=False,
            box=None,
            padding=(0, 2),
        )
        table.add_column("Key", style="bold")
        table.add_column("Value")

        table.add_row("Name", result.name)
        table.add_row("ID", f"[dim]{result.id}[/dim]")
        table.add_row("Path", result.path)
        table.add_row("Default", "[cyan]yes[/cyan]" if result.is_default else "no")
        table.add_row(
            "Setup",
            "[green]configured[/green]" if result.is_configured else "[yellow]needs setup[/yellow]",
        )
        table.add_row(
            "Server",
            f"[green]running[/green] (PID {pid})" if running else "[dim]stopped[/dim]",
        )
        if result.is_configured:
            ws_status = "[green]connected[/green]" if result.ws_connected else "[dim]disconnected[/dim]"
            if result.last_connected:
                ws_status += f" [dim](last: {result.last_connected})[/dim]"
            table.add_row("Gateway URL", result.gateway_url or "—")
            table.add_row("Gateway WS", ws_status)
            table.add_row("Device ID", result.device_id or "—")
            autostart_display = {
                "elevated": "[magenta]elevated[/magenta] (Task Scheduler, HIGHEST)",
                "schtasks": "[blue]schtasks[/blue] (Task Scheduler, LIMITED)",
                "registry": "[cyan]registry[/cyan] (HKCU Run key)",
                "skipped": "[dim]skipped[/dim]",
                "failed": "[red]failed[/red]",
            }.get(result.autostart_method or "", "[dim]—[/dim]")
            table.add_row("Autostart", autostart_display)
        table.add_row("HTTP port", str(result.http_port))
        table.add_row("Plugin port", str(result.plugin_port))
        table.add_row("Admin port", str(result.admin_port))
        table.add_row("Port slot", str(result.port_slot))

        console.print(table)
