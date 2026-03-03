import logging
import logging.handlers
import sys
import traceback
import contextvars
from contextlib import contextmanager
from typing import Mapping

import structlog
import colorama

colorama.init(autoreset=True)

__all__ = [
    "Logger",
    "configure",
    "get_logger",
    "set_level",
    "disable",
    "enable",
]

# ---------------------------------------------------------------------------
# Colour helpers / renderer
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Indentation support (context-local)
# ---------------------------------------------------------------------------

_INDENT_LEVEL: contextvars.ContextVar[int] = contextvars.ContextVar("indent_level", default=0)
_INDENT_UNIT: str = "--"

# ---------------------------------------------------------------------------
# File sinks and per-logger level overrides
# ---------------------------------------------------------------------------

_FILE_SINKS: list[tuple[int, logging.Handler, object]] = []

# Maps logger name prefix → minimum numeric level.  Populated via
# Logger.apply_level_overrides() from config at startup.
_LEVEL_OVERRIDES: dict[str, int] = {}


def _pick_module_color(name: str) -> str:
    if not name:
        return colorama.Fore.WHITE
    index = sum(ord(c) for c in name) % len(_MODULE_PALETTE)
    return _MODULE_PALETTE[index]


class _ColourRenderer:
    def __call__(self, logger, method_name, event_dict):
        ts = event_dict.pop("ts", "")
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
        ts = event_dict.pop("ts", "")
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


class _NullRenderer:
    """Discards all console output; used when console=False (background processes)."""

    def __call__(self, logger, method_name, event_dict):
        raise structlog.DropEvent()


def _module_level_filter(logger, method_name, event_dict):
    """Drop events that fall below the configured per-module level override."""
    if not _LEVEL_OVERRIDES:
        return event_dict

    module = str(event_dict.get("module", ""))
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)

    # Longest matching prefix wins
    for prefix in sorted(_LEVEL_OVERRIDES.keys(), key=len, reverse=True):
        if module == prefix or module.startswith(prefix + ".") or module.startswith(prefix):
            if event_level < _LEVEL_OVERRIDES[prefix]:
                raise structlog.DropEvent()
            break

    return event_dict


def _emit_to_file_sinks(logger, method_name, event_dict):
    level_name = str(event_dict.get("level", "")).upper()
    event_level = logging._nameToLevel.get(level_name, logging.INFO)

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

    for min_level, handler, renderer in list(_FILE_SINKS):
        if event_level >= min_level:
            try:
                copy_for_file = dict(event_dict)
                rendered = renderer(None, method_name, copy_for_file)

                if event_level >= logging.ERROR and exc_info is not None:
                    try:
                        tb_lines = traceback.format_exception(*exc_info)
                        tb_one_line = " | ".join(line.strip() for line in tb_lines if line and line.strip())
                        if tb_one_line:
                            rendered = f"{rendered} exception={tb_one_line}"
                    except Exception:
                        pass

                record = logging.LogRecord(
                    name=str(event_dict.get("module", "")),
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
    """Central logging facility for PHB.

    Call ``Logger.configure()`` once at process startup (or use the
    ``log_setup.init()`` shim which does this for you), then obtain
    per-module loggers with ``Logger.get("MODULE_NAME")``.

    Examples
    --------
    >>> Logger.configure(level="DEBUG", console=True)
    >>> log = Logger.get("GATEWAY")
    >>> log.info("Gateway started", host="0.0.0.0", port=8765)
    >>> with Logger.indent():
    ...     log.debug("Nested detail")
    """

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
        """One-time global logger configuration.

        Parameters
        ----------
        level:
            Root log level (e.g. ``"DEBUG"``).
        json:
            Emit JSON lines instead of colourised human output.
        enabled:
            ``False`` suppresses every log call (useful for tests).
        console:
            ``False`` disables all console/stdout output.  File sinks added
            via ``add_file_sink()`` still receive events.  Use for background
            processes that should not write to a terminal.
        """
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
            structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False, key="ts"),
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
        """Return a bound structlog logger, auto-configuring with defaults if needed."""
        if not cls._configured:
            cls.configure()
        if name is None:
            return structlog.get_logger()
        return structlog.get_logger(name).bind(module=name)

    @classmethod
    def apply_level_overrides(cls, overrides: dict[str, str]) -> None:
        """Apply per-logger level overrides from config.

        Parameters
        ----------
        overrides:
            Mapping of logger name (or prefix) to level string, e.g.
            ``{"AGENT": "DEBUG", "COMM": "WARNING"}``.
        """
        global _LEVEL_OVERRIDES
        for name, level_str in overrides.items():
            numeric = cls._determine_level(level_str)
            _LEVEL_OVERRIDES[name] = numeric

    @classmethod
    def set_level(cls, name: str, level: str | int):
        numeric = cls._determine_level(level)
        logging.getLogger(name).setLevel(numeric)

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
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        use_json: bool = False,
    ) -> logging.Handler:
        """Mirror log events at or above *level* into a file.

        Returns the created handler so callers may remove it later via
        ``remove_file_sink()``.
        """
        if not cls._configured:
            cls.configure()

        import os
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

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

        renderer = structlog.processors.JSONRenderer() if use_json else _PlainRenderer()
        _FILE_SINKS.append((min_level, handler, renderer))

        logging.getLogger().addHandler(handler)
        return handler

    @classmethod
    def remove_file_sink(cls, handler: logging.Handler):
        try:
            logging.getLogger().removeHandler(handler)
        except Exception:
            pass
        global _FILE_SINKS
        _FILE_SINKS = [(lvl, h, r) for (lvl, h, r) in _FILE_SINKS if h is not handler]

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
        """Context manager that visually indents nested log output.

        Indentation is stored in a ``contextvars.ContextVar`` so it is
        task-local in async code.
        """
        token = _INDENT_LEVEL.set(_INDENT_LEVEL.get() + steps)
        try:
            yield
        finally:
            _INDENT_LEVEL.reset(token)
