"""Bootstrap helpers for initial and runtime channel configuration."""

from __future__ import annotations

from pathlib import Path

from ..channel_config import (
    ChannelConfig,
    find_workspace_root,
    load_channel_config,
    save_channel_config,
)
from ..config import Config, master_key_path

MANDATORY_CHANNEL = "devices"


def ensure_mandatory_devices_channel(workspace_path: Path, config: Config) -> None:
    """Create/update the mandatory `devices` channel config inside the workspace."""
    existing = load_channel_config(workspace_path, MANDATORY_CHANNEL)
    uv_workspace = find_workspace_root()
    workspace_dir = str(uv_workspace) if uv_workspace else (
        existing.workspace_dir if existing else ""
    )
    channel_cfg = ChannelConfig(
        name=MANDATORY_CHANNEL,
        enabled=True,
        command=existing.command if existing and existing.command else [f"phb-channel-{MANDATORY_CHANNEL}"],
        config={
            **(existing.config if existing else {}),
            "gateway_url": config.gateway_url,
            "device_id": config.device_id,
            "master_key_path": str(master_key_path(workspace_path, config)),
            "ping_interval": (existing.config.get("ping_interval", 30) if existing else 30),
        },
        workspace_dir=workspace_dir,
    )
    save_channel_config(workspace_path, channel_cfg)
