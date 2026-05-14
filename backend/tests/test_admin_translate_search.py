"""Tests for translate_log search/filter on get_log."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def translate_log_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate translate_log.db to tmp_path and reset singleton between tests."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.translate_log as tl

    tl._reset()
    try:
        yield tl
    finally:
        tl._reset()


def _seed(tl, user_id: str, *, op: str, word: str, ctx: str = "") -> None:
    tl.record(
        user_id=user_id,
        operation=op,
        word=word,
        context=ctx,
        context_hash="h_" + word,
        source_lang="en",
        target_lang="zh-Hant",
        response_raw='{"t":"x"}',
        latency_ms=10,
    )


def test_get_log_no_filter_returns_all(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u1", op="translate_explain", word="banana")
    _seed(tl, "u1", op="translate_quick", word="cherry")

    rows = tl.get_log("u1")
    assert {r["word"] for r in rows} == {"apple", "banana", "cherry"}


def test_get_log_filter_by_operation(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u1", op="translate_explain", word="banana")
    _seed(tl, "u1", op="translate_quick", word="cherry")

    rows = tl.get_log("u1", op="translate_quick")
    assert {r["word"] for r in rows} == {"apple", "cherry"}


def test_get_log_filter_by_word_substring(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u1", op="translate_quick", word="pineapple")
    _seed(tl, "u1", op="translate_quick", word="banana")

    rows = tl.get_log("u1", q="apple")
    assert {r["word"] for r in rows} == {"apple", "pineapple"}


def test_get_log_filter_by_context_substring(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="run", ctx="I run every morning")
    _seed(tl, "u1", op="translate_quick", word="walk", ctx="quick walk")
    _seed(tl, "u1", op="translate_quick", word="jog", ctx="evening jog")

    rows = tl.get_log("u1", q="morning")
    assert [r["word"] for r in rows] == ["run"]


def test_get_log_combined_op_and_q(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u1", op="translate_explain", word="apple_pie")
    _seed(tl, "u1", op="translate_quick", word="banana")

    rows = tl.get_log("u1", op="translate_quick", q="apple")
    assert [r["word"] for r in rows] == ["apple"]


def test_get_log_q_is_case_insensitive(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="Apple")

    rows = tl.get_log("u1", q="apple")
    assert len(rows) == 1


def test_get_log_q_escapes_like_wildcards(translate_log_isolated):
    """A literal '%' or '_' in q must not be treated as a SQL wildcard."""
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u1", op="translate_quick", word="100%")

    rows = tl.get_log("u1", q="%")
    assert {r["word"] for r in rows} == {"100%"}


def test_get_log_isolates_users(translate_log_isolated):
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u2", op="translate_quick", word="apple")

    rows = tl.get_log("u1", q="apple")
    assert len(rows) == 1
    assert rows[0]["user_id"] == "u1"


def test_get_log_q_empty_string_returns_all(translate_log_isolated):
    """Empty/whitespace q should behave like no filter."""
    tl = translate_log_isolated
    _seed(tl, "u1", op="translate_quick", word="apple")
    _seed(tl, "u1", op="translate_quick", word="banana")

    rows = tl.get_log("u1", q="")
    assert len(rows) == 2
    rows2 = tl.get_log("u1", q="   ")
    assert len(rows2) == 2
