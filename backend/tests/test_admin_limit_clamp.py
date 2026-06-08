"""Lower-bound clamp on admin pagination params (Track-9 / R12).

These admin endpoints feed ``limit`` straight into SQLite ``LIMIT ?``.
A negative ``limit`` reaches ``LIMIT -1`` in SQLite, which means *no limit*
— the whole table is dumped past the intended CAP. The wiring layer already
clamps the upper bound (``min(limit, CAP)``); these tests pin the missing
lower bound, mirroring the ``max(1, min(limit, CAP))`` pattern already used by
``admin_audit.list_audit`` / ``admin_trends.collect_trends``.
"""
from __future__ import annotations

import pytest

from kg.admin_wiring import create_admin_handlers


def _noop(*_a, **_k):  # pragma: no cover - placeholder dep
    raise AssertionError("unexpected dependency call")


@pytest.fixture()
def handlers():
    """Build the real admin handler closures with placeholder deps.

    ``admin_pipeline_runs`` / ``admin_translate_history`` only touch their
    store modules (imported lazily inside the closure), so the other injected
    callables are never invoked and can stay as tripwire no-ops.
    """
    return create_admin_handlers(
        runtime_settings_fn=_noop,
        runtime_users_lock_file_fn=_noop,
        load_users_fn=_noop,
        save_users_fn=_noop,
        mem_log_getter=_noop,
        card_store_factory=_noop,
        build_entitlements_response_fn=_noop,
        current_admin_grant_record_fn=_noop,
    )


@pytest.fixture()
def pipeline_isolated(tmp_path, monkeypatch):
    from kg import pipeline_log

    monkeypatch.setattr(pipeline_log, "DB_PATH", tmp_path / "pipeline_runs.db")
    pipeline_log._reset()
    # Seed 5 runs for one user.
    for i in range(5):
        pipeline_log.start_run(f"r{i}", "u1", "nb1", "manual")
    try:
        yield pipeline_log
    finally:
        pipeline_log._reset()


@pytest.fixture()
def translate_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    from kg import translate_log

    translate_log._reset()
    for i in range(5):
        translate_log.record(
            user_id="u1",
            operation="translate_quick",
            word=f"w{i}",
            context="",
            context_hash=f"h{i}",
            source_lang="en",
            target_lang="zh-Hant",
            response_raw='{"t":"x"}',
            latency_ms=1,
        )
    try:
        yield translate_log
    finally:
        translate_log._reset()


# ---- #1 admin_pipeline_runs ----------------------------------------------

@pytest.mark.parametrize("bad_limit", [-1, 0, -100])
def test_pipeline_runs_non_positive_limit_clamped(handlers, pipeline_isolated, bad_limit):
    out = handlers.admin_pipeline_runs("u1", limit=bad_limit)
    # Must clamp to a single legal row, never dump the whole (5-row) table.
    assert len(out["runs"]) == 1, f"limit={bad_limit} leaked {len(out['runs'])} rows"


def test_pipeline_runs_positive_limit_unaffected(handlers, pipeline_isolated):
    out = handlers.admin_pipeline_runs("u1", limit=3)
    assert len(out["runs"]) == 3


# ---- #1 admin_translate_history ------------------------------------------

@pytest.mark.parametrize("bad_limit", [-1, 0, -100])
def test_translate_history_non_positive_limit_clamped(handlers, translate_isolated, bad_limit):
    out = handlers.admin_translate_history("u1", limit=bad_limit)
    assert len(out["history"]) == 1, f"limit={bad_limit} leaked {len(out['history'])} rows"


def test_translate_history_positive_limit_unaffected(handlers, translate_isolated):
    out = handlers.admin_translate_history("u1", limit=2)
    assert len(out["history"]) == 2
