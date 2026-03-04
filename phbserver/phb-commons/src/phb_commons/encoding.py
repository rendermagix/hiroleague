"""Encoding helpers shared across PHB services."""

from __future__ import annotations

import base64


def b64_encode(data: bytes) -> str:
    """Encode bytes to base64 ASCII."""
    return base64.b64encode(data).decode("ascii")


def b64_decode(data: str) -> bytes:
    """Decode base64 ASCII to bytes with strict validation."""
    return base64.b64decode(data.encode("ascii"), validate=True)
