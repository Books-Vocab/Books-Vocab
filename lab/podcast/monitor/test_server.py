"""Tests for the saga (multi-book) upload endpoint + saga-aware workspace summary.

Run:
    cd lab/podcast && uv run --with fastapi --with 'uvicorn[standard]' \
        --with python-multipart --with httpx --with pytest \
        pytest monitor/test_server.py -v
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

import server  # noqa: E402
import saga  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A TestClient whose upload staging points at an isolated tmp dir, so a
    test that asserts "staged files cleaned up" never sees other tests' debris
    and never touches the real monitor/.uploads."""
    staging = tmp_path / "uploads"
    staging.mkdir()
    monkeypatch.setattr(server, "UPLOAD_STAGING", staging)
    return TestClient(server.app)


def _epub(name: str, data: bytes = b"PKfake-epub-bytes") -> tuple:
    return (name, io.BytesIO(data), "application/epub+zip")


class _SpawnRecorder:
    """Records the argv passed to jobs.spawn and returns a fake Job, so no real
    pipeline subprocess is launched."""

    def __init__(self):
        self.argv: list[str] | None = None
        self.kwargs: dict | None = None

    def __call__(self, cmd, **kwargs):
        self.argv = list(cmd)
        self.kwargs = kwargs

        class _Job:
            id = "job-123"
            status = "running"

        return _Job()


@pytest.fixture
def spawn(monkeypatch):
    rec = _SpawnRecorder()
    monkeypatch.setattr(server.jobs, "spawn", rec)
    return rec


# ── start-saga endpoint ────────────────────────────────────────────────────


def test_start_saga_happy_path_argv_in_order(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "My Saga", "spoiler_mode": "readalong", "parallel": "5"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == "job-123"
    assert body["status"] == "running"
    assert body["label"] == "My Saga"
    assert body["books"] == 2

    argv = spawn.argv
    assert argv[:3] == ["uv", "run", "pipeline.py"]
    # two staged epub paths, in the order received, BEFORE the saga flags
    assert argv[3].endswith("_a.epub")
    assert argv[4].endswith("_b.epub")
    assert argv[5:] == [
        "--saga", "My Saga",
        "--spoiler-mode", "readalong",
        "--parallel", "5",
    ]
    # --saga implies saga mode; --mode must NOT be passed
    assert "--mode" not in argv


def test_start_saga_requires_two_books(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Solo", "spoiler_mode": "readalong"},
        files=[("epubs", _epub("only.epub"))],
    )
    assert resp.status_code == 400
    assert spawn.argv is None


def test_start_saga_rejects_non_epub(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Mix", "spoiler_mode": "readalong"},
        files=[
            ("epubs", _epub("a.epub")),
            ("epubs", ("notes.txt", io.BytesIO(b"nope"), "text/plain")),
        ],
    )
    assert resp.status_code == 400
    assert spawn.argv is None
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_start_saga_missing_title(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "   ", "spoiler_mode": "readalong"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 400
    assert spawn.argv is None
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_start_saga_invalid_spoiler_mode(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "bogus"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 400
    assert spawn.argv is None
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_start_saga_oversize_cleans_up_all_staged(client, spawn, monkeypatch):
    monkeypatch.setattr(server, "MAX_EPUB_BYTES", 4)
    big = ("big.epub", io.BytesIO(b"x" * 4096), "application/epub+zip")
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "readalong"},
        files=[("epubs", _epub("a.epub", b"x" * 4096)), ("epubs", big)],
    )
    assert resp.status_code == 413
    assert spawn.argv is None
    # ALL staged files (including the first, fully-written one) are removed.
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_start_saga_job_limit_returns_429_and_cleans_up(client, monkeypatch):
    def boom(*a, **k):
        # JobLimitReached(active, limit) — mirror the real ctor signature.
        raise server.JobLimitReached(4, 4)

    monkeypatch.setattr(server.jobs, "spawn", boom)
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "readalong"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 429
    assert list(server.UPLOAD_STAGING.glob("*")) == []


# ── _workspace_summary saga fields ─────────────────────────────────────────


def test_workspace_summary_single_book_is_not_saga(tmp_path):
    ws = tmp_path / "single"
    ws.mkdir()
    summary = server._workspace_summary(ws, None)
    assert summary["is_saga"] is False
    # legacy workspaces must never carry saga-only fields
    assert "book_count" not in summary
    assert "spoiler_mode" not in summary


def test_workspace_summary_saga_fields(tmp_path):
    ws = tmp_path / "saga_ws"
    ws.mkdir()
    books = saga.plan_books([
        {"title": "Book One", "author": "A"},
        {"title": "Book Two", "author": "B"},
        {"title": "Book Three", "author": "C"},
    ])
    (ws / "series.md").write_text(
        saga.render_series_manifest("The Trilogy", books), encoding="utf-8"
    )
    (ws / ".spoiler_mode").write_text("retrospective", encoding="utf-8")

    summary = server._workspace_summary(ws, None)
    assert summary["is_saga"] is True
    assert summary["book_count"] == 3
    assert summary["spoiler_mode"] == "retrospective"
    assert summary["display"] == "The Trilogy"


def test_workspace_summary_saga_malformed_manifest_falls_back(tmp_path):
    """A series.md present but unparseable must still mark is_saga=True without
    raising — graceful degradation, never a 500 on the sidebar list."""
    ws = tmp_path / "broken_saga"
    ws.mkdir()
    (ws / "series.md").write_text("not a real manifest", encoding="utf-8")
    summary = server._workspace_summary(ws, None)
    assert summary["is_saga"] is True
    # book_count/display degrade gracefully; spoiler_mode absent on disk
    assert summary.get("book_count", 0) == 0
