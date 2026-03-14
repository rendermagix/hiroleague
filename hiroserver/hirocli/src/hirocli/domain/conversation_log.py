"""Conversation message log — append-only JSONL files.

Each conversation thread writes to:
    <workspace>/conversations/<channel_id>.jsonl

One JSON object per line, appended sequentially.  The file is never
rewritten — only appended to — so it can be tailed, grepped, or fed into
a vector store without transformation.

File I/O is offloaded to a thread via asyncio.to_thread so the event loop
is never blocked, even when files grow large.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from hiro_commons.constants.storage import CONVERSATIONS_DIR


def _log_dir(workspace_path: Path) -> Path:
    return workspace_path / CONVERSATIONS_DIR


def _log_file(workspace_path: Path, channel_id: str) -> Path:
    return _log_dir(workspace_path) / f"{channel_id}.jsonl"


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def append_message(
    workspace_path: Path,
    channel_id: str,
    message: dict,
) -> None:
    """Append one message record as a JSON line to the channel's JSONL file."""
    log_file = _log_file(workspace_path, channel_id)
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    await asyncio.to_thread(_sync_append, log_file, line)


async def read_messages(
    workspace_path: Path,
    channel_id: str,
    limit: int = 100,
) -> list[dict]:
    """Return up to *limit* most-recent messages from the channel's JSONL file."""
    log_file = _log_file(workspace_path, channel_id)
    return await asyncio.to_thread(_sync_read, log_file, limit)


# ---------------------------------------------------------------------------
# Sync helpers (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------

def _sync_append(log_file: Path, line: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _sync_read(log_file: Path, limit: int) -> list[dict]:
    if not log_file.exists():
        return []
    lines = log_file.read_text(encoding="utf-8").splitlines()
    tail = lines[-limit:] if len(lines) > limit else lines
    messages: list[dict] = []
    for raw in tail:
        raw = raw.strip()
        if not raw:
            continue
        try:
            messages.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return messages
