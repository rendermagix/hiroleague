"""Workspace registry for phbcli.

Registry location (per platform):
  Windows:  %LOCALAPPDATA%\\phbcli\\registry.json
  macOS:    ~/Library/Application Support/phbcli/registry.json
  Linux:    ~/.local/share/phbcli/registry.json

Each workspace is a self-contained directory holding config, keys, channels,
logs, and PID files.

Port allocation — 3 ports per slot, starting at port_range_start (default 18080):
  http_port    = port_range_start + slot * 3
  plugin_port  = port_range_start + slot * 3 + 1
  gateway_port = port_range_start + slot * 3 + 2

Example (default port_range_start=18080):
  slot 0 → http=18080, plugin=18081, gateway=18082
  slot 1 → http=18083, plugin=18084, gateway=18085
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import BaseModel


class WorkspaceError(Exception):
    pass


class WorkspaceEntry(BaseModel):
    name: str
    path: str
    port_slot: int


class WorkspaceRegistry(BaseModel):
    default_workspace: str = "default"
    port_range_start: int = 18080
    workspaces: dict[str, WorkspaceEntry] = {}


# ---------------------------------------------------------------------------
# Platform paths
# ---------------------------------------------------------------------------

def _app_data_dir() -> Path:
    return Path(user_data_dir("phbcli", appauthor=False))


def registry_path() -> Path:
    return _app_data_dir() / "registry.json"


def default_workspace_path(name: str) -> Path:
    return _app_data_dir() / "workspaces" / name


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def http_port_for(registry: WorkspaceRegistry, slot: int) -> int:
    return registry.port_range_start + slot * 3


def plugin_port_for(registry: WorkspaceRegistry, slot: int) -> int:
    return registry.port_range_start + slot * 3 + 1


def gateway_port_for(registry: WorkspaceRegistry, slot: int) -> int:
    return registry.port_range_start + slot * 3 + 2


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
# Resolution
# ---------------------------------------------------------------------------

def resolve_workspace(name: str | None = None) -> tuple[WorkspaceEntry, WorkspaceRegistry]:
    """Resolve a workspace entry.

    Resolution order: name arg → PHB_WORKSPACE env var → registry default.
    Raises WorkspaceError if the workspace cannot be found.
    """
    registry = load_registry()
    target = name or os.environ.get("PHB_WORKSPACE") or registry.default_workspace

    if not registry.workspaces:
        raise WorkspaceError(
            "No workspaces configured. Run 'phbcli workspace create' first."
        )

    if not target or target not in registry.workspaces:
        available = ", ".join(registry.workspaces.keys())
        raise WorkspaceError(
            f"Workspace '{target}' not found. Available: {available}"
        )

    return registry.workspaces[target], registry


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

    if name in registry.workspaces:
        raise WorkspaceError(f"Workspace '{name}' already exists.")

    slot = next_free_slot(registry)
    workspace_path = path or default_workspace_path(name)
    workspace_path.mkdir(parents=True, exist_ok=True)

    entry = WorkspaceEntry(
        name=name,
        path=str(workspace_path),
        port_slot=slot,
    )
    registry.workspaces[name] = entry

    # Auto-set as default if this is the first workspace.
    if len(registry.workspaces) == 1:
        registry.default_workspace = name

    save_registry(registry)
    return entry, registry


def remove_workspace(name: str, *, purge: bool = False) -> None:
    """Remove a workspace from the registry.

    If purge=True, also deletes the workspace folder from disk.
    Raises WorkspaceError if the workspace does not exist.
    """
    registry = load_registry()

    if name not in registry.workspaces:
        raise WorkspaceError(f"Workspace '{name}' not found.")

    entry = registry.workspaces.pop(name)

    if registry.default_workspace == name:
        remaining = list(registry.workspaces.keys())
        registry.default_workspace = remaining[0] if remaining else ""

    save_registry(registry)

    if purge:
        workspace_path = Path(entry.path)
        if workspace_path.exists():
            shutil.rmtree(workspace_path, ignore_errors=True)


def set_default_workspace(name: str) -> None:
    """Set the default workspace. Raises WorkspaceError if not found."""
    registry = load_registry()
    if name not in registry.workspaces:
        raise WorkspaceError(f"Workspace '{name}' not found.")
    registry.default_workspace = name
    save_registry(registry)
