"""Bootstrap helpers for initial and runtime channel configuration."""

from __future__ import annotations

from ..channel_config import (
    ChannelConfig,
    find_workspace_root,
    load_channel_config,
    save_channel_config,
)
from ..config import Config, master_key_path

MANDATORY_CHANNEL = "devices"


def ensure_mandatory_devices_channel(config: Config) -> None:
    """Create/update the mandatory `devices` channel config."""
    existing = load_channel_config(MANDATORY_CHANNEL)
    workspace = find_workspace_root()
    workspace_dir = str(workspace) if workspace else (
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
            "master_key_path": str(master_key_path(config)),
            "ping_interval": (existing.config.get("ping_interval", 30) if existing else 30),
        },
        workspace_dir=workspace_dir,
    )
    save_channel_config(channel_cfg)
