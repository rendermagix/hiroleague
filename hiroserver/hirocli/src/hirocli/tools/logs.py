"""Log reading tools: search and tail server, plugin, and gateway log files.

These tools read CSV log files written by log_setup.init() (use_csv=True).
They are available to the AI agent (for natural-language log queries),
the CLI (hirocli logs search/tail), and the admin UI (direct import).

CSV log format: timestamp,level,module,message,extra
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import Tool, ToolParam

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LEVEL_ORDER: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}
_DEFAULT_TAIL_LINES = 500
_DEFAULT_SEARCH_LIMIT = 200
# How many bytes to read from near the end of a file for tail operations.
# Sized for ~1 000 typical log lines (average ~128 chars each).
_TAIL_READ_BYTES = 131_072


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _resolve_log_dir(workspace: str | None) -> Path:
    """Return the effective log directory for the given (or default) workspace."""
    from ..domain.config import load_config, resolve_log_dir
    from ..domain.workspace import resolve_workspace

    entry, _ = resolve_workspace(workspace)
    ws_path = Path(entry.path)
    config = load_config(ws_path)
    return resolve_log_dir(ws_path, config)


def _resolve_gateway_log_dir() -> Path | None:
    """Return the log directory for the default gateway instance, or None."""
    try:
        from hirogateway.config import load_config as gw_load_config
        from hirogateway.config import resolve_log_dir as gw_resolve_log_dir
        from hirogateway.instance import load_registry

        registry = load_registry()
        if not registry.instances:
            return None
        name = registry.default_instance or next(iter(registry.instances))
        entry = registry.instances.get(name)
        if entry is None:
            return None
        instance_path = Path(entry.path)
        config = gw_load_config(instance_path)
        return gw_resolve_log_dir(instance_path, config)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# File collection and CSV parsing helpers
# ---------------------------------------------------------------------------


def _collect_log_files(
    log_dir: Path,
    gateway_log_dir: Path | None,
    source: str,
) -> list[tuple[Path, str]]:
    """Return (file_path, source_label) pairs for the requested source(s)."""
    files: list[tuple[Path, str]] = []
    src = (source or "all").lower()

    if src in ("all", "server"):
        f = log_dir / "server.log"
        if f.exists():
            files.append((f, "server"))

    if src in ("all", "plugins"):
        for f in sorted(log_dir.glob("plugin-*.log")):
            plugin_name = f.stem.removeprefix("plugin-")
            files.append((f, f"plugin-{plugin_name}"))

    if src in ("all", "gateway") and gateway_log_dir is not None:
        f = gateway_log_dir / "gateway.log"
        if f.exists():
            files.append((f, "gateway"))

    return files


_LEVEL_CSS_CLASS = {
    "DEBUG": "log-lvl-debug",
    "INFO": "log-lvl-info",
    "WARNING": "log-lvl-warning",
    "ERROR": "log-lvl-error",
    "CRITICAL": "log-lvl-critical",
}


def _module_color_idx(module: str) -> int:
    """Stable 0-3 colour bucket for a module name (same hash as terminal renderer)."""
    return sum(ord(c) for c in module) % 4


def _parse_csv_row(row: list[str], source: str) -> dict[str, str] | None:
    """Parse a CSV row into a log record dict. Returns None for header/empty rows.

    Includes ``level_html`` / ``module_html`` fields with ``<span>`` wrappers
    for colour rendering via AG Grid ``html_columns``. Raw ``level`` and
    ``module`` are kept for filtering and sorting.
    """
    if not row or row[0] == "timestamp":
        return None  # skip header and blank lines
    if len(row) >= 4:
        level = row[1]
        module = row[2]
        lvl_cls = _LEVEL_CSS_CLASS.get(level, "")
        mod_cls = f"log-mod-{_module_color_idx(module)}"
        return {
            "timestamp": row[0],
            "level": level,
            "level_html": f'<span class="{lvl_cls}">{level}</span>',
            "module": module,
            "module_html": f'<span class="{mod_cls}">{module}</span>',
            "message": row[3],
            "extra": row[4] if len(row) >= 5 else "",
            "source": source,
        }
    return None


def _read_all_rows(path: Path, source: str) -> list[dict[str, str]]:
    """Read every CSV row from a log file."""
    rows: list[dict[str, str]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for row in csv.reader(fh):
                parsed = _parse_csv_row(row, source)
                if parsed is not None:
                    rows.append(parsed)
    except OSError:
        pass
    return rows


def _read_tail_rows(
    path: Path, source: str, n: int
) -> tuple[list[dict[str, str]], int]:
    """Read the last *n* CSV rows from *path*. Returns (rows, file_size_bytes)."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0

    rows: list[dict[str, str]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            seek_pos = max(0, size - _TAIL_READ_BYTES)
            fh.seek(seek_pos)
            chunk = fh.read()

        lines = chunk.splitlines()
        if seek_pos > 0 and lines:
            # First line may be a partial row — discard it.
            lines = lines[1:]

        for row in csv.reader(lines):
            parsed = _parse_csv_row(row, source)
            if parsed is not None:
                rows.append(parsed)
    except OSError:
        pass

    # Return last n rows and the file size as the initial offset for polling.
    return rows[-n:] if len(rows) > n else rows, size


def _read_rows_from_offset(
    path: Path, source: str, offset: int
) -> tuple[list[dict[str, str]], int]:
    """Read new CSV rows added after *offset* bytes. Returns (rows, new_offset)."""
    rows: list[dict[str, str]] = []
    new_offset = offset
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            chunk = fh.read()
            new_offset = fh.tell()
        if chunk:
            for row in csv.reader(io.StringIO(chunk)):
                parsed = _parse_csv_row(row, source)
                if parsed is not None:
                    rows.append(parsed)
    except OSError:
        pass
    return rows, new_offset


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def _apply_level_filter(rows: list[dict], min_level: str | None) -> list[dict]:
    if not min_level:
        return rows
    min_order = _LEVEL_ORDER.get(min_level.upper(), 0)
    return [r for r in rows if _LEVEL_ORDER.get(r.get("level", ""), 0) >= min_order]


def _apply_module_filter(rows: list[dict], module: str | None) -> list[dict]:
    if not module:
        return rows
    m = module.lower()
    return [r for r in rows if m in r.get("module", "").lower()]


def _apply_query_filter(rows: list[dict], query: str | None) -> list[dict]:
    if not query:
        return rows
    q = query.lower()
    return [
        r
        for r in rows
        if q in r.get("message", "").lower() or q in r.get("extra", "").lower()
    ]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LogSearchResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False


@dataclass
class LogTailResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    # JSON-serialisable {str(file_path): byte_offset} — pass back as
    # after_offsets on the next LogTailTool call for incremental polling.
    file_offsets: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class LogSearchTool(Tool):
    name = "log_search"
    description = (
        "Search server, plugin, and gateway log files for entries matching "
        "the given filters. Rows are returned sorted by timestamp."
    )
    params = {
        "source": ToolParam(
            str,
            "Log source: 'server', 'plugins', 'gateway', or 'all' (default: 'all')",
            required=False,
        ),
        "level": ToolParam(
            str,
            "Minimum log level: DEBUG, INFO, WARNING, ERROR, or CRITICAL",
            required=False,
        ),
        "module": ToolParam(
            str,
            "Filter by module name (case-insensitive substring match)",
            required=False,
        ),
        "query": ToolParam(
            str,
            "Full-text search across message and extra fields (case-insensitive)",
            required=False,
        ),
        "limit": ToolParam(
            int,
            f"Maximum rows to return (default {_DEFAULT_SEARCH_LIMIT})",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default)",
            required=False,
        ),
    }

    def execute(
        self,
        source: str | None = None,
        level: str | None = None,
        module: str | None = None,
        query: str | None = None,
        limit: int | None = None,
        workspace: str | None = None,
    ) -> LogSearchResult:
        log_dir = _resolve_log_dir(workspace)
        gateway_log_dir = _resolve_gateway_log_dir()
        effective_limit = limit if limit is not None else _DEFAULT_SEARCH_LIMIT

        files = _collect_log_files(log_dir, gateway_log_dir, source or "all")
        all_rows: list[dict] = []
        for file_path, src_label in files:
            all_rows.extend(_read_all_rows(file_path, src_label))

        all_rows = _apply_level_filter(all_rows, level)
        all_rows = _apply_module_filter(all_rows, module)
        all_rows = _apply_query_filter(all_rows, query)
        all_rows.sort(key=lambda r: r.get("timestamp", ""))

        total = len(all_rows)
        truncated = total > effective_limit
        return LogSearchResult(
            rows=all_rows[:effective_limit],
            total_matches=total,
            truncated=truncated,
        )


