"""In-memory ring-buffer log handler for the admin dashboard.

Extracted from ``api.py`` so the app factory module stays focused on
FastAPI wiring. ``api.py`` re-exports ``_mem_log`` for backward
compatibility (existing tests do ``from kg.api import _mem_log``).
"""

from __future__ import annotations

import collections
import logging


class _MemoryLogHandler(logging.Handler):
    """Ring-buffer log handler for the admin dashboard."""

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._buf: collections.deque = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from datetime import datetime as _dt

            from .request_context import request_id_var
            self._buf.append({
                "ts": _dt.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
                "request_id": request_id_var.get("-"),
            })
        except Exception:
            pass  # handler must never crash the application

    def get(self, n: int = 200, level: str | None = None) -> list[dict]:
        rows = list(self._buf)
        if level:
            rows = [r for r in rows if r["level"] == level]
        return rows[-n:]


def install_memory_log_handler(maxlen: int = 1000) -> _MemoryLogHandler:
    """Create the shared memory log handler and attach it to the loggers
    surfaced by the admin dashboard (root + uvicorn family).

    Returns the handler so callers can read the ring buffer via ``.get()``.
    """
    handler = _MemoryLogHandler(maxlen=maxlen)
    handler.setLevel(logging.DEBUG)
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(logger_name)
        if not any(h is handler for h in target.handlers):
            target.addHandler(handler)
    return handler
