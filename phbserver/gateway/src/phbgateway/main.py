"""phbgateway entry point."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
import websockets
from phb_channel_sdk import log_setup
from phb_commons.log import Logger
from phb_commons.process import is_running, read_pid, remove_pid, stop_process, write_pid
from rich.console import Console
from rich.table import Table

from .autostart import (
    register_autostart,
    register_autostart_elevated,
    unregister_autostart,
    unregister_autostart_elevated,
)
from .auth import GatewayAuthManager
from .config import GatewayConfig, load_config, resolve_log_dir, save_config
from .instance import (
    GatewayInstanceEntry,
    GatewayInstanceError,
    GatewayRegistry,
    create_instance,
    load_registry,
    remove_instance,
    resolve_instance,
    set_default_instance,
)
from .relay import configure_auth, get_connected_devices, handle_connection

cli = typer.Typer(
    name="phbgateway",
    help="Private Home Box relay gateway with instance management.",
    add_completion=False,
    invoke_without_command=True,
)
instance_app = typer.Typer(help="Manage gateway instances.")
cli.add_typer(instance_app, name="instance")
console = Console()
GATEWAY_PID_FILENAME = "gateway.pid"


@cli.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Default command: start the default instance."""
    if ctx.invoked_subcommand is None:
        start()


def _register_autostart_with_feedback(instance_name: str, *, elevated: bool) -> None:
    if elevated and sys.platform == "win32":
        console.print("[dim]Requesting UAC elevation for high-privilege task...[/dim]")
        try:
            accepted = register_autostart_elevated(instance_name)
        except RuntimeError as exc:
            console.print(f"[yellow]Elevated registration failed: {exc}[/yellow]")
            accepted = False
        if accepted:
            console.print(
                "[green]Auto-start registered[/green] via Task Scheduler (run-level: HIGHEST)."
            )
            return
        console.print(
            "[yellow]UAC prompt cancelled or failed. Falling back to standard auto-start...[/yellow]"
        )

    try:
        method = register_autostart(instance_name)
    except NotImplementedError as exc:
        console.print(f"[yellow]Auto-start skipped: {exc}[/yellow]")
        return
    except Exception as exc:
        console.print(f"[yellow]Auto-start registration failed: {exc}[/yellow]")
        return

    if method == "schtasks":
        console.print(
            "[green]Auto-start registered[/green] via Task Scheduler (run-level: LIMITED)."
        )
    elif method == "registry":
        console.print(
            "[green]Auto-start registered[/green] via Registry Run key "
            "[dim](Task Scheduler fallback)[/dim]."
        )
    else:
        console.print("[yellow]Auto-start method unknown.[/yellow]")


def _unregister_autostart_with_feedback(instance_name: str, *, elevated: bool) -> None:
    if elevated and sys.platform == "win32":
        console.print("[dim]Requesting UAC elevation to delete high-privilege task...[/dim]")
        try:
            accepted = unregister_autostart_elevated(instance_name)
        except RuntimeError as exc:
            console.print(f"[yellow]Elevated removal failed: {exc}[/yellow]")
            accepted = False
        if accepted:
            console.print("[green]Auto-start removed[/green] via elevated task delete.")
            return
        console.print(
            "[yellow]UAC prompt cancelled. Falling back to standard auto-start removal...[/yellow]"
        )

    try:
        unregister_autostart(instance_name)
        console.print("[green]Auto-start removed[/green] (Task Scheduler + Registry).")
    except NotImplementedError as exc:
        console.print(f"[yellow]Auto-start removal skipped: {exc}[/yellow]")
    except Exception as exc:
        console.print(f"[yellow]Auto-start removal failed: {exc}[/yellow]")


def _run_gateway(entry: GatewayInstanceEntry, config: GatewayConfig, *, verbose: bool) -> None:
    log_dir = resolve_log_dir(Path(entry.path), config)
    log_setup.init(
        "gateway",
        log_dir,
        level="DEBUG" if verbose else "INFO",
        foreground=True,
    )
    log = Logger.get("GATEWAY")
    auth_manager = GatewayAuthManager(desktop_public_key_b64=config.desktop_public_key)
    configure_auth(auth_manager)
    log.info("Gateway trust root configured", instance=entry.name)
    asyncio.run(_serve(entry.host, entry.port))


def _spawn_background(instance_name: str, *, verbose: bool) -> int:
    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        pythonw = str(Path(python).with_name("pythonw.exe"))
        if Path(pythonw).exists():
            python = pythonw

    cmd = [python, "-m", "phbgateway.main", "start", "--instance", instance_name, "--foreground"]
    if verbose:
        cmd.append("--verbose")

    env = {**os.environ}
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            env=env,
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            ),
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            env=env,
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return proc.pid


