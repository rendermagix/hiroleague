"""Devices channel plugin.

Owns the gateway WebSocket connection and translates between:
  - gateway relay envelope: {target_device_id?, sender_device_id?, payload}
  - UnifiedMessage (hiro-channel-sdk model)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hiro_commons.keys import load_private_key_pem
from hiro_commons.signing import sign_nonce
from websockets.exceptions import ConnectionClosed
from hiro_commons.log import Logger

from hiro_channel_sdk import ChannelInfo, ChannelPlugin, UnifiedMessage
from hiro_channel_sdk.constants import AUTH_ROLE_DESKTOP, RECONNECT_BACKOFF_BASE, RECONNECT_BACKOFF_MAX
from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.constants.network import DEFAULT_GATEWAY_PORT
from hiro_commons.constants.timing import DEFAULT_PING_INTERVAL_SECONDS

log = Logger.get("DEVICES")

BACKOFF_BASE = RECONNECT_BACKOFF_BASE
BACKOFF_MAX = RECONNECT_BACKOFF_MAX
AUTH_TIMEOUT_SECONDS = 15.0


def _default_master_key_path() -> Path:
    return Path.home() / ".hirocli" / "master_key.pem"


class DevicesChannel(ChannelPlugin):
    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            name=MANDATORY_CHANNEL_NAME,
            version="0.1.0",
            description="Bridges gateway-connected devices to UnifiedMessage.",
        )

    def __init__(self) -> None:
        self._gateway_url: str = f"ws://localhost:{DEFAULT_GATEWAY_PORT}"
        self._device_id: str = ""
        self._ping_interval: float = DEFAULT_PING_INTERVAL_SECONDS
        self._master_key_path: Path = _default_master_key_path()
        self._master_private_key: Ed25519PrivateKey | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._gateway_ws: websockets.WebSocketClientProtocol | None = None

    async def on_configure(self, config: dict) -> None:
        self._gateway_url = str(config.get("gateway_url", self._gateway_url))
        self._device_id = str(config.get("device_id", self._device_id))
        self._ping_interval = float(config.get("ping_interval", self._ping_interval))
        self._master_key_path = Path(
            str(config.get("master_key_path", str(self._master_key_path)))
        )
        log.info(
            "Devices channel configured",
            gateway=self._gateway_url,
            device_id=self._device_id,
            master_key=str(self._master_key_path),
        )

    async def on_start(self) -> None:
        if not self._device_id:
            raise RuntimeError("devices channel requires config.device_id")
        if not self._master_key_path.exists():
            raise RuntimeError(
                f"devices channel requires master key file: {self._master_key_path}"
            )
        self._master_private_key = load_private_key_pem(self._master_key_path.read_bytes())
        if self._runner_task is None:
            self._runner_task = asyncio.create_task(self._run_gateway_loop())

    async def on_stop(self) -> None:
        if self._runner_task is not None:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
            self._runner_task = None
        if self._gateway_ws is not None:
            try:
                await self._gateway_ws.close()
            except Exception:
                pass
            self._gateway_ws = None

    async def send(self, message: UnifiedMessage) -> None:
        """UnifiedMessage -> gateway envelope."""
        if self._gateway_ws is None:
            log.warning("Gateway not connected — dropping outbound message")
            return
        out = {
            "payload": message.model_dump(mode="json"),
        }
        if message.recipient_id:
            out["target_device_id"] = message.recipient_id
        log.info(
            "Forwarding message to gateway",
            msg_id=message.id,
            recipient=message.recipient_id or "*",
            content_type=message.content_type,
        )
        await self._gateway_ws.send(json.dumps(out))

    async def _run_gateway_loop(self) -> None:
        backoff = BACKOFF_BASE
        url = self._gateway_url

        while True:
            try:
                await self._run_gateway_connection(url)
                log.warning("Gateway disconnected, reconnecting", delay=f"{backoff:.0f}s")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Gateway error, reconnecting", error=str(exc), delay=f"{backoff:.0f}s")

            await self.emit_event(
                "gateway_disconnected",
                {"gateway_url": self._gateway_url, "device_id": self._device_id},
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def _run_gateway_connection(self, url: str) -> None:
        log.info("Connecting to gateway", url=url)
        async with websockets.connect(url, ping_interval=self._ping_interval) as ws:
            await self._authenticate_with_gateway(ws)
            self._gateway_ws = ws
            await self.emit_event(
                "gateway_connected",
                {"gateway_url": self._gateway_url, "device_id": self._device_id},
            )
            log.info("Connected to gateway", device_id=self._device_id)

            try:
                async for raw in ws:
                    await self._handle_gateway_message(str(raw))
            except ConnectionClosed:
                pass
            finally:
                self._gateway_ws = None

    async def _authenticate_with_gateway(
        self, ws: websockets.WebSocketClientProtocol
    ) -> None:
        key = self._master_private_key
        if key is None:
            raise RuntimeError("master private key is not loaded")

        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("gateway auth challenge timeout") from exc

        try:
            challenge = json.loads(str(raw))
        except json.JSONDecodeError as exc:
            raise RuntimeError("gateway auth challenge is not JSON") from exc

        if challenge.get("type") != "auth_challenge":
            raise RuntimeError(f"unexpected first frame from gateway: {challenge}")
        nonce = challenge.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise RuntimeError("gateway challenge missing nonce")

        auth_response = {
            "type": "auth_response",
            "auth_mode": AUTH_ROLE_DESKTOP,
            "device_id": self._device_id,
            "nonce_signature": sign_nonce(key, nonce),
        }
        await ws.send(json.dumps(auth_response))

        try:
            auth_ack_raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("gateway auth ack timeout") from exc

        try:
            auth_ack = json.loads(str(auth_ack_raw))
        except json.JSONDecodeError as exc:
            raise RuntimeError("gateway auth ack is not JSON") from exc

        if auth_ack.get("type") != "auth_ok":
            raise RuntimeError(f"gateway rejected auth: {auth_ack}")

        log.info("Gateway auth successful", device_id=self._device_id)

    async def _handle_gateway_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Invalid JSON from gateway", raw=raw[:200])
            return

        msg_type = msg.get("type")
        if msg_type == "pairing_request":
            await self._handle_pairing_request(msg)
            return

        payload = msg.get("payload")
        if not isinstance(payload, dict):
            log.warning("Gateway payload is not an object", payload=payload)
            return

        try:
            unified = UnifiedMessage.model_validate(payload)
        except Exception as exc:
            log.warning("Invalid UnifiedMessage from gateway", error=str(exc))
            return

        # Override the sender's timestamp with the server's receive time.
        # Device clocks can drift or be misconfigured — we have no control over
        # them. Using the receive time ensures messages are ordered by when the
        # server actually received them, not by whatever clock the sender runs.
        unified.timestamp = datetime.now(timezone.utc)

        sender_device_id = msg.get("sender_device_id")
        if isinstance(sender_device_id, str) and sender_device_id:
            unified.sender_id = sender_device_id
            unified.metadata = {
                **(unified.metadata or {}),
                "friendly_name": sender_device_id,
                "sender_device_id": sender_device_id,
            }

        unified.channel = MANDATORY_CHANNEL_NAME
        unified.direction = "inbound"
        log.info(
            "Inbound message from gateway",
            msg_id=unified.id,
            sender=unified.sender_id,
            content_type=unified.content_type,
        )
        await self.emit(unified)

    async def _handle_pairing_request(self, msg: dict) -> None:
        request_id = msg.get("request_id")
        pairing_code = msg.get("pairing_code")
        device_public_key = msg.get("device_public_key")
        if not isinstance(request_id, str) or not request_id:
            log.warning("Pairing request missing request_id")
            return
        if not isinstance(pairing_code, str) or not pairing_code:
            log.warning("Pairing request missing pairing_code")
            return
        if not isinstance(device_public_key, str) or not device_public_key:
            log.warning("Pairing request missing device_public_key")
            return

        device_name_raw = msg.get("device_name")
        device_name = device_name_raw if isinstance(device_name_raw, str) and device_name_raw else None

        log.info("Pairing request received", request_id=request_id)
        event_data: dict[str, object] = {
            "request_id": request_id,
            "pairing_code": pairing_code,
            "device_public_key": device_public_key,
        }
        if device_name:
            event_data["device_name"] = device_name
        await self.emit_event("pairing_request", event_data)

    async def on_event(self, event: str, data: dict) -> None:
        if event != "pairing_response":
            return
        ws = self._gateway_ws
        if ws is None:
            log.warning("Gateway not connected — cannot send pairing_response")
            return

        request_id = data.get("request_id")
        status = data.get("status")
        if not isinstance(request_id, str) or not request_id:
            log.warning("Pairing response missing request_id")
            return
        if not isinstance(status, str) or status not in {"approved", "rejected"}:
            log.warning("Pairing response invalid status", status=status)
            return

        log.info("Sending pairing response to gateway", request_id=request_id, status=status)

        outbound: dict[str, object] = {
            "type": "pairing_response",
            "request_id": request_id,
            "status": status,
        }
        if status == "approved":
            attestation = data.get("attestation")
            device_id = data.get("device_id")
            if isinstance(attestation, dict):
                outbound["attestation"] = attestation
            if isinstance(device_id, str) and device_id:
                outbound["device_id"] = device_id
        else:
            reason = data.get("reason")
            outbound["reason"] = reason if isinstance(reason, str) and reason else "rejected"

        await ws.send(json.dumps(outbound))
