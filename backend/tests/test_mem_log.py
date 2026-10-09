"""Tests for kg.mem_log._MemoryLogHandler + install_memory_log_handler.

Covers ring-buffer eviction, level filtering, tail slicing, swallow-on-emit
behavior, and the idempotent attach contract used by app startup.
"""

from __future__ import annotations

import io
import logging

import pytest

from kg.mem_log import _MemoryLogHandler, install_memory_log_handler


def _record(level: int = logging.INFO, msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="kg.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


# ---- ring buffer cap ------------------------------------------------------


def test_ring_buffer_evicts_oldest_when_full():
    h = _MemoryLogHandler(maxlen=3)
    for i in range(5):
        h.emit(_record(msg=f"m{i}"))
    rows = h.get(n=10)
    # capped at maxlen, oldest two ("m0","m1") evicted
    assert [r["msg"] for r in rows] == ["m2", "m3", "m4"]


# ---- level filter ---------------------------------------------------------


def test_get_filters_by_level():
    h = _MemoryLogHandler(maxlen=100)
    h.emit(_record(level=logging.INFO, msg="info-a"))
    h.emit(_record(level=logging.ERROR, msg="err-1"))
    h.emit(_record(level=logging.WARNING, msg="warn-x"))
    h.emit(_record(level=logging.ERROR, msg="err-2"))

    errs = h.get(level="ERROR")
    assert [r["msg"] for r in errs] == ["err-1", "err-2"]
    assert all(r["level"] == "ERROR" for r in errs)


# ---- tail slicing ---------------------------------------------------------


def test_get_returns_tail_n():
    h = _MemoryLogHandler(maxlen=100)
    for i in range(20):
        h.emit(_record(msg=f"m{i}"))
    rows = h.get(n=5)
    assert [r["msg"] for r in rows] == ["m15", "m16", "m17", "m18", "m19"]


def test_get_n_zero_does_not_return_all():
    """``n=0`` must NOT degenerate into ``rows[0:]`` (whole buffer).

    Tail-of-zero is an empty tail; the slice ``rows[-0:]`` == ``rows[:]``
    is the SQLite-style ``LIMIT -1`` footgun. Clamp to a single row.
    """
    h = _MemoryLogHandler(maxlen=100)
    for i in range(20):
        h.emit(_record(msg=f"m{i}"))
    rows = h.get(n=0)
    assert len(rows) <= 1
    assert len(rows) < 20  # the regression: do not dump the whole buffer


def test_get_negative_n_does_not_misalign():
    """``n=-5`` must not become ``rows[5:]`` (head-drop misalignment)."""
    h = _MemoryLogHandler(maxlen=100)
    for i in range(20):
        h.emit(_record(msg=f"m{i}"))
    rows = h.get(n=-5)
    # Must behave like the smallest legal tail, never a forward slice.
    assert [r["msg"] for r in rows] == ["m19"]


# ---- emit must swallow exceptions ----------------------------------------


class _BrokenRecord:
    """Looks vaguely like a LogRecord but explodes on attribute access used
    inside _MemoryLogHandler.emit (getMessage, created, levelname, name)."""

    created = 0.0
    levelname = "ERROR"
    name = "kg.broken"

    def getMessage(self) -> str:  # noqa: D401
        raise RuntimeError("intentionally broken")


def test_emit_swallows_exceptions():
    h = _MemoryLogHandler(maxlen=10)
    # must not raise — handler must never crash the app
    h.emit(_BrokenRecord())  # type: ignore[arg-type]
    # the broken record was rejected, so buffer stays empty
    assert h.get() == []


# ---- install_memory_log_handler idempotency ------------------------------


def test_install_reuses_shared_handler_without_duplicate_attachments():
    targets = [logging.getLogger(n) for n in ("", "uvicorn", "uvicorn.error", "uvicorn.access")]
    before = [list(t.handlers) for t in targets]

    h1 = install_memory_log_handler(maxlen=50)
    after_first = [list(t.handlers) for t in targets]
    h2 = install_memory_log_handler(maxlen=50)
    after_second = [list(t.handlers) for t in targets]

    try:
        assert h2 is h1, "repeated installation must return the shared handler"
        assert after_second == after_first, "repeated installation must not add handlers"
        assert all(sum(handler is h1 for handler in t.handlers) == 1 for t in targets)
    finally:
        # Restore each logger's pre-test handler list without disturbing
        # handlers installed by other tests or application setup.
        for target, original in zip(targets, before, strict=True):
            for handler in list(target.handlers):
                if handler not in original:
                    target.removeHandler(handler)


def test_install_returns_working_handler():
    targets = [logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")]
    before = [list(target.handlers) for target in targets]
    h = install_memory_log_handler(maxlen=4)
    try:
        h.emit(_record(msg="installed"))
        rows = h.get()
        assert any(r["msg"] == "installed" for r in rows)
    finally:
        for target, original in zip(targets, before, strict=True):
            for handler in list(target.handlers):
                if handler not in original:
                    target.removeHandler(handler)


# ---- access-log secret redaction -----------------------------------------

_ACCESS_FMT = '%s - "%s %s HTTP/%s" %d'


@pytest.fixture
def access_logger():
    logger = logging.getLogger("uvicorn.access")
    before_handlers = list(logger.handlers)
    before_filters = list(logger.filters)
    before_level = logger.level
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    stream_handler = logging.StreamHandler(stream)
    logger.addHandler(stream_handler)
    ring = install_memory_log_handler()
    try:
        yield logger, stream, ring
    finally:
        logger.setLevel(before_level)
        for h in list(logger.handlers):
            if h not in before_handlers:
                logger.removeHandler(h)
        for f in list(logger.filters):
            if f not in before_filters:
                logger.removeFilter(f)


@pytest.mark.parametrize("param", ["token", "code", "state"])
def test_access_log_redacts_sensitive_query_params(access_logger, param):
    logger, stream, ring = access_logger
    path = f"/admin/tests?{param}=s3cr3t&x=1"
    logger.info(_ACCESS_FMT, "127.0.0.1:1234", "GET", path, "1.1", 200)

    streamed = stream.getvalue()
    buffered = ring.get(1)[-1]["msg"]
    for text in (streamed, buffered):
        assert "s3cr3t" not in text
        assert f"{param}=[REDACTED]" in text
        assert "x=1" in text


def test_access_log_redacts_param_after_other_params(access_logger):
    logger, stream, ring = access_logger
    logger.info(_ACCESS_FMT, "c", "GET", "/cb?x=1&code=abc&state=def", "1.1", 200)
    for text in (stream.getvalue(), ring.get(1)[-1]["msg"]):
        assert "abc" not in text and "def" not in text
        assert "code=[REDACTED]&state=[REDACTED]" in text


def test_access_log_leaves_clean_records_unchanged(access_logger):
    logger, stream, ring = access_logger
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    logger.addHandler(_Capture())
    logger.info(_ACCESS_FMT, "c", "GET", "/api/x?mytoken=keep&y=2", "1.1", 200)
    rec = captured[-1]
    assert rec.args == ("c", "GET", "/api/x?mytoken=keep&y=2", "1.1", 200)
    assert rec.getMessage() == 'c - "GET /api/x?mytoken=keep&y=2 HTTP/1.1" 200'
    assert "mytoken=keep" in stream.getvalue()


def test_access_log_filter_installed_once(access_logger):
    logger, _, _ = access_logger
    install_memory_log_handler()
    install_memory_log_handler()
    from kg.mem_log import _SensitiveQueryRedactionFilter

    assert sum(isinstance(f, _SensitiveQueryRedactionFilter) for f in logger.filters) == 1


def test_emit_caps_oversized_message():
    """#2303: one huge log line must not bloat the ring buffer."""
    handler = _MemoryLogHandler(maxlen=10)
    handler.emit(_record(msg="x" * 50_000))
    (row,) = handler.get()
    assert len(row["msg"]) <= 2100
    assert row["msg"].startswith("xxx")
