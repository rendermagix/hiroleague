"""Logs page — live tail of server and plugin log files.

Two tabs:
  - Server logs:  tails server.log from the workspace log directory.
  - Plugin logs:  tails all plugin-*.log files combined, with the plugin name
                  prefixed to each line so output from multiple plugins is
                  distinguishable in a single view.

Tailing mechanism:
  Each tab uses a ui.timer that fires every _POLL_INTERVAL seconds, reads
  any new bytes appended to the log file(s), and pushes them to the ui.log
  element.  ui.timer runs within the NiceGUI page client context so push()
  is always delivered to the correct browser tab.  NiceGUI automatically
  deactivates timers when the client disconnects — no manual cleanup needed.

  On first fire the timer seeds the log with the last ~8 KB of existing
  content so the page is not blank on load.
"""

from __future__ import annotations

from nicegui import ui

from hirocli.ui import state
from hirocli.ui.app import create_page_layout

_POLL_INTERVAL = 0.5  # seconds between file checks
_INITIAL_READ_BYTES = 8192  # bytes read from near-end of file on first open


@ui.page("/logs")
async def logs_page() -> None:
    create_page_layout(active_path="/logs")

    with ui.column().classes("w-full gap-4 p-6"):
        ui.label("Logs").classes("text-2xl font-semibold")

        if state.log_dir is None:
            with ui.card().classes("w-full max-w-sm"):
                with ui.row().classes("items-center gap-3 p-2"):
                    ui.icon("article").classes("text-3xl opacity-30")
                    ui.label("Log directory not available.").classes("text-sm opacity-50")
            return

        log_dir = state.log_dir

        with ui.tabs().classes("w-full") as tabs:
            server_tab = ui.tab("Server logs")
            plugin_tab = ui.tab("Plugin logs")

        with ui.tab_panels(tabs, value=server_tab).classes("w-full"):

            # ----------------------------------------------------------------
            # Server logs tab
            # ----------------------------------------------------------------
            with ui.tab_panel(server_tab):
                server_log_elem = ui.log(max_lines=1000).classes(
                    "w-full h-96 font-mono text-xs"
                )
                # Mutable state captured by the timer callback closure.
                server_pos: dict[str, int] = {}

                def _update_server() -> None:
                    # log_setup.init("server", ...) always writes to server.log.
                    log_file = log_dir / "server.log"
                    if not log_file.exists():
                        return
                    key = str(log_file)
                    if key not in server_pos:
                        # On first fire: seed with last _INITIAL_READ_BYTES.
                        try:
                            size = log_file.stat().st_size
                            with log_file.open(encoding="utf-8", errors="replace") as fh:
                                fh.seek(max(0, size - _INITIAL_READ_BYTES))
                                initial = fh.read()
                                server_pos[key] = fh.tell()
                            for line in initial.splitlines():
                                if line:
                                    server_log_elem.push(line)
                        except OSError:
                            server_pos[key] = 0
                        return
                    try:
                        with log_file.open(encoding="utf-8", errors="replace") as fh:
                            fh.seek(server_pos[key])
                            chunk = fh.read()
                            server_pos[key] = fh.tell()
                        if chunk:
                            for line in chunk.splitlines():
                                if line:
                                    server_log_elem.push(line)
                    except OSError:
                        pass

                # ui.timer fires in this page's client context — push() works correctly.
                server_timer = ui.timer(_POLL_INTERVAL, _update_server)

                with ui.row().classes("items-center gap-2 mt-2"):
                    server_pause_btn = ui.button("Pause").props("flat dense outlined")

                    def _toggle_server_pause(
                        _btn=server_pause_btn, _timer=server_timer
                    ) -> None:
                        _timer.active = not _timer.active
                        _btn.text = "Resume" if not _timer.active else "Pause"

                    server_pause_btn.on_click(_toggle_server_pause)

            # ----------------------------------------------------------------
            # Plugin logs tab
            # ----------------------------------------------------------------
            with ui.tab_panel(plugin_tab):
                plugin_log_elem = ui.log(max_lines=1000).classes(
                    "w-full h-96 font-mono text-xs"
                )
                plugin_pos: dict[str, int] = {}

                def _update_plugins() -> None:
                    for log_file in sorted(log_dir.glob("plugin-*.log")):
                        key = str(log_file)
                        # Strip "plugin-" prefix so the label is just the plugin name.
                        plugin_name = log_file.stem.removeprefix("plugin-")
                        if key not in plugin_pos:
                            # On first fire: seed with last _INITIAL_READ_BYTES.
                            try:
                                size = log_file.stat().st_size
                                with log_file.open(
                                    encoding="utf-8", errors="replace"
                                ) as fh:
                                    fh.seek(max(0, size - _INITIAL_READ_BYTES))
                                    initial = fh.read()
                                    plugin_pos[key] = fh.tell()
                                for line in initial.splitlines():
                                    if line:
                                        plugin_log_elem.push(f"[{plugin_name}] {line}")
                            except OSError:
                                plugin_pos[key] = 0
                            continue
                        try:
                            with log_file.open(
                                encoding="utf-8", errors="replace"
                            ) as fh:
                                fh.seek(plugin_pos[key])
                                chunk = fh.read()
                                plugin_pos[key] = fh.tell()
                            if chunk:
                                for line in chunk.splitlines():
                                    if line:
                                        plugin_log_elem.push(f"[{plugin_name}] {line}")
                        except OSError:
                            pass

                plugin_timer = ui.timer(_POLL_INTERVAL, _update_plugins)

                with ui.row().classes("items-center gap-2 mt-2"):
                    plugin_pause_btn = ui.button("Pause").props("flat dense outlined")

                    def _toggle_plugin_pause(
                        _btn=plugin_pause_btn, _timer=plugin_timer
                    ) -> None:
                        _timer.active = not _timer.active
                        _btn.text = "Resume" if not _timer.active else "Pause"

                    plugin_pause_btn.on_click(_toggle_plugin_pause)
