"""Devices channel plugin.

Owns the gateway WebSocket connection and translates between:
  - gateway relay envelope: {target_device_id?, sender_device_id?, payload}
  - UnifiedMessage (phb-channel-sdk model)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)
from websockets.exceptions import ConnectionClosed

from phb_channel_sdk import ChannelInfo, ChannelPlugin, UnifiedMessage

logger = logging.getLogger(__name__)

BACKOFF_BASE = 1.0
BACKOFF_MAX = 60.0
AUTH_TIMEOUT_SECONDS = 15.0


def _default_master_key_path() -> Path:
    return Path.home() / ".phbcli" / "master_key.pem"


def _load_master_private_key(path: Path) -> Ed25519PrivateKey:
    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("master key must be Ed25519")
    return key


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _sign_nonce_b64(private_key: Ed25519PrivateKey, nonce_hex: str) -> str:
    signature = private_key.sign(bytes.fromhex(nonce_hex))
    return base64.b64encode(signature).decode("ascii")


class DevicesChannel(ChannelPlugin):
    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            name="devices",
            version="0.1.0",
            description="Bridges gateway-connected devices to UnifiedMessage.",
        )

    def __init__(self) -> None:
        self._gateway_url: str = "ws://localhost:8765"
        self._device_id: str = ""
        self._ping_interval: float = 30.0
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
        logger.info(
            "Configured devices channel. gateway=%s device_id=%s master_key=%s",
            self._gateway_url,
            self._device_id,
            self._master_key_path,
        )

    async def on_start(self) -> None:
        if not self._device_id:
            raise RuntimeError("devices channel requires config.device_id")
        if not self._master_key_path.exists():
            raise RuntimeError(
                f"devices channel requires master key file: {self._master_key_path}"
            )
        self._master_private_key = _load_master_private_key(self._master_key_path)
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
            logger.warning("Gateway is not connected; dropping outbound message.")
            return
        out = {
            "payload": message.model_dump(mode="json"),
        }
        if message.recipient_id:
            out["target_device_id"] = message.recipient_id
        logger.info(
            "Forwarding outbound message to gateway [msg_id=%s recipient=%s content_type=%s]",
            message.id,
            message.recipient_id or "*",
            message.content_type,
        )
        await self._gateway_ws.send(json.dumps(out))

    async def _run_gateway_loop(self) -> None:
        backoff = BACKOFF_BASE
        url = self._gateway_url

        while True:
            try:
                await self._run_gateway_connection(url)
                logger.warning(
                    "Gateway disconnected. Reconnecting in %.0fs...",
                    backoff,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Gateway error: %s. Reconnecting in %.0fs...", exc, backoff)

            await self.emit_event(
                "gateway_disconnected",
                {"gateway_url": self._gateway_url, "device_id": self._device_id},
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def _run_gateway_connection(self, url: str) -> None:
        logger.info("Connecting devices channel to gateway: %s", url)
        async with websockets.connect(url, ping_interval=self._ping_interval) as ws:
            await self._authenticate_with_gateway(ws)
            self._gateway_ws = ws
            await self.emit_event(
                "gateway_connected",
                {"gateway_url": self._gateway_url, "device_id": self._device_id},
            )
            logger.info("Connected to gateway.")

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
            "auth_mode": "desktop_claim",
            "device_id": self._device_id,
            "public_key": _public_key_b64(key),
            "nonce_signature": _sign_nonce_b64(key, nonce),
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

    async def _handle_gateway_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from gateway: %.200s", raw)
            return

        msg_type = msg.get("type")
        if msg_type == "pairing_request":
            await self._handle_pairing_request(msg)
            return

        payload = msg.get("payload")
        if not isinstance(payload, dict):
            logger.warning("Gateway payload is not an object: %s", payload)
            return

        try:
            unified = UnifiedMessage.model_validate(payload)
        except Exception as exc:
            logger.warning("Invalid UnifiedMessage payload from gateway: %s", exc)
            return

        sender_device_id = msg.get("sender_device_id")
        if isinstance(sender_device_id, str) and sender_device_id:
            unified.sender_id = sender_device_id
            unified.metadata = {
                **(unified.metadata or {}),
                "friendly_name": sender_device_id,
                "sender_device_id": sender_device_id,
            }

        unified.channel = "devices"
        unified.direction = "inbound"
        logger.info(
            "Received inbound message from gateway [msg_id=%s sender=%s content_type=%s]",
            unified.id,
            unified.sender_id,
            unified.content_type,
        )
        await self.emit(unified)

    async def _handle_pairing_request(self, msg: dict) -> None:
        request_id = msg.get("request_id")
        pairing_code = msg.get("pairing_code")
        device_public_key = msg.get("device_public_key")
        if not isinstance(request_id, str) or not request_id:
            logger.warning("pairing_request missing request_id")
            return
        if not isinstance(pairing_code, str) or not pairing_code:
            logger.warning("pairing_request missing pairing_code")
            return
        if not isinstance(device_public_key, str) or not device_public_key:
            logger.warning("pairing_request missing device_public_key")
            return

        await self.emit_event(
            "pairing_request",
            {
                "request_id": request_id,
                "pairing_code": pairing_code,
                "device_public_key": device_public_key,
            },
        )

    async def on_event(self, event: str, data: dict) -> None:
        if event != "pairing_response":
            return
        ws = self._gateway_ws
        if ws is None:
            logger.warning("Gateway is not connected; cannot send pairing_response.")
            return

        request_id = data.get("request_id")
        status = data.get("status")
        if not isinstance(request_id, str) or not request_id:
            logger.warning("pairing_response missing request_id")
            return
        if not isinstance(status, str) or status not in {"approved", "rejected"}:
            logger.warning("pairing_response invalid status")
            return

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
