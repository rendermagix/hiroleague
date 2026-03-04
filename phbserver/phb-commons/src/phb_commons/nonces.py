"""Nonce generation helpers."""

from __future__ import annotations

import secrets


def generate_nonce() -> str:
    """Create a random challenge nonce encoded as hex."""
    return secrets.token_hex(32)
