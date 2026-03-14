"""Channels page — list channel plugins for a workspace, with enable/disable actions.

The active workspace is selected globally in the header and stored in
nicegui_app.storage.user["selected_workspace"].
Each channel row shows name, enabled status, command, and config keys.
The mandatory 'devices' channel cannot be disabled.
"""

from __future__ import annotations

from nicegui import app as nicegui_app, ui


@ui.page("/channels")
async def channels_page() -> None:
    from hirocli.tools.channel import ChannelDisableTool, ChannelEnableTool, ChannelListTool
    from hirocli.ui.app import create_page_layout

    create_page_layout(active_path="/channels")

    ws_name: str | None = nicegui_app.storage.user.get("selected_workspace")

    # ------------------------------------------------------------------ refreshable channel table
    @ui.refreshable
    def channel_table() -> None:
        if ws_name is None:
            ui.label("No workspaces available.").classes("opacity-60 text-sm")
            return

        channels: list[dict] = []
        error: str | None = None
        try:
            result = ChannelListTool().execute(workspace=ws_name)
            channels = result.channels
        except Exception as exc:
            error = str(exc)

        if error:
            ui.label(f"Error loading channels: {error}").classes("text-negative")
            return

        if not channels:
            with ui.card().classes("w-full"):
                ui.label("No channels configured for this workspace.").classes(
                    "opacity-60 text-sm p-2"
                )
            return

        columns = [
            {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
            {"name": "enabled", "label": "Status", "field": "enabled", "align": "left"},
            {"name": "command", "label": "Command", "field": "command", "align": "left"},
            {"name": "config_keys", "label": "Config keys", "field": "config_keys", "align": "left"},
            {"name": "actions", "label": "", "field": "name", "align": "right"},
        ]

        table = ui.table(columns=columns, rows=channels, row_key="name").classes("w-full")
        table.add_slot(
            "body-cell-enabled",
            """
            <q-td :props="props">
                <q-badge :color="props.row.enabled ? 'positive' : 'grey-6'"
                         :label="props.row.enabled ? 'Enabled' : 'Disabled'" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-config_keys",
            """
            <q-td :props="props">
                <q-chip v-for="key in props.row.config_keys" :key="key"
                        dense size="sm" :label="key" class="mr-1" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-actions",
            # The mandatory 'devices' channel cannot be toggled.
            """
            <q-td :props="props" class="text-right">
                <template v-if="props.row.name !== 'devices'">
                    <q-btn v-if="props.row.enabled" flat dense size="sm"
                           icon="toggle_on" color="positive" title="Disable"
                           @click="() => $parent.$emit('disable', props.row)" />
                    <q-btn v-else flat dense size="sm"
                           icon="toggle_off" color="grey-6" title="Enable"
                           @click="() => $parent.$emit('enable', props.row)" />
                </template>
                <q-icon v-else name="lock" size="sm" class="opacity-30"
                        title="Mandatory channel — cannot be disabled" />
            </q-td>
            """,
        )

        async def handle_enable(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            name = row.get("name", "")
            try:
                ChannelEnableTool().execute(channel_name=name, workspace=ws_name)
                ui.notify(f"Channel '{name}' enabled.", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            channel_table.refresh()

        async def handle_disable(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            name = row.get("name", "")
            try:
                ChannelDisableTool().execute(channel_name=name, workspace=ws_name)
                ui.notify(f"Channel '{name}' disabled.", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            channel_table.refresh()

        table.on("enable", handle_enable)
        table.on("disable", handle_disable)

    # ------------------------------------------------------------------ page layout
    with ui.column().classes("w-full gap-6 p-6"):
        ui.label("Channels").classes("text-2xl font-semibold")
        channel_table()
