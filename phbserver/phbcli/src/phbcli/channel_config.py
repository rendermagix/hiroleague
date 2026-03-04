"""Channel plugin configuration management.

Each enabled channel plugin has a config file at:
    <workspace>/channels/<name>.json

All functions are workspace-scoped — they accept workspace_path: Path.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChannelConfig:
    """Persisted configuration for one channel plugin."""

    name: str
    enabled: bool = True
    # Shell command used to start the plugin process.
    # phbcli appends ["--phb-ws", <url>] automatically.
    # Defaults to ["phb-channel-<name>"] if empty.
    command: list[str] = field(default_factory=list)
    # Arbitrary channel-specific settings (API keys, etc.).
    # Pushed to the plugin via channel.configure on connect.
    config: dict[str, Any] = field(default_factory=dict)
    # If set, the command is run via `uv run --directory <workspace_dir>`.
    # Populated automatically by `phbcli channel setup` when it detects
    # a uv workspace in the current directory tree.  Leave empty for
    # plugins installed as uv tools (they are already on PATH).
    workspace_dir: str = ""

    def effective_command(self) -> list[str]:
        base = self.command if self.command else [f"phb-channel-{self.name}"]
        if self.workspace_dir:
            if self._should_use_module_launcher(base):
                module_name = f"phb_channel_{self.name.replace('-', '_')}.main"
                return [
                    "uv", "run", "--directory", self.workspace_dir,
                    "python", "-m", module_name,
                ]
            return ["uv", "run", "--directory", self.workspace_dir] + base
        return base

    def _should_use_module_launcher(self, base: list[str]) -> bool:
        if sys.platform != "win32":
            return False
        return base == [f"phb-channel-{self.name}"]


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (defaults to CWD) looking for a uv workspace root.

    A workspace root is a directory containing a ``pyproject.toml`` with a
    ``[tool.uv.workspace]`` section.
    """
    current = (start or Path.cwd()).resolve()
    for candidate_dir in [current, *current.parents]:
        toml_path = candidate_dir / "pyproject.toml"
        if toml_path.exists():
            try:
                data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                if "workspace" in data.get("tool", {}).get("uv", {}):
                    return candidate_dir
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def workspace_channels_dir(workspace_path: Path) -> Path:
    return workspace_path / "channels"


def channel_config_path(workspace_path: Path, name: str) -> Path:
    return workspace_channels_dir(workspace_path) / f"{name}.json"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def load_channel_config(workspace_path: Path, name: str) -> ChannelConfig | None:
    path = channel_config_path(workspace_path, name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChannelConfig(**data)
    except Exception:
        return None


def save_channel_config(workspace_path: Path, cfg: ChannelConfig) -> None:
    channels_dir = workspace_channels_dir(workspace_path)
    channels_dir.mkdir(parents=True, exist_ok=True)
    channel_config_path(workspace_path, cfg.name).write_text(
        json.dumps(
            {
                "name": cfg.name,
                "enabled": cfg.enabled,
                "command": cfg.command,
                "config": cfg.config,
                "workspace_dir": cfg.workspace_dir,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def list_channel_configs(workspace_path: Path) -> list[ChannelConfig]:
    channels_dir = workspace_channels_dir(workspace_path)
    channels_dir.mkdir(parents=True, exist_ok=True)
    configs: list[ChannelConfig] = []
    for path in sorted(channels_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            configs.append(ChannelConfig(**data))
        except Exception:
            pass
    return configs


def list_enabled_channels(workspace_path: Path) -> list[ChannelConfig]:
    return [c for c in list_channel_configs(workspace_path) if c.enabled]


def delete_channel_config(workspace_path: Path, name: str) -> bool:
    path = channel_config_path(workspace_path, name)
    if path.exists():
        path.unlink()
        return True
    return False
