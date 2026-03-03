"""FastAPI HTTP server for phbcli.

Runs concurrently with the WS client inside the same asyncio event loop.
Endpoints:
  GET /status   — server and WS connection status
  GET /channels — connected channel plugin names and info
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from phb_logger import Logger

from .config import Config, load_state
from .process import is_running, read_pid

log = Logger.get("HTTP")

app = FastAPI(title="phbcli", version="0.1.0", docs_url=None, redoc_url=None)

# Injected by _server_process.py after PluginManager is created.
_get_channel_info: Callable[[], list[dict[str, str]]] | None = None


def set_channel_info_provider(fn: Callable[[], list[dict[str, str]]]) -> None:
    """Register a callback that returns info about connected channel plugins."""
    global _get_channel_info
    _get_channel_info = fn


@app.get("/status")
async def get_status() -> JSONResponse:
    state = load_state()
    pid = read_pid()
    return JSONResponse(
        {
            "running": is_running(pid),
            "pid": pid,
            "ws_connected": state.ws_connected,
            "last_connected": state.last_connected,
            "gateway_url": state.gateway_url,
        }
    )


@app.get("/channels")
async def get_channels() -> JSONResponse:
    channels = _get_channel_info() if _get_channel_info else []
    return JSONResponse({"channels": channels})


async def run_http_server(config: Config, stop_event: asyncio.Event) -> None:
    """Start uvicorn and shut it down when stop_event is set."""
    uv_config = uvicorn.Config(
        app=app,
        host=config.http_host,
        port=config.http_port,
        log_level="warning",
        loop="none",  # use the existing event loop
    )
    server = uvicorn.Server(uv_config)

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        [serve_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done:
        server.should_exit = True
        await serve_task

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    log.info("HTTP server stopped")
