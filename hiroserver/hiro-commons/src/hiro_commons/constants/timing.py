"""Timing and log-rotation constants shared across all Hiro packages."""

from __future__ import annotations

DEFAULT_PING_INTERVAL_SECONDS: float = 30.0
DEFAULT_AUTH_TIMEOUT_SECONDS: float = 30.0
DEFAULT_PAIRING_WAIT_SECONDS: float = 120.0

LOG_ROTATION_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
LOG_ROTATION_BACKUP_COUNT: int = 5
