from __future__ import annotations

import logging
import sys
from typing import Optional

# Attempt to import colorlog; fall back gracefully if unavailable
try:
    import colorlog  # type: ignore

    _COLORLOG_AVAILABLE = True
except ImportError:
    _COLORLOG_AVAILABLE = False

_LOG_FORMAT = "[%(levelname)s] %(name)s: %(message)s"
_COLOR_LOG_FORMAT = "%(log_color)s[%(levelname)s]%(reset)s %(name)s: %(message)s"

_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold_red",
}

# Registry to avoid adding duplicate handlers on repeated calls
_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a named logger configured with colored output when available.

    Repeated calls with the same *name* return the same logger instance so
    that handlers are never duplicated.

    Args:
        name:  Logger name, typically ``__name__`` of the calling module.
        level: Logging level (default ``logging.INFO``).

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent propagation to root so we own the handler completely
    logger.propagate = False

    if logger.handlers:
        # Logger was already set up outside this module (e.g., in tests)
        _loggers[name] = logger
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if _COLORLOG_AVAILABLE:
        formatter: logging.Formatter = colorlog.ColoredFormatter(
            _COLOR_LOG_FORMAT,
            log_colors=_LOG_COLORS,
            reset=True,
            style="%",
        )
    else:
        formatter = logging.Formatter(_LOG_FORMAT)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _loggers[name] = logger
    return logger
