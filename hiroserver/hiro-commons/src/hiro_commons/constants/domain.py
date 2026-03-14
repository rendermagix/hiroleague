"""Domain-level defaults shared across all Hiro packages."""

from __future__ import annotations

DEFAULT_PAIRING_CODE_LENGTH: int = 6
DEFAULT_PAIRING_CODE_TTL_SECONDS: int = 300
DEFAULT_ATTESTATION_EXPIRY_DAYS: int = 30
NONCE_BYTE_LENGTH: int = 32
MANDATORY_CHANNEL_NAME: str = "devices"
DEFAULT_WORKSPACE_NAME: str = "default"
