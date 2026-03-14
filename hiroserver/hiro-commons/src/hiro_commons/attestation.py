"""Device attestation creation and verification helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .constants.domain import DEFAULT_ATTESTATION_EXPIRY_DAYS
from .signing import sign_bytes, verify_signature
from .timestamps import parse_iso8601_utc, utc_iso, utc_now


@dataclass(frozen=True)
class DeviceAttestation:
    """Validated device attestation payload."""

    device_id: str
    device_public_key_b64: str
    issued_at: datetime
    expires_at: datetime
    blob: str


def create_device_attestation(
    private_key: Ed25519PrivateKey,
    *,
    device_id: str,
    device_public_key_b64: str,
    expires_days: int = DEFAULT_ATTESTATION_EXPIRY_DAYS,
) -> dict[str, Any]:
    """Create and sign a canonical device attestation blob."""
    issued_at = utc_now()
    expires_at = issued_at + timedelta(days=expires_days)
    blob_obj = {
        "device_id": device_id,
        "device_public_key": device_public_key_b64,
        "issued_at": utc_iso(issued_at),
        "expires_at": utc_iso(expires_at),
    }
    blob = json.dumps(blob_obj, separators=(",", ":"), sort_keys=True)
    signature = sign_bytes(private_key, blob.encode("utf-8"))
    return {"blob": blob, "desktop_signature": signature}


def parse_device_attestation_blob(attestation_blob: str) -> DeviceAttestation:
    """Parse and validate a device attestation blob JSON."""
    try:
        blob: dict[str, Any] = json.loads(attestation_blob)
    except Exception as exc:
        raise ValueError("attestation blob is not valid JSON") from exc

    device_id = blob.get("device_id")
    device_public_key_b64 = blob.get("device_public_key")
    issued_at = blob.get("issued_at")
    expires_at = blob.get("expires_at")

    if not isinstance(device_id, str) or not device_id:
        raise ValueError("attestation missing device_id")
    if not isinstance(device_public_key_b64, str) or not device_public_key_b64:
        raise ValueError("attestation missing device_public_key")
    if not isinstance(expires_at, str) or not expires_at:
        raise ValueError("attestation missing expires_at")

    try:
        expires_at_dt = parse_iso8601_utc(expires_at)
    except Exception as exc:
        raise ValueError("attestation expires_at invalid") from exc

    if isinstance(issued_at, str) and issued_at:
        try:
            issued_at_dt = parse_iso8601_utc(issued_at)
        except Exception:
            issued_at_dt = utc_now()
    else:
        issued_at_dt = utc_now()

    return DeviceAttestation(
        device_id=device_id,
        device_public_key_b64=device_public_key_b64,
        issued_at=issued_at_dt,
        expires_at=expires_at_dt,
        blob=attestation_blob,
    )


def verify_device_attestation(
    root_public_key: Ed25519PublicKey,
    *,
    attestation_blob: str,
    desktop_signature_b64: str,
) -> DeviceAttestation:
    """Verify attestation signature and return validated attestation payload."""
    if not verify_signature(
        root_public_key,
        attestation_blob.encode("utf-8"),
        desktop_signature_b64,
    ):
        raise ValueError("attestation signature invalid")
    return parse_device_attestation_blob(attestation_blob)
