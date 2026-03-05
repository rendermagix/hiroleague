"""Config and state file management for phbcli.

All files live under the resolved workspace directory.  No module-level
path constants exist — every helper accepts a workspace_path: Path argument.

Workspace layout:
  <workspace>/
    config.json
    state.json
    master_key.pem
    logs/
    channels/
    agent/
    pairing_session.json
    devices.json
    phbcli.pid
    gateway instances are managed separately by phbgateway
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class Config(BaseModel):
    device_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gateway_url: str = "ws://localhost:8765"
    http_host: str = "127.0.0.1"
    http_port: int = 18080
    plugin_port: int = 18081
    master_key_file: str = "master_key.pem"
    pairing_code_length: int = 6
    pairing_code_ttl_seconds: int = 300
    attestation_expires_days: int = 30
    log_dir: str = ""
    log_levels: dict[str, str] = Field(default_factory=dict)


class State(BaseModel):
    ws_connected: bool = False
    last_connected: Optional[str] = None  # ISO 8601
    gateway_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def workspace_config_file(workspace_path: Path) -> Path:
    return workspace_path / "config.json"


def workspace_state_file(workspace_path: Path) -> Path:
    return workspace_path / "state.json"


def workspace_log_dir(workspace_path: Path) -> Path:
    return workspace_path / "logs"


def master_key_path(workspace_path: Path, config: Config) -> Path:
    return workspace_path / config.master_key_file


def resolve_log_dir(workspace_path: Path, config: Config) -> Path:
    """Return the effective log directory, falling back to <workspace>/logs/."""
    if config.log_dir:
        return Path(config.log_dir)
    return workspace_log_dir(workspace_path)


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def load_config(workspace_path: Path) -> Config:
    workspace_path.mkdir(parents=True, exist_ok=True)
    cfg_file = workspace_config_file(workspace_path)
    if cfg_file.exists():
        return Config.model_validate_json(cfg_file.read_text(encoding="utf-8"))
    return Config()


def save_config(workspace_path: Path, config: Config) -> None:
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace_config_file(workspace_path).write_text(
        config.model_dump_json(indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def load_state(workspace_path: Path) -> State:
    workspace_path.mkdir(parents=True, exist_ok=True)
    state_file = workspace_state_file(workspace_path)
    if state_file.exists():
        try:
            return State.model_validate_json(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return State()


def save_state(workspace_path: Path, state: State) -> None:
    workspace_path.mkdir(parents=True, exist_ok=True)
    workspace_state_file(workspace_path).write_text(
        state.model_dump_json(indent=2), encoding="utf-8"
    )


def mark_connected(workspace_path: Path, gateway_url: str) -> None:
    state = load_state(workspace_path)
    state.ws_connected = True
    state.last_connected = datetime.now(timezone.utc).isoformat()
    state.gateway_url = gateway_url
    save_state(workspace_path, state)


def mark_disconnected(workspace_path: Path) -> None:
    state = load_state(workspace_path)
    state.ws_connected = False
    save_state(workspace_path, state)
