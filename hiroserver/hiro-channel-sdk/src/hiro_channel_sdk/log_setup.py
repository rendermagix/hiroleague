"""Shared logging initialiser for all Hiro components."""

from __future__ import annotations

from pathlib import Path

from hiro_commons.constants.timing import LOG_ROTATION_BACKUP_COUNT, LOG_ROTATION_MAX_BYTES
from hiro_commons.log import Logger


def init(
    component: str,
    log_dir: Path,
    *,
    level: str = "INFO",
    foreground: bool = False,
    log_levels: dict[str, str] | None = None,
) -> None:
    """Initialise logging for one Hiro process.

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
        Use for ``hirocli start --foreground`` and direct gateway runs.
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
        max_bytes=LOG_ROTATION_MAX_BYTES,
        backup_count=LOG_ROTATION_BACKUP_COUNT,
        use_csv=True,
    )

    if log_levels:
        Logger.apply_level_overrides(log_levels)
