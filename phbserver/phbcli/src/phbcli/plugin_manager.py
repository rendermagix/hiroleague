"""PluginManager — phbcli-side orchestrator for channel plugins.

Responsibilities:
  - Runs a local WebSocket server on plugin_port (default 18081).
  - Spawns a subprocess for each enabled channel on startup.
  - Accepts JSON-RPC connections from channel plugins.
  - Dispatches incoming channel.receive / channel.event notifications.
  - Routes channel.send / channel.configure / channel.status to plugins.
  - Terminates subprocesses on shutdown.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed
from phb_commons.log import Logger

from .channel_config import ChannelConfig, list_enabled_channels
from .config import Config, resolve_log_dir
from . import rpc_helpers as rpc

log = Logger.get("PLUGINS")


@dataclass
class _ConnectedChannel:
    name: str
    version: str
    description: str
    ws: ServerConnection
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)


class PluginManager:
    """Manages the lifecycle of channel plugins as subprocesses."""

    def __init__(
        self,
        config: Config,
        stop_event: asyncio.Event,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._stop_event = stop_event
        self._on_message = on_message
        self._on_event = on_event
        self._channels: dict[str, _ConnectedChannel] = {}
        self._subprocesses: list[subprocess.Popen[bytes]] = []
        self._host = "127.0.0.1"
        self._port = config.plugin_port

    # ------------------------------------------------------------------
    # Main coroutine
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the plugin WS server and spawn enabled channel subprocesses."""
        async with websockets.serve(
            self._handle_connection, self._host, self._port
        ):
            log.info("Plugin server listening", url=f"ws://{self._host}:{self._port}")
            await self._spawn_channels()
            await self._stop_event.wait()
            await self._shutdown_channels()

        log.info("Plugin server stopped")

    # ------------------------------------------------------------------
    # Subprocess management
    # ------------------------------------------------------------------

    async def _spawn_channels(self) -> None:
        channels = list_enabled_channels()
        if not channels:
            log.info("No enabled channel plugins configured")
            return

        phb_ws = f"ws://{self._host}:{self._port}"
        for ch in channels:
            await self._spawn_one(ch, phb_ws)

    async def _spawn_one(self, ch: ChannelConfig, phb_ws: str) -> None:
        log_dir = resolve_log_dir(self._config)
        cmd = ch.effective_command() + [
            "--phb-ws", phb_ws,
            "--log-dir", str(log_dir),
        ]
        log.info("Spawning channel plugin", channel=ch.name, cmd=cmd)
        try:
            if sys.platform == "win32":
                proc = subprocess.Popen(
                    cmd,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | subprocess.CREATE_NO_WINDOW
                    ),
                    close_fds=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    close_fds=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self._subprocesses.append(proc)
        except FileNotFoundError:
            log.error(
                "Channel command not found",
                cmd=cmd[0],
                hint=f"phbcli channel install {ch.name}",
            )
        except Exception as exc:
            log.error("Failed to spawn channel plugin", channel=ch.name, error=str(exc))

    async def _shutdown_channels(self) -> None:
        for ch in list(self._channels.values()):
            try:
                await ch.ws.send(rpc.build_notification("channel.stop", {}))
            except Exception:
                pass

        await asyncio.sleep(1)
        for proc in self._subprocesses:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # WebSocket connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(self, ws: ServerConnection) -> None:
        channel_name: str | None = None
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("Invalid JSON from plugin", raw=str(raw)[:200])
                    continue

                if "method" not in data:
                    await self._handle_response(channel_name, data)
                    continue

                method: str = data["method"]
                params: dict[str, Any] = data.get("params", {})
                req_id: Any = data.get("id")

                match method:
                    case "channel.register":
                        channel_name = params["name"]
                        self._channels[channel_name] = _ConnectedChannel(
                            name=channel_name,
                            version=params.get("version", "?"),
                            description=params.get("description", ""),
                            ws=ws,
                        )
                        log.info(
                            "Channel registered",
                            channel=channel_name,
                            version=params.get("version", "?"),
                        )
                        await self._push_config(channel_name)

                    case "channel.receive":
                        if self._on_message:
                            try:
                                await self._on_message(params)
                            except Exception as exc:
                                log.error(
                                    "on_message handler error",
                                    channel=channel_name,
                                    error=str(exc),
                                    exc_info=True,
                                )

                    case "channel.event":
                        event_name = params.get("event")
                        event_data = params.get("data", {})
                        log.info(
                            "Channel event received",
                            channel=channel_name or "?",
                            event_name=event_name,
                            data=event_data,
                        )
                        if self._on_event and isinstance(event_name, str):
                            try:
                                await self._on_event(event_name, event_data)
                            except Exception as exc:
                                log.error(
                                    "on_event handler error",
                                    channel=channel_name or "?",
                                    error=str(exc),
                                    exc_info=True,
                                )

                    case _:
                        log.warning(
                            "Unknown method from channel plugin",
                            channel=channel_name or "?",
                            method=method,
                        )
                        if req_id is not None:
                            await ws.send(
                                rpc.build_error(
                                    -32601,
                                    f"Method not found: {method}",
                                    req_id,
                                )
                            )

        except ConnectionClosed:
            pass
        except Exception as exc:
            log.error(
                "Error in plugin connection",
                channel=channel_name or "?",
                error=str(exc),
            )
        finally:
            if channel_name and channel_name in self._channels:
                del self._channels[channel_name]
                log.info("Channel disconnected", channel=channel_name)

    async def _handle_response(
        self, channel_name: str | None, data: dict[str, Any]
    ) -> None:
        if channel_name is None:
            return
        ch = self._channels.get(channel_name)
        if ch is None:
            return
        resp_id = str(data.get("id", ""))
        fut = ch.pending.pop(resp_id, None)
        if fut and not fut.done():
            if data.get("error"):
                fut.set_exception(RuntimeError(data["error"]["message"]))
            else:
                fut.set_result(data.get("result"))

    async def _push_config(self, channel_name: str) -> None:
        from .channel_config import load_channel_config

        cfg = load_channel_config(channel_name)
        payload = dict(cfg.config) if cfg else {}
        if channel_name == "devices":
            payload.setdefault("gateway_url", self._config.gateway_url)
            payload.setdefault("device_id", self._config.device_id)
            payload.setdefault("ping_interval", 30)
        if payload:
            await self.configure_channel(channel_name, payload)

    # ------------------------------------------------------------------
    # Outbound API (phbcli → plugin)
    # ------------------------------------------------------------------

    async def send_to_channel(
        self, channel_name: str, message: dict[str, Any]
    ) -> None:
        """Send a channel.send notification to a specific plugin."""
        ch = self._channels.get(channel_name)
        if ch is None:
            log.warning("Cannot send to channel — not connected", channel=channel_name)
            return
        await ch.ws.send(rpc.build_notification("channel.send", message))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a channel.send notification to all connected plugins."""
        for ch in list(self._channels.values()):
            try:
                await ch.ws.send(rpc.build_notification("channel.send", message))
            except Exception as exc:
                log.warning("Failed to broadcast to channel", channel=ch.name, error=str(exc))

    async def configure_channel(
        self, channel_name: str, config: dict[str, Any]
    ) -> None:
        """Push credentials/config to a specific plugin."""
        ch = self._channels.get(channel_name)
        if ch is None:
            return
        await ch.ws.send(
            rpc.build_notification("channel.configure", {"config": config})
        )

    async def send_event_to_channel(
        self, channel_name: str, event: str, data: dict[str, Any]
    ) -> None:
        """Send an event notification to a specific plugin."""
        ch = self._channels.get(channel_name)
        if ch is None:
            log.warning(
                "Cannot send event to channel — not connected", channel=channel_name
            )
            return
        await ch.ws.send(
            rpc.build_notification(
                "channel.event",
                {"event": event, "data": data},
            )
        )

    async def probe_channel(self, channel_name: str) -> dict[str, Any] | None:
        """Send channel.status and await the response."""
        ch = self._channels.get(channel_name)
        if ch is None:
            return None
        from uuid import uuid4

        req_id = uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        ch.pending[req_id] = fut
        await ch.ws.send(rpc.build_request("channel.status", request_id=req_id))
        try:
            return await asyncio.wait_for(fut, timeout=5.0)
        except asyncio.TimeoutError:
            ch.pending.pop(req_id, None)
            return None

    def get_connected_channels(self) -> list[str]:
        return list(self._channels.keys())

    def get_channel_info(self) -> list[dict[str, str]]:
        return [
            {
                "name": ch.name,
                "version": ch.version,
                "description": ch.description,
            }
            for ch in self._channels.values()
        ]
