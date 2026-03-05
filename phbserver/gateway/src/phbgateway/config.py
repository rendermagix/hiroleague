"""Config file management for phbgateway instances."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class GatewayConfig(BaseModel):
    desktop_public_key: str
    log_dir: str = ""


def instance_config_file(instance_path: Path) -> Path:
    return instance_path / "config.json"


def instance_log_dir(instance_path: Path) -> Path:
    return instance_path / "logs"


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
