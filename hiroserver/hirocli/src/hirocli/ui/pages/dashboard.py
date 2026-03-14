"""Dashboard page — the landing page for the admin UI.

Assembles aggregate statistics by calling tools in-process on page load.
No real-time push: the user navigates back or refreshes to see updated counts.

Statistics shown:
  - Total workspaces        (WorkspaceListTool)
  - Running workspaces      (StatusTool)
  - Gateway running         (GatewayStatusTool — any instance running)
  - Total paired devices    (DeviceListTool per workspace)
  - Installed channels      (ChannelListTool per workspace)
  - Enabled channels        (ChannelListTool — filtered)
"""

from __future__ import annotations

from nicegui import ui


@ui.page("/")
async def dashboard_page() -> None:
    from hirocli.tools.channel import ChannelListTool
    from hirocli.tools.device import DeviceListTool
    from hirocli.tools.gateway import GatewayStatusTool
    from hirocli.tools.server import StatusTool
    from hirocli.tools.workspace import WorkspaceListTool
    from hirocli.ui.app import create_page_layout

    # ------------------------------------------------------------------ data
    workspaces: list[dict] = []
    total_workspaces = 0
    running_workspaces = 0
    # Gateway running is based on the gateway process itself, not the workspace
    # server's ws_connected state (which only reflects the channel client connection).
    gateway_running = False
    total_devices = 0
    total_channels = 0
    enabled_channels = 0

    try:
        ws_result = WorkspaceListTool().execute()
        workspaces = ws_result.workspaces
        total_workspaces = len(workspaces)
    except Exception:
        pass

    try:
        status_result = StatusTool().execute()
        running_workspaces = sum(1 for w in status_result.workspaces if w.server_running)
    except Exception:
        pass

    gateway_desktop_connected = False
    gateway_auth_error: str | None = None
    try:
        gw_result = GatewayStatusTool().execute()
        gateway_running = any(inst.running for inst in gw_result.instances)
        gateway_desktop_connected = any(inst.desktop_connected for inst in gw_result.instances)
        # Surface the first auth error found across all instances.
        for inst in gw_result.instances:
            if inst.last_auth_error:
                gateway_auth_error = inst.last_auth_error
                break
    except Exception:
        pass

    for ws in workspaces:
        ws_id: str | None = ws.get("id")
        try:
            devices = DeviceListTool().execute(workspace=ws_id)
            total_devices += len(devices.devices)
        except Exception:
            pass
        try:
            channels = ChannelListTool().execute(workspace=ws_id)
            total_channels += len(channels.channels)
            enabled_channels += sum(1 for c in channels.channels if c.get("enabled"))
        except Exception:
            pass

    # ------------------------------------------------------------------ layout
    create_page_layout(active_path="/")

    with ui.column().classes("w-full gap-6 p-6"):
        ui.label("Dashboard").classes("text-2xl font-semibold")

        with ui.grid(columns=3).classes("w-full gap-4"):
            _stat_card("Total workspaces", str(total_workspaces), "workspaces")
            _stat_card("Running workspaces", str(running_workspaces), "activity")
            if not gateway_running:
                _gw_label, _gw_icon, _gw_ok = "Stopped", "wifi_off", False
            elif gateway_desktop_connected:
                _gw_label, _gw_icon, _gw_ok = "Connected", "wifi", True
            elif gateway_auth_error:
                _gw_label, _gw_icon, _gw_ok = "Auth Error", "wifi_off", False
            else:
                _gw_label, _gw_icon, _gw_ok = "Running", "wifi", None
            _stat_card("Gateway", _gw_label, _gw_icon, ok=_gw_ok)
            _stat_card("Paired devices", str(total_devices), "smartphone")
            _stat_card("Installed channels", str(total_channels), "extension")
            _stat_card("Enabled channels", str(enabled_channels), "check_circle")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stat_card(title: str, value: str, icon: str, *, ok: bool | None = None) -> None:
    # Use Quasar semantic color roles so values adapt to dark/light theme automatically.
    value_classes = "text-2xl font-bold"
    if ok is True:
        value_classes += " text-positive"
    elif ok is False:
        value_classes += " text-negative"

    with ui.card().classes("w-full"):
        with ui.row().classes("items-start gap-3 p-1"):
            # opacity-50 on inherited color adapts to both themes instead of a fixed gray
            ui.icon(icon).classes("text-3xl opacity-50 mt-1")
            with ui.column().classes("gap-0"):
                ui.label(value).classes(value_classes)
                ui.label(title).classes("text-sm opacity-60")
