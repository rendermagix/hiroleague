"""NiceGUI app shell — shared layout, sidebar navigation, and page registration.

Call `register_pages()` once before starting the Uvicorn server.  Each page
calls `create_page_layout(active_path)` at the top of its page function.

Dark mode strategy:
  NiceGUI's ui.dark_mode() sets Quasar's body--dark class, which is NOT the
  same as Tailwind's 'dark' selector.  All layout elements therefore use Quasar
  components (QHeader, QDrawer, QItem, etc.) which auto-adapt — no hardcoded
  Tailwind colors on structural elements.

Workspace selection strategy:
  The active workspace is stored in nicegui_app.storage.user["selected_workspace"]
  (by workspace *id*) so it persists across page navigations within a browser
  session.  The header renders a single workspace dropdown; changing it reloads
  the current page so all page content reflects the new selection.
"""

from __future__ import annotations

from nicegui import app as nicegui_app, ui

_NAV: list[tuple[str | None, str, str | None, str | None]] = [
    # (group, label, icon, path)  — group=None marks a section header row
    (None, "Server", None, None),
    ("Server", "Dashboard", "dashboard", "/"),
    ("Server", "Workspaces", "storage", "/workspaces"),
    ("Server", "Channels", "cable", "/channels"),
    ("Server", "Agents", "smart_toy", "/agents"),
    (None, "Nodes / Devices", None, None),
    ("Nodes / Devices", "Devices", "devices", "/devices"),
    ("Nodes / Devices", "Chats", "chat", "/chats"),
    (None, "Configuration", None, None),
    ("Configuration", "Logs", "article", "/logs"),
]


def create_page_layout(active_path: str = "/") -> None:
    """Render the full shell (header + collapsible sidebar) for a page.

    Must be called at the top of every @ui.page function.  The drawer is
    instantiated first so the header toggle button can reference it.
    """
    from phbcli.ui import state as ui_state
    from phbcli.tools.workspace import WorkspaceListTool

    # NiceGUI ui.select accepts {value: label} dicts or plain lists of strings.
    # A list-of-dicts format is NOT supported — each dict would be treated as the
    # option value itself, causing "Invalid value" when a string id is passed.
    workspace_options: dict[str, str] = {}  # {ws_id: display_label}
    default_ws_id: str | None = None
    try:
        ws_result = WorkspaceListTool().execute()
        for ws in ws_result.workspaces:
            label = ws["name"]
            if ui_state.workspace_id and ws["id"] == ui_state.workspace_id:
                label += " (this UI)"
            workspace_options[ws["id"]] = label
        default_ws_id = ws_result.default_workspace or (
            next(iter(workspace_options), None)
        )
    except Exception:
        pass

    ws_ids = list(workspace_options.keys())

    stored = nicegui_app.storage.user.get("selected_workspace")
    # Use a local variable so the validated id is passed directly to ui.select
    # without re-reading from browser-backed storage (write may not propagate
    # within the same request).
    selected_id = stored if stored in ws_ids else default_ws_id
    nicegui_app.storage.user["selected_workspace"] = selected_id

    # Sidebar mini state: when True, drawer shows only icons (narrow); persists in user storage.
    if "sidebar_mini" not in nicegui_app.storage.user:
        nicegui_app.storage.user["sidebar_mini"] = False
    sidebar_mini = nicegui_app.storage.user["sidebar_mini"]

    # width/mini-width set explicitly; Quasar default (300/57) is too wide/narrow
    drawer = ui.left_drawer(value=True).props('behavior="desktop" bordered :width="210" :mini-width="88"')
    # Set initial mini state if needed
    if sidebar_mini:
        drawer.props(add="mini")

    def toggle_sidebar_mini() -> None:
        nicegui_app.storage.user["sidebar_mini"] = not nicegui_app.storage.user["sidebar_mini"]
        mini = nicegui_app.storage.user["sidebar_mini"]
        
        # Toggle mini prop on the drawer element
        if mini:
            drawer.props(add="mini")
        else:
            drawer.props(remove="mini")

    with drawer:
        _sidebar(active_path)

    ui.dark_mode().bind_value(nicegui_app.storage.user, "dark_mode")

    # Build header title — include the UI workspace name when available
    header_title = "PHB Admin"
    if ui_state.workspace_name:
        header_title = f"PHB Admin — {ui_state.workspace_name}"

    with ui.header(elevated=True).classes("items-center justify-between"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="menu", on_click=toggle_sidebar_mini).props('flat dense round color="white"')
            ui.icon("home").classes("text-primary text-xl")
            ui.label(header_title).classes("text-lg font-semibold")

        with ui.row().classes("items-center gap-4"):
            if workspace_options:
                def on_workspace_change(e) -> None:
                    nicegui_app.storage.user["selected_workspace"] = e.value
                    ui.navigate.reload()

                ui.select(
                    workspace_options,
                    value=selected_id,
                    label="Workspace",
                    on_change=on_workspace_change,
                ).classes("min-w-40").props("dense outlined dark")

            ui.switch("Dark mode").props("dense").bind_value(
                nicegui_app.storage.user, "dark_mode"
            )


