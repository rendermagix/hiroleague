"""Infrastructure-level channel event handlers.

Handles pairing requests, gateway connectivity tracking, and other
infrastructure concerns dispatched by ChannelEventHandler.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hiro_commons.attestation import create_device_attestation
from hiro_commons.log import Logger

from hirocli.constants import DEVICE_ID_PREFIX, DEVICE_ID_SUFFIX_LENGTH
from hirocli.domain.config import Config, mark_connected, mark_disconnected
from hirocli.domain.pairing import (
    ApprovedDevice,
    clear_pairing_session,
    load_pairing_session,
    upsert_approved_device,
)

if TYPE_CHECKING:
    from hirocli.runtime.channel_event_handler import ChannelEventHandler
    from hirocli.runtime.channel_manager import ChannelManager

log = Logger.get("INFRA")


class InfraEventHandlers:
    """Handles infrastructure channel events: pairing, gateway connectivity."""

    def __init__(
        self,
        workspace_path: Path,
        config: Config,
        desktop_private_key: Ed25519PrivateKey,
    ) -> None:
        self._workspace_path = workspace_path
        self._config = config
        self._desktop_private_key = desktop_private_key
        self._channel_manager: ChannelManager | None = None

    def set_channel_manager(self, cm: ChannelManager) -> None:
        self._channel_manager = cm

    def register_all(self, handler: ChannelEventHandler) -> None:
        handler.register("pairing_request", self.handle_pairing_request)
        handler.register("gateway_connected", self.handle_gateway_connected)
        handler.register("gateway_disconnected", self.handle_gateway_disconnected)

    async def handle_pairing_request(self, data: dict[str, Any]) -> None:
        if self._channel_manager is None:
            return
        request_id = data.get("request_id")
        pairing_code = data.get("pairing_code")
        device_public_key = data.get("device_public_key")
        device_name_raw = data.get("device_name")
        device_name = device_name_raw if isinstance(device_name_raw, str) and device_name_raw else None

        if not isinstance(request_id, str) or not request_id:
            return
        if not isinstance(pairing_code, str) or not pairing_code:
            await self._channel_manager.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "invalid_pairing_code"},
            )
            return
        if not isinstance(device_public_key, str) or not device_public_key:
            await self._channel_manager.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "invalid_device_public_key"},
            )
            return

        session = load_pairing_session(self._workspace_path)
        if session is None:
            await self._channel_manager.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "no_active_pairing_session"},
            )
            return

        if (not session.is_valid()) or (session.code != pairing_code):
            await self._channel_manager.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "pairing_code_invalid_or_expired"},
            )
            return

        device_id = f"{DEVICE_ID_PREFIX}{uuid.uuid4().hex[:DEVICE_ID_SUFFIX_LENGTH]}"
        attestation = create_device_attestation(
            self._desktop_private_key,
            device_id=device_id,
            device_public_key_b64=device_public_key,
            expires_days=self._config.attestation_expires_days,
        )
        blob = json.loads(attestation["blob"])
        expires_at_raw = blob.get("expires_at")
        expires_at = None
        if isinstance(expires_at_raw, str):
            try:
                expires_at = datetime.fromisoformat(
                    expires_at_raw.replace("Z", "+00:00")
                ).astimezone(UTC)
            except Exception:
                expires_at = None

        upsert_approved_device(
            self._workspace_path,
            ApprovedDevice(
                device_id=device_id,
                device_public_key=device_public_key,
                paired_at=datetime.now(UTC),
                expires_at=expires_at,
                metadata={"source": "gateway_pairing"},
                device_name=device_name,
            ),
        )
        clear_pairing_session(self._workspace_path)
        await self._channel_manager.send_event_to_channel(
            "devices", "pairing_response",
            {
                "request_id": request_id,
                "status": "approved",
                "device_id": device_id,
                "attestation": attestation,
            },
        )

    async def handle_gateway_connected(self, data: dict[str, Any]) -> None:
        gateway_url = str(data.get("gateway_url") or self._config.gateway_url)
        mark_connected(self._workspace_path, gateway_url)

    async def handle_gateway_disconnected(self, data: dict[str, Any]) -> None:
        mark_disconnected(self._workspace_path)
