"""PluginTransport — the WS bridge between a channel plugin and Hiro Server.

Usage inside a channel's ``main.py``::

    plugin = MyChannel()
    transport = PluginTransport(plugin, hiro_ws_url)
    asyncio.run(transport.run())

The transport:
  1. Connects to Hiro Server's Channel Manager via websocket.
  2. Sends a ``channel.register`` notification.
  3. Wires ``plugin.emit`` → ``channel.receive`` notifications to Channel Manager.
  4. Calls ``plugin.on_start()`` to let the plugin begin listening.
  5. Dispatches incoming JSON-RPC calls from Channel Manager to the plugin.
  6. Calls ``plugin.on_stop()`` on disconnect / shutdown.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import websockets
from websockets.exceptions import ConnectionClosed
from hiro_commons.log import Logger

from . import rpc
from .base import ChannelPlugin
from .constants import (
    JSONRPC_ERROR_INTERNAL,
    JSONRPC_ERROR_METHOD_NOT_FOUND,
    METHOD_CONFIGURE,
    METHOD_EVENT,
    METHOD_RECEIVE,
    METHOD_REGISTER,
    METHOD_SEND,
    METHOD_STATUS,
    METHOD_STOP,
    RECONNECT_DELAY_SECONDS,
)
from .models import RpcRequest, RpcResponse, UnifiedMessage

log = Logger.get("CH_TRANSPORT")

RECONNECT_DELAY = RECONNECT_DELAY_SECONDS


class PluginTransport:
    """Manages the bidirectional JSON-RPC connection to Channel Manager."""

    def __init__(self, plugin: ChannelPlugin, hiro_ws_url: str) -> None:
        self._plugin = plugin
        self._url = hiro_ws_url
        self._ws: Any = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._stop_event = asyncio.Event()
        self._started = False

    async def run(self) -> None:
        """Connect to Channel Manager, register, and run the message loop.

        Automatically reconnects on unexpected disconnection until
        ``stop()`` is called.
        """
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
            except ConnectionClosed:
                if self._stop_event.is_set():
                    break
                log.warning(
                    "Disconnected from Channel Manager, reconnecting",
                    delay=f"{RECONNECT_DELAY:.0f}s",
                )
            except OSError as exc:
                if self._stop_event.is_set():
                    break
                log.warning(
                    "Could not reach Channel Manager, reconnecting",
                    error=str(exc),
                    delay=f"{RECONNECT_DELAY:.0f}s",
                )

            if not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=RECONNECT_DELAY
                    )
                except asyncio.TimeoutError:
                    pass

    async def stop(self) -> None:
        """Signal the transport to disconnect and stop reconnecting."""
        self._stop_event.set()

    async def _connect_and_run(self) -> None:
        log.info(
            f"Connecting plugin {self._plugin.info.name} to Channel Manager",
            url=self._url
        )
        async with websockets.connect(self._url) as ws:
            self._ws = ws

            await ws.send(
                rpc.build_notification(
                    METHOD_REGISTER,
                    {
                        "name": self._plugin.info.name,
                        "version": self._plugin.info.version,
                        "description": self._plugin.info.description,
                    },
                )
            )
            log.info(f"Channel ({self._plugin.info.name}) registered with Channel Manager")

            async def _forward_inbound(msg: UnifiedMessage) -> None:
                await self._notify(METHOD_RECEIVE, msg.model_dump(mode="json"))

            self._plugin._emit_callback = _forward_inbound
            self._plugin._event_callback = self._notify_event

            try:
                async for raw in ws:
                    await self._handle_frame(str(raw))
            except ConnectionClosed:
                pass
            finally:
                if self._started:
                    await self._plugin.on_stop()
                    self._started = False
                self._plugin._emit_callback = None
                self._plugin._event_callback = None
                self._ws = None

    # ------------------------------------------------------------------
    # Incoming frame dispatch
    # ------------------------------------------------------------------

    async def _handle_frame(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"Invalid JSON from Channel Manager: {raw[:200]}")
            return

        if "method" in data:
            req = RpcRequest.model_validate(data)
            await self._dispatch(req)
        else:
            resp = RpcResponse.model_validate(data)
            fut = self._pending.pop(str(resp.id), None)
            if fut and not fut.done():
                if resp.error:
                    fut.set_exception(RuntimeError(resp.error["message"]))
                else:
                    fut.set_result(resp.result)

    async def _dispatch(self, req: RpcRequest) -> None:
        result: Any = None
        error: dict[str, Any] | None = None

        try:
            match req.method:
                case _ if req.method == METHOD_SEND:
                    msg = UnifiedMessage.model_validate(req.params)
                    await self._plugin.send(msg)
                    result = {"ok": True}

                case _ if req.method == METHOD_CONFIGURE:
                    await self._plugin.on_configure(req.params.get("config", {}))
                    if not self._started:
                        await self._plugin.on_start()
                        self._started = True
                    result = {"ok": True}

                case _ if req.method == METHOD_EVENT:
                    event = req.params.get("event")
                    data = req.params.get("data", {})
                    if not isinstance(event, str) or not event:
                        raise ValueError(f"{METHOD_EVENT} requires params.event")
                    if not isinstance(data, dict):
                        raise ValueError(f"{METHOD_EVENT} params.data must be an object")
                    await self._plugin.on_event(event, data)
                    result = {"ok": True}

                case _ if req.method == METHOD_STOP:
                    self._stop_event.set()
                    result = {"ok": True}

                case _ if req.method == METHOD_STATUS:
                    result = {
                        "name": self._plugin.info.name,
                        "version": self._plugin.info.version,
                        "status": "running",
                    }

                case _:
                    error = {
                        "code": JSONRPC_ERROR_METHOD_NOT_FOUND,
                        "message": f"Method not found: {req.method}",
                    }

        except Exception as exc:
            log.error(
                f"Error handling RPC method ({req.method})",
                error=str(exc),
                exc_info=True,
            )
            error = {"code": JSONRPC_ERROR_INTERNAL, "message": str(exc)}

        if req.id is not None and self._ws is not None:
            if error:
                await self._ws.send(
                    rpc.build_error(error["code"], error["message"], req.id)
                )
            else:
                await self._ws.send(rpc.build_success(result, req.id))

    # ------------------------------------------------------------------
    # Outgoing helpers
    # ------------------------------------------------------------------

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._ws is not None:
            await self._ws.send(rpc.build_notification(method, params))

    async def _notify_event(self, event: str, data: dict[str, Any]) -> None:
        await self._notify(METHOD_EVENT, {"event": event, "data": data})

    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Send a JSON-RPC request to Channel Manager and await the response."""
        if self._ws is None:
            raise RuntimeError("Not connected to Channel Manager")
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = fut
        await self._ws.send(
            rpc.build_request(method, params or {}, request_id=request_id)
        )
        return await fut
