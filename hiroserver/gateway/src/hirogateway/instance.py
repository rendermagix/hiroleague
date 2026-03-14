"""Gateway instance registry and resolution helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import BaseModel

from hiro_commons.constants.storage import REGISTRY_FILENAME

from .constants import APP_NAME, DEFAULT_INSTANCE_NAME, ENV_INSTANCE


class GatewayInstanceError(Exception):
    pass


class GatewayInstanceEntry(BaseModel):
    name: str
    path: str
    host: str
    port: int


class GatewayRegistry(BaseModel):
    default_instance: str = DEFAULT_INSTANCE_NAME
    instances: dict[str, GatewayInstanceEntry] = {}


def _app_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def registry_path() -> Path:
    return _app_data_dir() / REGISTRY_FILENAME


def default_instance_path(name: str) -> Path:
    return _app_data_dir() / "instances" / name


def load_registry() -> GatewayRegistry:
    rp = registry_path()
    if rp.exists():
        try:
            return GatewayRegistry.model_validate_json(rp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return GatewayRegistry()


def save_registry(registry: GatewayRegistry) -> None:
    rp = registry_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(registry.model_dump_json(indent=2), encoding="utf-8")


def resolve_instance(name: str | None = None) -> tuple[GatewayInstanceEntry, GatewayRegistry]:
    registry = load_registry()
    target = name or os.environ.get(ENV_INSTANCE) or registry.default_instance

    if not registry.instances:
        raise GatewayInstanceError(
            "No gateway instances configured. Run 'hirogateway instance create <name>' first."
        )

    if not target or target not in registry.instances:
        available = ", ".join(registry.instances.keys())
        raise GatewayInstanceError(
            f"Gateway instance '{target}' not found. Available: {available}"
        )

    return registry.instances[target], registry


def create_instance(
    name: str,
    *,
    host: str,
    port: int,
    path: Path | None = None,
) -> tuple[GatewayInstanceEntry, GatewayRegistry]:
    registry = load_registry()

    if name in registry.instances:
        raise GatewayInstanceError(f"Gateway instance '{name}' already exists.")

    for entry in registry.instances.values():
        if entry.port == port and entry.host == host:
            raise GatewayInstanceError(
                f"Port conflict: {host}:{port} is already used by instance '{entry.name}'."
            )

    instance_path = path or default_instance_path(name)
    instance_path.mkdir(parents=True, exist_ok=True)

    entry = GatewayInstanceEntry(
        name=name,
        path=str(instance_path),
        host=host,
        port=port,
    )
    registry.instances[name] = entry
    if len(registry.instances) == 1:
        registry.default_instance = name
    save_registry(registry)
    return entry, registry


def remove_instance(name: str, *, purge: bool = False) -> None:
    registry = load_registry()
    if name not in registry.instances:
        raise GatewayInstanceError(f"Gateway instance '{name}' not found.")

    entry = registry.instances.pop(name)
    if registry.default_instance == name:
        remaining = list(registry.instances.keys())
        registry.default_instance = remaining[0] if remaining else ""
    save_registry(registry)

    if purge:
        instance_path = Path(entry.path)
        if instance_path.exists():
            shutil.rmtree(instance_path, ignore_errors=True)


def set_default_instance(name: str) -> None:
    registry = load_registry()
    if name not in registry.instances:
        raise GatewayInstanceError(f"Gateway instance '{name}' not found.")
    registry.default_instance = name
    save_registry(registry)
