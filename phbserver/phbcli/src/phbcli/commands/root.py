"""Root CLI command registrations."""

from __future__ import annotations

import shutil

import click
import typer
from rich.console import Console
from rich.table import Table

from phb_commons.keys import public_key_to_b64

from ..config import APP_DIR, Config, load_config, load_state, master_key_path, save_config
from ..crypto import load_or_create_master_key
from ..process import is_running, read_pid, remove_pid, stop_server
from ..services.autostart_feedback import (
    register_autostart_with_feedback,
    unregister_autostart_with_feedback,
)
from ..services.bootstrap import ensure_mandatory_devices_channel
from ..services.server_control import do_start


def register(app: typer.Typer, console: Console) -> None:
    """Register root-level commands on the provided app."""

    @app.command()
    def setup(
        gateway_url: str = typer.Option(
            None, "--gateway-url", "-g", help="WebSocket gateway URL (e.g. ws://myhost:8765)"
        ),
        http_port: int = typer.Option(18080, "--port", "-p", help="Local HTTP server port"),
        skip_autostart: bool = typer.Option(
            False, "--skip-autostart", help="Do not register auto-start"
        ),
        elevated_task: bool = typer.Option(
            False,
            "--elevated-task",
            help="(Windows) Request UAC elevation to create a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """One-time setup: configure gateway, generate device ID, register auto-start."""
        console.print("[bold cyan]phbcli setup[/bold cyan]")

        existing = load_config()

        effective_gateway_url = gateway_url
        if effective_gateway_url is None:
            effective_gateway_url = typer.prompt(
                "Gateway WebSocket URL",
                default=existing.gateway_url,
            )

        config = Config(
            device_id=existing.device_id,  # preserve existing device_id
            gateway_url=effective_gateway_url,
            http_host=existing.http_host,
            http_port=http_port,
            plugin_port=existing.plugin_port,
            master_key_file=existing.master_key_file,
            pairing_code_length=existing.pairing_code_length,
            pairing_code_ttl_seconds=existing.pairing_code_ttl_seconds,
            attestation_expires_days=existing.attestation_expires_days,
        )
        save_config(config)
        private_key = load_or_create_master_key(APP_DIR, filename=config.master_key_file)
        public_key_b64 = public_key_to_b64(private_key.public_key())
        ensure_mandatory_devices_channel(config)
        console.print(f"[green]Config saved to[/green] {APP_DIR / 'config.json'}")
        console.print(f"  device_id  : [bold]{config.device_id}[/bold]")
        console.print(f"  gateway_url: [bold]{config.gateway_url}[/bold]")
        console.print(f"  http_port  : [bold]{config.http_port}[/bold]")
        console.print(f"  master_key : [bold]{master_key_path(config)}[/bold]")
        console.print(f"  desktop_pub: [bold]{public_key_b64}[/bold]")
        console.print("  channel    : [bold]devices[/bold] (mandatory)")

        if not skip_autostart:
            register_autostart_with_feedback(console, elevated=elevated_task)

        console.print("\nStarting server…")
        do_start(config, console, foreground=False)

    @app.command()
    def start(
        foreground: bool = typer.Option(
            False,
            "--foreground",
            "-f",
            help=(
                "Run the server in the foreground with live log output. "
                "Plugin log files are also tailed and printed to the terminal. "
                "Press Ctrl+C to stop."
            ),
        ),
    ) -> None:
        """Start the phbcli server (background by default, foreground with -f)."""
        config = load_config()
        if not (APP_DIR / "config.json").exists():
            console.print(
                "[red]Not configured. Run [bold]phbcli setup[/bold] first.[/red]"
            )
            raise typer.Exit(1)
        do_start(config, console, foreground=foreground)

    @app.command()
    def stop() -> None:
        """Stop the running phbcli server."""
        pid = read_pid()
        if pid is None or not is_running(pid):
            console.print("[yellow]Server is not running.[/yellow]")
            remove_pid()
            return
        stopped = stop_server()
        if stopped:
            console.print(f"[green]Server stopped[/green] (was PID {pid}).")
        else:
            console.print("[red]Failed to stop server.[/red]")

    @app.command()
    def status() -> None:
        """Show server and WebSocket connection status."""
        pid = read_pid()
        running = is_running(pid)
        state = load_state()
        config = load_config()

        table = Table(title="phbcli status", show_header=False, box=None, padding=(0, 2))
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

    @app.command()
    def teardown(
        purge: bool = typer.Option(
            False,
            "--purge",
            help="Also delete the ~/.phbcli/ app directory (config, state, PID file).",
        ),
        elevated_task: bool = typer.Option(
            False,
            "--elevated-task",
            help="(Windows) Request UAC elevation to delete a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """Stop server and remove all auto-start registrations."""
        console.print("[bold cyan]phbcli teardown[/bold cyan]")

        pid = read_pid()
        if pid and is_running(pid):
            stopped = stop_server()
            if stopped:
                console.print(f"[green]Server stopped[/green] (was PID {pid}).")
            else:
                console.print("[yellow]Could not stop server — continuing teardown.[/yellow]")
        else:
            console.print("[dim]Server was not running.[/dim]")
            remove_pid()

        unregister_autostart_with_feedback(console, elevated=elevated_task)

        if purge:
            if APP_DIR.exists():
                shutil.rmtree(APP_DIR, ignore_errors=True)
                console.print(f"[green]App directory removed:[/green] {APP_DIR}")
            else:
                console.print(f"[dim]App directory not found (already clean): {APP_DIR}[/dim]")

        console.print("\n[green]Teardown complete.[/green]")

    @app.command()
    def uninstall(
        purge: bool = typer.Option(
            False,
            "--purge",
            help="Also delete the ~/.phbcli/ app directory.",
        ),
        elevated_task: bool = typer.Option(
            False,
            "--elevated-task",
            help="(Windows) Request UAC elevation to delete a high-privilege Task Scheduler entry.",
        ),
    ) -> None:
        """Stop server, remove auto-start, then print package uninstall commands."""
        ctx = click.get_current_context()
        ctx.invoke(teardown, purge=purge, elevated_task=elevated_task)

        console.print(
            "\n[bold]To fully remove phbcli, run one of:[/bold]\n"
            "  [cyan]uv tool uninstall phbcli[/cyan]       (if installed via uv tool)\n"
            "  [cyan]pip uninstall phbcli[/cyan]            (if installed via pip)\n"
        )
