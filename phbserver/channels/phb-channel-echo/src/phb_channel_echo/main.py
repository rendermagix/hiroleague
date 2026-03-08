"""Entry point for the phb-channel-echo plugin process.

Invoked by phbcli's ChannelManager as:
    phb-channel-echo --phb-ws ws://127.0.0.1:18081
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from phb_channel_sdk import log_setup
from phb_channel_sdk.transport import PluginTransport
from phb_commons.constants.network import DEFAULT_LOCALHOST, PORT_OFFSET_PLUGIN, PORT_RANGE_START
from phb_commons.constants.storage import LOGS_DIR

from .plugin import EchoChannel

_DEFAULT_LOG_DIR = str(Path.home() / ".phbcli" / LOGS_DIR)
_DEFAULT_PLUGIN_WS = f"ws://{DEFAULT_LOCALHOST}:{PORT_RANGE_START + PORT_OFFSET_PLUGIN}"

app = typer.Typer(
    name="phb-channel-echo",
    help="Private Home Box echo channel plugin.",
    add_completion=False,
)


@app.command()
def run(
    phb_ws: str = typer.Option(
        _DEFAULT_PLUGIN_WS,
        "--phb-ws",
        help="WebSocket URL of phbcli's plugin server.",
        envvar="PHB_WS",
    ),
    log_dir: str = typer.Option(
        _DEFAULT_LOG_DIR,
        "--log-dir",
        help="Directory for rotating log files.",
    ),
) -> None:
    """Connect to phbcli and start the echo channel."""
    plugin = EchoChannel()
    log_setup.init(f"plugin-{plugin.info.name}", Path(log_dir))
    transport = PluginTransport(plugin, phb_ws)
    asyncio.run(transport.run())


if __name__ == "__main__":
    app()
