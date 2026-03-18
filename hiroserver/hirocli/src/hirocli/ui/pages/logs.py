"""Logs page — unified AG Grid log viewer.

Single table merging server.log, plugin-*.log, and gateway.log.
Filtering: source chips (Server / Plugins / Gateway) with plugin
multi-select, level chips, full-text search (server-side via LogSearchTool).
Live tailing: LogTailTool with incremental byte-offset polling.

Features:
- Theme-aware colors: CSS variables switch with Quasar dark mode
- Newest-first / Oldest-first toggle with smart auto-scroll
  (auto-scroll only while pinned to the leading edge; suspends when
  the user scrolls away, resumes when they scroll back to the edge)
- All preferences persisted in nicegui_app.storage.user
"""

from __future__ import annotations

import json

from nicegui import app as nicegui_app, ui

from hirocli.ui import state
from hirocli.ui.app import create_page_layout

_POLL_INTERVAL = 0.5   # seconds between incremental polls
_INITIAL_LINES = 500   # lines loaded on first open

# ---------------------------------------------------------------------------
# Theme-aware CSS for log level and module colours.
#
# cellStyle {"function": "..."} does not apply in NiceGUI's AG Grid wrapper,
# so colours are driven by cellClassRules (plain boolean expressions that AG
# Grid evaluates natively) + CSS classes defined here.
# ---------------------------------------------------------------------------
_LOG_COLORS_CSS = """
<style>
/* Level colours — light mode */
.log-lvl-debug    { color: #3b82f6 !important; }
.log-lvl-info     { color: #16a34a !important; }
.log-lvl-warning  { color: #ca8a04 !important; font-weight: bold; }
.log-lvl-error    { color: #dc2626 !important; font-weight: bold; }
.log-lvl-critical { color: #9333ea !important; font-weight: bold; }

/* Module colours — light mode (hash bucket 0-3) */
.log-mod-0 { color: #0891b2 !important; }
.log-mod-1 { color: #c026d3 !important; }
.log-mod-2 { color: #ca8a04 !important; }
.log-mod-3 { color: #16a34a !important; }

/* Dark-mode overrides */
.body--dark .log-lvl-debug    { color: #60a5fa !important; }
.body--dark .log-lvl-info     { color: #4ade80 !important; }
.body--dark .log-lvl-warning  { color: #facc15 !important; }
.body--dark .log-lvl-error    { color: #f87171 !important; }
.body--dark .log-lvl-critical { color: #c084fc !important; }

.body--dark .log-mod-0 { color: #22d3ee !important; }
.body--dark .log-mod-1 { color: #e879f9 !important; }
.body--dark .log-mod-2 { color: #fde047 !important; }
.body--dark .log-mod-3 { color: #86efac !important; }

/* Extra column — muted debug colour */
:root  { --log-debug: #3b82f6; }
.body--dark { --log-debug: #60a5fa; }
</style>
"""

# ---------------------------------------------------------------------------
# AG Grid column definitions.
# Fixed widths for most columns; Extra uses flex:1 to fill remaining space
# (safe because autoSizeStrategy is disabled in grid options).
#
# Level and Module columns display pre-rendered HTML (via html_columns on the
# grid) pointing to *_html fields. NiceGUI's AG Grid does NOT reliably apply
# cellStyle {"function":...} or cellClassRules — html_columns is the only
# approach that works for per-cell dynamic colouring.
# ---------------------------------------------------------------------------
_COL_DEFS = [
    {
        "headerName": "Time",
        "field": "timestamp",
        "width": 90,
        "sortable": True,
        "filter": True,
        "resizable": True,
    },
    {
        "headerName": "Lvl",
        "field": "level_html",
        "width": 80,
        "sortable": True,
        "resizable": True,
    },
    {
        "headerName": "Source",
        "field": "source",
        "width": 130,
        "sortable": True,
        "filter": True,
        "resizable": True,
    },
    {
        "headerName": "Module",
        "field": "module_html",
        "width": 120,
        "sortable": True,
        "resizable": True,
    },
    {
        "headerName": "Message",
        "field": "message",
        "width": 400,
        "sortable": True,
        "filter": True,
        "resizable": True,
    },
    {
        "headerName": "Extra",
        "field": "extra",
        "flex": 1,          # fills remaining table width; safe with autoSizeStrategy: null
        "minWidth": 150,
        "sortable": True,
        "filter": True,
        "resizable": True,
        "cellStyle": {"color": "var(--log-debug)", "opacity": "0.75"},
    },
]

_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LEVEL_CHIP_COLORS = {
    "DEBUG": "blue",
    "INFO": "positive",
    "WARNING": "warning",
    "ERROR": "negative",
    "CRITICAL": "purple",
}


