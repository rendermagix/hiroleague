"""Agent configuration management for hirocli.

All functions are workspace-scoped — they accept workspace_path: Path.
Data is stored in the agents table of workspace.db.

A workspace has exactly one default agent (is_default = 1).  On first access
the row is created with built-in defaults; subsequent reads/writes update that
single row.  The multi-agent schema is in place for the future — callers that
only know about one agent continue to work unchanged.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from hiro_commons.timestamps import utc_iso, utc_now

from .db import db_path, ensure_db

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a helpful home assistant running on Hiro.
Answer questions concisely and helpfully.
"""

_DEFAULT_AGENT_NAME = "default"


class AgentConfig(BaseModel):
    """LLM provider and generation settings for the agent."""

    provider: str = "openai"
    model: str = "gpt-4.1-mini"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)

    @property
    def model_string(self) -> str:
        """Return the 'provider:model' identifier used by init_chat_model."""
        return f"{self.provider}:{self.model}"


# ---------------------------------------------------------------------------
# I/O — backed by workspace.db agents table
# ---------------------------------------------------------------------------

def load_agent_config(workspace_path: Path) -> AgentConfig:
    """Load the default agent config from workspace.db, creating it if absent."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM agents WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if row is None:
            # first boot: seed the default agent row and return defaults
            _insert_default_agent(conn)
            return AgentConfig()
        return AgentConfig(
            provider=row["provider"],
            model=row["model"],
            temperature=row["temperature"],
            max_tokens=row["max_tokens"],
        )


def save_agent_config(workspace_path: Path, config: AgentConfig) -> None:
    """Persist LLM settings for the default agent."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id FROM agents WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if row is None:
            _insert_default_agent(conn, config=config)
        else:
            conn.execute(
                """
                UPDATE agents
                SET provider = ?, model = ?, temperature = ?, max_tokens = ?
                WHERE id = ?
                """,
                (config.provider, config.model, config.temperature, config.max_tokens, row["id"]),
            )
            conn.commit()


def load_system_prompt(workspace_path: Path) -> str:
    """Load the system prompt for the default agent, seeding defaults if absent."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT system_prompt FROM agents WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if row is None:
            _insert_default_agent(conn)
            return _DEFAULT_SYSTEM_PROMPT.strip()
        prompt = row["system_prompt"] or ""
        return (prompt if prompt else _DEFAULT_SYSTEM_PROMPT).strip()


def save_system_prompt(workspace_path: Path, prompt: str) -> None:
    """Persist a new system prompt for the default agent."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        if not conn.execute(
            "SELECT 1 FROM agents WHERE is_default = 1"
        ).fetchone():
            _insert_default_agent(conn)
        conn.execute(
            "UPDATE agents SET system_prompt = ? WHERE is_default = 1",
            (prompt.strip(),),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _insert_default_agent(
    conn: sqlite3.Connection,
    config: AgentConfig | None = None,
) -> None:
    """Insert the default agent row with built-in defaults."""
    cfg = config or AgentConfig()
    conn.execute(
        """
        INSERT INTO agents
            (id, name, is_default, provider, model, temperature, max_tokens, system_prompt, created_at)
        VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            _DEFAULT_AGENT_NAME,
            cfg.provider,
            cfg.model,
            cfg.temperature,
            cfg.max_tokens,
            _DEFAULT_SYSTEM_PROMPT.strip(),
            utc_iso(utc_now()),
        ),
    )
    conn.commit()
    logger.info("Created default agent row in workspace.db")