@cli.command()
def start(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (default: registry default)."
    ),
    log_dir: str = typer.Option(
        "",
        "--log-dir",
        help="Optional override log directory for this start only.",
    ),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start a configured gateway instance."""
    try:
        entry, _ = resolve_instance(instance)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    instance_path = Path(entry.path)
    pid = read_pid(instance_path, GATEWAY_PID_FILENAME)
    if pid and is_running(pid):
        console.print(f"[yellow]Gateway already running[/yellow] (PID {pid}).")
        return

    try:
        config = load_config(instance_path)
    except Exception as exc:
        console.print(f"[red]Failed to load config: {exc}[/red]")
        raise typer.Exit(1)

    if log_dir:
        config.log_dir = log_dir

    if foreground:
        console.print(
            f"[green]Gateway starting[/green] in foreground at ws://{entry.host}:{entry.port} "
            "[dim](Ctrl+C to stop)[/dim]"
        )
        try:
            _run_gateway(entry, config, verbose=verbose)
        except KeyboardInterrupt:
            pass
        console.print("[green]Gateway stopped.[/green]")
        return

    child_pid = _spawn_background(entry.name, verbose=verbose)
    write_pid(instance_path, GATEWAY_PID_FILENAME, child_pid)
    console.print(
        f"[green]Gateway started[/green] (PID {child_pid}). "
        f"WS: ws://{entry.host}:{entry.port}"
    )


@cli.command()
def stop(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (default: registry default)."
    ),
) -> None:
    """Stop a running gateway instance."""
    try:
        entry, _ = resolve_instance(instance)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    instance_path = Path(entry.path)
    pid = read_pid(instance_path, GATEWAY_PID_FILENAME)
    if pid is None or not is_running(pid):
        console.print("[yellow]Gateway is not running.[/yellow]")
        remove_pid(instance_path, GATEWAY_PID_FILENAME)
        return
    if stop_process(instance_path, GATEWAY_PID_FILENAME):
        console.print(f"[green]Gateway stopped[/green] (was PID {pid}).")
    else:
        console.print("[red]Failed to stop gateway.[/red]")


@cli.command()
def status(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (omit to show all instances)."
    ),
) -> None:
    """Show status for gateway instances."""
    registry = load_registry()
    if not registry.instances:
        console.print("[dim]No gateway instances configured.[/dim]")
        return

    if instance is not None:
        if instance not in registry.instances:
            console.print(f"[red]Gateway instance '{instance}' not found.[/red]")
            raise typer.Exit(1)
        _print_instance_status(registry, instance)
        return

    if len(registry.instances) == 1:
        only = next(iter(registry.instances))
        _print_instance_status(registry, only)
        return

    for name in registry.instances:
        _print_instance_status(registry, name)
        console.print()


@cli.command()
def teardown(
    instance: Optional[str] = typer.Option(
        None, "--instance", "-I", help="Gateway instance name (default: registry default)."
    ),
    purge: bool = typer.Option(
        False, "--purge", help="Also remove instance from registry and delete files."
    ),
    elevated_task: bool = typer.Option(
        False, "--elevated-task", help="(Windows) Request UAC for high-privilege task removal."
    ),
) -> None:
    """Stop gateway and remove auto-start registration for an instance."""
    try:
        entry, _ = resolve_instance(instance)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    instance_path = Path(entry.path)
    stop_process(instance_path, GATEWAY_PID_FILENAME)
    _unregister_autostart_with_feedback(entry.name, elevated=elevated_task)

    if purge:
        remove_instance(entry.name, purge=True)
        console.print(f"[green]Gateway instance '{entry.name}' removed.[/green]")
    else:
        console.print("[green]Teardown complete.[/green]")


@instance_app.command("list")
def instance_list() -> None:
    """List configured gateway instances."""
    registry = load_registry()
    if not registry.instances:
        console.print("[dim]No gateway instances configured.[/dim]")
        return

    table = Table(title="Gateway instances", show_header=True)
    table.add_column("", width=2, no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Bind")
    table.add_column("Path")

    for name, entry in registry.instances.items():
        pid = read_pid(Path(entry.path), GATEWAY_PID_FILENAME)
        running = is_running(pid)
        default_marker = "[cyan]*[/cyan]" if name == registry.default_instance else ""
        status_text = "[green]running[/green]" if running else "[dim]stopped[/dim]"
        table.add_row(default_marker, name, status_text, f"{entry.host}:{entry.port}", entry.path)

    console.print(table)
    console.print("\n[cyan]*[/cyan] = default instance")


@instance_app.command("create")
def instance_create(
    name: str = typer.Argument(..., help="Gateway instance name."),
    desktop_pubkey: str = typer.Option(
        ...,
        "--desktop-pubkey",
        help="Desktop Ed25519 public key (base64). Mandatory at creation.",
    ),
    port: int = typer.Option(..., "--port", "-p", help="Gateway bind port."),
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="Gateway bind host."),
    path: Optional[str] = typer.Option(None, "--path", help="Custom instance folder path."),
    log_dir: str = typer.Option("", "--log-dir", help="Custom log directory."),
    make_default: bool = typer.Option(False, "--set-default", help="Set as default instance."),
    skip_autostart: bool = typer.Option(
        False, "--skip-autostart", help="Do not register auto-start during create."
    ),
    elevated_task: bool = typer.Option(
        False, "--elevated-task", help="(Windows) Request UAC for high-privilege task creation."
    ),
) -> None:
    """Create a new gateway instance with mandatory values."""
    custom_path = Path(path) if path else None
    try:
        entry, registry = create_instance(name, host=host, port=port, path=custom_path)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    save_config(
        Path(entry.path),
        GatewayConfig(
            desktop_public_key=desktop_pubkey,
            log_dir=log_dir,
        ),
    )

    if make_default:
        set_default_instance(name)
        registry = load_registry()

    console.print(f"[green]Gateway instance '[bold]{name}[/bold]' created.[/green]")
    console.print(f"  path : [bold]{entry.path}[/bold]")
    console.print(f"  bind : [bold]{entry.host}:{entry.port}[/bold]")
    if name == registry.default_instance:
        console.print("  [cyan]Set as default instance.[/cyan]")

    if not skip_autostart:
        _register_autostart_with_feedback(name, elevated=elevated_task)

    console.print(f"\nNext: [bold]phbgateway start --instance {name}[/bold]")


@instance_app.command("set-default")
def instance_set_default(
    name: str = typer.Argument(..., help="Gateway instance name."),
) -> None:
    """Set default gateway instance."""
    try:
        set_default_instance(name)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Default gateway instance set to '[bold]{name}[/bold]'.[/green]")


@instance_app.command("show")
def instance_show(
    name: Optional[str] = typer.Argument(None, help="Instance name (omit to show default)."),
) -> None:
    """Show details for a gateway instance."""
    try:
        entry, registry = resolve_instance(name)
    except GatewayInstanceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _print_instance_details(entry, registry)


@instance_app.command("remove")
def instance_remove(
    name: str = typer.Argument(..., help="Gateway instance name to remove."),
    purge: bool = typer.Option(
        False, "--purge", help="Also delete instance files from disk."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    elevated_task: bool = typer.Option(
        False, "--elevated-task", help="(Windows) Request UAC for high-privilege task removal."
    ),
) -> None:
    """Remove a gateway instance."""
    if not yes:
        action = "remove and delete files for" if purge else "remove"
        typer.confirm(f"Are you sure you want to {action} instance '{name}'?", abort=True)

    registry = load_registry()
    if name not in registry.instances:
        console.print(f"[red]Gateway instance '{name}' not found.[/red]")
        raise typer.Exit(1)

    entry = registry.instances[name]
    stop_process(Path(entry.path), GATEWAY_PID_FILENAME)
    _unregister_autostart_with_feedback(name, elevated=elevated_task)
    remove_instance(name, purge=purge)
    console.print(f"[green]Gateway instance '[bold]{name}[/bold]' removed.[/green]")


def _print_instance_status(registry: GatewayRegistry, name: str) -> None:
    entry = registry.instances[name]
    instance_path = Path(entry.path)
    pid = read_pid(instance_path, GATEWAY_PID_FILENAME)
    running = is_running(pid)

    title = f"phbgateway status — {name}"
    if name == registry.default_instance:
        title += " [cyan](default)[/cyan]"

    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Gateway running", "[green]yes[/green]" if running else "[red]no[/red]")
    table.add_row("PID", str(pid) if pid else "—")
    table.add_row("WebSocket URL", f"ws://{entry.host}:{entry.port}")
    table.add_row("Path", entry.path)
    console.print(table)


def _print_instance_details(entry: GatewayInstanceEntry, registry: GatewayRegistry) -> None:
    instance_path = Path(entry.path)
    pid = read_pid(instance_path, GATEWAY_PID_FILENAME)
    running = is_running(pid)
    config = load_config(instance_path)
    resolved_log_dir = resolve_log_dir(instance_path, config)

    table = Table(
        title=f"Gateway instance: {entry.name}",
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Name", entry.name)
    table.add_row("Path", entry.path)
    table.add_row(
        "Default", "[cyan]yes[/cyan]" if entry.name == registry.default_instance else "no"
    )
    table.add_row(
        "Gateway",
        f"[green]running[/green] (PID {pid})" if running else "[dim]stopped[/dim]",
    )
    table.add_row("Bind", f"{entry.host}:{entry.port}")
    table.add_row("Log dir", str(resolved_log_dir))
    table.add_row("Desktop key", "[dim]configured in config.json[/dim]")
    console.print(table)


async def _serve(host: str, port: int) -> None:
    log = Logger.get("GATEWAY")
    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _shutdown)
    else:
        # signal handlers on Windows run in the main thread outside the event
        # loop, so call_soon_threadsafe is required to safely set the asyncio
        # Event from there.
        signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(stop_event.set))
        signal.signal(signal.SIGINT,  lambda *_: loop.call_soon_threadsafe(stop_event.set))

    async with websockets.serve(handle_connection, host, port, reuse_address=True) as server:
        log.info("Gateway listening", url=f"ws://{host}:{port}")
        await stop_event.wait()
        log.info("Shutting down", connected_devices=get_connected_devices())

    log.info("Gateway stopped")


if __name__ == "__main__":
    cli()
