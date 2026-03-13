"""Device connection registry and message relay logic.

Connections are authenticated with a nonce challenge:
1) gateway sends {"type":"auth_challenge","nonce":"..."}
2) peer responds with {"type":"auth_response", ...}
3) on success, the socket is registered with its authenticated device_id

Messages are JSON objects with an optional `target_device_id` field:
  - Present  -> unicast to that specific device
  - Absent   -> broadcast to all OTHER connected devices

Message envelope:
{
    "target_device_id": "<uuid>",   # optional
    "sender_device_id": "<uuid>",   # injected by gateway
    "payload": { ... }              # arbitrary application data
}
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import websockets
from websockets.asyncio.server import ServerConnection
from phb_commons.nonces import generate_nonce
from phb_commons.log import Logger

from phb_channel_sdk.constants import (
    AUTH_ROLE_DESKTOP,
    AUTH_ROLE_DEVICE,
    WS_CLOSE_AUTH_FAILED,
    WS_CLOSE_DESKTOP_NOT_CONNECTED,
    WS_CLOSE_DUPLICATE_DEVICE,
    WS_CLOSE_NORMAL,
    WS_CLOSE_PAIRING_FIELD_MISSING,
    WS_CLOSE_PAIRING_TIMEOUT,
)
from phb_commons.constants.timing import DEFAULT_AUTH_TIMEOUT_SECONDS, DEFAULT_PAIRING_WAIT_SECONDS

from .auth import GatewayAuthManager
from .config import GatewayState, load_state, save_state
from .constants import PAIRING_REQUEST_ID_BYTES, WS_REASON_MAX_LENGTH

log = Logger.get("RELAY")

# device_id -> websocket
_registry: Dict[str, ServerConnection] = {}
_registry_lock = asyncio.Lock()

AUTH_TIMEOUT_SECONDS = DEFAULT_AUTH_TIMEOUT_SECONDS
_auth_manager: GatewayAuthManager | None = None
_desktop_ws: ServerConnection | None = None
_pairing_pending: Dict[str, ServerConnection] = {}
_pairing_lock = asyncio.Lock()
PAIRING_WAIT_SECONDS = DEFAULT_PAIRING_WAIT_SECONDS

_instance_path: "Path | None" = None


def _message_id(msg: dict[str, object]) -> str | None:
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        return None
    msg_id = payload.get("id")
    return msg_id if isinstance(msg_id, str) and msg_id else None


def configure_auth(auth_manager: GatewayAuthManager) -> None:
    """Inject the auth manager configured at gateway startup."""
    global _auth_manager
    _auth_manager = auth_manager


def configure_instance_path(instance_path: Path) -> None:
    """Inject the instance path so relay can persist connection state."""
    global _instance_path
    _instance_path = instance_path


def _write_desktop_connected() -> None:
    if _instance_path is None:
        return
    state = load_state(_instance_path)
    state.desktop_connected = True
    state.last_connected = datetime.now(timezone.utc).isoformat()
    state.last_auth_error = None
    save_state(_instance_path, state)


def _write_desktop_disconnected() -> None:
    if _instance_path is None:
        return
    state = load_state(_instance_path)
    state.desktop_connected = False
    save_state(_instance_path, state)


def _write_auth_error(reason: str) -> None:
    if _instance_path is None:
        return
    state = load_state(_instance_path)
    state.desktop_connected = False
    state.last_auth_error = reason
    save_state(_instance_path, state)


async def register(device_id: str, ws: ServerConnection) -> bool:
    async with _registry_lock:
        if device_id in _registry:
            old_ws = _registry[device_id]
            if old_ws is ws:
                return True
            log.warning("Duplicate device connection rejected", device_id=device_id)
            try:
                await ws.close(code=WS_CLOSE_DUPLICATE_DEVICE, reason="device already connected")
            except Exception:
                pass
            return False
        _registry[device_id] = ws
        log.info("Device registered", device_id=device_id, total=len(_registry))
        return True


async def unregister(device_id: str, ws: ServerConnection) -> None:
    async with _registry_lock:
        if _registry.get(device_id) is ws:
            _registry.pop(device_id, None)
            log.info("Device unregistered", device_id=device_id, total=len(_registry))


async def relay_message(sender_id: str, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Non-JSON message ignored", sender_id=sender_id)
        return

    msg["sender_device_id"] = sender_id
    target_id: str | None = msg.get("target_device_id")
    msg_id = _message_id(msg)
    out = json.dumps(msg)

    async with _registry_lock:
        if target_id:
            target_ws = _registry.get(target_id)
            if target_ws is None:
                log.warning(
                    "Target device not connected, message dropped",
                    target_id=target_id,
                    sender_id=sender_id,
                    msg_id=msg_id or "-",
                )
                return
            recipients = [(target_id, target_ws)]
        else:
            recipients = [(did, ws) for did, ws in _registry.items() if did != sender_id]

    for did, ws in recipients:
        try:
            await ws.send(out)
            log.info(
                "Message relayed",
                msg_id=msg_id or "-",
                sender=sender_id,
                recipient=did,
                target=target_id or "*",
            )
        except Exception as exc:
            log.warning("Failed to send to device", device_id=did, error=str(exc))


async def _authenticate_connection(
    nonce: str,
    msg: dict[str, object],
) -> tuple[bool, str | None, str, str | None]:
    auth = _auth_manager
    if auth is None:
        return False, None, "auth not configured", None
    if msg.get("type") != "auth_response":
        return False, None, "first message must be auth_response", None

    mode = msg.get("auth_mode")
    if not isinstance(mode, str):
        return False, None, "auth_mode is required", None

    if mode == AUTH_ROLE_DESKTOP:
        device_id = msg.get("device_id")
        signature = msg.get("nonce_signature") or msg.get("signature")
        if not isinstance(device_id, str) or not device_id:
            return False, None, "desktop auth requires device_id", None
        if not isinstance(signature, str) or not signature:
            return False, None, "desktop auth requires nonce_signature", None
        result = auth.verify_desktop_auth(
            nonce_hex=nonce,
            nonce_signature_b64=signature,
        )
        return (
            result.ok,
            device_id if result.ok else None,
            result.reason or "auth failed",
            AUTH_ROLE_DESKTOP,
        )

    if mode == AUTH_ROLE_DEVICE:
        attestation = msg.get("attestation")
        nonce_signature = msg.get("nonce_signature") or msg.get("signature")
        if not isinstance(attestation, dict):
            return False, None, "device auth requires attestation object", None
        if not isinstance(nonce_signature, str) or not nonce_signature:
            return False, None, "device auth requires nonce_signature", None
        blob = attestation.get("blob")
        desktop_signature = attestation.get("desktop_signature")
        if not isinstance(blob, str) or not blob:
            return False, None, "attestation.blob is required", None
        if not isinstance(desktop_signature, str) or not desktop_signature:
            return False, None, "attestation.desktop_signature is required", None
        result = auth.verify_device_auth(
            nonce_hex=nonce,
            attestation_blob=blob,
            desktop_signature_b64=desktop_signature,
            nonce_signature_b64=nonce_signature,
        )
        return result.ok, result.device_id, result.reason or "auth failed", "device"

    return False, None, f"unsupported auth_mode: {mode}", None


async def _register_desktop_ws(ws: ServerConnection) -> None:
    global _desktop_ws
    async with _pairing_lock:
        _desktop_ws = ws
    _write_desktop_connected()


async def _unregister_desktop_ws(ws: ServerConnection) -> None:
    global _desktop_ws
    async with _pairing_lock:
        if _desktop_ws is ws:
            _desktop_ws = None
    _write_desktop_disconnected()


async def _get_desktop_ws() -> ServerConnection | None:
    async with _pairing_lock:
        return _desktop_ws


async def _forward_pairing_request(ws: ServerConnection, msg: dict[str, object]) -> None:
    pairing_code = msg.get("pairing_code")
    device_public_key = msg.get("device_public_key")
    if not isinstance(pairing_code, str) or not pairing_code:
        await ws.close(code=WS_CLOSE_PAIRING_FIELD_MISSING, reason="pairing_code is required")
        return
    if not isinstance(device_public_key, str) or not device_public_key:
        await ws.close(code=WS_CLOSE_PAIRING_FIELD_MISSING, reason="device_public_key is required")
        return

    desktop_ws = await _get_desktop_ws()
    if desktop_ws is None:
        await ws.close(code=WS_CLOSE_DESKTOP_NOT_CONNECTED, reason="desktop not connected")
        return

    request_id = secrets.token_hex(PAIRING_REQUEST_ID_BYTES)
    async with _pairing_lock:
        _pairing_pending[request_id] = ws

    # Forward device_name if provided — used for admin UI device list labelling.
    device_name = msg.get("device_name")
    forward_payload: dict[str, object] = {
        "type": "pairing_request",
        "request_id": request_id,
        "pairing_code": pairing_code,
        "device_public_key": device_public_key,
    }
    if isinstance(device_name, str) and device_name:
        forward_payload["device_name"] = device_name

    await desktop_ws.send(json.dumps(forward_payload))
    await ws.send(json.dumps({"type": "pairing_pending", "request_id": request_id}))

    try:
        await asyncio.wait_for(ws.wait_closed(), timeout=PAIRING_WAIT_SECONDS)
    except asyncio.TimeoutError:
        async with _pairing_lock:
            _pairing_pending.pop(request_id, None)
        await ws.close(code=WS_CLOSE_PAIRING_TIMEOUT, reason="pairing timeout")


async def _handle_pairing_response_from_desktop(msg: dict[str, object]) -> None:
    request_id = msg.get("request_id")
    status = msg.get("status")
    if not isinstance(request_id, str) or not request_id:
        log.warning("Ignoring pairing_response without request_id")
        return
    if not isinstance(status, str) or status not in {"approved", "rejected"}:
        log.warning("Ignoring pairing_response with invalid status")
        return

    async with _pairing_lock:
        pending_ws = _pairing_pending.pop(request_id, None)
    if pending_ws is None:
        log.warning("No pending pairing request found", request_id=request_id)
        return

    outbound: dict[str, object] = {
        "type": "pairing_response",
        "status": status,
    }
    if status == "approved":
        attestation = msg.get("attestation")
        device_id = msg.get("device_id")
        if isinstance(attestation, dict):
            outbound["attestation"] = attestation
        if isinstance(device_id, str) and device_id:
            outbound["device_id"] = device_id
    else:
        reason = msg.get("reason")
        outbound["reason"] = reason if isinstance(reason, str) and reason else "rejected"

    try:
        await pending_ws.send(json.dumps(outbound))
    finally:
        await pending_ws.close(code=WS_CLOSE_NORMAL, reason="pairing complete")


async def handle_connection(ws: ServerConnection) -> None:
    """Handle a single WebSocket connection lifetime."""
    nonce = generate_nonce()
    await ws.send(json.dumps({"type": "auth_challenge", "nonce": nonce}))

    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        log.warning("Auth rejected", reason="timeout")
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason="auth timeout")
        return
    except websockets.ConnectionClosed:
        return

    try:
        first_msg = json.loads(str(raw))
    except json.JSONDecodeError:
        log.warning("Auth rejected", reason="first message invalid JSON")
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason="invalid json")
        return
    if not isinstance(first_msg, dict):
        log.warning("Auth rejected", reason="first message must be object")
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason="invalid first message")
        return

    if first_msg.get("type") == "pairing_request":
        await _forward_pairing_request(ws, first_msg)
        return

    ok, device_id, reason, role = await _authenticate_connection(nonce, first_msg)
    if not ok or not device_id:
        log.warning("Auth rejected", reason=reason)
        # Record auth errors for desktop role so the dashboard can surface them.
        if first_msg.get("auth_mode") == AUTH_ROLE_DESKTOP:
            _write_auth_error(reason)
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason=reason[:WS_REASON_MAX_LENGTH])
        return

    await ws.send(json.dumps({"type": "auth_ok", "device_id": device_id}))
    log.info("Device authenticated", device_id=device_id, role=role)

    is_desktop = role == AUTH_ROLE_DESKTOP
    if not await register(device_id, ws):
        return
    if is_desktop:
        await _register_desktop_ws(ws)
    try:
        async for message in ws:
            if is_desktop:
                try:
                    maybe = json.loads(str(message))
                except json.JSONDecodeError:
                    maybe = None
                if isinstance(maybe, dict) and maybe.get("type") == "pairing_response":
                    await _handle_pairing_response_from_desktop(maybe)
                    continue
            await relay_message(device_id, message)
    except websockets.ConnectionClosed:
        pass
    finally:
        if is_desktop:
            await _unregister_desktop_ws(ws)
        await unregister(device_id, ws)


def get_connected_devices() -> list[str]:
    return list(_registry.keys())
