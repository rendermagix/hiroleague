"""Workspace database module.

Manages workspace.db (SQLite) — the single authoritative store for all
structured entity data: agents, conversation_channels, devices, channel_plugins.

Two interfaces are provided:
- ensure_db / db_path — synchronous helpers used by domain functions and CLI
  commands that run outside an async context.
- init_db / get_db — async interface (aiosqlite) used at server startup and
  wherever a long-lived async connection is needed (e.g. LangGraph checkpointer
  wiring in server_process.py).

Schema evolution policy
-----------------------
Both ensure_db and init_db run two passes on first call per process:

1. CREATE TABLE IF NOT EXISTS — creates all tables on a fresh database.
2. PRAGMA table_info + ALTER TABLE ADD COLUMN — adds any column listed in
   _EXPECTED_COLUMNS that is absent from the actual table.

To add a column: append one entry to _EXPECTED_COLUMNS and to the matching
CREATE TABLE statement. Never remove entries from _EXPECTED_COLUMNS — old
databases are upgraded automatically on next startup, no version counter needed.

Every new column must be nullable or have a DEFAULT so ALTER TABLE succeeds on
existing rows.  Enforce NOT NULL without a default only on primary keys and
columns always set by application code at insert time.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from hiro_commons.constants.storage import CONVERSATIONS_DIR, WORKSPACE_DB_FILENAME

# Per-process cache: paths for which ensure_db has already run successfully.
# Keyed by the resolved string workspace path.
_initialized: set[str] = set()

# ---------------------------------------------------------------------------
# DDL — CREATE TABLE statements for fresh databases
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS agents (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
        is_default    INTEGER NOT NULL DEFAULT 0,
        provider      TEXT NOT NULL,
        model         TEXT NOT NULL,
        temperature   REAL NOT NULL DEFAULT 0.7,
        max_tokens    INTEGER NOT NULL DEFAULT 1024,
        system_prompt TEXT NOT NULL DEFAULT '',
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_channels (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL UNIQUE,
        type            TEXT NOT NULL DEFAULT 'direct',
        agent_id        TEXT REFERENCES agents(id),
        created_at      TEXT NOT NULL,
        last_message_at TEXT
    )
    """,
    # Unique index on conversation_channels.name for existing databases that
    # were created before the UNIQUE constraint was added to the DDL above.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cc_name ON conversation_channels(name)",
    """
    CREATE TABLE IF NOT EXISTS devices (
        device_id          TEXT PRIMARY KEY,
        device_public_key  TEXT NOT NULL,
        paired_at          TEXT NOT NULL,
        expires_at         TEXT,
        metadata           TEXT NOT NULL DEFAULT '{}',
        device_name        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channel_plugins (
        name          TEXT PRIMARY KEY,
        enabled       INTEGER NOT NULL DEFAULT 1,
        command       TEXT NOT NULL DEFAULT '[]',
        config        TEXT NOT NULL DEFAULT '{}',
        workspace_dir TEXT NOT NULL DEFAULT ''
    )
    """,
]

# ---------------------------------------------------------------------------
# Expected columns — drives the introspection-based upgrade pass
#
# List every non-primary-key column for every table.
# Each entry: (table_name, column_name, ALTER TABLE compatible definition)
#
# Rules:
# - Never remove an entry — old databases are upgraded on next startup.
# - Every definition must be nullable or have a DEFAULT (required for
#   ALTER TABLE ADD COLUMN on existing rows).
# - When adding a new column: append here AND to the CREATE TABLE above.
# ---------------------------------------------------------------------------

