"""Workspace management subcommands.

phbcli workspace list
phbcli workspace create <name> [--path P] [--with-gateway] [--set-default]
phbcli workspace remove <name> [--purge] [--yes]
phbcli workspace set-default <name>
phbcli workspace show [<name>]
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..process import is_running, read_gateway_pid, read_pid
from ..workspace import (
    WorkspaceError,
    create_workspace,
    gateway_port_for,
    http_port_for,
    load_registry,
    plugin_port_for,
    remove_workspace,
    resolve_workspace,
    set_default_workspace,
)


def register(workspace_app: typer.Typer, console: Console) -> None:
    """Register workspace management commands."""

    @workspace_app.command("list")
    def workspace_list() -> None:
        """List all configured workspaces."""
        registry = load_registry()
        if not registry.workspaces:
            console.print(
                "[dim]No workspaces configured. "
                "Run [bold]phbcli workspace create <name>[/bold] to get started.[/dim]"
            )
            return

        table = Table(title="Workspaces", show_header=True)
        table.add_column("", width=2, no_wrap=True)
        table.add_column("Name", style="bold")
        table.add_column("Status")
        table.add_column("HTTP")
        table.add_column("Gateway")
        table.add_column("Path")

        for name, entry in registry.workspaces.items():
            workspace_path = Path(entry.path)
            pid = read_pid(workspace_path)
            running = is_running(pid)

            gw_port = gateway_port_for(registry, entry.port_slot)
            gw_pid = read_gateway_pid(workspace_path) if entry.local_gateway else None
            gw_running = is_running(gw_pid)

            default_marker = "[cyan]*[/cyan]" if name == registry.default_workspace else ""
            status = "[green]running[/green]" if running else "[dim]stopped[/dim]"
            http_str = f":{http_port_for(registry, entry.port_slot)}"

            if entry.local_gateway:
                gw_status = "[green]up[/green]" if gw_running else "[dim]down[/dim]"
                gw_str = f":{gw_port} ({gw_status})"
            else:
                gw_str = "[dim]external[/dim]"

            table.add_row(default_marker, name, status, http_str, gw_str, entry.path)

        console.print(table)
        console.print("\n[cyan]*[/cyan] = default workspace")

    @workspace_app.command("create")
    def workspace_create(
        name: str = typer.Argument(..., help="Workspace name (e.g. 'default', 'work')"),
        path: str = typer.Option(
            None, "--path", "-p",
            help="Custom folder path. Defaults to the platform data dir.",
        ),
        with_gateway: bool = typer.Option(
            False, "--with-gateway",
            help="Manage a local phbgateway process for this workspace.",
        ),
        make_default: bool = typer.Option(
            False, "--set-default",
            help="Set this workspace as the default after creation.",
        ),
    ) -> None:
        """Create a new workspace."""
        custom_path = Path(path) if path else None
        try:
            entry, registry = create_workspace(
                name, path=custom_path, local_gateway=with_gateway
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if make_default:
            set_default_workspace(name)
            registry = load_registry()

        http = http_port_for(registry, entry.port_slot)
        plugin = plugin_port_for(registry, entry.port_slot)
        gw = gateway_port_for(registry, entry.port_slot)

        console.print(f"[green]Workspace '[bold]{name}[/bold]' created.[/green]")
        console.print(f"  path         : [bold]{entry.path}[/bold]")
        console.print(f"  http_port    : [bold]{http}[/bold]")
        console.print(f"  plugin_port  : [bold]{plugin}[/bold]")
        gw_note = "(local — managed by phbcli)" if with_gateway else "(external)"
        console.print(f"  gateway_port : [bold]{gw}[/bold]  {gw_note}")

        if name == registry.default_workspace:
            console.print("  [cyan]Set as default workspace.[/cyan]")

        console.print(f"\nNext: [bold]phbcli setup --workspace {name}[/bold]")

    @workspace_app.command("remove")
    def workspace_remove(
        name: str = typer.Argument(..., help="Workspace name to remove"),
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
                f"Are you sure you want to {action} workspace '{name}'?", abort=True
            )
        try:
            remove_workspace(name, purge=purge)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Workspace '[bold]{name}[/bold]' removed.[/green]")
        if purge:
            console.print("  Workspace folder deleted from disk.")

    @workspace_app.command("set-default")
    def workspace_set_default(
        name: str = typer.Argument(..., help="Workspace name to set as default"),
    ) -> None:
        """Set the default workspace used when --workspace is not specified."""
        try:
            set_default_workspace(name)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(
            f"[green]Default workspace set to '[bold]{name}[/bold]'.[/green]"
        )

    @workspace_app.command("show")
    def workspace_show(
        name: str = typer.Argument(
            None, help="Workspace name (omit to show the default)"
        ),
    ) -> None:
        """Show details of a workspace."""
        try:
            entry, registry = resolve_workspace(name)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        workspace_path = Path(entry.path)
        pid = read_pid(workspace_path)
        running = is_running(pid)
        gw_pid = read_gateway_pid(workspace_path) if entry.local_gateway else None
        gw_running = is_running(gw_pid)

        http = http_port_for(registry, entry.port_slot)
        plugin = plugin_port_for(registry, entry.port_slot)
        gw = gateway_port_for(registry, entry.port_slot)

        table = Table(
            title=f"Workspace: {entry.name}",
            show_header=False,
            box=None,
            padding=(0, 2),
        )
        table.add_column("Key", style="bold")
        table.add_column("Value")

        table.add_row("Name", entry.name)
        table.add_row("Path", entry.path)
        table.add_row(
            "Default", "[cyan]yes[/cyan]" if entry.name == registry.default_workspace else "no"
        )
        table.add_row(
            "Server",
            f"[green]running[/green] (PID {pid})" if running else "[dim]stopped[/dim]",
        )
        table.add_row("HTTP port", str(http))
        table.add_row("Plugin port", str(plugin))
        table.add_row("Gateway port", str(gw))
        if entry.local_gateway:
            table.add_row(
                "Local gateway",
                f"[green]running[/green] (PID {gw_pid})" if gw_running else "[dim]stopped[/dim]",
            )
        else:
            table.add_row("Local gateway", "[dim]external (not managed)[/dim]")
        table.add_row("Port slot", str(entry.port_slot))

        console.print(table)
