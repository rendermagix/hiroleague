"""Auto-start registration wrappers for hirogateway instances."""

from __future__ import annotations

from hiro_commons.autostart import (
    AutostartMethod,
    register_autostart as commons_register_autostart,
    register_autostart_elevated as commons_register_autostart_elevated,
    unregister_autostart as commons_unregister_autostart,
    unregister_autostart_elevated as commons_unregister_autostart_elevated,
)


def register_autostart(instance_name: str) -> AutostartMethod:
    return commons_register_autostart(
        instance_name,
        entry_name_prefix="hirogateway",
        executable_name="hirogateway",
        launch_args=["start", "--instance", instance_name],
    )


def register_autostart_elevated(instance_name: str) -> bool:
    return commons_register_autostart_elevated(
        instance_name,
        entry_name_prefix="hirogateway",
        executable_name="hirogateway",
        launch_args=["start", "--instance", instance_name],
    )


def unregister_autostart(instance_name: str) -> None:
    commons_unregister_autostart(instance_name, entry_name_prefix="hirogateway")


def unregister_autostart_elevated(instance_name: str) -> bool:
    return commons_unregister_autostart_elevated(instance_name, entry_name_prefix="hirogateway")
