"""Auto-start registration wrappers for phbcli workspaces."""

from __future__ import annotations

from phb_commons.autostart import (
    AutostartMethod,
    register_autostart as commons_register_autostart,
    register_autostart_elevated as commons_register_autostart_elevated,
    unregister_autostart as commons_unregister_autostart,
    unregister_autostart_elevated as commons_unregister_autostart_elevated,
)


def register_autostart(workspace_name: str) -> AutostartMethod:
    """Register phbcli to start automatically on user login for the given workspace."""
    return commons_register_autostart(
        workspace_name,
        entry_name_prefix="phbcli",
        executable_name="phbcli",
        launch_args=["start", "--workspace", workspace_name],
    )


def register_autostart_elevated(workspace_name: str) -> bool:
    """Windows only: register a /RL HIGHEST task via UAC prompt."""
    return commons_register_autostart_elevated(
        workspace_name,
        entry_name_prefix="phbcli",
        executable_name="phbcli",
        launch_args=["start", "--workspace", workspace_name],
    )


def unregister_autostart(workspace_name: str) -> None:
    """Remove auto-start registrations for the given workspace."""
    commons_unregister_autostart(workspace_name, entry_name_prefix="phbcli")


def unregister_autostart_elevated(workspace_name: str) -> bool:
    """Windows only: delete the Task Scheduler task via UAC prompt."""
    return commons_unregister_autostart_elevated(workspace_name, entry_name_prefix="phbcli")