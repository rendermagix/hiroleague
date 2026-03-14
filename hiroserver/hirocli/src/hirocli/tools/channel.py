"""Channel plugin management tools.

Six operations: list, install, setup, enable, disable, remove.
'channel status' (runtime connectivity query) is CLI/HTTP-only — it reads
ephemeral in-memory state, not persistent config, so it is not a tool.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME

from hiro_commons.process import find_workspace_root

from ..domain.channel_config import (
    ChannelConfig,
    delete_channel_config,
    list_channel_configs,
    load_channel_config,
    save_channel_config,
)
from ..domain.config import load_config, master_key_path
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ChannelListResult:
    channels: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChannelInstallResult:
    package: str
    success: bool
    output: str


@dataclass
class ChannelSetupResult:
    name: str
    enabled: bool
    command: str
    workspace_dir: str


@dataclass
class ChannelEnableResult:
    name: str
    enabled: bool


@dataclass
class ChannelDisableResult:
    name: str
    enabled: bool


@dataclass
class ChannelRemoveResult:
    name: str
    removed: bool


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ChannelListTool(Tool):
    name = "channel_list"
    description = "List all configured channel plugins and their enabled status"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ChannelListResult:
        workspace_path = _resolve_path(workspace)
        configs = list_channel_configs(workspace_path)
        return ChannelListResult(
            channels=[
                {
                    "name": cfg.name,
                    "enabled": cfg.enabled,
                    "command": " ".join(cfg.effective_command()),
                    "config_keys": list(cfg.config.keys()),
                }
                for cfg in configs
            ]
        )


class ChannelInstallTool(Tool):
    name = "channel_install"
    description = "Install a channel plugin package via uv tool install"
    params = {
        "channel_name": ToolParam(str, "Channel name, e.g. 'telegram'"),
        "package": ToolParam(str, "Package name override (default: hiro-channel-<name>)", required=False),
        "editable": ToolParam(bool, "Install in editable/development mode", required=False),
    }

    def execute(
        self,
        channel_name: str,
        package: str | None = None,
        editable: bool = False,
    ) -> ChannelInstallResult:
        pkg = package or f"hiro-channel-{channel_name}"
        cmd = ["uv", "tool", "install"]
        if editable:
            cmd.append("--editable")
        cmd.append(pkg)

        proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        output = (proc.stdout or proc.stderr).strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Install failed (exit {proc.returncode}): {proc.stderr.strip()}"
            )

        return ChannelInstallResult(package=pkg, success=True, output=output)


class ChannelSetupTool(Tool):
    name = "channel_setup"
    description = "Configure and register a channel plugin"
    params = {
        "channel_name": ToolParam(str, "Channel name, e.g. 'telegram'"),
        "command": ToolParam(str, "Executable to run for this channel, e.g. 'hiro-channel-telegram'"),
        "enabled": ToolParam(bool, "Whether to enable the channel immediately", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        channel_name: str,
        command: str,
        enabled: bool = True,
        workspace: str | None = None,
    ) -> ChannelSetupResult:
        workspace_path = _resolve_path(workspace)
        existing = load_channel_config(workspace_path, channel_name)

        if channel_name == MANDATORY_CHANNEL_NAME:
            enabled = True

        cmd_parts = command.split()
        uv_workspace = find_workspace_root()
        workspace_dir = str(uv_workspace) if uv_workspace else (
            existing.workspace_dir if existing else ""
        )

        channel_data = existing.config if existing else {}
        if channel_name == MANDATORY_CHANNEL_NAME:
            current = load_config(workspace_path)
            channel_data = {
                **channel_data,
                "gateway_url": current.gateway_url,
                "device_id": current.device_id,
                "master_key_path": str(master_key_path(workspace_path, current)),
                "ping_interval": channel_data.get("ping_interval", 30),
            }

        cfg = ChannelConfig(
            name=channel_name,
            enabled=enabled,
            command=cmd_parts,
            config=channel_data,
            workspace_dir=workspace_dir,
        )
        save_channel_config(workspace_path, cfg)

        return ChannelSetupResult(
            name=channel_name,
            enabled=enabled,
            command=command,
            workspace_dir=workspace_dir,
        )


class ChannelEnableTool(Tool):
    name = "channel_enable"
    description = "Enable a configured channel plugin"
    params = {
        "channel_name": ToolParam(str, "Channel name to enable"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelEnableResult:
        workspace_path = _resolve_path(workspace)
        cfg = load_channel_config(workspace_path, channel_name)
        if cfg is None:
            raise ValueError(
                f"Channel '{channel_name}' is not configured. "
                f"Run channel_setup first."
            )
        cfg.enabled = True
        save_channel_config(workspace_path, cfg)
        return ChannelEnableResult(name=channel_name, enabled=True)


class ChannelDisableTool(Tool):
    name = "channel_disable"
    description = "Disable a channel plugin without removing its configuration"
    params = {
        "channel_name": ToolParam(str, "Channel name to disable"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelDisableResult:
        workspace_path = _resolve_path(workspace)
        if channel_name == MANDATORY_CHANNEL_NAME:
            raise ValueError(f"The '{MANDATORY_CHANNEL_NAME}' channel is mandatory and cannot be disabled.")
        cfg = load_channel_config(workspace_path, channel_name)
        if cfg is None:
            raise ValueError(f"Channel '{channel_name}' is not configured.")
        cfg.enabled = False
        save_channel_config(workspace_path, cfg)
        return ChannelDisableResult(name=channel_name, enabled=False)


class ChannelRemoveTool(Tool):
    name = "channel_remove"
    description = "Remove a channel plugin's configuration permanently"
    params = {
        "channel_name": ToolParam(str, "Channel name to remove"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, channel_name: str, workspace: str | None = None) -> ChannelRemoveResult:
        workspace_path = _resolve_path(workspace)
        if channel_name == MANDATORY_CHANNEL_NAME:
            raise ValueError(f"The '{MANDATORY_CHANNEL_NAME}' channel is mandatory and cannot be removed.")
        removed = delete_channel_config(workspace_path, channel_name)
        return ChannelRemoveResult(name=channel_name, removed=removed)
