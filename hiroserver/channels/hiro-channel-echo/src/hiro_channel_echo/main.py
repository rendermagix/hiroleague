"""Entry point for the hiro-channel-echo plugin process.

Invoked by hirocli's ChannelManager as:
    hiro-channel-echo --hiro-ws ws://127.0.0.1:18081
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from hiro_channel_sdk import log_setup
from hiro_channel_sdk.transport import PluginTransport
from hiro_commons.constants.network import DEFAULT_LOCALHOST, PORT_OFFSET_PLUGIN, PORT_RANGE_START
from hiro_commons.constants.storage import LOGS_DIR

from .plugin import EchoChannel

_DEFAULT_LOG_DIR = str(Path.home() / ".hirocli" / LOGS_DIR)
_DEFAULT_PLUGIN_WS = f"ws://{DEFAULT_LOCALHOST}:{PORT_RANGE_START + PORT_OFFSET_PLUGIN}"

app = typer.Typer(
    name="hiro-channel-echo",
    help="Hiro echo channel plugin.",
    add_completion=False,
)


@app.command()
def run(
    hiro_ws: str = typer.Option(
        _DEFAULT_PLUGIN_WS,
        "--hiro-ws",
        help="WebSocket URL of hirocli's plugin server.",
        envvar="HIRO_WS",
    ),
    log_dir: str = typer.Option(
        _DEFAULT_LOG_DIR,
        "--log-dir",
        help="Directory for rotating log files.",
    ),
) -> None:
    """Connect to hirocli and start the echo channel."""
    plugin = EchoChannel()
    log_setup.init(f"plugin-{plugin.info.name}", Path(log_dir))
    transport = PluginTransport(plugin, hiro_ws)
    asyncio.run(transport.run())


if __name__ == "__main__":
    app()
