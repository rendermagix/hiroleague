"""Workspaces page — list, create, configure, start, stop, restart, set default, remove.

Safety rules enforced here (in addition to tool-level guards):
  - Stop / Remove: blocked if the target is the workspace hosting this Admin UI.
    The user must start another workspace's Admin UI to perform those actions.
  - Restart: a dialog asks whether to also launch the Admin UI on the restarted
    process. If the current workspace is being restarted the option is forced ON
    and read-only (the UI would disappear otherwise).
  - Setup: available for unconfigured workspaces ("Needs setup" status). Mirrors
    the options from `hirocli setup` CLI command. Elevated task option is shown on
    Windows only and triggers a UAC prompt on the server machine.
"""

from __future__ import annotations

import sys

from nicegui import ui


@ui.page("/workspaces")
async def workspaces_page() -> None:
    from hirocli.tools.server import RestartTool, StartTool, StopTool
    from hirocli.tools.workspace import (
        WorkspaceCreateTool,
        WorkspaceGetPublicKeyTool,
        WorkspaceListTool,
        WorkspaceRegenerateKeyTool,
        WorkspaceRemoveTool,
        WorkspaceUpdateTool,
    )
    from hirocli.ui import state as ui_state
    from hirocli.ui.app import create_page_layout

    create_page_layout(active_path="/workspaces")

    # Id of the workspace whose server process is running this Admin UI.
    current_ws_id: str | None = ui_state.workspace_id

    # Mutable containers so inner async callbacks can reference mutable state.
    pending_remove: list[dict] = [{}]
    pending_edit: list[dict] = [{}]
    pending_restart: list[dict] = [{}]
    pending_setup: list[dict] = [{}]
    pending_pubkey: list[dict] = [{}]

    # ------------------------------------------------------------------ create dialog
    with ui.dialog() as create_dialog, ui.card().classes("w-96"):
        ui.label("Create workspace").classes("text-lg font-semibold mb-2")
        name_input = ui.input("Name", placeholder="e.g. work").classes("w-full")
        path_input = ui.input(
            "Path (optional)",
            placeholder="Leave blank for default location",
        ).classes("w-full")

        async def do_create() -> None:
            name = name_input.value.strip()
            if not name:
                ui.notify("Name is required.", color="negative")
                return
            path = path_input.value.strip() or None
            try:
                WorkspaceCreateTool().execute(name=name, path=path)
                ui.notify(f"Workspace '{name}' created.", color="positive")
                create_dialog.close()
                name_input.set_value("")
                path_input.set_value("")
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=create_dialog.close).props("flat")
            ui.button("Create", on_click=do_create)

    # ------------------------------------------------------------------ remove dialog
    with ui.dialog() as remove_dialog, ui.card().classes("w-96"):
        remove_title = ui.label("").classes("text-lg font-semibold mb-2")
        purge_checkbox = ui.checkbox("Also delete workspace folder from disk")

        async def do_remove() -> None:
            row = pending_remove[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                WorkspaceRemoveTool().execute(workspace=ws_id, purge=purge_checkbox.value)
                ui.notify(f"Workspace '{ws_name}' removed.", color="positive")
                remove_dialog.close()
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=remove_dialog.close).props("flat")
            ui.button("Remove", on_click=do_remove).props('color="negative"')

    # ------------------------------------------------------------------ edit dialog (name, gateway, default)
    with ui.dialog() as edit_dialog, ui.card().classes("w-[480px]"):
        edit_title = ui.label("").classes("text-lg font-semibold mb-2")
        edit_name_input = ui.input("Display name").classes("w-full")
        edit_gateway_input = ui.input(
            "Gateway WebSocket URL",
            placeholder="ws://myhost:8765",
        ).classes("w-full mt-2")
        edit_default_checkbox = ui.checkbox("Set as default workspace").classes("mt-2")
        edit_info = ui.label("").classes("text-xs opacity-60 mt-2")

        async def do_edit() -> None:
            row = pending_edit[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")

            new_name = edit_name_input.value.strip() or None
            new_gateway = edit_gateway_input.value.strip() or None
            make_default = edit_default_checkbox.value

            if new_name is None and new_gateway is None and not make_default:
                ui.notify("Nothing to update.", color="warning")
                return
            try:
                result = WorkspaceUpdateTool().execute(
                    workspace=ws_id,
                    name=new_name,
                    set_default=make_default,
                    gateway_url=new_gateway,
                )
                msgs = []
                if result.renamed:
                    msgs.append(f"renamed to '{result.name}'")
                if result.default_changed:
                    msgs.append("set as default")
                if result.gateway_updated:
                    msgs.append("gateway updated")
                ui.notify(
                    f"Workspace '{ws_name}' updated: {', '.join(msgs) or 'no changes'}.",
                    color="positive",
                )
                edit_dialog.close()
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=edit_dialog.close).props("flat")
            ui.button("Save", on_click=do_edit)

    # ------------------------------------------------------------------ restart dialog
    with ui.dialog() as restart_dialog, ui.card().classes("w-[440px]"):
        restart_title = ui.label("").classes("text-lg font-semibold mb-2")
        restart_info = ui.label("").classes("text-sm opacity-60 mb-3")
        admin_ui_checkbox = ui.checkbox("Also start Admin UI on the restarted process")

        async def do_restart() -> None:
            row = pending_restart[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                RestartTool().execute(workspace=ws_id, admin=admin_ui_checkbox.value)
                if ws_id == current_ws_id:
                    ui.notify(
                        "Restarting… the Admin UI will be back shortly.",
                        color="info",
                        timeout=6000,
                    )
                else:
                    ui.notify(f"'{ws_name}' restarted.", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            restart_dialog.close()
            workspace_list.refresh()

        with ui.row().classes("justify-end gap-2 w-full mt-4"):
            ui.button("Cancel", on_click=restart_dialog.close).props("flat")
            ui.button("Restart", on_click=do_restart).props('color="warning"')

    # ------------------------------------------------------------------ public key dialog (DEV)
    with ui.dialog() as pubkey_dialog, ui.card().classes("w-[520px]"):
        pubkey_title = ui.label("").classes("text-lg font-semibold mb-1")

        with ui.card().classes("w-full bg-amber-50 dark:bg-amber-900/30 border border-amber-400 mb-3"):
            with ui.row().classes("items-start gap-2 p-1"):
                ui.icon("warning").classes("text-amber-500 text-xl mt-0.5 shrink-0")
                ui.label(
                    "This key must be registered in every gateway instance that trusts this "
                    "workspace. Regenerating it invalidates all existing gateway trust relationships."
                ).classes("text-sm text-amber-800 dark:text-amber-200")

        ui.label("Workspace public key (Ed25519, base64):").classes(
            "text-xs font-semibold opacity-70"
        )
        with ui.row().classes("w-full items-start gap-2"):
            pubkey_display = ui.textarea().classes("w-full font-mono text-xs").props(
                "readonly rows=3 outlined"
            )

            async def _copy_pubkey_dialog() -> None:
                await ui.clipboard.write(pubkey_display.value)
                ui.notify("Public key copied to clipboard.", color="positive", timeout=2500)

            ui.button(icon="content_copy", on_click=_copy_pubkey_dialog).props(
                "flat dense"
            ).classes("mt-1 shrink-0").tooltip("Copy to clipboard")

        async def do_regenerate_key() -> None:
            row = pending_pubkey[0]
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                result = WorkspaceRegenerateKeyTool().execute(workspace=ws_id)
                pubkey_display.set_value(result.public_key_b64)
                ui.notify(
                    f"New key generated for '{ws_name}'. Update your gateway instance.",
                    color="warning",
                    timeout=6000,
                )
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        with ui.row().classes("justify-between w-full mt-4"):
            ui.button(
                "Regenerate key",
                icon="autorenew",
                on_click=do_regenerate_key,
            ).props('color="warning" outline')
            ui.button("Close", on_click=pubkey_dialog.close).props("flat")

    # ------------------------------------------------------------------ setup dialog
    # persistent=True prevents accidental dismissal by clicking outside the dialog.
    # The card has two panels: the form (setup_form_panel) and the post-setup public
    # key reveal (setup_key_panel). Only one is visible at a time.
    setup_dialog = ui.dialog().props("persistent")

    with setup_dialog, ui.card().classes("w-[520px]"):

        # ---- form panel ----
        setup_form_panel = ui.column().classes("w-full gap-0")
        with setup_form_panel:
            setup_title = ui.label("").classes("text-lg font-semibold mb-1")
            setup_path_info = ui.label("").classes("text-xs opacity-50 mb-3")

            setup_gateway_input = ui.input(
                "Gateway WebSocket URL *",
                placeholder="ws://myhost:8765",
            ).classes("w-full")

            with ui.expansion("Advanced options", icon="tune").classes("w-full mt-2"):
                setup_port_input = ui.number(
                    "HTTP port override",
                    placeholder="Leave blank to use auto-assigned port",
                    min=1024,
                    max=65535,
                    precision=0,
                ).classes("w-full")
                setup_port_info = ui.label("").classes("text-xs opacity-50 mt-1 mb-2")

                setup_skip_autostart = ui.checkbox(
                    "Skip auto-start registration",
                ).classes("mt-1")
                ui.label(
                    "By default, the server is registered to start automatically on login."
                ).classes("text-xs opacity-50 ml-6 mb-2")

                setup_start_server = ui.checkbox(
                    "Start server immediately after setup",
                ).classes("mt-1")

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
                    # Non-Windows: create a dummy checkbox that is never shown/used
                    setup_elevated_task = ui.checkbox("").classes("hidden")

        # ---- key reveal panel (hidden until setup succeeds) ----
        setup_key_panel = ui.column().classes("w-full gap-3")
        with setup_key_panel:
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle").classes("text-positive text-2xl")
                setup_key_ws_label = ui.label("").classes("text-lg font-semibold")

            with ui.card().classes("w-full bg-amber-50 dark:bg-amber-900/30 border border-amber-400"):
                with ui.row().classes("items-start gap-2 p-1"):
                    ui.icon("warning").classes("text-amber-500 text-xl mt-0.5 shrink-0")
                    ui.label(
                        "Save this public key — it will not be shown again. "
                        "You must paste it into the Desktop public key field "
                        "when creating a gateway instance for this workspace."
                    ).classes("text-sm text-amber-800 dark:text-amber-200")

            ui.label("Workspace public key (Ed25519, base64):").classes(
                "text-xs font-semibold opacity-70 mt-1"
            )
            with ui.row().classes("w-full items-start gap-2"):
                setup_pubkey_display = ui.textarea().classes("w-full font-mono text-xs").props(
                    "readonly rows=3 outlined"
                )

                async def _copy_pubkey() -> None:
                    await ui.clipboard.write(setup_pubkey_display.value)
                    ui.notify("Public key copied to clipboard.", color="positive", timeout=2500)

                ui.button(icon="content_copy", on_click=_copy_pubkey).props(
                    "flat dense"
                ).classes("mt-1 shrink-0").tooltip("Copy to clipboard")

        setup_key_panel.set_visibility(False)

        # ---- form action buttons (rendered after both panels so they sit below) ----
        with setup_form_panel:
            with ui.row().classes("justify-end gap-2 w-full mt-4"):
                ui.button("Cancel", on_click=setup_dialog.close).props("flat")
                setup_run_btn = ui.button("Run setup", icon="settings")

        # ---- key panel dismiss button ----
        with setup_key_panel:
            with ui.row().classes("justify-end w-full mt-2"):
                ui.button(
                    "I've saved the key — close",
                    icon="lock",
                    on_click=lambda: _dismiss_setup_key_panel(),
                ).props('color="primary"')

        async def do_setup() -> None:
            from hirocli.tools.server import SetupTool

            row = pending_setup[0]
            ws_id = row.get("id", "")

            gateway = setup_gateway_input.value.strip()
            if not gateway:
                ui.notify("Gateway WebSocket URL is required.", color="negative")
                return

            port_val = setup_port_input.value
            http_port: int | None = int(port_val) if port_val else None

            try:
                result = SetupTool().execute(
                    gateway_url=gateway,
                    workspace=ws_id,
                    http_port=http_port,
                    skip_autostart=setup_skip_autostart.value,
                    start_server=setup_start_server.value,
                    elevated_task=setup_elevated_task.value,
                )
                # Swap to key reveal panel — form is hidden until dialog is reopened
                setup_key_ws_label.set_text(f"Workspace '{result.workspace}' configured")
                setup_pubkey_display.set_value(result.desktop_pub)
                setup_form_panel.set_visibility(False)
                setup_key_panel.set_visibility(True)
                workspace_list.refresh()
            except Exception as exc:
                ui.notify(str(exc), color="negative")

        setup_run_btn.on("click", do_setup)

        def _dismiss_setup_key_panel() -> None:
            setup_key_panel.set_visibility(False)
            setup_form_panel.set_visibility(True)
            _reset_setup_form()
            setup_dialog.close()

        def _reset_setup_form() -> None:
            setup_gateway_input.set_value("")
            setup_port_input.set_value(None)
            setup_skip_autostart.set_value(False)
            setup_start_server.set_value(False)
            setup_elevated_task.set_value(False)
            setup_pubkey_display.set_value("")

    # ------------------------------------------------------------------ refreshable table
    @ui.refreshable
    def workspace_list() -> None:
        from pathlib import Path

        from hiro_commons.process import is_running, read_pid

        rows: list[dict] = []
        error: str | None = None

        try:
            ws_result = WorkspaceListTool().execute()
            for ws in ws_result.workspaces:
                ws_path = Path(ws["path"])
                pid = read_pid(ws_path, "hirocli.pid")
                running = is_running(pid)
                rows.append({
                    **ws,
                    "running": running,
                    "pid": pid,
                    "is_current": ws["id"] == current_ws_id,
                })
        except Exception as exc:
            error = str(exc)

        if error:
            ui.label(f"Error loading workspaces: {error}").classes("text-negative")
            return

        if not rows:
            with ui.card().classes("w-full"):
                ui.label("No workspaces configured yet. Create one to get started.").classes(
                    "opacity-60 text-sm p-2"
                )
            return

        columns = [
            {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
            {"name": "setup", "label": "Setup", "field": "is_configured", "align": "left"},
            {"name": "status", "label": "Server", "field": "running", "align": "left"},
            {"name": "autostart", "label": "Autostart", "field": "autostart_method", "align": "left"},
            {"name": "gateway_url", "label": "Gateway", "field": "gateway_url", "align": "left"},
            {"name": "http_port", "label": "HTTP", "field": "http_port", "align": "left"},
            {"name": "admin_port", "label": "Admin", "field": "admin_port", "align": "left"},
            {"name": "folder", "label": "Folder", "field": "path", "align": "left"},
            {"name": "is_default", "label": "Default", "field": "is_default", "align": "center"},
            {"name": "actions", "label": "", "field": "name", "align": "right"},
        ]

        table = ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")

        table.add_slot(
            "body-cell-setup",
            """
            <q-td :props="props">
                <q-badge
                    :color="props.row.is_configured ? 'positive' : 'warning'"
                    :label="props.row.is_configured ? 'Configured' : 'Needs setup'" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-status",
            """
            <q-td :props="props">
                <q-badge
                    :color="props.row.running ? 'positive' : 'grey-6'"
                    :label="props.row.running ? 'Running' : 'Stopped'" />
                <q-badge v-if="props.row.is_current" color="info" label="this UI"
                         class="q-ml-xs" />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-autostart",
            """
            <q-td :props="props">
                <q-badge v-if="props.row.autostart_method === 'elevated'"
                         color="deep-purple" label="elevated" />
                <q-badge v-else-if="props.row.autostart_method === 'schtasks'"
                         color="primary" label="schtasks" />
                <q-badge v-else-if="props.row.autostart_method === 'registry'"
                         color="teal" label="registry" />
                <q-badge v-else-if="props.row.autostart_method === 'skipped'"
                         color="grey-6" label="skipped" />
                <q-badge v-else-if="props.row.autostart_method === 'failed'"
                         color="negative" label="failed" />
                <span v-else class="opacity-30 text-xs">—</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-gateway_url",
            """
            <q-td :props="props">
                <div v-if="props.row.gateway_url && props.row.running"
                     class="row items-center gap-1">
                    <q-icon name="cable" size="xs" color="primary" />
                    <a :href="props.row.gateway_url.replace(/^ws/, 'http')"
                       target="_blank"
                       class="text-xs font-mono text-primary hover:underline cursor-pointer"
                       :title="props.row.gateway_url">
                        {{ props.row.gateway_url }}
                    </a>
                </div>
                <span v-else-if="props.row.gateway_url" class="text-xs font-mono opacity-50">
                    {{ props.row.gateway_url }}
                </span>
                <span v-else class="opacity-30 text-xs">—</span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-http_port",
            """
            <q-td :props="props">
                <div v-if="props.row.running" class="row items-center gap-2">
                    <a :href="'http://127.0.0.1:' + props.row.http_port + '/status'"
                       target="_blank"
                       class="text-primary hover:opacity-70"
                       :title="'http://127.0.0.1:' + props.row.http_port + '/status'">
                        <q-icon name="open_in_browser" size="xs" />
                    </a>
                </div>
                <span v-else class="text-xs font-mono opacity-50">
                    {{ props.row.http_port }}
                </span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-admin_port",
            """
            <q-td :props="props">
                <div v-if="props.row.running" class="row items-center gap-2">
                    <a :href="'http://127.0.0.1:' + props.row.admin_port + '/'"
                       target="_blank"
                       class="text-primary hover:opacity-70"
                       :title="'Admin UI: http://127.0.0.1:' + props.row.admin_port + '/'">
                        <q-icon name="dashboard" size="xs" />
                    </a>
                </div>
                <span v-else class="text-xs font-mono opacity-50">
                    {{ props.row.admin_port }}
                </span>
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-folder",
            """
            <q-td :props="props">
                <span class="text-xs cursor-pointer text-primary hover:underline"
                      @click="() => $parent.$emit('open-folder', props.row)"
                      title="Open workspace folder">
                    📁
                </span>
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
            "body-cell-actions",
            """
            <q-td :props="props">
              <div class="row no-wrap justify-end items-center">

                <!-- Setup: only for unconfigured workspaces -->
                <q-btn v-if="!props.row.is_configured"
                       flat size="sm" icon="settings" color="warning"
                       title="Run setup" class="q-ma-xs"
                       @click="() => $parent.$emit('setup', props.row)" />

                <!-- Public key: only for configured workspaces (DEV) -->
                <q-btn v-if="props.row.is_configured"
                       flat size="sm" icon="key" color="secondary"
                       title="View / regenerate public key" class="q-ma-xs"
                       @click="() => $parent.$emit('pubkey', props.row)" />

                <!-- Start: only for configured + stopped workspaces -->
                <q-btn v-if="props.row.is_configured && !props.row.running"
                       flat size="sm" icon="play_arrow" color="positive"
                       title="Start" class="q-ma-xs"
                       @click="() => $parent.$emit('start', props.row)" />

                <!-- Stop: hidden for current workspace; shown for all others -->
                <q-btn v-if="props.row.running && !props.row.is_current"
                       flat size="sm" icon="stop" color="negative"
                       title="Stop" class="q-ma-xs"
                       @click="() => $parent.$emit('stop', props.row)" />

                <!-- Restart: only when running -->
                <q-btn v-if="props.row.running"
                       flat size="sm" icon="restart_alt" color="primary"
                       title="Restart" class="q-ma-xs"
                       @click="() => $parent.$emit('restart', props.row)" />

                <!-- Edit (name, gateway, default) -->
                <q-btn flat size="sm" icon="edit" color="secondary"
                       title="Edit workspace" class="q-ma-xs"
                       @click="() => $parent.$emit('edit', props.row)" />

                <!-- Remove: replaced with lock icon for current workspace -->
                <q-btn v-if="!props.row.is_current"
                       flat size="sm" icon="delete" color="negative"
                       title="Remove" class="q-ma-xs"
                       @click="() => $parent.$emit('remove', props.row)" />
                <q-btn v-if="props.row.is_current"
                       flat size="sm" icon="lock" color="grey-5"
                       title="Cannot remove: this workspace is running the Admin UI"
                       class="q-ma-xs" disable />

              </div>
            </q-td>
            """,
        )

        # ---------------------------------------------------------------- event handlers

        async def handle_start(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            try:
                result = StartTool().execute(workspace=ws_id)
                if result.already_running:
                    ui.notify(f"'{ws_name}' is already running.", color="warning")
                else:
                    ui.notify(f"'{ws_name}' started (PID {result.pid}).", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            workspace_list.refresh()

        async def handle_stop(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            if ws_id == current_ws_id:
                ui.notify(
                    "Cannot stop the workspace running this Admin UI. "
                    "Start another workspace's Admin UI to do this.",
                    color="negative",
                    timeout=6000,
                )
                return
            try:
                StopTool().execute(workspace=ws_id)
                ui.notify(f"'{ws_name}' stopped.", color="positive")
            except Exception as exc:
                ui.notify(str(exc), color="negative")
            workspace_list.refresh()

        def handle_restart(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_restart[0] = row
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            is_current = (ws_id == current_ws_id)

            restart_title.set_text(f"Restart workspace '{ws_name}'")
            if is_current:
                restart_info.set_text(
                    "This workspace is running the current Admin UI. "
                    "The Admin UI will restart automatically — keep the option below enabled."
                )
                admin_ui_checkbox.set_value(True)
                admin_ui_checkbox.props(add="disable")
            else:
                restart_info.set_text(f"Path: {row.get('path', '')}")
                admin_ui_checkbox.set_value(False)
                admin_ui_checkbox.props(remove="disable")

            restart_dialog.open()

        def handle_edit(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_edit[0] = row
            ws_name = row.get("name", "")
            edit_title.set_text(f"Edit workspace '{ws_name}'")
            edit_name_input.set_value(ws_name)
            edit_gateway_input.set_value(row.get("gateway_url") or "")
            edit_default_checkbox.set_value(row.get("is_default", False))
            http = row.get("http_port", "")
            admin = row.get("admin_port", "")
            edit_info.set_text(
                f"HTTP port: {http}  •  Admin port: {admin}  •  Path: {row.get('path', '')}"
            )
            edit_dialog.open()

        def handle_setup(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_setup[0] = row
            ws_name = row.get("name", "")
            setup_title.set_text(f"Setup workspace '{ws_name}'")
            setup_path_info.set_text(f"Path: {row.get('path', '')}")
            # Pre-fill gateway if already partially configured
            setup_gateway_input.set_value(row.get("gateway_url") or "")
            setup_port_input.set_value(None)
            setup_port_info.set_text(
                f"Auto-assigned HTTP port: {row.get('http_port', 'unknown')}"
            )
            setup_skip_autostart.set_value(False)
            setup_start_server.set_value(False)
            setup_elevated_task.set_value(False)
            # Always open on the form panel (guard against stale state)
            setup_key_panel.set_visibility(False)
            setup_form_panel.set_visibility(True)
            setup_dialog.open()

        def handle_pubkey(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            pending_pubkey[0] = row
            ws_name = row.get("name", "")
            ws_id = row.get("id", "")
            pubkey_title.set_text(f"Public key — '{ws_name}'")
            pubkey_display.set_value("")
            try:
                result = WorkspaceGetPublicKeyTool().execute(workspace=ws_id)
                pubkey_display.set_value(result.public_key_b64)
            except Exception as exc:
                ui.notify(str(exc), color="negative")
                return
            pubkey_dialog.open()

        def handle_open_folder(e) -> None:
            import platform
            import subprocess

            row = e.args if isinstance(e.args, dict) else {}
            folder_path = row.get("path", "")
            if not folder_path:
                ui.notify("Folder path not available.", color="warning")
                return

            try:
                system = platform.system()
                if system == "Windows":
                    subprocess.Popen(f'explorer "{folder_path}"')
                elif system == "Darwin":  # macOS
                    subprocess.Popen(["open", folder_path])
                else:  # Linux and others
                    subprocess.Popen(["xdg-open", folder_path])
                ui.notify(f"Opening folder: {folder_path}", color="info", timeout=2000)
            except Exception as exc:
                ui.notify(f"Could not open folder: {str(exc)}", color="negative")

        def handle_remove(e) -> None:
            row = e.args if isinstance(e.args, dict) else {}
            ws_id = row.get("id", "")
            ws_name = row.get("name", "")
            if ws_id == current_ws_id:
                ui.notify(
                    "Cannot remove the workspace running this Admin UI. "
                    "Start another workspace's Admin UI to do this.",
                    color="negative",
                    timeout=6000,
                )
                return
            pending_remove[0] = row
            remove_title.set_text(f"Remove workspace '{ws_name}'?")
            purge_checkbox.set_value(False)
            remove_dialog.open()

        table.on("setup", handle_setup)
        table.on("pubkey", handle_pubkey)
        table.on("open-folder", handle_open_folder)
        table.on("start", handle_start)
        table.on("stop", handle_stop)
        table.on("restart", handle_restart)
        table.on("edit", handle_edit)
        table.on("remove", handle_remove)

    # ------------------------------------------------------------------ page layout
    with ui.column().classes("w-full gap-6 p-6"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Workspaces").classes("text-2xl font-semibold")
            ui.button("Create workspace", icon="add", on_click=create_dialog.open)

        workspace_list()