def _sidebar(active_path: str) -> None:
    """Render sidebar navigation using Quasar QItem components (auto-adapt to dark mode).

    Uses proper QItemSection structure so Quasar's mini mode auto-centers icons.
    The avatar section's default right-padding (16px) is overridden to 8px to
    keep icon and label close together in expanded mode.
    Section headers and label sections use q-mini-drawer-hide to vanish in mini mode.
    """
    with ui.column().classes("w-full py-0"):
        for group, label, icon, path in _NAV:
            if group is None:
                ui.label(label).classes(
                    "text-xs font-semibold uppercase tracking-wider opacity-50 px-4 pt-1 pb-0 q-mini-drawer-hide"
                )
            else:
                is_active = path == active_path
                with ui.item(on_click=lambda p=path: ui.navigate.to(p)).props(
                    "clickable v-ripple dense"
                ).classes("rounded-md mx-2 my-0" + (" text-primary" if is_active else "")):
                    # avatar section: override default 16px right-gap to keep icon tight to label
                    with ui.item_section().props("avatar").style("min-width:0; padding-right:8px"):
                        if icon:
                            icon_elem = ui.icon(icon).classes(
                                "text-lg " + ("text-primary" if is_active else "opacity-60")
                            )
                            icon_elem.tooltip(label)
                    with ui.item_section().classes("q-mini-drawer-hide"):
                        ui.label(label).classes("text-sm")


def register_pages() -> None:
    """Register all UI pages.  Import page modules so their @ui.page decorators fire."""
    from phbcli.ui.pages import dashboard as _dashboard  # noqa: F401 — side-effect import
    from phbcli.ui.pages import workspaces as _workspaces  # noqa: F401 — side-effect import
    from phbcli.ui.pages import channels as _channels  # noqa: F401 — side-effect import
    from phbcli.ui.pages import devices as _devices  # noqa: F401 — side-effect import
    from phbcli.ui.pages import agents as _agents  # noqa: F401 — side-effect import
    from phbcli.ui.pages import logs as _logs  # noqa: F401 — side-effect import

    _register_stub_pages()


# ---------------------------------------------------------------------------
# Stub pages for routes not yet implemented
# ---------------------------------------------------------------------------

_STUBS: list[tuple[str, str, str]] = [
    ("/chats", "Chats", "chat"),
]


def _register_stub_pages() -> None:
    for path, label, icon in _STUBS:
        _make_stub_page(path, label, icon)


def _make_stub_page(path: str, label: str, icon: str) -> None:
    @ui.page(path)
    def _stub_page() -> None:
        create_page_layout(active_path=path)
        with ui.column().classes("w-full gap-4 p-6"):
            ui.label(label).classes("text-2xl font-semibold")
            with ui.card().classes("w-full max-w-sm items-center text-center"):
                ui.icon(icon).classes("text-4xl opacity-30 mt-2")
                ui.label("Coming soon").classes("text-lg font-medium opacity-50 mb-1")
                ui.label("This page is planned but not yet implemented.").classes(
                    "text-sm opacity-40 mb-2"
                )
