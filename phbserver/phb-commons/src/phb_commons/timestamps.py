"""UTC timestamp helpers shared across PHB services."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


def utc_iso(value: datetime) -> str:
    """Format datetime as ISO 8601 UTC using trailing Z."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso8601_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp and normalize to UTC."""
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(UTC)