class LogTailTool(Tool):
    name = "log_tail"
    description = (
        "Return the most recent log entries. To tail live, pass the "
        "file_offsets JSON from a previous result back as after_offsets — "
        "only new lines written since that call are returned."
    )
    params = {
        "source": ToolParam(
            str,
            "Log source: 'server', 'plugins', 'gateway', or 'all' (default: 'all')",
            required=False,
        ),
        "lines": ToolParam(
            int,
            f"Number of recent lines for the initial load (default {_DEFAULT_TAIL_LINES})",
            required=False,
        ),
        "after_offsets": ToolParam(
            str,
            "JSON string of {file_path: byte_offset} from a previous LogTailResult "
            "for incremental polling — only new lines are returned",
            required=False,
        ),
        "workspace": ToolParam(
            str,
            "Workspace name (default: registry default)",
            required=False,
        ),
    }

    def execute(
        self,
        source: str | None = None,
        lines: int | None = None,
        after_offsets: str | None = None,
        workspace: str | None = None,
    ) -> LogTailResult:
        log_dir = _resolve_log_dir(workspace)
        gateway_log_dir = _resolve_gateway_log_dir()
        n = lines if lines is not None else _DEFAULT_TAIL_LINES

        prev_offsets: dict[str, int] = {}
        if after_offsets:
            try:
                prev_offsets = json.loads(after_offsets)
            except Exception:
                pass

        files = _collect_log_files(log_dir, gateway_log_dir, source or "all")
        all_rows: list[dict] = []
        new_offsets: dict[str, int] = {}

        for file_path, src_label in files:
            key = str(file_path)
            if key in prev_offsets:
                # Incremental: only read bytes appended since last poll.
                rows, offset = _read_rows_from_offset(file_path, src_label, prev_offsets[key])
            else:
                # Initial: read the last n lines.
                rows, offset = _read_tail_rows(file_path, src_label, n)
            all_rows.extend(rows)
            new_offsets[key] = offset

        all_rows.sort(key=lambda r: r.get("timestamp", ""))
        return LogTailResult(rows=all_rows, file_offsets=new_offsets)
