"""Channel subcommands — thin CLI layer over channel tools.

'channel install' and 'channel status' are CLI-only (subprocess / HTTP query)
and are kept here as direct implementations.  All other commands delegate to
the corresponding Tool class in tools/channel.py.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

from ..domain.channel_config import load_channel_config
from ..domain.workspace import WorkspaceError, resolve_workspace
from ..tools.channel import (
    ChannelDisableTool,
    ChannelEnableTool,
    ChannelInstallTool,
    ChannelListTool,
    ChannelRemoveTool,
    ChannelSetupTool,
)


def register(channel_app: typer.Typer, console: Console) -> None:
    """Register channel management commands."""

    @channel_app.command("list")
    def channel_list(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """List all configured channel plugins."""
        try:
            result = ChannelListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.channels:
            console.print(
                "[dim]No channels configured. "
                "Run [bold]hirocli channel setup <name>[/bold] to add one.[/dim]"
            )
            return

        table = Table(title="Channel plugins", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Enabled")
        table.add_column("Launch command")
        table.add_column("Config keys")

        for ch in result.channels:
            enabled_str = "[green]yes[/green]" if ch["enabled"] else "[red]no[/red]"
            keys_str = ", ".join(ch["config_keys"]) if ch["config_keys"] else "[dim]—[/dim]"
            table.add_row(ch["name"], enabled_str, ch["command"], keys_str)

        console.print(table)

    @channel_app.command("install")
    def channel_install(
        name: str = typer.Argument(..., help="Channel name, e.g. 'telegram'"),
        package: Optional[str] = typer.Option(
            None, "--package", "-p",
            help="Package name to install (default: hiro-channel-<name>)",
        ),
        editable: bool = typer.Option(
            False, "--editable", "-e", help="Install in editable mode (uv tool install -e)"
        ),
    ) -> None:
        """Install a channel plugin via uv tool install."""
        pkg = package or f"hiro-channel-{name}"
        console.print(f"Installing [bold]{pkg}[/bold]…")
        try:
            result = ChannelInstallTool().execute(
                channel_name=name,
                package=package,
                editable=editable,
            )
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.output:
            console.print(result.output)
        console.print(f"[green]Installed {result.package}.[/green]")
        console.print(f"  Next: [bold]hirocli channel setup {name}[/bold] to configure it.")

    @channel_app.command("setup")
    def channel_setup(
        name: str = typer.Argument(..., help="Channel name, e.g. 'telegram'"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        command: Optional[str] = typer.Option(
            None, "--command", "-c",
            help=(
                "Executable to run (default: hiro-channel-<name>). "
                "Use a space-separated string for multi-word commands."
            ),
        ),
        enable: bool = typer.Option(True, "--enable/--no-enable", help="Enable on setup"),
    ) -> None:
        """Configure and register a channel plugin."""
        workspace_path = _resolve_workspace_path(workspace, console)
        existing = load_channel_config(workspace_path, name)

        if command is None and existing and existing.command:
            default_cmd = " ".join(existing.command)
        else:
            default_cmd = command or f"hiro-channel-{name}"

        resolved_command: str = typer.prompt(
            f"Command to start the '{name}' plugin",
            default=default_cmd,
        )

        try:
            result = ChannelSetupTool().execute(
                channel_name=name,
                command=resolved_command,
                enabled=enable,
                workspace=workspace,
            )
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        console.print(
            f"[green]Channel '{result.name}' configured.[/green] "
            f"({'[green]enabled[/green]' if result.enabled else '[yellow]disabled[/yellow]'})"
        )
        console.print(f"  command  : [bold]{result.command}[/bold]")
        if result.workspace_dir:
            console.print(f"  workspace: [dim]{result.workspace_dir}[/dim]")
        console.print(
            "\nRestart hirocli to activate: [bold]hirocli stop[/bold] then [bold]hirocli start[/bold]"
        )

    @channel_app.command("enable")
    def channel_enable(
        name: str = typer.Argument(..., help="Channel name"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Enable a configured channel plugin."""
        try:
            result = ChannelEnableTool().execute(channel_name=name, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]Channel '{result.name}' enabled.[/green]")

    @channel_app.command("disable")
    def channel_disable(
        name: str = typer.Argument(..., help="Channel name"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Disable a channel plugin without removing its configuration."""
        try:
            result = ChannelDisableTool().execute(channel_name=name, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        console.print(f"[yellow]Channel '{result.name}' disabled.[/yellow]")

    @channel_app.command("remove")
    def channel_remove(
        name: str = typer.Argument(..., help="Channel name"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ) -> None:
        """Remove a channel plugin's configuration."""
        if not yes:
            typer.confirm(f"Remove configuration for channel '{name}'?", abort=True)
        try:
            result = ChannelRemoveTool().execute(channel_name=name, workspace=workspace)
        except (WorkspaceError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.removed:
            console.print(f"[green]Channel '{result.name}' configuration removed.[/green]")
        else:
            console.print(f"[yellow]Channel '{result.name}' was not configured.[/yellow]")

    @channel_app.command("status")
    def channel_status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Show connected channel plugins (queries the running server)."""
        workspace_path = _resolve_workspace_path(workspace, console)
        from ..domain.config import load_config
        config = load_config(workspace_path)
        url = f"http://{config.http_host}:{config.http_port}/channels"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                data = json.loads(resp.read())
        except Exception as exc:
            console.print(
                f"[red]Could not reach hirocli server at {url}: {exc}[/red]\n"
                "[dim]Is hirocli running? Try [bold]hirocli status[/bold].[/dim]"
            )
            raise typer.Exit(1)

        channels: list[dict[str, str]] = data.get("channels", [])
        if not channels:
            console.print("[dim]No channel plugins currently connected.[/dim]")
            return

        table = Table(title="Connected channels", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Version")
        table.add_column("Description")

        for ch in channels:
            table.add_row(
                ch.get("name", "?"),
                ch.get("version", "?"),
                ch.get("description", ""),
            )
        console.print(table)


def _resolve_workspace_path(workspace: str | None, console: Console) -> Path:
    try:
        entry, _ = resolve_workspace(workspace)
        return Path(entry.path)
    except WorkspaceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
