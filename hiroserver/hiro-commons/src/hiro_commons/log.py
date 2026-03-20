"""Shared Hiro structured logging.

Module-prefix routing
---------------------
File sinks support ``include_prefix`` / ``exclude_prefix`` filters so that
events are routed to the correct log file without any per-call boilerplate:

* ``CLI.*`` modules  →  ``cli.log``
* Everything else    →  ``server.log``

Channel plugins run in separate processes, each with their own
``channel-<name>.log`` created by ``log_setup.init()``.

``Logger.open_log_dir(log_dir)`` opens both routed sinks in one call
and is idempotent — safe to call from both the CLI callback and the
server startup path.
"""

from __future__ import annotations

import contextvars
import csv
import datetime
import io
import logging
import logging.handlers
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping

import colorama
import structlog

from .constants.timing import LOG_ROTATION_BACKUP_COUNT, LOG_ROTATION_MAX_BYTES

colorama.init(autoreset=True)

__all__ = [
    "Logger",
    "configure",
    "get_logger",
    "set_level",
    "disable",
    "enable",
]

_LEVEL_ABBREV = {
    "DEBUG": "DBG",
    "INFO": "INF",
    "WARNING": "WRN",
    "ERROR": "ERR",
    "CRITICAL": "CRT",
}

_LEVEL_COLORS = {
    "DEBUG": colorama.Fore.BLUE,
    "INFO": colorama.Fore.GREEN,
    "WARNING": colorama.Fore.YELLOW,
    "ERROR": colorama.Fore.RED,
    "CRITICAL": colorama.Fore.MAGENTA,
}

_MODULE_PALETTE = [
    colorama.Fore.CYAN,
    colorama.Fore.MAGENTA,
    colorama.Fore.YELLOW,
    colorama.Fore.GREEN,
]

_INDENT_LEVEL: contextvars.ContextVar[int] = contextvars.ContextVar(
    "indent_level", default=0
)
_INDENT_UNIT: str = "--"

# (min_level, handler, renderer, include_prefix, exclude_prefixes)
# include_prefix: only events whose module starts with this string pass through.
# exclude_prefixes: events whose module starts with any of these are skipped.
_FILE_SINKS: list[tuple[int, logging.Handler, object, str | None, tuple[str, ...] | None]] = []
_LEVEL_OVERRIDES: dict[str, int] = {}


def _pick_module_color(name: str) -> str:
    if not name:
        return colorama.Fore.WHITE
    index = sum(ord(c) for c in name) % len(_MODULE_PALETTE)
    return _MODULE_PALETTE[index]


def _epoch_to_time_str(epoch: float | str) -> str:
    """Format an epoch float as HH:MM:SS for terminal display."""
    try:
        return datetime.datetime.fromtimestamp(float(epoch)).strftime("%H:%M:%S")
    except Exception:
        return str(epoch)


class _ColourRenderer:
    def __call__(self, logger, method_name, event_dict):
        ts = _epoch_to_time_str(event_dict.pop("ts", 0))
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        module_raw = module
        if len(module_raw) > 12:
            module_disp = module_raw[:12]
        else:
            module_disp = module_raw.ljust(12, "_")

        message = event_dict.pop("event", "")
        indent_level: int = _INDENT_LEVEL.get()
        indent_prefix = _INDENT_UNIT * max(indent_level, 0)
        if indent_prefix:
            message = f"{indent_prefix}{message}"

        lvl_abbr = _LEVEL_ABBREV.get(level, level[:3])
        lvl_color = _LEVEL_COLORS.get(level, colorama.Fore.WHITE)
        module_color = _pick_module_color(module)
        kv_str = " ".join(f"{k}={v}" for k, v in event_dict.items())

        parts = [
            f"{colorama.Style.DIM}[{ts}]",
            f"{lvl_color}[{lvl_abbr}]",
            f"{module_color}[{module_disp}]",
            colorama.Style.RESET_ALL + message,
        ]

        if kv_str:
            parts.append(colorama.Style.DIM + " " + kv_str)
        parts.append(colorama.Style.RESET_ALL)
        return " ".join(parts)


