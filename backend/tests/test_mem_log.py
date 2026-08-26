"""Tests for kg.mem_log._MemoryLogHandler + install_memory_log_handler.

Covers ring-buffer eviction, level filtering, tail slicing, swallow-on-emit
behavior, and the idempotent attach contract used by app startup.
"""

from __future__ import annotations

import logging

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
    h = install_memory_log_handler(maxlen=4)
    try:
        h.emit(_record(msg="installed"))
        rows = h.get()
        assert any(r["msg"] == "installed" for r in rows)
    finally:
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
            logging.getLogger(name).removeHandler(h)
