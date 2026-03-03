"""Shared logging initialiser for all PHB components.

Thin shim over ``phb_logger.Logger``.  Call ``init()`` once at process start,
before any other logging calls.  The signature is preserved so all existing
call sites work without changes.
"""

from __future__ import annotations

from pathlib import Path

from phb_logger import Logger

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_BACKUP_COUNT = 5


def init(
    component: str,
    log_dir: Path,
    *,
    level: str = "INFO",
    foreground: bool = False,
    log_levels: dict[str, str] | None = None,
) -> None:
    """Initialise logging for one PHB process.

    Parameters
    ----------
    component:
        Short label used as the log-file stem, e.g. ``"server"``,
        ``"plugin-devices"``, ``"gateway"``.
    log_dir:
        Directory where the rotating log file is written.  Created if absent.
    level:
        Root log level string (``"INFO"``, ``"DEBUG"``, …).
    foreground:
        If *True*, colourised output is also written to stdout.
        Use for ``phbcli start --foreground`` and direct gateway runs.
    log_levels:
        Optional per-logger level overrides, e.g.
        ``{"AGENT": "DEBUG", "COMM": "WARNING"}``.
    """
    log_dir = Path(log_dir)

    Logger.configure(level=level, console=foreground)

    Logger.add_file_sink(
        str(log_dir / f"{component}.log"),
        level=level,
        rotate=True,
        max_bytes=_MAX_BYTES,
        backup_count=_BACKUP_COUNT,
    )

    if log_levels:
        Logger.apply_level_overrides(log_levels)