class _PlainRenderer:
    def __call__(self, logger, method_name, event_dict):
        ts = _epoch_to_time_str(event_dict.pop("ts", 0))
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        module_raw = module
        if len(module_raw) > 12:
            module_disp = module_raw[:12]
        else:
            module_disp = module_raw.ljust(12, "_")

        message = event_dict.pop("event", "")
        indent_level: int = _INDENT_LEVEL.get()
        indent_prefix = _INDENT_UNIT * max(indent_level, 0)
        if indent_prefix:
            message = f"{indent_prefix}{message}"

        lvl_abbr = _LEVEL_ABBREV.get(level, level[:3])
        kv_str = " ".join(f"{k}={v}" for k, v in event_dict.items())

        parts = [
            f"[{ts}]",
            f"[{lvl_abbr}]",
            f"[{module_disp}]",
            message,
        ]
        if kv_str:
            parts.append(" " + kv_str)
        return " ".join(parts)


class _CsvRenderer:
    """Renders log events as CSV rows for structured file logging.

    Columns: timestamp,level,module,message,extra
    timestamp is a Unix epoch float (e.g. 1742312005.437821) — gives
    sub-second precision for correct ordering of same-second events.
    Extra contains remaining key=value pairs joined by spaces.
    A CSV header line is written once when the file sink is first opened.
    """

    HEADER = "timestamp,level,module,message,extra"

    def __call__(self, logger, method_name, event_dict):
        ts = event_dict.pop("ts", 0)
        level = event_dict.pop("level", "").upper()
        module = event_dict.pop("module", "")
        message = event_dict.pop("event", "")
        extra = " ".join(f"{k}={v}" for k, v in event_dict.items())

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([ts, level, module, message, extra])
        return buf.getvalue().rstrip("\r\n")


class _NullRenderer:
    """Discards all console output; used when console=False."""

    def __call__(self, logger, method_name, event_dict):
        raise structlog.DropEvent()


class _StdlibBridge(logging.Handler):
    """Bridge stdlib logging records into the Hiro structured logger.

    Attached to third-party stdlib loggers (e.g. ``websockets``) so their
    warnings/errors flow through the structlog pipeline with proper
    timestamps, module tags, and file-sink routing.
    """

    def __init__(self, module: str, level: int = logging.WARNING):
        super().__init__(level)
        self._module = module

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log = structlog.get_logger(self._module).bind(module=self._module)
            level = record.levelname.lower()
            log_method = getattr(log, level, log.warning)
            log_method(record.getMessage(), stdlib_logger=record.name)
        except Exception:
            pass


def _module_level_filter(logger, method_name, event_dict):
    """Drop events below configured per-module level overrides."""
    if not _LEVEL_OVERRIDES:
        return event_dict

    module = str(event_dict.get("module", ""))
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)

    for prefix in sorted(_LEVEL_OVERRIDES.keys(), key=len, reverse=True):
        if module == prefix or module.startswith(prefix + ".") or module.startswith(prefix):
            if event_level < _LEVEL_OVERRIDES[prefix]:
                raise structlog.DropEvent()
            break
    return event_dict


def _emit_to_file_sinks(logger, method_name, event_dict):
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)
    module = str(event_dict.get("module", ""))

    exc_info = None
    try:
        supplied = event_dict.get("exc_info")
        if supplied is True:
            exc_info = sys.exc_info()
        elif isinstance(supplied, tuple) and len(supplied) == 3:
            exc_info = supplied
        elif supplied and isinstance(supplied, BaseException):
            exc_info = (type(supplied), supplied, supplied.__traceback__)
        if exc_info is None:
            cur_exc = sys.exc_info()
            if cur_exc and cur_exc[0] is not None:
                exc_info = cur_exc
    except Exception:
        exc_info = None

    for min_level, handler, renderer, include_pfx, exclude_pfxs in list(_FILE_SINKS):
        if event_level < min_level:
            continue
        # Prefix-based routing filters
        if include_pfx is not None and not module.startswith(include_pfx):
            continue
        if exclude_pfxs is not None and any(module.startswith(p) for p in exclude_pfxs):
            continue
        try:
            copy_for_file = dict(event_dict)
            rendered = renderer(None, method_name, copy_for_file)
            if event_level >= logging.ERROR and exc_info is not None:
                try:
                    tb_lines = traceback.format_exception(*exc_info)
                    tb_one_line = " | ".join(
                        line.strip() for line in tb_lines if line and line.strip()
                    )
                    if tb_one_line:
                        rendered = f"{rendered} exception={tb_one_line}"
                except Exception:
                    pass

            record = logging.LogRecord(
                name=module,
                level=event_level,
                pathname="",
                lineno=0,
                msg=rendered,
                args=(),
                exc_info=None,
            )
            handler.handle(record)
        except Exception:
            pass
    return event_dict


