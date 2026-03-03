from .xlogger import Logger

configure = Logger.configure
get_logger = Logger.get
set_level = Logger.set_level
disable = Logger.disable
enable = Logger.enable

__all__ = [
    "Logger",
    "configure",
    "get_logger",
    "set_level",
    "disable",
    "enable",
]
