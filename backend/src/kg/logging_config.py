"""JSON logging setup: escapes message content so each record is exactly one parseable line."""

from __future__ import annotations

import json
import logging

from .request_context import request_id_var


class JsonLogFormatter(logging.Formatter):
    """Render records as single-line JSON (ts, level, logger, msg[, request_id, exc, stack])."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get("-")
        if request_id and request_id != "-":
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Install JSON-formatted INFO logging on the root logger (no-op if handlers exist)."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
