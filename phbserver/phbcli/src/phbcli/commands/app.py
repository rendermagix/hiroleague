"""CLI composition root: build app and wire command groups."""

from __future__ import annotations

import typer
from rich.console import Console

from .channel import register as register_channel_commands
from .device import register as register_device_commands
from .root import register as register_root_commands
from .workspace import register as register_workspace_commands

app = typer.Typer(
    name="phbcli",
    help="Private Home Box — desktop server CLI.",
    add_completion=False,
)
console = Console()

channel_app = typer.Typer(
    name="channel",
    help="Manage channel plugins (Telegram, WhatsApp, etc.).",
    add_completion=False,
)
device_app = typer.Typer(
    name="device",
    help="Manage paired device approvals.",
    add_completion=False,
)
workspace_app = typer.Typer(
    name="workspace",
    help="Manage workspaces (isolated server instances).",
    add_completion=False,
)

app.add_typer(channel_app, name="channel")
app.add_typer(device_app, name="device")
app.add_typer(workspace_app, name="workspace")

register_root_commands(app, console)
register_channel_commands(channel_app, console)
register_device_commands(device_app, console)
register_workspace_commands(workspace_app, console)
