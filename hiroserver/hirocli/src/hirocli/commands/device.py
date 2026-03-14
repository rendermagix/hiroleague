"""Device pairing/approval subcommands — thin CLI layer over device tools."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..tools.device import DeviceAddTool, DeviceListTool, DeviceRevokeTool
from ..domain.workspace import WorkspaceError


def register(device_app: typer.Typer, console: Console) -> None:
    """Register device management commands."""

    @device_app.command("add")
    def device_add(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
        ttl_seconds: Optional[int] = typer.Option(
            None, "--ttl-seconds",
            help="Pairing code lifetime in seconds (default from config).",
        ),
        code_length: Optional[int] = typer.Option(
            None, "--code-length",
            help="Pairing code length in digits (default from config).",
        ),
    ) -> None:
        """Generate a short-lived pairing code for onboarding a mobile device."""
        try:
            result = DeviceAddTool().execute(
                workspace=workspace,
                ttl_seconds=ttl_seconds,
                code_length=code_length,
            )
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        from ..ui.qr import render_qr_terminal
        render_qr_terminal(result.qr_payload)
        console.print("[bold cyan]Pairing code created[/bold cyan]")
        console.print(f"  gateway   : [bold]{result.gateway_url}[/bold]")
        console.print(f"  code      : [bold]{result.code}[/bold]")
        console.print(f"  expires_at: [bold]{result.expires_at}[/bold]")
        console.print("Scan the QR code or enter the details manually in the mobile app.")

    @device_app.command("list")
    def device_list(
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """List approved paired devices."""
        try:
            result = DeviceListTool().execute(workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if not result.devices:
            console.print("[dim]No approved devices yet.[/dim]")
            return

        table = Table(title="Approved devices", show_header=True)
        table.add_column("Name", style="bold")
        table.add_column("Device ID")
        table.add_column("Paired At")
        table.add_column("Expires At")

        for device in result.devices:
            table.add_row(
                device.get("device_name") or "—",
                device["device_id"],
                device["paired_at"],
                device["expires_at"] or "—",
            )
        console.print(table)

    @device_app.command("revoke")
    def device_revoke(
        device_id: str = typer.Argument(..., help="Approved device_id to revoke"),
        workspace: Optional[str] = typer.Option(
            None, "--workspace", "-W", help="Workspace name (default: registry default)."
        ),
    ) -> None:
        """Revoke a previously approved paired device."""
        try:
            result = DeviceRevokeTool().execute(device_id=device_id, workspace=workspace)
        except WorkspaceError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        if result.removed:
            console.print(f"[green]Revoked device[/green] [bold]{result.device_id}[/bold].")
        else:
            console.print(f"[yellow]Device not found:[/yellow] {result.device_id}")
