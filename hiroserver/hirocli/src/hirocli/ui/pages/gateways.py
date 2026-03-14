"""Gateways page — list, create (setup), start, stop, teardown gateway instances.

All operations delegate to GatewayStatusTool / GatewayStartTool / GatewayStopTool /
GatewaySetupTool / GatewayTeardownTool, which in turn call hirogateway.service.

The desktop_public_key (Ed25519, base64) is provided manually by the user in the
setup dialog — it serves as the trust root for the gateway WebSocket server.
"""

from __future__ import annotations

import sys
from dataclasses import asdict

from nicegui import ui


@ui.page("/gateways")
async def gateways_page() -> None:
    from hirocli.tools.gateway import (
        GatewaySetupTool,
        GatewayStartTool,
        GatewayStatusTool,
        GatewayStopTool,
        GatewayTeardownTool,
    )
    from hirocli.ui.app import create_page_layout

    create_page_layout(active_path="/gateways")

    # Mutable containers so inner async callbacks can reference mutable state.
    pending_stop: list[dict] = [{}]
    pending_remove: list[dict] = [{}]

    # ------------------------------------------------------------------ setup dialog
    with ui.dialog() as setup_dialog, ui.card().classes("w-[520px]"):
        ui.label("Create gateway instance").classes("text-lg font-semibold mb-2")

        setup_name_input = ui.input("Name *", placeholder="e.g. main").classes("w-full")
        setup_key_input = ui.textarea(
            "Desktop public key * (Ed25519, base64)",
            placeholder="Paste the desktop Ed25519 public key here",
        ).classes("w-full mt-2").props("rows=3")
        setup_port_input = ui.number(
            "Port *",
            placeholder="e.g. 8765",
            min=1024,
            max=65535,
            precision=0,
        ).classes("w-full mt-2")

        with ui.expansion("Advanced options", icon="tune").classes("w-full mt-2"):
            setup_host_input = ui.input(
                "Host",
                placeholder="0.0.0.0",
            ).classes("w-full")
            ui.label("Leave blank to bind on all interfaces (0.0.0.0).").classes(
                "text-xs opacity-50 ml-1 mb-2"
            )

            setup_make_default = ui.checkbox("Set as default gateway instance").classes("mt-1")

            setup_skip_autostart = ui.checkbox("Skip auto-start registration").classes("mt-1")
            ui.label(
                "By default, the gateway is registered to start automatically on login."
            ).classes("text-xs opacity-50 ml-6 mb-2")

            # Elevated task option — only relevant on Windows (UAC prompt on server machine)
            if sys.platform == "win32":
                setup_elevated_task = ui.checkbox(
                    "Request elevated Task Scheduler entry (Windows UAC)",
                ).classes("mt-1")
                ui.label(
                    "Triggers a UAC prompt on the server machine to register the task "
                    "with highest privileges. Only works if you have physical or RDP "
                    "access to the server."
                ).classes("text-xs opacity-50 ml-6 mb-1")
            else:
                setup_elevated_task = ui.checkbox("").classes("hidden")

        async def do_setup() -> None:
            name = setup_name_input.value.strip()
            key = setup_key_input.value.strip()
            port_val = setup_port_input.value

            if not name:
                ui.notify("Name is required.", color="negative")
                return
            if not key:
                ui.notify("Desktop public key is required.", color="negative")
                return
            if not port_val:
                ui.notify("Port is required.", color="negative")
                return

            host = setup_host_input.value.strip() or "0.0.0.0"

            try:
                result = GatewaySetupTool().execute(
                    name=name,
                    desktop_public_key=key,
                    port=int(port_val),
                    host=host,
                    make_default=setup_make_default.value,
                    skip_autostart=setup_skip_autostart.value,
                    elevated_task=setup_elevated_task.value,
                )
                msg_parts = [f"Port: {result.port}"]
                if result.autostart_registered:
                    msg_parts.append(f"Autostart: {result.autostart_method}")
                ui.notify(
                    f"Gateway '{result.instance_name}' created.  •  " + "  •  ".join(msg_parts),
                    color="positive",
                    timeout=8000,
                )
                setup_dialog.close()
                _reset_setup_form()
                gateway_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        def _reset_setup_form() -> None:
            setup_name_input.set_value("")
            setup_key_input.set_value("")
            setup_port_input.set_value(None)
            setup_host_input.set_value("")
            setup_make_default.set_value(False)
            setup_skip_autostart.set_value(False)
            setup_elevated_task.set_value(False)

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=setup_dialog.close).props("flat")
            ui.button("Create", icon="add", on_click=do_setup)

    # ------------------------------------------------------------------ stop dialog
    with ui.dialog() as stop_dialog, ui.card().classes("w-96"):
        stop_title = ui.label("").classes("text-lg font-semibold mb-2")
        ui.label("This will stop the running gateway process.").classes("text-sm opacity-60")

        async def do_stop() -> None:
            row = pending_stop[0]
            name = row.get("name", "")
            try:
                result = GatewayStopTool().execute(instance=name)
                if result.was_running:
                    ui.notify(f"Gateway '{name}' stopped.", color="positive")
                else:
                    ui.notify(f"Gateway '{name}' was not running.", color="warning")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            stop_dialog.close()
            gateway_list.refresh()

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=stop_dialog.close).props("flat")
            ui.button("Stop", icon="stop", on_click=do_stop).props('color="negative"')

    # ------------------------------------------------------------------ remove (teardown) dialog
    with ui.dialog() as remove_dialog, ui.card().classes("w-[440px]"):
        remove_title = ui.label("").classes("text-lg font-semibold mb-2")
        remove_info = ui.label("").classes("text-sm opacity-60 mb-3")
        purge_checkbox = ui.checkbox("Also delete instance files from disk")
        ui.label(
            "When enabled, the instance folder and all its files will be permanently deleted."
        ).classes("text-xs opacity-50 ml-6 mb-1")

        async def do_remove() -> None:
            row = pending_remove[0]
            name = row.get("name", "")
            try:
                result = GatewayTeardownTool().execute(
                    instance=name,
                    purge=purge_checkbox.value,
                    elevated_task=False,
                )
                parts = []
                if result.stopped:
                    parts.append("stopped")
                if result.autostart_removed:
                    parts.append("autostart removed")
                if result.purged:
                    parts.append("files deleted")
                ui.notify(
                    f"Gateway '{name}' removed" + (f": {', '.join(parts)}" if parts else "") + ".",
                    color="positive",
                    timeout=6000,
                )
                remove_dialog.close()
                gateway_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=remove_dialog.close).props("flat")
            ui.button("Remove", icon="delete", on_click=do_remove).props('color="negative"')

    # ------------------------------------------------------------------ refreshable table
    @ui.refreshable
    def gateway_list() -> None:
        rows: list[dict] = []
        error: str | None = None

        try:
            result = GatewayStatusTool().execute()
            rows = [asdict(inst) for inst in result.instances]
        except Exception as exc:
            error = str(exc)

        if error:
            ui.label(f"Error loading gateways: {error}").classes("text-negative")
            return

        if not rows:
            with ui.card().classes("w-full"):
                ui.label(
                    "No gateway instances configured yet. Create one to get started."
                ).classes("opacity-60 text-sm p-2")
            return

        columns = [
            {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
            {"name": "status", "label": "Status", "field": "running", "align": "left"},
            {"name": "host_port", "label": "Host : Port", "field": "port", "align": "left"},
            {"name": "is_default", "label": "Default", "field": "is_default", "align": "center"},
            {"name": "path", "label": "Path", "field": "path", "align": "left"},
            {"name": "actions", "label": "", "field": "name", "align": "right"},
        ]

        table = ui.table(columns=columns, rows=rows, row_key="name").classes("w-full")

        table.add_slot(
            "body-cell-status",
            """
            <q-td :props="props">
                <q-badge
                    :color="props.row.running ? 'positive' : 'grey-6'"
                    :label="props.row.running ? 'Running' : 'Stopped'" />
                <span v-if="props.row.pid && props.row.running"
                      class="text-xs opacity-50 q-ml-xs">PID {{ props.row.pid }}</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-host_port",
            """
            <q-td :props="props">
                <span class="text-xs font-mono">{{ props.row.host }}:{{ props.row.port }}</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-is_default",
            """
            <q-td :props="props" class="text-center">
                <q-icon v-if="props.row.is_default" name="star" color="warning" size="sm" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-path",
            """
            <q-td :props="props">
                <span class="text-xs font-mono opacity-60">{{ props.row.path }}</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-actions",
            """
            <q-td :props="props">
              <div class="row no-wrap justify-end items-center">

                <!-- Start: only when stopped -->
                <q-btn v-if="!props.row.running"
                       flat size="sm" icon="play_arrow" color="positive"
                       title="Start" class="q-ma-xs"
                       @click="() => $parent.$emit('start', props.row)" />

                <!-- Stop: only when running -->
                <q-btn v-if="props.row.running"
                       flat size="sm" icon="stop" color="negative"
                       title="Stop" class="q-ma-xs"
                       @click="() => $parent.$emit('stop', props.row)" />

                <!-- Remove (teardown) -->
                <q-btn flat size="sm" icon="delete" color="negative"
                       title="Remove (teardown)" class="q-ma-xs"
                       @click="() => $parent.$emit('remove', props.row)" />

              </div>
            </q-td>
            """,
        )

        # ---------------------------------------------------------------- event handlers

        async def handle_start(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            name = row.get("name", "")
            try:
                result = GatewayStartTool().execute(instance=name)
                if result.already_running:
                    ui.notify(f"Gateway '{name}' is already running.", color="warning")
                else:
                    ui.notify(
                        f"Gateway '{name}' started (PID {result.pid}).",
                        color="positive",
                    )
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            gateway_list.refresh()

        def handle_stop(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_stop[0] = row
            name = row.get("name", "")
            stop_title.set_text(f"Stop gateway '{name}'?")
            stop_dialog.open()

        def handle_remove(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_remove[0] = row
            name = row.get("name", "")
            path = row.get("path", "")
            remove_title.set_text(f"Remove gateway '{name}'?")
            remove_info.set_text(f"Path: {path}")
            purge_checkbox.set_value(False)
            remove_dialog.open()

        table.on("start", handle_start)
        table.on("stop", handle_stop)
        table.on("remove", handle_remove)

    # ------------------------------------------------------------------ page layout
    with ui.column().classes("w-full gap-6 p-6"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Gateways").classes("text-2xl font-semibold")
            ui.button("Create gateway", icon="add", on_click=setup_dialog.open)

        gateway_list()
