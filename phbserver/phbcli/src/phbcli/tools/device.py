"""Device management tools.

Three operations: generate pairing code, list approved devices, revoke a device.
Both the CLI (commands/device.py) and the AI agent call these directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import load_config
from ..pairing import (
    create_pairing_session,
    load_approved_devices,
    revoke_approved_device,
    save_pairing_session,
)
from ..workspace import resolve_workspace
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DeviceAddResult:
    code: str
    expires_at: str


@dataclass
class DeviceListResult:
    devices: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DeviceRevokeResult:
    removed: bool
    device_id: str


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class DeviceAddTool(Tool):
    name = "device_add"
    description = "Generate a short-lived pairing code to onboard a new mobile device"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "ttl_seconds": ToolParam(int, "Pairing code lifetime in seconds", required=False),
        "code_length": ToolParam(int, "Pairing code length in digits", required=False),
    }

    def execute(
        self,
        workspace: str | None = None,
        ttl_seconds: int | None = None,
        code_length: int | None = None,
    ) -> DeviceAddResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        session = create_pairing_session(
            code_length=code_length or config.pairing_code_length,
            ttl_seconds=ttl_seconds or config.pairing_code_ttl_seconds,
        )
        save_pairing_session(workspace_path, session)
        return DeviceAddResult(
            code=session.code,
            expires_at=session.expires_at.isoformat().replace("+00:00", "Z"),
        )


class DeviceListTool(Tool):
    name = "device_list"
    description = "List all approved paired mobile devices"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> DeviceListResult:
        workspace_path = _resolve_path(workspace)
        devices = load_approved_devices(workspace_path)
        return DeviceListResult(
            devices=[
                {
                    "device_id": d.device_id,
                    "paired_at": d.paired_at.isoformat().replace("+00:00", "Z"),
                    "expires_at": (
                        d.expires_at.isoformat().replace("+00:00", "Z")
                        if d.expires_at
                        else None
                    ),
                }
                for d in devices
            ]
        )


class DeviceRevokeTool(Tool):
    name = "device_revoke"
    description = "Revoke a previously approved paired device"
    params = {
        "device_id": ToolParam(str, "Device ID to revoke"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, device_id: str, workspace: str | None = None) -> DeviceRevokeResult:
        workspace_path = _resolve_path(workspace)
        removed = revoke_approved_device(workspace_path, device_id)
        return DeviceRevokeResult(removed=removed, device_id=device_id)
