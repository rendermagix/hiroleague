"""Workspace management tools.

Seven operations: list, create, remove, update, show, get_public_key,
regenerate_key.
The CLI (commands/workspace.py) and the AI agent call these directly.

All tool parameters named ``workspace`` accept either a workspace name or
a workspace UUID id for resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.keys import generate_private_key, private_key_to_pem, public_key_to_b64
from hiro_commons.process import is_running, read_pid

from ..constants import PID_FILENAME
from ..domain.config import load_config, load_state
from ..domain.crypto import load_or_create_master_key, MASTER_KEY_FILE
from ..domain.workspace import (
    WorkspaceError,
    admin_port_for,
    create_workspace,
    http_port_for,
    load_registry,
    plugin_port_for,
    remove_workspace,
    rename_workspace,
    resolve_workspace,
    set_default_workspace,
)
from .base import Tool, ToolParam


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class WorkspaceListResult:
    workspaces: list[dict[str, Any]] = field(default_factory=list)
    default_workspace: str = ""


@dataclass
class WorkspaceCreateResult:
    id: str
    name: str
    path: str
    http_port: int
    plugin_port: int
    admin_port: int
    is_default: bool


@dataclass
class WorkspaceRemoveResult:
    id: str
    name: str
    purged: bool


@dataclass
class WorkspaceUpdateResult:
    id: str
    name: str
    is_default: bool
    renamed: bool
    default_changed: bool
    gateway_updated: bool


@dataclass
class WorkspaceShowResult:
    id: str
    name: str
    path: str
    is_default: bool
    is_configured: bool
    http_port: int
    plugin_port: int
    admin_port: int
    port_slot: int
    gateway_url: str | None
    device_id: str | None
    ws_connected: bool
    last_connected: str | None
    autostart_method: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_workspace_config_safe(workspace_path: Path) -> Any | None:
    """Return Config if config.json exists, otherwise None."""
    if not (workspace_path / "config.json").exists():
        return None
    try:
        return load_config(workspace_path)
    except Exception:
        return None


def _load_workspace_state_safe(workspace_path: Path) -> Any | None:
    """Return State if state.json exists, otherwise None."""
    try:
        return load_state(workspace_path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class WorkspaceListTool(Tool):
    name = "workspace_list"
    description = "List all configured workspaces with their ports and status"
    params: dict = {}

    def execute(self) -> WorkspaceListResult:
        registry = load_registry()
        workspaces = []
        for ws_id, entry in registry.workspaces.items():
            ws_path = Path(entry.path)
            config = _load_workspace_config_safe(ws_path)
            workspaces.append({
                "id": ws_id,
                "name": entry.name,
                "path": entry.path,
                "is_default": ws_id == registry.default_workspace,
                "is_configured": config is not None,
                "http_port": http_port_for(registry, entry.port_slot),
                "plugin_port": plugin_port_for(registry, entry.port_slot),
                "admin_port": admin_port_for(registry, entry.port_slot),
                "port_slot": entry.port_slot,
                "gateway_url": config.gateway_url if config else None,
                "autostart_method": config.autostart_method if config else None,
            })
        return WorkspaceListResult(
            workspaces=workspaces,
            default_workspace=registry.default_workspace,
        )


class WorkspaceCreateTool(Tool):
    name = "workspace_create"
    description = "Create a new workspace and register it with auto-assigned ports"
    params = {
        "name": ToolParam(str, "Workspace name, e.g. 'default' or 'work'"),
        "path": ToolParam(str, "Custom folder path (default: platform data dir)", required=False),
        "set_default": ToolParam(bool, "Set this workspace as the default after creation", required=False),
    }

    def execute(
        self,
        name: str,
        path: str | None = None,
        set_default: bool = False,
    ) -> WorkspaceCreateResult:
        custom_path = Path(path) if path else None
        entry, registry = create_workspace(name, path=custom_path)

        if set_default:
            set_default_workspace(entry.id)
            registry = load_registry()

        return WorkspaceCreateResult(
            id=entry.id,
            name=entry.name,
            path=entry.path,
            http_port=http_port_for(registry, entry.port_slot),
            plugin_port=plugin_port_for(registry, entry.port_slot),
            admin_port=admin_port_for(registry, entry.port_slot),
            is_default=entry.id == registry.default_workspace,
        )


class WorkspaceRemoveTool(Tool):
    name = "workspace_remove"
    description = "Remove a workspace from the registry, optionally deleting its folder from disk"
    params = {
        "workspace": ToolParam(str, "Workspace name or id to remove"),
        "purge": ToolParam(bool, "Also delete the workspace folder from disk", required=False),
    }

    def execute(self, workspace: str, purge: bool = False) -> WorkspaceRemoveResult:
        entry, registry = resolve_workspace(workspace)
        ws_path = Path(entry.path)

        pid = read_pid(ws_path, PID_FILENAME)
        if is_running(pid):
            raise WorkspaceError(
                f"Workspace '{entry.name}' is currently running (PID {pid}). "
                "Stop it before removing."
            )

        if registry.default_workspace == entry.id and len(registry.workspaces) > 1:
            raise WorkspaceError(
                f"Workspace '{entry.name}' is the default workspace. "
                "Set another workspace as the default before removing this one."
            )

        remove_workspace(entry.id, purge=purge)
        return WorkspaceRemoveResult(id=entry.id, name=entry.name, purged=purge)


class WorkspaceUpdateTool(Tool):
    name = "workspace_update"
    description = (
        "Update mutable workspace properties: display name, default flag, and/or gateway URL. "
        "Only supplied fields are changed. For full reconfiguration (keys, autostart) use setup."
    )
    params = {
        "workspace": ToolParam(str, "Workspace name or id to update"),
        "name": ToolParam(str, "New display name", required=False),
        "set_default": ToolParam(bool, "Set this workspace as the default", required=False),
        "gateway_url": ToolParam(str, "New gateway WebSocket URL (light update — no key regen)", required=False),
    }

    def execute(
        self,
        workspace: str,
        name: str | None = None,
        set_default: bool = False,
        gateway_url: str | None = None,
    ) -> WorkspaceUpdateResult:
        entry, registry = resolve_workspace(workspace)
        renamed = False
        default_changed = False
        gateway_updated = False

        if name is not None and name != entry.name:
            rename_workspace(entry.id, name)
            renamed = True
            entry.name = name  # keep local ref in sync for result

        if set_default and registry.default_workspace != entry.id:
            if not (Path(entry.path) / "config.json").exists():
                raise WorkspaceError(
                    f"Workspace '{entry.name}' is not configured. "
                    f"Run 'hirocli setup --workspace {entry.name}' before setting it as the default."
                )
            set_default_workspace(entry.id)
            default_changed = True

        if gateway_url is not None:
            # Light update: patch only the gateway_url in config.json without regenerating keys.
            from ..domain.config import load_config, save_config
            ws_path = Path(entry.path)
            if not (ws_path / "config.json").exists():
                raise WorkspaceError(
                    f"Workspace '{entry.name}' is not configured. "
                    f"Run 'hirocli setup --workspace {entry.name}' first."
                )
            config = load_config(ws_path)
            config.gateway_url = gateway_url
            save_config(ws_path, config)
            gateway_updated = True

        updated_registry = load_registry()
        return WorkspaceUpdateResult(
            id=entry.id,
            name=entry.name,
            is_default=updated_registry.default_workspace == entry.id,
            renamed=renamed,
            default_changed=default_changed,
            gateway_updated=gateway_updated,
        )


class WorkspaceShowTool(Tool):
    name = "workspace_show"
    description = "Show details of a workspace: path, ports, configuration, and runtime state"
    params = {
        "workspace": ToolParam(str, "Workspace name or id (omit to show the default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> WorkspaceShowResult:
        entry, registry = resolve_workspace(workspace)
        ws_path = Path(entry.path)
        config = _load_workspace_config_safe(ws_path)
        state = _load_workspace_state_safe(ws_path)
        return WorkspaceShowResult(
            id=entry.id,
            name=entry.name,
            path=entry.path,
            is_default=entry.id == registry.default_workspace,
            is_configured=config is not None,
            http_port=http_port_for(registry, entry.port_slot),
            plugin_port=plugin_port_for(registry, entry.port_slot),
            admin_port=admin_port_for(registry, entry.port_slot),
            port_slot=entry.port_slot,
            gateway_url=config.gateway_url if config else None,
            device_id=config.device_id if config else None,
            ws_connected=state.ws_connected if state else False,
            last_connected=state.last_connected if state else None,
            autostart_method=config.autostart_method if config else None,
        )


@dataclass
class WorkspacePublicKeyResult:
    id: str
    name: str
    public_key_b64: str


class WorkspaceGetPublicKeyTool(Tool):
    name = "workspace_get_public_key"
    description = "Return the current Ed25519 public key (base64) for a workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name or id (omit to use the default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> WorkspacePublicKeyResult:
        entry, _ = resolve_workspace(workspace)
        ws_path = Path(entry.path)
        config = _load_workspace_config_safe(ws_path)
        if config is None:
            raise WorkspaceError(
                f"Workspace '{entry.name}' is not configured. "
                f"Run setup first."
            )
        key_filename = config.master_key_file or MASTER_KEY_FILE
        key_path = ws_path / key_filename
        if not key_path.exists():
            raise WorkspaceError(
                f"Master key file not found for workspace '{entry.name}'. "
                f"Run setup to generate it."
            )
        private_key = load_or_create_master_key(ws_path, filename=key_filename)
        public_key_b64 = public_key_to_b64(private_key.public_key())
        return WorkspacePublicKeyResult(
            id=entry.id,
            name=entry.name,
            public_key_b64=public_key_b64,
        )


# DEV-ONLY: regenerating the master key invalidates all existing gateway trust
# relationships — the new public key must be re-registered in every gateway
# instance that trusts this workspace.
class WorkspaceRegenerateKeyTool(Tool):
    name = "workspace_regenerate_key"
    description = (
        "DEV-ONLY: Regenerate the Ed25519 master key for a workspace. "
        "The old key is permanently replaced; the new public key must be "
        "re-registered in every gateway instance that trusts this workspace."
    )
    params = {
        "workspace": ToolParam(str, "Workspace name or id (omit to use the default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> WorkspacePublicKeyResult:
        entry, _ = resolve_workspace(workspace)
        ws_path = Path(entry.path)
        config = _load_workspace_config_safe(ws_path)
        if config is None:
            raise WorkspaceError(
                f"Workspace '{entry.name}' is not configured. "
                f"Run setup first."
            )
        key_filename = config.master_key_file or MASTER_KEY_FILE
        key_path = ws_path / key_filename

        new_private_key = generate_private_key()
        key_path.write_bytes(private_key_to_pem(new_private_key))
        try:
            key_path.chmod(0o600)
        except OSError:
            # Windows doesn't fully support POSIX perms via chmod.
            pass

        public_key_b64 = public_key_to_b64(new_private_key.public_key())
        return WorkspacePublicKeyResult(
            id=entry.id,
            name=entry.name,
            public_key_b64=public_key_b64,
        )
