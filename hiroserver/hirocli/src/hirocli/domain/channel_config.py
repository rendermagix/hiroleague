"""Channel plugin configuration management.

All functions are workspace-scoped — they accept workspace_path: Path.
Config is stored in the channel_plugins table of workspace.db.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.process import find_workspace_root

from .db import db_path, ensure_db

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """Persisted configuration for one channel plugin."""

    name: str
    enabled: bool = True
    # Shell command used to start the plugin process.
    # hirocli appends ["--hiro-ws", <url>] automatically.
    # Defaults to ["hiro-channel-<name>"] if empty.
    command: list[str] = field(default_factory=list)
    # Arbitrary channel-specific settings (API keys, etc.).
    # Pushed to the plugin via channel.configure on connect.
    config: dict[str, Any] = field(default_factory=dict)
    # If set, the command is run via `uv run --directory <workspace_dir>`.
    # Populated automatically by `hirocli channel setup` when it detects
    # a uv workspace in the current directory tree.  Leave empty for
    # plugins installed as uv tools (they are already on PATH).
    workspace_dir: str = ""

    def effective_command(self) -> list[str]:
        base = self.command if self.command else [f"hiro-channel-{self.name}"]
        if self.workspace_dir:
            if self._should_use_module_launcher(base):
                module_name = f"hiro_channel_{self.name.replace('-', '_')}.main"
                return [
                    "uv", "run", "--directory", self.workspace_dir,
                    "python", "-m", module_name,
                ]
            return ["uv", "run", "--directory", self.workspace_dir] + base
        return base

    def _should_use_module_launcher(self, base: list[str]) -> bool:
        if sys.platform != "win32":
            return False
        return base == [f"hiro-channel-{self.name}"]


# ---------------------------------------------------------------------------
# CRUD — backed by workspace.db channel_plugins table
# ---------------------------------------------------------------------------

def load_channel_config(workspace_path: Path, name: str) -> ChannelConfig | None:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM channel_plugins WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        try:
            return _row_to_config(row)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Corrupt channel_plugins row (name=%r): %s", name, exc)
            return None


def save_channel_config(workspace_path: Path, cfg: ChannelConfig) -> None:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.execute(
            """
            INSERT INTO channel_plugins (name, enabled, command, config, workspace_dir)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                enabled       = excluded.enabled,
                command       = excluded.command,
                config        = excluded.config,
                workspace_dir = excluded.workspace_dir
            """,
            (
                cfg.name,
                int(cfg.enabled),
                json.dumps(cfg.command),
                json.dumps(cfg.config),
                cfg.workspace_dir,
            ),
        )
        conn.commit()


def list_channel_configs(workspace_path: Path) -> list[ChannelConfig]:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM channel_plugins ORDER BY name"
        ).fetchall()
        configs: list[ChannelConfig] = []
        for row in rows:
            try:
                configs.append(_row_to_config(row))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning(
                    "Skipping corrupt channel_plugins row (name=%r): %s",
                    row["name"],
                    exc,
                )
        return configs


def list_enabled_channels(workspace_path: Path) -> list[ChannelConfig]:
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM channel_plugins WHERE enabled = 1 ORDER BY name"
        ).fetchall()
        configs: list[ChannelConfig] = []
        for row in rows:
            try:
                configs.append(_row_to_config(row))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning(
                    "Skipping corrupt channel_plugins row (name=%r): %s",
                    row["name"],
                    exc,
                )
        return configs


def delete_channel_config(workspace_path: Path, name: str) -> bool:
    """Delete a channel_plugins row by name. Returns True if a row was removed."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        cursor = conn.execute(
            "DELETE FROM channel_plugins WHERE name = ?", (name,)
        )
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_config(row: sqlite3.Row) -> ChannelConfig:
    return ChannelConfig(
        name=row["name"],
        enabled=bool(row["enabled"]),
        command=json.loads(row["command"] or "[]"),
        config=json.loads(row["config"] or "{}"),
        workspace_dir=row["workspace_dir"] or "",
    )
