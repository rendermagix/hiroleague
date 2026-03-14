"""Config file management for hirogateway instances."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from hiro_commons.constants.storage import CONFIG_FILENAME, LOGS_DIR

STATE_FILENAME = "state.json"


class GatewayConfig(BaseModel):
    desktop_public_key: str
    log_dir: str = ""
    autostart_method: str = "skipped"


class GatewayState(BaseModel):
    desktop_connected: bool = False
    last_connected: Optional[str] = None  # ISO 8601
    last_auth_error: Optional[str] = None  # last rejection reason, cleared on success


def instance_config_file(instance_path: Path) -> Path:
    return instance_path / CONFIG_FILENAME


def instance_state_file(instance_path: Path) -> Path:
    return instance_path / STATE_FILENAME


def instance_log_dir(instance_path: Path) -> Path:
    return instance_path / LOGS_DIR


def resolve_log_dir(instance_path: Path, config: GatewayConfig) -> Path:
    if config.log_dir:
        return Path(config.log_dir)
    return instance_log_dir(instance_path)


def load_config(instance_path: Path) -> GatewayConfig:
    cfg_file = instance_config_file(instance_path)
    if not cfg_file.exists():
        raise FileNotFoundError(
            f"Missing gateway config at {cfg_file}. "
            "Create the instance again or restore its config.json."
        )
    return GatewayConfig.model_validate_json(cfg_file.read_text(encoding="utf-8"))


def save_config(instance_path: Path, config: GatewayConfig) -> None:
    instance_path.mkdir(parents=True, exist_ok=True)
    instance_config_file(instance_path).write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )


def load_state(instance_path: Path) -> GatewayState:
    state_file = instance_state_file(instance_path)
    if state_file.exists():
        try:
            return GatewayState.model_validate_json(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return GatewayState()


def save_state(instance_path: Path, state: GatewayState) -> None:
    instance_path.mkdir(parents=True, exist_ok=True)
    instance_state_file(instance_path).write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )
