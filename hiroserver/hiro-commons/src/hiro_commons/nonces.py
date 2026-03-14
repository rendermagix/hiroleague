"""Nonce generation helpers."""

from __future__ import annotations

import secrets

from .constants.domain import NONCE_BYTE_LENGTH


def generate_nonce() -> str:
    """Create a random challenge nonce encoded as hex."""
    return secrets.token_hex(NONCE_BYTE_LENGTH)
