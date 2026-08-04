"""Console logging: mirror terminal output to logs.txt (reset each run)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import auth

LOG_PATH = auth.BASE_DIR / "logs.txt"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_log_file = None


class _Tee:
    """Write to the real terminal and to logs.txt at the same time."""

    def __init__(self, stream, log_file):
        self._stream = stream
        self._log_file = log_file

    def write(self, data) -> None:
        if not data:
            return
        if not isinstance(data, str):
            data = str(data)
        self._stream.write(data)
        self._log_file.write(data)

    def flush(self) -> None:
        self._stream.flush()
        self._log_file.flush()

    def isatty(self) -> bool:
        return getattr(self._stream, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self._stream.fileno()


def setup_run_logging() -> Path:
    """Reset logs.txt and tee stdout/stderr + logging to console and file."""
    global _log_file

    LOG_PATH.unlink(missing_ok=True)
    _log_file = LOG_PATH.open("w", encoding="utf-8", buffering=1)

    sys.stdout = _Tee(sys.__stdout__, _log_file)
    sys.stderr = _Tee(sys.__stderr__, _log_file)

    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        stream=sys.stdout,
        force=True,
    )
    return LOG_PATH