_EXPECTED_COLUMNS: list[tuple[str, str, str]] = [
    # agents
    ("agents", "name",          "TEXT NOT NULL DEFAULT ''"),
    ("agents", "is_default",    "INTEGER NOT NULL DEFAULT 0"),
    ("agents", "provider",      "TEXT NOT NULL DEFAULT 'openai'"),
    ("agents", "model",         "TEXT NOT NULL DEFAULT 'gpt-4.1-mini'"),
    ("agents", "temperature",   "REAL NOT NULL DEFAULT 0.7"),
    ("agents", "max_tokens",    "INTEGER NOT NULL DEFAULT 1024"),
    ("agents", "system_prompt", "TEXT NOT NULL DEFAULT ''"),
    ("agents", "created_at",    "TEXT NOT NULL DEFAULT ''"),
    # conversation_channels
    ("conversation_channels", "name",            "TEXT NOT NULL DEFAULT ''"),
    ("conversation_channels", "type",            "TEXT NOT NULL DEFAULT 'direct'"),
    ("conversation_channels", "agent_id",        "TEXT"),
    ("conversation_channels", "created_at",      "TEXT NOT NULL DEFAULT ''"),
    ("conversation_channels", "last_message_at", "TEXT"),
    # devices
    ("devices", "device_public_key", "TEXT NOT NULL DEFAULT ''"),
    ("devices", "paired_at",         "TEXT NOT NULL DEFAULT ''"),
    ("devices", "expires_at",        "TEXT"),
    ("devices", "metadata",          "TEXT NOT NULL DEFAULT '{}'"),
    ("devices", "device_name",       "TEXT"),
    # channel_plugins
    ("channel_plugins", "enabled",       "INTEGER NOT NULL DEFAULT 1"),
    ("channel_plugins", "command",       "TEXT NOT NULL DEFAULT '[]'"),
    ("channel_plugins", "config",        "TEXT NOT NULL DEFAULT '{}'"),
    ("channel_plugins", "workspace_dir", "TEXT NOT NULL DEFAULT ''"),
]


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def db_path(workspace_path: Path) -> Path:
    """Return the absolute path to workspace.db inside *workspace_path*."""
    return workspace_path / WORKSPACE_DB_FILENAME


# ---------------------------------------------------------------------------
# Synchronous interface — used by domain functions and CLI commands
# ---------------------------------------------------------------------------

def ensure_db(workspace_path: Path) -> None:
    """Create workspace.db, upgrade all tables, and ensure subdirectories (sync, idempotent).

    Runs the full setup only once per process per workspace path.  Subsequent
    calls are a no-op so calling ensure_db at the top of every domain function
    has no measurable overhead in production.

    Pass 1: CREATE TABLE IF NOT EXISTS for fresh databases.
    Pass 2: PRAGMA table_info + ALTER TABLE ADD COLUMN for existing databases
            that are missing columns introduced after initial creation.
    """
    key = str(workspace_path.resolve())
    if key in _initialized:
        return

    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / CONVERSATIONS_DIR).mkdir(exist_ok=True)

    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        for ddl in _DDL:
            conn.execute(ddl)

        # Add any columns that exist in _EXPECTED_COLUMNS but not in the table.
        # PRAGMA table_info is called once per table, not once per column.
        table_existing: dict[str, set[str]] = {}
        for table, col_name, col_def in _EXPECTED_COLUMNS:
            if table not in table_existing:
                table_existing[table] = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
            if col_name not in table_existing[table]:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                table_existing[table].add(col_name)

        conn.commit()

    _initialized.add(key)


# ---------------------------------------------------------------------------
# Async interface — used by the server process and LangGraph checkpointer
# ---------------------------------------------------------------------------

async def init_db(workspace_path: Path) -> aiosqlite.Connection:
    """Open workspace.db, ensure all tables exist, and return the open connection.

    Calls ensure_db synchronously first (fast — no-op after the first call per
    process) then opens the aiosqlite connection for async callers.

    The caller is responsible for closing the connection.
    Prefer get_db() as an async context manager for automatic cleanup.
    """
    ensure_db(workspace_path)
    return await aiosqlite.connect(str(db_path(workspace_path)))


@asynccontextmanager
async def get_db(workspace_path: Path):
    """Async context manager that opens workspace.db, ensures tables, and yields the connection."""
    conn = await init_db(workspace_path)
    try:
        yield conn
    finally:
        await conn.close()
