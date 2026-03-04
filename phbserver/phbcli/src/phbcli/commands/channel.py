"""Channel subcommands for plugin lifecycle/config management."""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..channel_config import (
    ChannelConfig,
    delete_channel_config,
    find_workspace_root,
    list_channel_configs,
    load_channel_config,
    save_channel_config,
    workspace_channels_dir,
)
from ..config import load_config, master_key_path
from ..services.bootstrap import MANDATORY_CHANNEL
from ..workspace import WorkspaceError, resolve_workspace


def register(channel_app: typer.Typer, console: Console) -> None:
    """Register channel management commands."""

    @channel_app.command("list")
    def channel_list(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """List all configured channel plugins."""
        workspace_path = _resolve_workspace_path(workspace, console)
        configs = list_channel_configs(workspace_path)
        if not configs:
            console.print(
                "[dim]No channels configured. "
                "Run [bold]phbcli channel setup <name>[/bold] to add one.[/dim]"
            )
            return

        table = Table(title="Channel plugins", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Enabled")
        table.add_column("Launch command")
        table.add_column("Config keys")

        for cfg in configs:
            enabled_str = "[green]yes[/green]" if cfg.enabled else "[red]no[/red]"
            cmd_str = " ".join(cfg.effective_command())
            keys_str = ", ".join(cfg.config.keys()) if cfg.config else "[dim]—[/dim]"
            table.add_row(cfg.name, enabled_str, cmd_str, keys_str)

        console.print(table)

    @channel_app.command("install")
    def channel_install(
        name: str = typer.Argument(..., help="Channel name, e.g. 'telegram'"),
        package: Optional[str] = typer.Option(
            None, "--package", "-p",
            help="Package name to install (default: phb-channel-<name>)",
        ),
        editable: bool = typer.Option(
            False, "--editable", "-e", help="Install in editable mode (uv tool install -e)"
        ),
    ) -> None:
        """Install a channel plugin via uv tool install."""
        pkg = package or f"phb-channel-{name}"
        cmd = ["uv", "tool", "install"]
        if editable:
            cmd.append("--editable")
        cmd.append(pkg)

        console.print(f"Installing [bold]{pkg}[/bold]…")
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode == 0:
            console.print(f"[green]Installed {pkg}.[/green]")
            console.print(
                f"  Next: [bold]phbcli channel setup {name}[/bold] to configure it."
            )
        else:
            console.print(f"[red]Install failed (exit {result.returncode}).[/red]")
            raise typer.Exit(1)

    @channel_app.command("setup")
    def channel_setup(
        name: str = typer.Argument(..., help="Channel name, e.g. 'telegram'"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        command: Optional[str] = typer.Option(
            None, "--command", "-c",
            help=(
                "Executable to run (default: phb-channel-<name>). "
                "Use a space-separated string for multi-word commands."
            ),
        ),
        enable: bool = typer.Option(True, "--enable/--no-enable", help="Enable on setup"),
    ) -> None:
        """Configure and register a channel plugin."""
        workspace_path = _resolve_workspace_path(workspace, console)
        existing = load_channel_config(workspace_path, name)

        if name == MANDATORY_CHANNEL and not enable:
            console.print("[yellow]Ignoring --no-enable: 'devices' is mandatory.[/yellow]")
            enable = True

        if command is None and existing and existing.command:
            default_cmd = " ".join(existing.command)
        else:
            default_cmd = command or f"phb-channel-{name}"

        cmd_str: str = typer.prompt(
            f"Command to start the '{name}' plugin",
            default=default_cmd,
        )
        cmd_parts = cmd_str.split()

        uv_workspace = find_workspace_root()
        workspace_dir = str(uv_workspace) if uv_workspace else (
            existing.workspace_dir if existing else ""
        )

        channel_data = existing.config if existing else {}
        if name == MANDATORY_CHANNEL:
            current = load_config(workspace_path)
            channel_data = {
                **channel_data,
                "gateway_url": current.gateway_url,
                "device_id": current.device_id,
                "master_key_path": str(master_key_path(workspace_path, current)),
                "ping_interval": channel_data.get("ping_interval", 30),
            }

        cfg = ChannelConfig(
            name=name,
            enabled=enable,
            command=cmd_parts,
            config=channel_data,
            workspace_dir=workspace_dir,
        )
        save_channel_config(workspace_path, cfg)

        channels_dir = workspace_channels_dir(workspace_path)
        console.print(
            f"[green]Channel '{name}' configured.[/green] "
            f"({'[green]enabled[/green]' if enable else '[yellow]disabled[/yellow]'})"
        )
        console.print(f"  command  : [bold]{cmd_str}[/bold]")
        if workspace_dir:
            console.print(f"  workspace: [dim]{workspace_dir}[/dim]")
            console.print(
                f"  launcher : [dim]uv run --directory {workspace_dir} {cmd_str}[/dim]"
            )
        console.print(f"  config   : {channels_dir / (name + '.json')}")
        console.print(
            "\nRestart phbcli to activate: [bold]phbcli stop[/bold] then [bold]phbcli start[/bold]"
        )

    @channel_app.command("enable")
    def channel_enable(
        name: str = typer.Argument(..., help="Channel name"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Enable a configured channel plugin."""
        workspace_path = _resolve_workspace_path(workspace, console)
        cfg = load_channel_config(workspace_path, name)
        if cfg is None:
            console.print(
                f"[red]Channel '{name}' not configured. "
                f"Run [bold]phbcli channel setup {name}[/bold] first.[/red]"
            )
            raise typer.Exit(1)
        cfg.enabled = True
        save_channel_config(workspace_path, cfg)
        console.print(f"[green]Channel '{name}' enabled.[/green]")

    @channel_app.command("disable")
    def channel_disable(
        name: str = typer.Argument(..., help="Channel name"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Disable a channel plugin without removing its configuration."""
        workspace_path = _resolve_workspace_path(workspace, console)
        if name == MANDATORY_CHANNEL:
            console.print("[red]The 'devices' channel is mandatory and cannot be disabled.[/red]")
            raise typer.Exit(1)
        cfg = load_channel_config(workspace_path, name)
        if cfg is None:
            console.print(f"[yellow]Channel '{name}' not configured.[/yellow]")
            raise typer.Exit(1)
        cfg.enabled = False
        save_channel_config(workspace_path, cfg)
        console.print(f"[yellow]Channel '{name}' disabled.[/yellow]")

    @channel_app.command("remove")
    def channel_remove(
        name: str = typer.Argument(..., help="Channel name"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ) -> None:
        """Remove a channel plugin's configuration."""
        workspace_path = _resolve_workspace_path(workspace, console)
        if name == MANDATORY_CHANNEL:
            console.print("[red]The 'devices' channel is mandatory and cannot be removed.[/red]")
            raise typer.Exit(1)
        if not yes:
            typer.confirm(
                f"Remove configuration for channel '{name}'?", abort=True
            )
        removed = delete_channel_config(workspace_path, name)
        if removed:
            console.print(f"[green]Channel '{name}' configuration removed.[/green]")
        else:
            console.print(f"[yellow]Channel '{name}' was not configured.[/yellow]")

    @channel_app.command("status")
    def channel_status(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Show connected channel plugins (queries the running server)."""
        workspace_path = _resolve_workspace_path(workspace, console)
        config = load_config(workspace_path)
        url = f"http://{config.http_host}:{config.http_port}/channels"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                data = json.loads(resp.read())
        except Exception as exc:
            console.print(
                f"[red]Could not reach phbcli server at {url}: {exc}[/red]\n"
                "[dim]Is phbcli running? Try [bold]phbcli status[/bold].[/dim]"
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