def _strip_exception_for_console(logger, method_name, event_dict):
    try:
        event_dict.pop("exc_info", None)
        event_dict.pop("exception", None)
        event_dict.pop("stack", None)
        event_dict.pop("stack_info", None)
    except Exception:
        pass
    return event_dict


class Logger:
    """Central logging facility for Hiro."""

    _DEFAULT_LEVEL = "INFO"
    _configured: bool = False
    _LEVELS: Mapping[str, int] = {
        name: level for name, level in logging._nameToLevel.items()
    }

    @classmethod
    def _determine_level(cls, level: str | int | None):
        if level is None:
            return cls._LEVELS.get(cls._DEFAULT_LEVEL, logging.INFO)
        if isinstance(level, int):
            return level
        return cls._LEVELS.get(str(level).upper(), logging.INFO)

    @classmethod
    def configure(
        cls,
        *,
        level: str | int | None = None,
        json: bool = False,
        enabled: bool = True,
        console: bool = True,
    ):
        """One-time global logger configuration."""
        if cls._configured:
            return

        numeric_level = cls._determine_level(level)
        if not enabled:
            numeric_level = logging.CRITICAL + 1

        logging.basicConfig(
            level=numeric_level,
            format="%(message)s",
            stream=sys.stdout,
            force=True,
        )

        def _add_module(logger, method_name, event_dict):
            if logger and getattr(logger, "name", None):
                event_dict["module"] = logger.name
            return event_dict

        processors = [
            # Raw epoch float (UTC) for sub-second sort precision across all logs.
            # structlog requires utc=True when fmt=None.
            # Renderers convert to local time for display.
            structlog.processors.TimeStamper(fmt=None, utc=True, key="ts"),
            structlog.processors.add_log_level,
            _add_module,
            _module_level_filter,
            _emit_to_file_sinks,
            _strip_exception_for_console,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        if not console:
            processors.append(_NullRenderer())
        elif json:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(_ColourRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
            context_class=dict,
            cache_logger_on_first_use=True,
        )
        cls._configured = True

    @classmethod
    def get(cls, name: str | None = None):
        """Return a bound logger, auto-configuring with defaults if needed."""
        if not cls._configured:
            cls.configure()
        if name is None:
            return structlog.get_logger()
        return structlog.get_logger(name).bind(module=name)

    @classmethod
    def apply_level_overrides(cls, overrides: dict[str, str]) -> None:
        """Apply per-logger level overrides."""
        for name, level_str in overrides.items():
            _LEVEL_OVERRIDES[name] = cls._determine_level(level_str)

    @classmethod
    def set_level(cls, name: str, level: str | int):
        logging.getLogger(name).setLevel(cls._determine_level(level))

    @classmethod
    def disable(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def enable(cls, level: str | int | None = None):
        logging.disable(logging.NOTSET)
        if level is not None:
            cls.set_level("", level)

    @classmethod
    def add_file_sink(
        cls,
        path: str,
        *,
        level: str | int = "ERROR",
        rotate: bool = True,
        mode: str = "a",
        max_bytes: int = LOG_ROTATION_MAX_BYTES,
        backup_count: int = LOG_ROTATION_BACKUP_COUNT,
        use_json: bool = False,
        use_csv: bool = False,
        include_prefix: str | None = None,
        exclude_prefix: str | tuple[str, ...] | None = None,
    ) -> logging.Handler:
        """Mirror log events at or above *level* into a file.

        use_csv=True writes CSV rows (timestamp,level,module,message,extra).
        A header line is written when a new file is created (not when appending).
        use_json takes precedence over use_csv if both are set.

        include_prefix / exclude_prefix control module-based routing:
        - include_prefix="CLI." → only CLI.* events reach this sink.
        - exclude_prefix=("CLI.",) → CLI.* events are skipped.
        """
        if not cls._configured:
            cls.configure()

        import os

        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        is_new_file = mode == "w" or not os.path.exists(path)

        min_level = cls._determine_level(level)
        if rotate:
            handler: logging.Handler = logging.handlers.RotatingFileHandler(
                path,
                mode=mode,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        else:
            handler = logging.FileHandler(path, mode=mode, encoding="utf-8")

        handler.setLevel(min_level)
        handler.setFormatter(logging.Formatter("%(message)s"))

        if use_json:
            renderer = structlog.processors.JSONRenderer()
        elif use_csv:
            renderer = _CsvRenderer()
            if is_new_file:
                try:
                    with open(path, mode, encoding="utf-8") as fh:
                        fh.write(_CsvRenderer.HEADER + "\n")
                except OSError:
                    pass
        else:
            renderer = _PlainRenderer()

        # Normalise exclude_prefix to a tuple (or None).
        if isinstance(exclude_prefix, str):
            exclude_prefix = (exclude_prefix,)

        _FILE_SINKS.append((min_level, handler, renderer, include_prefix, exclude_prefix))
        logging.getLogger().addHandler(handler)
        return handler

    @classmethod
    def remove_file_sink(cls, handler: logging.Handler):
        try:
            logging.getLogger().removeHandler(handler)
        except Exception:
            pass
        global _FILE_SINKS
        _FILE_SINKS = [entry for entry in _FILE_SINKS if entry[1] is not handler]

    # Tracks the log directory opened by open_log_dir for idempotency.
    _log_dir: Path | None = None

    @classmethod
    def open_log_dir(cls, log_dir: Path, *, level: str | int = "INFO") -> None:
        """Open routed file sinks for a workspace log directory (idempotent).

        Creates two CSV sinks with module-prefix routing:
        - ``server.log``  — all events *except* ``CLI.*`` modules.
        - ``cli.log``     — only ``CLI.*`` modules.

        Channel plugins run in separate processes and create their own
        ``channel-<name>.log`` via ``log_setup.init()`` — no routing
        needed here.

        Safe to call from both the CLI callback (``commands/app.py``) and
        the server startup path (``runtime/server_process.py``). The second
        call with the same *log_dir* is a no-op.
        """
        log_dir = Path(log_dir)
        if cls._log_dir == log_dir:
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        cls._log_dir = log_dir

        cls.add_file_sink(
            str(log_dir / "server.log"),
            level=level,
            use_csv=True,
            exclude_prefix=("CLI.",),
        )
        cls.add_file_sink(
            str(log_dir / "cli.log"),
            level=level,
            use_csv=True,
            include_prefix="CLI.",
        )

    @classmethod
    def silence_stdlib(
        cls,
        logger_name: str,
        *,
        module: str,
        level: str | int = "WARNING",
    ) -> None:
        """Redirect a stdlib logger into the Hiro structured logger.

        Messages below *level* are suppressed.  Messages at or above
        *level* are re-emitted through ``Logger.get(module)`` so they
        appear in the console and file sinks with proper formatting.

        Propagation is disabled to prevent bare-text duplicates on the
        root logger.
        """
        if not cls._configured:
            cls.configure()
        numeric = cls._determine_level(level)
        stdlib_logger = logging.getLogger(logger_name)
        stdlib_logger.setLevel(numeric)
        stdlib_logger.addHandler(_StdlibBridge(module, numeric))
        stdlib_logger.propagate = False

    @classmethod
    def set_indent_unit(cls, unit: str):
        global _INDENT_UNIT
        _INDENT_UNIT = unit

    @classmethod
    def push(cls, steps: int = 1):
        _INDENT_LEVEL.set(_INDENT_LEVEL.get() + steps)

    @classmethod
    def pop(cls, steps: int = 1):
        _INDENT_LEVEL.set(max(_INDENT_LEVEL.get() - steps, 0))

    @classmethod
    @contextmanager
    def indent(cls, steps: int = 1):
        token = _INDENT_LEVEL.set(_INDENT_LEVEL.get() + steps)
        try:
            yield
        finally:
            _INDENT_LEVEL.reset(token)


configure = Logger.configure
get_logger = Logger.get
set_level = Logger.set_level
disable = Logger.disable
enable = Logger.enable
