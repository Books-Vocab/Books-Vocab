"""In-memory ring-buffer log handler for the admin dashboard.

Extracted from ``api.py`` so the app factory module stays focused on
FastAPI wiring. ``api.py`` re-exports ``_mem_log`` for backward
compatibility (existing tests do ``from kg.api import _mem_log``).
"""

from __future__ import annotations

import collections
import logging
import re
import threading

_SENSITIVE_QUERY_RE = re.compile(r"([?&](?:token|code|state))=[^&\s\"]+")


def _redact(value):
    if isinstance(value, str):
        return _SENSITIVE_QUERY_RE.sub(r"\1=[REDACTED]", value)
    return value


class _SensitiveQueryRedactionFilter(logging.Filter):
    """Redact credential-bearing query values from access-log records.

    Attached to the ``uvicorn.access`` logger (not a handler) so every handler
    -- stdout and the admin ring buffer -- sees the already-redacted record.
    Idempotent: redacted text no longer matches.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: _redact(v) for k, v in args.items()}
        return True


class _MemoryLogHandler(logging.Handler):
    """Ring-buffer log handler for the admin dashboard."""

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._buf: collections.deque = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from datetime import datetime as _dt

            from .request_context import request_id_var

            self._buf.append(
                {
                    "ts": _dt.fromtimestamp(record.created).strftime("%H:%M:%S"),
                    "level": record.levelname,
                    "name": record.name,
                    "msg": record.getMessage(),
                    "request_id": request_id_var.get("-"),
                }
            )
        except Exception:
            pass  # handler must never crash the application

    def get(self, n: int = 200, level: str | None = None) -> list[dict]:
        # Clamp the lower bound: n=0 makes rows[-0:] == rows[:] (whole
        # buffer) and n<0 makes rows[n:] a forward slice (head-dropped,
        # misaligned). Both are the wrong "tail". Floor at a single row.
        n = max(1, n)
        rows = list(self._buf)
        if level:
            rows = [r for r in rows if r["level"] == level]
        return rows[-n:]


_shared_memory_log_handler: _MemoryLogHandler | None = None
_shared_memory_log_handler_lock = threading.Lock()


def install_memory_log_handler(maxlen: int = 1000) -> _MemoryLogHandler:
    """Create the shared memory log handler and attach it to the loggers
    surfaced by the admin dashboard (root + uvicorn family).

    Returns the handler so callers can read the ring buffer via ``.get()``.
    """
    global _shared_memory_log_handler
    with _shared_memory_log_handler_lock:
        if _shared_memory_log_handler is None:
            _shared_memory_log_handler = _MemoryLogHandler(maxlen=maxlen)
            _shared_memory_log_handler.setLevel(logging.DEBUG)

        handler = _shared_memory_log_handler
        for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
            target = logging.getLogger(logger_name)
            if not any(h is handler for h in target.handlers):
                target.addHandler(handler)
        access = logging.getLogger("uvicorn.access")
        if not any(isinstance(f, _SensitiveQueryRedactionFilter) for f in access.filters):
            access.addFilter(_SensitiveQueryRedactionFilter())
    return handler
