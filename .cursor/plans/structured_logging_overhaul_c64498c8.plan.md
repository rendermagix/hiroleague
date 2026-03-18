---
name: Structured logging overhaul
overview: Overhaul the logging system to write structured CSV log files, add LogSearchTool/LogTailTool following the Tool architecture, replace the admin UI log viewer with a tabular AG Grid (theme-aware colors, persistent preferences, sort-direction toggle), add gateway logs, and add comprehensive startup and message-flow logging.
todos:
  - id: csv-renderer
    content: Add _CsvRenderer to log.py and use_csv param to add_file_sink; update log_setup.py to use CSV
    status: completed
  - id: log-tools
    content: Create LogSearchTool and LogTailTool in tools/logs.py following Tool pattern; add to all_tools(); add CLI wrappers
    status: completed
  - id: admin-ui-logs
    content: "Rewrite logs.py: single AG Grid table with source chips (Server/Plugins/Gateway), plugin multi-select, search/filter/sort, uses LogSearchTool/LogTailTool"
    status: completed
  - id: gateway-log-dir
    content: Add gateway_log_dir to UI state.py and resolve it in run.py and server_process.py
    status: completed
  - id: ui-sort-autoscroll
    content: Add newest-first/oldest-first toggle with smart auto-scroll (pin to edge unless user scrolled away)
    status: completed
  - id: ui-theme-colors
    content: "Theme-aware log colors: CSS custom properties with light/dark variants for levels and modules"
    status: completed
  - id: ui-persist-prefs
    content: Persist log page preferences (source chips, plugin selection, level filters, sort order, search) in nicegui_app.storage.user
    status: completed
  - id: startup-logging
    content: Add per-component startup log messages in server_process.py with model/config details
    status: completed
  - id: message-flow-logging
    content: Add detailed message flow logs in audio_adapter.py (timing), agent_manager.py (model timing), channel_manager.py
    status: completed
  - id: update-docs
    content: "Update terminal-logging.mdx and server-logging.mdx: fix naming, cross-links, document CSV format, document LogSearchTool"
    status: completed
isProject: false
---

# Structured logging overhaul

## Current state

The logging system has two layers that share the same source:

- `**hiro_commons.log**` ([log.py](hiroserver/hiro-commons/src/hiro_commons/log.py)) -- the `Logger` class with `_ColourRenderer` (terminal), `_PlainRenderer` (file), and `_NullRenderer`
- `**hiro_channel_sdk.log_setup**` ([log_setup.py](hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/log_setup.py)) -- calls `Logger.configure()` + `Logger.add_file_sink()` for each component

The admin UI logs page ([logs.py](hiroserver/hirocli/src/hirocli/ui/pages/logs.py)) tails `server.log` and `plugin-*.log` into a `ui.log` (monospace text box) with no filtering, searching, or sorting. Gateway logs are not shown.

---

## 1. Confirm docs describe the same source

The two docs pages (`build/terminal-logging.mdx` and `build/server-logging.mdx`) cover the same underlying system but from different angles. The terminal-logging page documents the `Logger` API in `hiro_commons.log`; the server-logging page documents `log_setup.init()` in `hiro_channel_sdk` which wraps Logger. They should be **merged into a single page** (or the terminal-logging page should be updated to clearly state it documents the foundation that `log_setup` builds on, with a cross-link). Recommend keeping both but:

