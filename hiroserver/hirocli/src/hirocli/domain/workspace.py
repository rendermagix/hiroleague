"""Workspace registry for hirocli.

Registry location (per platform):
  Windows:  %LOCALAPPDATA%\\hirocli\\registry.json
  macOS:    ~/Library/Application Support/hirocli/registry.json
  Linux:    ~/.local/share/hirocli/registry.json

Each workspace is a self-contained directory holding config, keys, channels,
logs, and PID files.

Identity model:
  Each workspace has an immutable UUID ``id`` (registry dict key, autostart
  task suffix) and a mutable ``name`` (display label, CLI convenience).
  Renaming only touches the ``name`` field — no cascading side-effects.

Port allocation — 4 ports per slot, starting at port_range_start (default 18080):
  http_port    = port_range_start + slot * 4
  plugin_port  = port_range_start + slot * 4 + 1
  (offset +2 is reserved)
  admin_port   = port_range_start + slot * 4 + 3

Example (default port_range_start=18080):
  slot 0 → http=18080, plugin=18081, (reserved=18082), admin=18083
  slot 1 → http=18084, plugin=18085, (reserved=18086), admin=18087
"""

from __future__ import annotations

import os
import shutil
import uuid as _uuid
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import BaseModel, Field

from hiro_commons.constants.network import PORT_OFFSET_ADMIN, PORT_OFFSET_PLUGIN, PORT_RANGE_START, PORTS_PER_SLOT
from hiro_commons.constants.storage import REGISTRY_FILENAME

from ..constants import APP_NAME, ENV_WORKSPACE


class WorkspaceError(Exception):
    pass


class WorkspaceEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    path: str
    port_slot: int


class WorkspaceRegistry(BaseModel):
    default_workspace: str = ""  # workspace *id* (not name)
    port_range_start: int = PORT_RANGE_START
    workspaces: dict[str, WorkspaceEntry] = {}  # keyed by workspace id


# ---------------------------------------------------------------------------
# Platform paths
# ---------------------------------------------------------------------------

def _app_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def registry_path() -> Path:
    return _app_data_dir() / REGISTRY_FILENAME


def default_workspace_path(name: str) -> Path:
    return _app_data_dir() / "workspaces" / name


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def http_port_for(registry: WorkspaceRegistry, slot: int) -> int:
    return registry.port_range_start + slot * PORTS_PER_SLOT


def plugin_port_for(registry: WorkspaceRegistry, slot: int) -> int:
    return registry.port_range_start + slot * PORTS_PER_SLOT + PORT_OFFSET_PLUGIN


def admin_port_for(registry: WorkspaceRegistry, slot: int) -> int:
    return registry.port_range_start + slot * PORTS_PER_SLOT + PORT_OFFSET_ADMIN


def next_free_slot(registry: WorkspaceRegistry) -> int:
    used = {e.port_slot for e in registry.workspaces.values()}
    slot = 0
    while slot in used:
        slot += 1
    return slot


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------

def load_registry() -> WorkspaceRegistry:
    rp = registry_path()
    if rp.exists():
        try:
            return WorkspaceRegistry.model_validate_json(rp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return WorkspaceRegistry()


def save_registry(registry: WorkspaceRegistry) -> None:
    rp = registry_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(registry.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _find_by_name(registry: WorkspaceRegistry, name: str) -> WorkspaceEntry | None:
    """Find a workspace by display name. Returns None if no match."""
    matches = [e for e in registry.workspaces.values() if e.name == name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(m.id[:8] for m in matches)
        raise WorkspaceError(
            f"Multiple workspaces named '{name}' (ids: {ids}). "
            "Use the workspace id instead."
        )
    return None


def _find_entry(registry: WorkspaceRegistry, identifier: str) -> WorkspaceEntry | None:
    """Find a workspace by id or name. Returns None if not found."""
    if identifier in registry.workspaces:
        return registry.workspaces[identifier]
    return _find_by_name(registry, identifier)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_workspace(identifier: str | None = None) -> tuple[WorkspaceEntry, WorkspaceRegistry]:
    """Resolve a workspace entry by id or name.

    Resolution order: identifier arg → HIRO_WORKSPACE env var → registry default.
    Raises WorkspaceError if the workspace cannot be found.
    """
    registry = load_registry()

    if not registry.workspaces:
        raise WorkspaceError(
            "No workspaces configured. Run 'hirocli workspace create' first."
        )

    target = identifier or os.environ.get(ENV_WORKSPACE) or registry.default_workspace

    if not target:
        available = ", ".join(e.name for e in registry.workspaces.values())
        raise WorkspaceError(
            f"No workspace specified and no default set. Available: {available}"
        )

    entry = _find_entry(registry, target)
    if entry is None:
        available = ", ".join(e.name for e in registry.workspaces.values())
        raise WorkspaceError(
            f"Workspace '{target}' not found. Available: {available}"
        )

    return entry, registry


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_workspace(
    name: str,
    *,
    path: Path | None = None,
) -> tuple[WorkspaceEntry, WorkspaceRegistry]:
    """Create a new workspace and add it to the registry.

    Returns (entry, updated_registry).  Raises WorkspaceError if the name
    is already taken.
    """
    registry = load_registry()

    if _find_by_name(registry, name) is not None:
        raise WorkspaceError(f"Workspace '{name}' already exists.")

    slot = next_free_slot(registry)
    workspace_path = path or default_workspace_path(name)
    workspace_path.mkdir(parents=True, exist_ok=True)

    entry = WorkspaceEntry(
        name=name,
        path=str(workspace_path),
        port_slot=slot,
    )
    registry.workspaces[entry.id] = entry

    if len(registry.workspaces) == 1:
        registry.default_workspace = entry.id

    save_registry(registry)
    return entry, registry


def remove_workspace(ws_id: str, *, purge: bool = False) -> None:
    """Remove a workspace from the registry by id.

    If purge=True, also deletes the workspace folder from disk.
    Raises WorkspaceError if the workspace does not exist.
    """
    registry = load_registry()

    if ws_id not in registry.workspaces:
        raise WorkspaceError(f"Workspace id '{ws_id}' not found.")

    entry = registry.workspaces.pop(ws_id)

    if registry.default_workspace == ws_id:
        remaining = list(registry.workspaces.keys())
        registry.default_workspace = remaining[0] if remaining else ""

    save_registry(registry)

    if purge:
        workspace_path = Path(entry.path)
        if workspace_path.exists():
            shutil.rmtree(workspace_path, ignore_errors=True)


def rename_workspace(ws_id: str, new_name: str) -> WorkspaceEntry:
    """Rename a workspace.  Only changes the display name in the registry."""
    registry = load_registry()

    if ws_id not in registry.workspaces:
        raise WorkspaceError(f"Workspace id '{ws_id}' not found.")

    existing = _find_by_name(registry, new_name)
    if existing is not None and existing.id != ws_id:
        raise WorkspaceError(f"A workspace named '{new_name}' already exists.")

    entry = registry.workspaces[ws_id]
    entry.name = new_name
    save_registry(registry)
    return entry


def set_default_workspace(ws_id: str) -> None:
    """Set the default workspace by id. Raises WorkspaceError if not found."""
    registry = load_registry()
    if ws_id not in registry.workspaces:
        raise WorkspaceError(f"Workspace id '{ws_id}' not found.")
    registry.default_workspace = ws_id
    save_registry(registry)
