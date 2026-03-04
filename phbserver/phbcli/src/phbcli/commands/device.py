"""Device pairing/approval subcommands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..pairing import (
    create_pairing_session,
    load_approved_devices,
    revoke_approved_device,
    save_pairing_session,
)


def register(device_app: typer.Typer, console: Console) -> None:
    """Register device management commands."""

    @device_app.command("add")
    def device_add(
        ttl_seconds: int = typer.Option(
            None,
            "--ttl-seconds",
            help="Pairing code lifetime in seconds (default from config).",
        ),
        code_length: int = typer.Option(
            None,
            "--code-length",
            help="Pairing code length in digits (default from config).",
        ),
    ) -> None:
        """Generate a short-lived pairing code for onboarding a mobile device."""
        config = load_config()
        effective_ttl = ttl_seconds or config.pairing_code_ttl_seconds
        effective_length = code_length or config.pairing_code_length
        session = create_pairing_session(
            code_length=effective_length,
            ttl_seconds=effective_ttl,
        )
        save_pairing_session(session)

        console.print("[bold cyan]Pairing code created[/bold cyan]")
        console.print(f"  code      : [bold]{session.code}[/bold]")
        console.print(
            f"  expires_at: [bold]{session.expires_at.isoformat().replace('+00:00', 'Z')}[/bold]"
        )
        console.print("Use this code in the mobile app immediately.")

    @device_app.command("list")
    def device_list() -> None:
        """List approved paired devices."""
        devices = load_approved_devices()
        if not devices:
            console.print("[dim]No approved devices yet.[/dim]")
            return

        table = Table(title="Approved devices", show_header=True)
        table.add_column("Device ID", style="bold")
        table.add_column("Paired At")
        table.add_column("Expires At")

        for device in devices:
            paired_at = device.paired_at.isoformat().replace("+00:00", "Z")
            expires_at = (
                device.expires_at.isoformat().replace("+00:00", "Z")
                if device.expires_at
                else "—"
            )
            table.add_row(device.device_id, paired_at, expires_at)
        console.print(table)

    @device_app.command("revoke")
    def device_revoke(
        device_id: str = typer.Argument(..., help="Approved device_id to revoke"),
    ) -> None:
        """Revoke a previously approved paired device."""
        removed = revoke_approved_device(device_id)
        if removed:
            console.print(f"[green]Revoked device[/green] [bold]{device_id}[/bold].")
        else:
            console.print(f"[yellow]Device not found:[/yellow] {device_id}")
