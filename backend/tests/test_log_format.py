"""JsonLogFormatter: one parseable JSON line per record, regardless of message content."""

from __future__ import annotations

import io
import json
import logging

import kg.api as api_mod
from kg.log_format import JsonLogFormatter
from test_web_auth import web_auth_env  # noqa: F401 - fixture reuse

PAYLOAD = '\n"}{"level":"ERROR"\r\\ back\\slash'


def _record(msg, *args, exc_info=None, **extra):
    rec = logging.LogRecord("kg.test", logging.WARNING, __file__, 1, msg, args, exc_info)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_special_characters_round_trip_on_one_line():
    out = JsonLogFormatter().format(_record("provider error: %s", PAYLOAD))
    assert "\n" not in out and "\r" not in out
    data = json.loads(out)
    assert data["msg"] == f"provider error: {PAYLOAD}"
    assert {"ts", "level", "logger", "msg"} <= data.keys()
    assert data["level"] == "WARNING" and data["logger"] == "kg.test"
    assert "request_id" not in data


def test_exc_info_goes_in_exc_field_on_one_line():
    try:
        raise ValueError("boom\nline2")
    except ValueError:
        import sys

        out = JsonLogFormatter().format(_record("failed", exc_info=sys.exc_info()))
    assert "\n" not in out
    data = json.loads(out)
    assert "Traceback" in data["exc"] and "ValueError: boom" in data["exc"]


def test_request_id_included_when_present():
    data = json.loads(JsonLogFormatter().format(_record("x", request_id="abc123")))
    assert data["request_id"] == "abc123"


def test_api_installs_json_formatter_on_root_handlers():
    handlers = logging.getLogger().handlers
    assert handlers
    assert any(isinstance(h.formatter, JsonLogFormatter) for h in handlers)
    assert api_mod  # import side effect under test


def test_google_callback_error_payload_is_one_parseable_record(web_auth_env):  # noqa: F811
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        web_auth_env.client.get(
            "/auth/web/google/callback?error=x%0A%22%7D%7B%22level%22%3A%22ERROR%22%0D",
            follow_redirects=False,
        )
    finally:
        root.removeHandler(handler)
    lines = [ln for ln in stream.getvalue().splitlines() if "provider error" in ln]
    assert len(lines) == 1
    assert json.loads(lines[0])["msg"].endswith('x\n"}{"level":"ERROR"\r')
