"""Pairing session and approved-device persistence helpers.

All functions are workspace-scoped — they accept workspace_path: Path.

Pairing sessions are short-lived and read at boot; they stay as a JSON file:
  <workspace>/pairing_session.json

Approved devices are durable structured records; they are stored in the
devices table of workspace.db.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from phb_commons.constants.domain import DEFAULT_PAIRING_CODE_LENGTH, DEFAULT_PAIRING_CODE_TTL_SECONDS
from phb_commons.constants.storage import PAIRING_SESSION_FILENAME
from phb_commons.timestamps import utc_iso

from .db import db_path, ensure_db

logger = logging.getLogger(__name__)


class PairingSession(BaseModel):
    code: str
    created_at: datetime
    ttl_seconds: int

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.ttl_seconds)

    def is_valid(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current < self.expires_at

    def remaining_seconds(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        delta = self.expires_at - current
        return max(0, int(delta.total_seconds()))


class ApprovedDevice(BaseModel):
    device_id: str
    device_public_key: str
    paired_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    device_name: str | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _pairing_session_file(workspace_path: Path) -> Path:
    return workspace_path / PAIRING_SESSION_FILENAME


# ---------------------------------------------------------------------------
# Pairing code
# ---------------------------------------------------------------------------

def generate_pairing_code(length: int = DEFAULT_PAIRING_CODE_LENGTH) -> str:
    if length <= 0:
        raise ValueError("pairing code length must be > 0")
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def create_pairing_session(code_length: int = DEFAULT_PAIRING_CODE_LENGTH, ttl_seconds: int = DEFAULT_PAIRING_CODE_TTL_SECONDS) -> PairingSession:
    if ttl_seconds <= 0:
        raise ValueError("pairing code ttl_seconds must be > 0")
    return PairingSession(
        code=generate_pairing_code(code_length),
        created_at=datetime.now(UTC),
        ttl_seconds=ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Pairing session I/O — file-backed (short-lived, read at boot)
# ---------------------------------------------------------------------------

def load_pairing_session(workspace_path: Path) -> PairingSession | None:
    workspace_path.mkdir(parents=True, exist_ok=True)
    path = _pairing_session_file(workspace_path)
    if not path.exists():
        return None
    try:
        session = PairingSession.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not session.is_valid():
        clear_pairing_session(workspace_path)
        return None
    return session


def save_pairing_session(workspace_path: Path, session: PairingSession) -> None:
    workspace_path.mkdir(parents=True, exist_ok=True)
    _pairing_session_file(workspace_path).write_text(
        session.model_dump_json(indent=2), encoding="utf-8"
    )


def clear_pairing_session(workspace_path: Path) -> None:
    try:
        _pairing_session_file(workspace_path).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Approved devices I/O — backed by workspace.db devices table
# ---------------------------------------------------------------------------

def load_approved_devices(workspace_path: Path) -> list[ApprovedDevice]:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM devices").fetchall()
        devices: list[ApprovedDevice] = []
        for row in rows:
            try:
                devices.append(
                    ApprovedDevice(
                        device_id=row["device_id"],
                        device_public_key=row["device_public_key"],
                        paired_at=datetime.fromisoformat(row["paired_at"]),
                        expires_at=(
                            datetime.fromisoformat(row["expires_at"])
                            if row["expires_at"]
                            else None
                        ),
                        metadata=json.loads(row["metadata"] or "{}"),
                        device_name=row["device_name"] or None,
                    )
                )
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning(
                    "Skipping corrupt device row (device_id=%r): %s",
                    row["device_id"] if row["device_id"] else "?",
                    exc,
                )
        return devices


def save_approved_devices(workspace_path: Path, devices: list[ApprovedDevice]) -> None:
    """Replace the full device list in workspace.db."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute("DELETE FROM devices")
        for device in devices:
            conn.execute(
                """
                INSERT INTO devices (device_id, device_public_key, paired_at, expires_at, metadata, device_name)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    device.device_id,
                    device.device_public_key,
                    utc_iso(device.paired_at),
                    utc_iso(device.expires_at) if device.expires_at else None,
                    json.dumps(device.metadata),
                    device.device_name,
                ),
            )
        conn.commit()


def upsert_approved_device(workspace_path: Path, device: ApprovedDevice) -> None:
    """Insert or update a single approved device row."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            """
            INSERT INTO devices (device_id, device_public_key, paired_at, expires_at, metadata, device_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                device_public_key = excluded.device_public_key,
                paired_at         = excluded.paired_at,
                expires_at        = excluded.expires_at,
                metadata          = excluded.metadata,
                device_name       = excluded.device_name
            """,
            (
                device.device_id,
                device.device_public_key,
                utc_iso(device.paired_at),
                utc_iso(device.expires_at) if device.expires_at else None,
                json.dumps(device.metadata),
                device.device_name,
            ),
        )
        conn.commit()


def revoke_approved_device(workspace_path: Path, device_id: str) -> bool:
    """Delete a device row by device_id. Returns True if a row was removed."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(
            "DELETE FROM devices WHERE device_id = ?", (device_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
