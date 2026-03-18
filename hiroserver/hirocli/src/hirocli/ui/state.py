"""Shared mutable state for the admin UI.

Holds values set during startup that page modules need to read at request time.
Using plain module-level variables avoids circular imports — run.py writes here,
pages/*.py read here.

workspace_path / workspace_id / workspace_name identify the workspace whose
server process is hosting this admin UI.  Pages use these to prevent actions
(stop, remove) that would kill the running UI.
"""

from __future__ import annotations

from pathlib import Path

log_dir: Path | None = None
gateway_log_dir: Path | None = None
workspace_path: Path | None = None
workspace_id: str | None = None
workspace_name: str | None = None
