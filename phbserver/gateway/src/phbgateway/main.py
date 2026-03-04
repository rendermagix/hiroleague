"""phbgateway entry point.

Starts the asyncio WebSocket relay server.
Can be run directly (`python -m phbgateway.main`) or via the
`phbgateway` console script.

Usage:
  phbgateway [--host HOST] [--port PORT]
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import typer
import websockets
from phb_channel_sdk import log_setup
from phb_commons.log import Logger

from .auth import GatewayAuthManager
from .relay import configure_auth, get_connected_devices, handle_connection

_DEFAULT_LOG_DIR = Path.home() / ".phbgateway" / "logs"

cli = typer.Typer(
    name="phbgateway",
    help="Private Home Box relay gateway.",
    add_completion=False,
    invoke_without_command=True,
)


@cli.callback()
def run(
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="Bind host"),
    port: int = typer.Option(8765, "--port", "-p", help="Bind port"),
    desktop_pubkey: str = typer.Option(
        "",
        "--desktop-pubkey",
        help="Desktop Ed25519 public key (base64). If omitted, gateway can be claimed by first desktop connection.",
    ),
    state_dir: str = typer.Option(
        ".",
        "--state-dir",
        help="Directory used to persist gateway auth state.",
    ),
    log_dir: str = typer.Option(
        "",
        "--log-dir",
        help=(
            f"Directory for rotating log files. "
            f"Defaults to {_DEFAULT_LOG_DIR}"
        ),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the phbgateway WebSocket relay server."""
    resolved_log_dir = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
    log_setup.init(
        "gateway",
        resolved_log_dir,
        level="DEBUG" if verbose else "INFO",
        foreground=True,
    )
    log = Logger.get("GATEWAY")

    auth_manager = GatewayAuthManager(
        state_file=Path(state_dir).resolve() / "gateway_state.json",
        desktop_public_key_b64=desktop_pubkey or None,
    )
    configure_auth(auth_manager)

    if auth_manager.is_claimed():
        log.info("Gateway trust root configured")
    else:
        log.warning(
            "Gateway trust root not configured — waiting for first desktop claim"
        )

    asyncio.run(_serve(host, port))


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