- Add a clear "Relationship" section at the top of each, linking to the other
- Update `terminal-logging.mdx` to reference `hiro_commons.log` (not the old `datamagix.xlogger` name)
- Update `server-logging.mdx` format section to match the actual format: `[HH:MM:SS] [LVL] [module____] message key=value` (currently shows ISO-8601 UTC which doesn't match the code -- the code uses `%H:%M:%S` local time)

---

## 2. Switch file logs from plain text to CSV

### Changes in [log.py](hiroserver/hiro-commons/src/hiro_commons/log.py)

Add a new `_CsvRenderer` class that renders each log event as a CSV row:

```python
import csv
import io

class _CsvRenderer:
    HEADER = "timestamp,level,module,message,extra\n"

    def __call__(self, logger, method_name, event_dict):
        ts = event_dict.pop("ts", "")
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        message = event_dict.pop("event", "")
        # Remaining keys as key=value pairs in the extra column
        extra = " ".join(f"{k}={v}" for k, v in event_dict.items())
        
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([ts, level, module, message, extra])
        return buf.getvalue().rstrip("\r\n")
```

Columns: `timestamp`, `level`, `module`, `message`, `extra` (key=value pairs).

### Changes in `Logger.add_file_sink()`

- Add a `use_csv: bool = False` parameter
- When `use_csv=True`, use `_CsvRenderer` and write the CSV header as the first line of a new file
- Default `use_csv=True` so all new file sinks use CSV format

### Changes in [log_setup.py](hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/log_setup.py)

- Pass `use_csv=True` to `Logger.add_file_sink()`
- Change the file extension from `.log` to `.log.csv` (or keep `.log` -- to discuss, but `.log` is simpler)

**Note:** Per the no-backward-compatibility rule, no migration of old `.log` files is needed.

---

## 3. LogSearchTool and LogTailTool

Following the [tools architecture](hiro-docs/mintdocs/architecture/tools-architecture.mdx), create two new Tool classes in `hirocli/tools/logs.py`. This gives the AI agent, CLI, and admin UI the same log-reading capability through a single implementation.

### LogSearchTool

Searches across log files for matching entries. Server-side filtering for large logs.

```python
@dataclass
class LogSearchResult:
    rows: list[dict]    # [{timestamp, level, module, message, extra, source}, ...]
    total_matches: int
    truncated: bool     # True if more matches than limit

class LogSearchTool(Tool):
    name = "log_search"
    description = "Search server, plugin, and gateway log files for entries matching filters"
    params = {
        "source": ToolParam(str, "Log source: 'server', 'plugins', 'gateway', or 'all'", required=False),
        "level": ToolParam(str, "Minimum level filter: DEBUG, INFO, WARNING, ERROR, CRITICAL", required=False),
        "module": ToolParam(str, "Module name filter (substring match)", required=False),
        "query": ToolParam(str, "Text search across message and extra fields", required=False),
        "limit": ToolParam(int, "Max rows to return (default 200)", required=False),
        "workspace": ToolParam(str, "Workspace name", required=False),
    }
```

Implementation: reads CSV log files from `resolve_log_dir()`, parses with `csv.reader`, applies filters, returns structured rows. For gateway, reads from the gateway instance's log dir.

### LogTailTool

Returns the most recent N log entries (for live tailing and initial page load).

```python
@dataclass
class LogTailResult:
    rows: list[dict]
    has_more: bool

class LogTailTool(Tool):
    name = "log_tail"
    description = "Return the most recent log entries from server, plugin, or gateway logs"
    params = {
        "source": ToolParam(str, "Log source: 'server', 'plugins', 'gateway', or 'all'", required=False),
        "lines": ToolParam(int, "Number of recent lines (default 500)", required=False),
        "after_line": ToolParam(int, "Return only lines after this line number (for incremental polling)", required=False),
        "workspace": ToolParam(str, "Workspace name", required=False),
    }
```

Implementation: seeks to end of file, reads backward to find N lines, parses CSV, returns rows. The `after_line` param enables incremental polling -- the admin UI passes the last seen line number and gets only new entries.

### Registration

Add both to `tools/__init__.py` / `all_tools()`. This automatically makes them available to:

- **AI agent** -- can search logs to debug issues ("find all errors in the last hour", "what happened when message X was processed")
- **CLI** -- `hirocli logs search --level ERROR --module AGENT` (thin wrapper in `commands/logs.py`)
- **Admin UI** -- imports and calls directly (same pattern as `DeviceListTool` in the devices page)

---

## 4. Admin UI: tabular log viewer with AG Grid

### Rewrite [logs.py](hiroserver/hirocli/src/hirocli/ui/pages/logs.py)

Replace `ui.log` with `ui.aggrid`. The admin UI page uses `LogTailTool` for initial load and polling, and `LogSearchTool` for the search input (server-side search for large files, complementing AG Grid's client-side filtering on loaded data).

#### Layout -- single unified table with source chips

No tabs. One `ui.aggrid` table showing all log sources merged together. Filtering by source is done via **chips** above the table, not tabs.

**Source chips row** (toggle on/off, all active by default):

- **Server** -- toggles server.log entries
- **Plugins** -- toggles all plugin-*.log entries; when active, a **plugin multi-select dropdown** appears next to it listing each discovered plugin (e.g. "devices", "echo", "telegram") so the user can include/exclude individual plugins
- **Gateway** -- toggles gateway.log entries

**Columns**: Timestamp, Level, Source, Module, Message, Extra

- **Source** column shows "server", "plugin-devices", "plugin-echo", "gateway", etc. -- derived from the log file name
- AG Grid column header filters are also available on every column for additional ad-hoc filtering

**Controls row** (above the table, next to source chips):

- Search input (calls `LogSearchTool` for server-side filtering)
- Level filter chips (DEBUG / INFO / WARNING / ERROR / CRITICAL -- toggle on/off)
- Pause / Resume button
- Newest-first / Oldest-first toggle (see section 4a)

#### Data flow

1. **Initial load**: `LogTailTool().execute(source=..., lines=500)` populates the grid
2. **Polling**: `ui.timer(0.5s)` calls `LogTailTool().execute(source=..., after_line=last_line)` for incremental updates
3. **Search**: user types in search box -> `LogSearchTool().execute(query=..., source=..., level=...)` replaces grid data with results
4. **Clear search**: reverts to tail mode

### 4a. Sort direction and auto-scroll

- **Toggle button**: "Newest first" / "Oldest first" switches the AG Grid default sort on the Timestamp column
- **Auto-scroll behavior**:
  - When set to "Newest first": new rows appear at the top; if user has NOT scrolled down (is at the top edge), the view stays pinned to show new entries. If user scrolled down, it does not jump.
  - When set to "Oldest first": new rows appear at the bottom; if user is at the bottom edge, auto-scrolls to show them. If user scrolled up, it does not jump.
  - Use AG Grid's `ensureIndexVisible()` after appending rows, gated by a `_user_scrolled` flag that is set/cleared by a scroll event listener on the grid viewport.

### 4b. Theme-aware color system (light/dark)

The admin UI uses Quasar's dark mode (`body--dark` class). Define CSS custom properties that switch with the theme:

```css
:root {
  --log-debug: #3b82f6;     /* blue */
  --log-info: #22c55e;      /* green */
  --log-warning: #eab308;   /* yellow */
  --log-error: #ef4444;     /* red */
  --log-critical: #a855f7;  /* purple */
  /* Module palette (same 4 as terminal) */
  --log-mod-0: #06b6d4;     /* cyan */
  --log-mod-1: #d946ef;     /* magenta/fuchsia */
  --log-mod-2: #eab308;     /* yellow */
  --log-mod-3: #22c55e;     /* green */
}
.body--dark {
  --log-debug: #60a5fa;     /* lighter blue */
  --log-info: #4ade80;      /* lighter green */
  --log-warning: #facc15;   /* lighter yellow */
  --log-error: #f87171;     /* lighter red */
  --log-critical: #c084fc;  /* lighter purple */
  --log-mod-0: #22d3ee;
  --log-mod-1: #e879f9;
  --log-mod-2: #fde047;
  --log-mod-3: #86efac;
}
```

AG Grid `cellStyle` functions reference these variables: `{ color: 'var(--log-info)' }`. This adapts automatically when the user toggles dark mode.

Module colors use the same hash function as the terminal (sum of char codes mod 4), implemented in a JS `cellStyle` callback:

```javascript
function(params) {
  var name = params.value || '';
  var idx = 0;
  for (var i = 0; i < name.length; i++) idx += name.charCodeAt(i);
  return { color: 'var(--log-mod-' + (idx % 4) + ')' };
}
```

### 4c. Persist user preferences

Use `nicegui_app.storage.user` (already enabled via `storage_secret` in `run.py`) to persist:

- `logs_sources` -- which source chips are active, e.g. `["server", "plugins", "gateway"]`
- `logs_plugins` -- which plugins are selected in the plugin multi-select, e.g. `["devices", "echo"]`
- `logs_sort_order` -- `"newest"` or `"oldest"`
- `logs_level_filter` -- list of selected levels, e.g. `["INFO", "WARNING", "ERROR"]`
- `logs_search_text` -- last search query
- `logs_paused` -- whether live tailing is paused

On page load, read these from storage and apply them to the grid config and UI controls. On change, write back immediately. This means the user returns to the exact same view they left.

#### Gateway log dir

The gateway log directory is separate (`~/.hirogateway/logs/`). Resolve it by reading the gateway instance registry in `run.py` and storing in `state.gateway_log_dir`. The `LogSearchTool` and `LogTailTool` also need access -- they resolve it internally via the gateway registry (same as `GatewayStatusTool` does).

---

## 4. Ensure server, channels, and gateway all log properly

All three already call `log_setup.init()`:

- **Server**: `server_process.py` line 100-105
- **Channels**: each plugin's `main.py` calls `log_setup.init(f"plugin-{name}", log_dir)`
- **Gateway**: `main.py` line 87-92

The CSV format change in `log_setup.init()` will apply to all three automatically.

For the admin UI to display gateway logs, we need to resolve the gateway log directory. Add logic in `server_process.py` to find the gateway instance path and pass its log dir to the admin UI.

---

## 5. Better startup logging

### In [server_process.py](hiroserver/hirocli/src/hirocli/runtime/server_process.py) `_main()`

Add structured startup logs after each major component is initialized:

```python
log.info("Config loaded", workspace=str(workspace_path), http_port=config.http_port, plugin_port=config.plugin_port)
log.info("STT service ready", providers=["openai", "gemini"])
log.info("Vision service ready")
log.info("Adapter pipeline ready", adapters=["audio_transcription", "image_understanding"])
log.info("Communication manager ready")
log.info("Channel event handler ready", events=["pairing_request", "gateway_connected", "gateway_disconnected"])
log.info("Agent config", model=agent_config.model, provider=agent_config.provider, temperature=agent_config.temperature)
log.info("Tool registry ready", tools=len(tool_registry))
```

### In component `run()` methods

Already have "started" logs (e.g. `AgentManager started`, `CommunicationManager started`). Add model info to agent startup:

```python
log.info("AgentManager started", model=config.model, provider=config.provider, tools=len(tools))
```

### In gateway [relay.py](hiroserver/gateway/src/hirogateway/relay.py) / [main.py](hiroserver/gateway/src/hirogateway/main.py)

Already has `"Gateway listening"` and `"Gateway trust root configured"`. Add:

```python
log.info("Auth manager ready", desktop_key_configured=bool(config.desktop_public_key))
```

---

## 6. Comprehensive message flow logging

Add detailed logging at each step of the message lifecycle. These are "development-phase" logs that can be tuned down later via `log_levels` config without code changes.

### Message flow logging points


| Step                          | File                     | Module        | Log message                                                  |
| ----------------------------- | ------------------------ | ------------- | ------------------------------------------------------------ |
| Gateway receives message      | relay.py                 | RELAY         | "Inbound message received" with sender_id, target, msg_id    |
| Devices channel translates    | plugin.py                | DEVICES       | "Message translated to UnifiedMessage" with content_types    |
| CommunicationManager receives | communication_manager.py | COMM          | Already has "Message acked, adapter task spawned"            |
| Audio adapter starts          | audio_adapter.py         | ADAPTER.AUDIO | "Transcribing audio" with body_length, provider              |
| Audio adapter result          | audio_adapter.py         | ADAPTER.AUDIO | "Transcription complete" with transcript_length, duration_ms |
| Adapter pipeline done         | communication_manager.py | COMM          | Already has "Inbound message queued after adaptation"        |
| Agent receives                | agent_manager.py         | AGENT         | Already has "Processing message"                             |
| Agent model invoked           | agent_manager.py         | AGENT         | "Model invoked" with model_name, input_length                |
| Agent model returned          | agent_manager.py         | AGENT         | "Model returned" with output_length, duration_ms             |
| Agent reply enqueued          | agent_manager.py         | AGENT         | Already has "Agent reply enqueued"                           |
| Outbound dispatched           | communication_manager.py | COMM          | Already has "Dispatching outbound message"                   |
| Channel sends                 | channel_manager.py       | PLUGINS       | "Message sent to channel" with channel, msg_id               |


Most of these already exist; add the missing ones (audio adapter detail, agent model invocation timing, channel send confirmation).

For audio specifically, add timing:

```python
import time
start = time.perf_counter()
transcript = await self._service.transcribe(item.body)
elapsed_ms = (time.perf_counter() - start) * 1000
log.info("Transcription complete", transcript_len=len(transcript), elapsed_ms=f"{elapsed_ms:.0f}")
```

---

## 7. Color consistency between terminal and admin UI

Covered in section 4b above. The key principle: the same hash function (`sum(ord(c) for c in name) % 4`) maps module names to the same palette index in both terminal (colorama) and admin UI (CSS custom properties). Level colors also match (blue/green/yellow/red/magenta). The CSS variables adapt to light/dark mode via the `.body--dark` selector.

---

## Files to modify


| File                                                    | Changes                                                                                      |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `hiro-commons/src/hiro_commons/log.py`                  | Add `_CsvRenderer`, add `use_csv` param to `add_file_sink`                                   |
| `hiro-channel-sdk/src/hiro_channel_sdk/log_setup.py`    | Pass `use_csv=True`                                                                          |
| `hirocli/src/hirocli/tools/logs.py`                     | **New file**: `LogSearchTool`, `LogTailTool`, result dataclasses                             |
| `hirocli/src/hirocli/tools/__init__.py`                 | Import and add `LogSearchTool`, `LogTailTool` to `all_tools()`                               |
| `hirocli/src/hirocli/commands/logs.py`                  | **New file**: thin CLI wrappers `hirocli logs search`, `hirocli logs tail`                   |
| `hirocli/src/hirocli/ui/pages/logs.py`                  | Full rewrite: AG Grid, 4 tabs, tool-backed data, theme colors, persistent prefs, auto-scroll |
| `hirocli/src/hirocli/ui/state.py`                       | Add `gateway_log_dir`                                                                        |
| `hirocli/src/hirocli/ui/run.py`                         | Resolve and set `gateway_log_dir` from gateway registry                                      |
| `hirocli/src/hirocli/runtime/server_process.py`         | Add per-component startup logs, resolve gateway log dir                                      |
| `hirocli/src/hirocli/runtime/adapters/audio_adapter.py` | Add timing and detail logs                                                                   |
| `hirocli/src/hirocli/runtime/agent_manager.py`          | Add model invocation timing logs                                                             |
| `hiro-docs/mintdocs/build/terminal-logging.mdx`         | Fix xlogger naming, add cross-link to server-logging                                         |
| `hiro-docs/mintdocs/build/server-logging.mdx`           | Fix format section, cross-link, document CSV format, document log tools                      |


