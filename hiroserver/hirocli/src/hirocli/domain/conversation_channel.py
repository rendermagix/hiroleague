"""Conversation channel CRUD — workspace.db conversation_channels table.

A ConversationChannel is the metadata record for one persistent conversation
thread.  Its id is a UUID that doubles as the JSONL filename
(<workspace>/conversations/<id>.jsonl) and the LangGraph thread_id.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from pydantic import BaseModel

from hiro_commons.timestamps import utc_iso, utc_now

from .db import db_path, ensure_db


class ConversationChannel(BaseModel):
    """Metadata for a single conversation thread."""

    id: str
    name: str
    type: str = "direct"
    agent_id: str | None = None
    created_at: str
    last_message_at: str | None = None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_channel(
    workspace_path: Path,
    name: str,
    *,
    channel_type: str = "direct",
    agent_id: str | None = None,
) -> ConversationChannel:
    """Insert a new conversation channel row and return it.

    Raises sqlite3.IntegrityError if a channel with the same name already exists.
    Use get_or_create_channel for idempotent lookup-or-create.
    """
    ensure_db(workspace_path)
    channel = ConversationChannel(
        id=str(uuid.uuid4()),
        name=name,
        type=channel_type,
        agent_id=agent_id,
        created_at=utc_iso(utc_now()),
    )
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            """
            INSERT INTO conversation_channels
                (id, name, type, agent_id, created_at, last_message_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel.id, channel.name, channel.type, channel.agent_id,
             channel.created_at, channel.last_message_at),
        )
        conn.commit()
    return channel


def get_channel(workspace_path: Path, channel_id: str) -> ConversationChannel | None:
    """Return a channel by id, or None if not found."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM conversation_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return _row_to_channel(row) if row else None


def list_channels(workspace_path: Path) -> list[ConversationChannel]:
    """Return all channels ordered by most-recently-active first."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM conversation_channels
            ORDER BY COALESCE(last_message_at, created_at) DESC
            """
        ).fetchall()
        return [_row_to_channel(row) for row in rows]


def get_or_create_channel(
    workspace_path: Path,
    name: str,
    *,
    channel_type: str = "direct",
    agent_id: str | None = None,
) -> ConversationChannel:
    """Return the channel with the given name, creating it if it does not exist.

    The entire operation runs inside a single connection: INSERT OR IGNORE seeds
    a new row if the name is absent, then SELECT fetches whatever row now owns
    that name.  This is safe for the single-process server and eliminates the
    two-connection check-then-act race in the previous implementation.
    """
    ensure_db(workspace_path)
    new_id = str(uuid.uuid4())
    now = utc_iso(utc_now())
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_channels
                (id, name, type, agent_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id, name, channel_type, agent_id, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM conversation_channels WHERE name = ?", (name,)
        ).fetchone()
        return _row_to_channel(row)


def delete_channel(workspace_path: Path, channel_id: str) -> bool:
    """Delete a channel row by id. Returns True if a row was removed."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(
            "DELETE FROM conversation_channels WHERE id = ?", (channel_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


def update_last_message_at(
    workspace_path: Path,
    channel_id: str,
    ts: str | None = None,
) -> None:
    """Stamp last_message_at on a channel row (defaults to now)."""
    ensure_db(workspace_path)
    timestamp = ts or utc_iso(utc_now())
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            "UPDATE conversation_channels SET last_message_at = ? WHERE id = ?",
            (timestamp, channel_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_channel(row: sqlite3.Row) -> ConversationChannel:
    return ConversationChannel(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        agent_id=row["agent_id"],
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
    )
