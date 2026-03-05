"""FastAPI HTTP server for phbcli.

Runs concurrently with the WS client inside the same asyncio event loop.
Endpoints:
  GET  /status   — server and WS connection status
  GET  /channels — connected channel plugin names and info
  GET  /tools    — list all registered tools and their schemas
  POST /invoke   — execute a tool by name with a flat params dict
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from phb_commons.log import Logger
from phb_commons.process import is_running, read_pid
from pydantic import BaseModel

from .config import Config, load_state
from .constants import APP_NAME, PID_FILENAME
from .tools.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry

log = Logger.get("HTTP")

app = FastAPI(title=APP_NAME, version="0.1.0", docs_url=None, redoc_url=None)

# Injected by _server_process.py before the server starts.
_workspace_path: Path | None = None
_get_channel_info: Callable[[], list[dict[str, str]]] | None = None
_tool_registry: ToolRegistry | None = None


def set_workspace_path(path: Path) -> None:
    global _workspace_path
    _workspace_path = path


def set_channel_info_provider(fn: Callable[[], list[dict[str, str]]]) -> None:
    global _get_channel_info
    _get_channel_info = fn


def set_tool_registry(registry: ToolRegistry) -> None:
    global _tool_registry
    _tool_registry = registry


@app.get("/status")
async def get_status() -> JSONResponse:
    assert _workspace_path is not None, "workspace_path not initialised"
    state = load_state(_workspace_path)
    pid = read_pid(_workspace_path, PID_FILENAME)
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


@app.get("/tools")
async def get_tools() -> JSONResponse:
    """Return the schema of every registered tool."""
    if _tool_registry is None:
        return JSONResponse({"tools": []})
    return JSONResponse({"tools": _tool_registry.schema()})


class InvokeRequest(BaseModel):
    tool: str
    params: dict[str, Any] = {}


@app.post("/invoke")
async def invoke_tool(request: InvokeRequest) -> JSONResponse:
    """Execute a tool by name.

    Request body::

        { "tool": "device_add", "params": { "ttl_seconds": 120 } }

    Response on success::

        { "tool": "device_add", "result": { ... } }

    The result is the tool's return dataclass serialised to a dict.
    """
    if _tool_registry is None:
        raise HTTPException(status_code=503, detail="Tool registry not initialised")

    try:
        invoke_result = _tool_registry.invoke(request.tool, request.params)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ToolExecutionError as exc:
        log.error("Tool execution error", tool=request.tool, error=str(exc.cause), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = invoke_result.result
    if hasattr(result, "__dataclass_fields__"):
        import dataclasses
        result_dict = dataclasses.asdict(result)
    else:
        result_dict = result

    return JSONResponse({"tool": invoke_result.tool_name, "result": result_dict})


async def run_http_server(config: Config, stop_event: asyncio.Event) -> None:
    """Start uvicorn and shut it down when stop_event is set."""
    uv_config = uvicorn.Config(
        app=app,
        host=config.http_host,
        port=config.http_port,
        log_level="warning",
        loop="none",
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
