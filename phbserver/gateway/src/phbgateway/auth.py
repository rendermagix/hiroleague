"""Authentication helpers for gateway connection handshakes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from phb_commons.attestation import verify_device_attestation
from phb_commons.keys import load_public_key_b64, public_key_to_b64
from phb_commons.signing import verify_signature
from phb_commons.timestamps import utc_iso, utc_now


@dataclass
class AuthResult:
    ok: bool
    device_id: str | None = None
    reason: str | None = None


class GatewayAuthManager:
    """Stores desktop trust root and validates desktop/device auth payloads."""

    def __init__(
        self,
        *,
        state_file: Path,
        desktop_public_key_b64: str | None = None,
    ) -> None:
        self._state_file = state_file
        self._desktop_public_key: Ed25519PublicKey | None = None

        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state_if_exists()

        if desktop_public_key_b64:
            self._desktop_public_key = load_public_key_b64(desktop_public_key_b64)
            self._save_state()

    def is_claimed(self) -> bool:
        return self._desktop_public_key is not None

    def desktop_public_key_b64(self) -> str | None:
        if self._desktop_public_key is None:
            return None
        return public_key_to_b64(self._desktop_public_key)

    def verify_desktop_claim(
        self,
        *,
        nonce_hex: str,
        public_key_b64: str,
        nonce_signature_b64: str,
    ) -> AuthResult:
        try:
            key = load_public_key_b64(public_key_b64)
            if not verify_signature(key, bytes.fromhex(nonce_hex), nonce_signature_b64):
                return AuthResult(ok=False, reason="desktop claim signature invalid")
        except Exception:
            return AuthResult(ok=False, reason="desktop claim signature invalid")

        if self._desktop_public_key is not None:
            # Idempotent claim from the same desktop key is accepted.
            if public_key_to_b64(self._desktop_public_key) != public_key_to_b64(key):
                return AuthResult(ok=False, reason="gateway already claimed by another desktop")
            return AuthResult(ok=True)

        self._desktop_public_key = key
        self._save_state()
        return AuthResult(ok=True)

    def verify_desktop_auth(self, *, nonce_hex: str, nonce_signature_b64: str) -> AuthResult:
        key = self._desktop_public_key
        if key is None:
            return AuthResult(ok=False, reason="gateway not claimed by desktop yet")
        if not verify_signature(key, bytes.fromhex(nonce_hex), nonce_signature_b64):
            return AuthResult(ok=False, reason="desktop signature invalid")
        return AuthResult(ok=True)

    def verify_device_auth(
        self,
        *,
        nonce_hex: str,
        attestation_blob: str,
        desktop_signature_b64: str,
        nonce_signature_b64: str,
    ) -> AuthResult:
        root_key = self._desktop_public_key
        if root_key is None:
            return AuthResult(ok=False, reason="gateway not claimed by desktop yet")

        try:
            attestation = verify_device_attestation(
                root_key,
                attestation_blob=attestation_blob,
                desktop_signature_b64=desktop_signature_b64,
            )
        except ValueError as exc:
            return AuthResult(ok=False, reason=str(exc))

        if attestation.expires_at <= utc_now():
            return AuthResult(ok=False, reason="attestation expired")

        try:
            device_key = load_public_key_b64(attestation.device_public_key_b64)
            if not verify_signature(device_key, bytes.fromhex(nonce_hex), nonce_signature_b64):
                return AuthResult(ok=False, reason="device nonce signature invalid")
        except Exception:
            return AuthResult(ok=False, reason="device nonce signature invalid")

        return AuthResult(ok=True, device_id=attestation.device_id)

    def _load_state_if_exists(self) -> None:
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
            public_key_b64 = payload.get("desktop_public_key")
            if isinstance(public_key_b64, str) and public_key_b64:
                self._desktop_public_key = load_public_key_b64(public_key_b64)
        except Exception:
            # Corrupt state should not crash startup; gateway can be re-claimed.
            self._desktop_public_key = None

    def _save_state(self) -> None:
        payload = {
            "desktop_public_key": self.desktop_public_key_b64(),
            "claimed_at": utc_iso(utc_now()),
        }
        self._state_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
