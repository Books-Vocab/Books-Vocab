"""JsonLogFormatter: one parseable JSON line per record, regardless of message content."""

from __future__ import annotations

import io
import json
import logging

from kg.logging_config import JsonLogFormatter, configure_logging
from kg.request_context import request_id_var
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


def test_request_id_taken_from_contextvar_when_record_lacks_it():
    token = request_id_var.set("ctx-42")
    try:
        data = json.loads(JsonLogFormatter().format(_record("x")))
    finally:
        request_id_var.reset(token)
    assert data["request_id"] == "ctx-42"
    assert "request_id" not in json.loads(JsonLogFormatter().format(_record("x")))


def test_configure_logging_installs_json_handler_on_empty_root():
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers = []
    try:
        configure_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
        assert root.level == logging.INFO
    finally:
        root.handlers, root.level = saved, level


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