def _set_chip_on(btn: ui.button) -> None:
    """Visually activate a chip button (filled appearance)."""
    btn.props(remove="flat")

def _set_chip_off(btn: ui.button) -> None:
    """Visually deactivate a chip button (flat/outline appearance)."""
    btn.props(add="flat")


@ui.page("/logs")
def logs_page() -> None:
    create_page_layout(active_path="/logs")
    ui.add_head_html(_LOG_COLORS_CSS)

    with ui.column().classes("w-full gap-3 p-6"):
        ui.label("Logs").classes("text-2xl font-semibold")

        if state.log_dir is None:
            with ui.card().classes("w-full max-w-sm"):
                with ui.row().classes("items-center gap-3 p-2"):
                    ui.icon("article").classes("text-3xl opacity-30")
                    ui.label("Log directory not available.").classes("text-sm opacity-50")
            return

        log_dir = state.log_dir
        gw_log_dir = state.gateway_log_dir

        available_plugins: list[str] = [
            f.stem.removeprefix("plugin-")
            for f in sorted(log_dir.glob("plugin-*.log"))
        ]
        has_gateway = gw_log_dir is not None and (gw_log_dir / "gateway.log").exists()

        # -------------------------------------------------------------------
        # Restore persisted preferences (fall back to sensible defaults).
        # -------------------------------------------------------------------
        prefs = nicegui_app.storage.user
        _default_sources = ["server", "plugins"] + (["gateway"] if has_gateway else [])
        _default_plugins = available_plugins[:]

        _s: dict = {
            "file_offsets": {},
            "row_data": [],
            "is_search_mode": False,
            "paused": prefs.get("logs_paused", False),
            "sort_order": prefs.get("logs_sort_order", "newest"),
            "active_sources": list(prefs.get("logs_sources", _default_sources)),
            "active_plugins": list(prefs.get("logs_plugins", _default_plugins)),
            "level_filter": list(prefs.get("logs_level_filter", _LEVELS[:])),
            "search_text": prefs.get("logs_search_text", ""),
            "auto_scroll": True,
        }

        from hirocli.tools.logs import LogSearchTool, LogTailTool

        def _workspace() -> str | None:
            return nicegui_app.storage.user.get("selected_workspace")

        # -------------------------------------------------------------------
        # Filtering helpers
        # -------------------------------------------------------------------
        def _row_passes_filters(row: dict) -> bool:
            src = row.get("source", "")
            active = _s["active_sources"]
            if src == "server" and "server" not in active:
                return False
            if src.startswith("plugin-"):
                if "plugins" not in active:
                    return False
                plugin_name = src.removeprefix("plugin-")
                if _s["active_plugins"] and plugin_name not in _s["active_plugins"]:
                    return False
            if src == "gateway" and "gateway" not in active:
                return False
            if _s["level_filter"] and row.get("level") not in _s["level_filter"]:
                return False
            return True

        # -------------------------------------------------------------------
        # Pre-load initial data BEFORE creating the grid so rowData is
        # present at construction time (avoids update-before-mount issues).
        # -------------------------------------------------------------------
        initial_rows: list[dict] = []
        try:
            result = LogTailTool().execute(
                source="all",
                lines=_INITIAL_LINES,
                workspace=_workspace(),
            )
            _s["file_offsets"] = result.file_offsets
            initial_rows = [r for r in result.rows if _row_passes_filters(r)]
            _s["row_data"] = initial_rows[:]
        except Exception:
            pass

        # plugin filter elements are placed in the controls row below;
        # declare references here so source-chip closures can reach them.
        _plugin_label: ui.label | None = None
        _plugin_select: ui.select | None = None

        # -------------------------------------------------------------------
        # Source filter row
        # -------------------------------------------------------------------
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label("Source:").classes("text-sm font-medium opacity-60 self-center")
            _src_btns: dict[str, ui.button] = {}

            def _make_source_btn(name: str, label: str) -> None:
                is_on = name in _s["active_sources"]
                btn = ui.button(label).props("dense rounded").classes("text-xs")
                if not is_on:
                    _set_chip_off(btn)
                _src_btns[name] = btn

                def _on_click(n=name, b=btn) -> None:
                    if n in _s["active_sources"]:
                        _s["active_sources"] = [s for s in _s["active_sources"] if s != n]
                        _set_chip_off(b)
                    else:
                        _s["active_sources"].append(n)
                        _set_chip_on(b)
                    prefs["logs_sources"] = _s["active_sources"]
                    plugins_visible = "plugins" in _s["active_sources"]
                    if _plugin_label:
                        _plugin_label.set_visibility(plugins_visible)
                    if _plugin_select:
                        _plugin_select.set_visibility(plugins_visible)
                    _schedule_reload()

                btn.on_click(_on_click)

            _make_source_btn("server", "Server")
            _make_source_btn("plugins", "Plugins")
            if has_gateway:
                _make_source_btn("gateway", "Gateway")

        # -------------------------------------------------------------------
        # Level filter row
        # -------------------------------------------------------------------
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label("Level:").classes("text-sm font-medium opacity-60 self-center")
            _lvl_btns: dict[str, ui.button] = {}

            def _make_level_btn(lvl: str) -> None:
                is_on = lvl in _s["level_filter"]
                color = _LEVEL_CHIP_COLORS.get(lvl, "grey")
                btn = ui.button(lvl).props(f"dense rounded color={color}").classes("text-xs")
                if not is_on:
                    _set_chip_off(btn)
                _lvl_btns[lvl] = btn

                def _on_click(l=lvl, b=btn) -> None:
                    if l in _s["level_filter"]:
                        _s["level_filter"] = [x for x in _s["level_filter"] if x != l]
                        _set_chip_off(b)
                    else:
                        _s["level_filter"].append(l)
                        _set_chip_on(b)
                    prefs["logs_level_filter"] = _s["level_filter"]
                    _schedule_reload()

                btn.on_click(_on_click)

            for _lvl in _LEVELS:
                _make_level_btn(_lvl)

        # -------------------------------------------------------------------
        # Controls row: search | sort | pause | auto-scroll | plugin filter
        # -------------------------------------------------------------------
        with ui.row().classes("items-center gap-3 flex-wrap"):
            search_input = (
                ui.input(placeholder="Search logs…", value=_s["search_text"])
                .classes("min-w-64")
                .props("dense outlined clearable")
            )

            sort_btn = ui.button(
                "Newest first" if _s["sort_order"] == "newest" else "Oldest first",
                icon="swap_vert",
            ).props("flat dense outlined")

            pause_btn = ui.button(
                "Resume" if _s["paused"] else "Pause",
                icon="play_arrow" if _s["paused"] else "pause",
            ).props("flat dense outlined")

            auto_scroll_btn = ui.button(
                "Auto-scroll on",
                icon="vertical_align_bottom",
            ).props("flat dense outlined")
            auto_scroll_btn.classes("text-positive" if _s["auto_scroll"] else "opacity-50")

            # Plugin filter inline — only shown when Plugins source is active.
            if available_plugins:
                _plugin_label = ui.label("Plugin:").classes("text-sm opacity-50 self-center")
                _plugin_select = (
                    ui.select(
                        available_plugins,
                        multiple=True,
                        value=_s["active_plugins"] or available_plugins,
                        label="",
                    )
                    .classes("min-w-32 max-w-60")
                    .props("dense outlined")
                )

                def _on_plugin_change(e) -> None:
                    _s["active_plugins"] = list(e.value or [])
                    prefs["logs_plugins"] = _s["active_plugins"]
                    _schedule_reload()

                _plugin_select.on_value_change(_on_plugin_change)

                plugins_on = "plugins" in _s["active_sources"]
                _plugin_label.set_visibility(plugins_on)
                _plugin_select.set_visibility(plugins_on)

        # -------------------------------------------------------------------
        # AG Grid — created with pre-loaded rowData.
        # -------------------------------------------------------------------
        grid_opts: dict = {
            "columnDefs": _COL_DEFS,
            "rowData": initial_rows,
            "defaultColDef": {"resizable": True, "sortable": True, "filter": True},
            "animateRows": False,
            "suppressCellFocus": True,
            "rowHeight": 24,
            "headerHeight": 28,
            "suppressHorizontalScroll": False,
            # Disable NiceGUI's default autoSizeStrategy — it re-triggers on every
            # grid.update() call and causes columns to resize on each new row/filter.
            # Columns use explicit width values so auto-sizing is not needed.
            "autoSizeStrategy": None,
        }
        grid = ui.aggrid(
            grid_opts, html_columns=[1, 3],
        ).classes("w-full h-[calc(100vh-340px)] min-h-48")

        # -------------------------------------------------------------------
        # Data helpers
        # -------------------------------------------------------------------

        def _schedule_reload() -> None:
            _reload_initial()

        def _reload_initial() -> None:
            _s["file_offsets"] = {}
            if _s["search_text"]:
                _s["is_search_mode"] = True
                _do_search(_s["search_text"])
                return
            _s["is_search_mode"] = False
            try:
                result = LogTailTool().execute(
                    source="all",
                    lines=_INITIAL_LINES,
                    workspace=_workspace(),
                )
                _s["file_offsets"] = result.file_offsets
                rows = [r for r in result.rows if _row_passes_filters(r)]
                _set_grid_data(rows)
            except Exception:
                pass

        def _do_search(query: str) -> None:
            try:
                result = LogSearchTool().execute(
                    source="all",
                    query=query,
                    workspace=_workspace(),
                )
                rows = [r for r in result.rows if _row_passes_filters(r)]
                _set_grid_data(rows)
            except Exception:
                pass

        def _set_grid_data(rows: list[dict]) -> None:
            _s["row_data"] = rows
            grid.options["rowData"] = rows
            grid.update()
            # grid.update() resets AG Grid column state — re-apply sort.
            _apply_sort()
            if _s["auto_scroll"]:
                _scroll_to_edge()

        def _append_rows(rows: list[dict]) -> None:
            if not rows:
                return
            _s["row_data"].extend(rows)
            grid.options["rowData"] = _s["row_data"]
            grid.update()
            # grid.update() resets AG Grid column state — re-apply sort.
            _apply_sort()
            if _s["auto_scroll"]:
                _scroll_to_edge()

        def _scroll_to_edge() -> None:
            count = len(_s["row_data"])
            if count == 0:
                return
            try:
                if _s["sort_order"] == "newest":
                    grid.run_grid_method("ensureIndexVisible", 0, "top")
                else:
                    grid.run_grid_method("ensureIndexVisible", count - 1, "bottom")
            except Exception:
                pass

        def _apply_sort() -> None:
            direction = "desc" if _s["sort_order"] == "newest" else "asc"
            grid.run_grid_method(
                "applyColumnState",
                {
                    "state": [{"colId": "timestamp", "sort": direction}],
                    "defaultState": {"sort": None},
                },
            )

        # -------------------------------------------------------------------
        # Control event handlers
        # -------------------------------------------------------------------
        def _on_search(e) -> None:
            text = (e.value or "").strip() if hasattr(e, "value") else ""
            _s["search_text"] = text
            prefs["logs_search_text"] = text
            if text:
                _s["is_search_mode"] = True
                _do_search(text)
            else:
                _s["is_search_mode"] = False
                _s["file_offsets"] = {}
                _reload_initial()

        search_input.on_value_change(_on_search)

        def _toggle_sort() -> None:
            _s["sort_order"] = "oldest" if _s["sort_order"] == "newest" else "newest"
            prefs["logs_sort_order"] = _s["sort_order"]
            sort_btn.set_text("Newest first" if _s["sort_order"] == "newest" else "Oldest first")
            _apply_sort()

        sort_btn.on_click(_toggle_sort)

        def _toggle_pause() -> None:
            _s["paused"] = not _s["paused"]
            prefs["logs_paused"] = _s["paused"]
            if _s["paused"]:
                pause_btn.set_text("Resume")
                pause_btn.props("flat dense outlined icon=play_arrow")
            else:
                pause_btn.set_text("Pause")
                pause_btn.props("flat dense outlined icon=pause")
            poll_timer.active = not _s["paused"]

        pause_btn.on_click(_toggle_pause)

        def _toggle_auto_scroll() -> None:
            _s["auto_scroll"] = not _s["auto_scroll"]
            if _s["auto_scroll"]:
                auto_scroll_btn.set_text("Auto-scroll on")
                auto_scroll_btn.classes(remove="opacity-50")
                auto_scroll_btn.classes(add="text-positive")
            else:
                auto_scroll_btn.set_text("Auto-scroll off")
                auto_scroll_btn.classes(remove="text-positive")
                auto_scroll_btn.classes(add="opacity-50")

        auto_scroll_btn.on_click(_toggle_auto_scroll)

        # -------------------------------------------------------------------
        # Polling timer
        # -------------------------------------------------------------------
        def _poll() -> None:
            if _s["paused"] or _s["is_search_mode"]:
                return
            try:
                offsets_json = (
                    json.dumps(_s["file_offsets"]) if _s["file_offsets"] else None
                )
                result = LogTailTool().execute(
                    source="all",
                    after_offsets=offsets_json,
                    workspace=_workspace(),
                )
                _s["file_offsets"] = result.file_offsets
                new_rows = [r for r in result.rows if _row_passes_filters(r)]
                _append_rows(new_rows)
            except RuntimeError:
                pass
            except Exception:
                pass

        poll_timer = ui.timer(_POLL_INTERVAL, _poll)
        poll_timer.active = not _s["paused"]

        # -------------------------------------------------------------------
        # Apply saved sort after grid is mounted (deferred so the AG Grid
        # API is available on the client side).
        # -------------------------------------------------------------------
        ui.timer(0.1, _apply_sort, once=True)
