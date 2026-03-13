"""Devices page — generate pairing codes and manage approved paired devices.

Two sections:
  - Pair new device: button that calls DeviceAddTool and shows the code in a dialog.
  - Approved devices: table with device ID, paired date, expiry date, and a revoke action.

The active workspace is selected globally in the header and stored in
nicegui_app.storage.user["selected_workspace"].
"""

from __future__ import annotations

from nicegui import app as nicegui_app, ui


@ui.page("/devices")
async def devices_page() -> None:
    from phbcli.tools.device import DeviceAddTool, DeviceListTool, DeviceRevokeTool
    from phbcli.ui.app import create_page_layout

    create_page_layout(active_path="/devices")

    ws_name: str | None = nicegui_app.storage.user.get("selected_workspace")

    # Mutable container for the revoke confirmation dialog
    pending_revoke_id: list[str] = [""]
    # Stores the full QR payload JSON for the copy button
    pending_qr_payload: list[str] = [""]

    # ------------------------------------------------------------------ pairing code dialog
    with ui.dialog() as pairing_dialog, ui.card().classes("w-96 items-center text-center gap-2"):
        ui.label("Pairing code").classes("text-base font-semibold")
        pairing_qr_html = ui.html("").classes("w-48 h-48 mx-auto my-2")
        pairing_code_label = ui.label("").classes(
            "text-5xl font-bold font-mono tracking-widest text-primary my-3"
        )
        pairing_expires_label = ui.label("").classes("text-sm opacity-60")
        ui.label("Scan the QR code or enter the code manually in the mobile app.").classes(
            "text-sm opacity-70 mb-2"
        )

        # Gateway URL display
        with ui.row().classes("w-full items-center justify-center gap-1 mb-1"):
            ui.icon("cable").classes("text-xs opacity-50")
            pairing_gateway_label = ui.label("").classes("text-xs font-mono opacity-60")

        # Copy full QR message (JSON payload) for pasting into the Flutter app
        # ui.clipboard.write() returns None in this NiceGUI version — do not await it.
        async def _copy_qr_payload() -> None:
            ui.clipboard.write(pending_qr_payload[0])
            ui.notify("Pairing message copied to clipboard.", color="positive", timeout=2500)

        ui.button(
            "Copy pairing message",
            icon="content_copy",
            on_click=_copy_qr_payload,
        ).props("flat dense size=sm").classes("mb-1").tooltip(
            "Copy the full pairing JSON — paste it as a single field in the mobile app"
        )

        ui.button("Close", on_click=pairing_dialog.close).props("flat")

    # ------------------------------------------------------------------ revoke dialog
    with ui.dialog() as revoke_dialog, ui.card().classes("w-96"):
        revoke_title = ui.label("").classes("text-lg font-semibold mb-2")
        ui.label("This device will no longer be able to connect.").classes("text-sm opacity-60")

        async def do_revoke() -> None:
            device_id = pending_revoke_id[0]
            try:
                DeviceRevokeTool().execute(
                    device_id=device_id, workspace=nicegui_app.storage.user.get("selected_workspace")
                )
                ui.notify("Device revoked.", color="positive")
                revoke_dialog.close()
                device_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=revoke_dialog.close).props("flat")
            ui.button("Revoke", on_click=do_revoke).props('color="negative"')

    # ------------------------------------------------------------------ refreshable device list
    @ui.refreshable
    def device_list() -> None:
        ws_name = nicegui_app.storage.user.get("selected_workspace")
        if ws_name is None:
            return

        devices: list[dict] = []
        error: str | None = None
        try:
            result = DeviceListTool().execute(workspace=ws_name)
            devices = result.devices
        except Exception as exc:
            error = str(exc)

        if error:
            ui.label(f"Error loading devices: {error}").classes("text-negative")
            return

        if not devices:
            with ui.card().classes("w-full"):
                ui.label(
                    "No paired devices. Use the button above to generate a pairing code."
                ).classes("opacity-60 text-sm p-2")
            return

        columns = [
            {"name": "device_name", "label": "Name", "field": "device_name", "align": "left"},
            {"name": "device_id", "label": "Device ID", "field": "device_id", "align": "left"},
            {"name": "paired_at", "label": "Paired", "field": "paired_at", "align": "left"},
            {"name": "expires_at", "label": "Expires", "field": "expires_at", "align": "left"},
            {"name": "actions", "label": "", "field": "device_id", "align": "right"},
        ]

        table = ui.table(columns=columns, rows=devices, row_key="device_id").classes("w-full")
        table.add_slot(
            "body-cell-device_name",
            """
            <q-td :props="props">
                <span v-if="props.row.device_name" class="font-medium">{{ props.row.device_name }}</span>
                <span v-else class="opacity-40">—</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-expires_at",
            """
            <q-td :props="props">
                {{ props.row.expires_at || '—' }}
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-actions",
            """
            <q-td :props="props" class="text-right">
                <q-btn flat dense size="sm" icon="link_off" color="negative" title="Revoke"
                       @click="() => $parent.$emit('revoke', props.row)" />
            </q-td>
            """,
        )

        def handle_revoke(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            device_id = row.get("device_id", "")
            pending_revoke_id[0] = device_id
            # Show device name in the confirmation dialog if available.
            display_name = row.get("device_name") or None
            if not display_name:
                short_id = device_id[:12] + "…" if len(device_id) > 12 else device_id
                display_name = short_id
            revoke_title.set_text(f"Revoke '{display_name}'?")
            revoke_dialog.open()

        table.on("revoke", handle_revoke)

    # ------------------------------------------------------------------ generate pairing code
    async def generate_pairing_code() -> None:
        from phbcli.ui.qr import render_qr_svg

        ws = nicegui_app.storage.user.get("selected_workspace")
        if ws is None:
            ui.notify("No workspace selected.", color="negative")
            return
        try:
            result = DeviceAddTool().execute(workspace=ws)
            pairing_qr_html.set_content(render_qr_svg(result.qr_payload))
            pairing_code_label.set_text(result.code)
            # Format the ISO timestamp to be more readable
            expires = result.expires_at.replace("T", " ").replace("Z", " UTC")
            pairing_expires_label.set_text(f"Expires: {expires}")
            pairing_gateway_label.set_text(result.gateway_url or "no gateway configured")
            pending_qr_payload[0] = result.qr_payload
            pairing_dialog.open()
            device_list.refresh()
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    # ------------------------------------------------------------------ page layout
    with ui.column().classes("w-full gap-6 p-6"):
        ui.label("Devices").classes("text-2xl font-semibold")

        # ---- Pair new device card
        with ui.card().classes("w-full"):
            ui.label("Pair new device").classes("text-base font-semibold mb-3")
            ui.label(
                "Generate a short-lived code and enter it on your mobile device to authorize it."
            ).classes("text-sm opacity-60 mb-3")
            ui.button("Generate pairing code", icon="add_link", on_click=generate_pairing_code)

        # ---- Approved devices
        ui.label("Approved devices").classes("text-lg font-semibold")
        device_list()
