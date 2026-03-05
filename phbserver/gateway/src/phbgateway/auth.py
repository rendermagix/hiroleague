"""Authentication helpers for gateway connection handshakes."""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from phb_commons.attestation import verify_device_attestation
from phb_commons.keys import load_public_key_b64, public_key_to_b64
from phb_commons.signing import verify_signature
from phb_commons.timestamps import utc_now


@dataclass
class AuthResult:
    ok: bool
    device_id: str | None = None
    reason: str | None = None


class GatewayAuthManager:
    """Holds desktop trust root and validates desktop/device auth payloads."""

    def __init__(
        self,
        *,
        desktop_public_key_b64: str,
    ) -> None:
        self._desktop_public_key: Ed25519PublicKey = load_public_key_b64(desktop_public_key_b64)

    def is_claimed(self) -> bool:
        return True

    def desktop_public_key_b64(self) -> str | None:
        return public_key_to_b64(self._desktop_public_key)

    def verify_desktop_auth(self, *, nonce_hex: str, nonce_signature_b64: str) -> AuthResult:
        if not verify_signature(self._desktop_public_key, bytes.fromhex(nonce_hex), nonce_signature_b64):
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
        try:
            attestation = verify_device_attestation(
                self._desktop_public_key,
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
