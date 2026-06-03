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
            label = "job-label"

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


# ── tts_model plumbing (start + start-saga) ────────────────────────────────


def test_start_pipeline_valid_tts_model_appends_flag(client, spawn):
    resp = client.post(
        "/api/pipeline/start",
        data={"parallel": "3", "tts_model": "gemini-2.5-pro-tts"},
        files={"epub": _epub("book.epub")},
    )
    assert resp.status_code == 200, resp.text
    argv = spawn.argv
    assert argv[-2:] == ["--tts-model", "gemini-2.5-pro-tts"]
    assert spawn.kwargs["metadata"]["tts_model"] == "gemini-2.5-pro-tts"


def test_start_pipeline_omits_flag_when_tts_model_blank(client, spawn):
    resp = client.post(
        "/api/pipeline/start",
        data={"parallel": "3"},
        files={"epub": _epub("book.epub")},
    )
    assert resp.status_code == 200, resp.text
    assert "--tts-model" not in spawn.argv
    assert spawn.kwargs["metadata"]["tts_model"] is None


def test_start_pipeline_rejects_unknown_tts_model(client, spawn):
    resp = client.post(
        "/api/pipeline/start",
        data={"parallel": "3", "tts_model": "gpt-voice-9000"},
        files={"epub": _epub("book.epub")},
    )
    assert resp.status_code == 422
    assert spawn.argv is None
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_start_saga_valid_tts_model_appends_flag(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "readalong", "tts_model": "gemini-2.5-flash-tts"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 200, resp.text
    assert spawn.argv[-2:] == ["--tts-model", "gemini-2.5-flash-tts"]
    assert spawn.kwargs["metadata"]["tts_model"] == "gemini-2.5-flash-tts"


def test_start_saga_rejects_unknown_tts_model(client, spawn):
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "readalong", "tts_model": "bogus-tts"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 422
    assert spawn.argv is None
    assert list(server.UPLOAD_STAGING.glob("*")) == []


# ── upload content-hash dedup (concurrent same-EPUB guard) ──────────────────


def test_start_pipeline_passes_content_hash_dedup_key(client, spawn):
    """start_pipeline hashes the streamed EPUB bytes and passes the digest as
    spawn(dedup_key="epub:<hash>") so two concurrent uploads of the same file
    collide in JobTracker's atomic guard."""
    import hashlib

    data = b"PKfake-epub-bytes-unique-A"
    resp = client.post(
        "/api/pipeline/start",
        files={"epub": ("book.epub", io.BytesIO(data), "application/epub+zip")},
    )
    assert resp.status_code == 200, resp.text
    key = spawn.kwargs["dedup_key"]
    assert key == f"epub:{hashlib.sha256(data).hexdigest()}"
    # workspace= must NOT also be passed (ws unknown at spawn time).
    assert spawn.kwargs.get("workspace") is None


def test_start_pipeline_same_bytes_same_key_distinct_bytes_differ(client, spawn):
    """Hash is content-derived: identical bytes → identical key; one differing
    byte → different key. Filename is irrelevant to dedup."""
    client.post("/api/pipeline/start",
                files={"epub": ("x.epub", io.BytesIO(b"AAAA"), "application/epub+zip")})
    k1 = spawn.kwargs["dedup_key"]
    client.post("/api/pipeline/start",
                files={"epub": ("y.epub", io.BytesIO(b"AAAA"), "application/epub+zip")})
    k2 = spawn.kwargs["dedup_key"]
    client.post("/api/pipeline/start",
                files={"epub": ("z.epub", io.BytesIO(b"AAAB"), "application/epub+zip")})
    k3 = spawn.kwargs["dedup_key"]
    assert k1 == k2
    assert k1 != k3


def test_start_pipeline_busy_returns_409_and_cleans_up(client, monkeypatch):
    """When the atomic guard rejects (same EPUB already processing), the endpoint
    returns 409 and unlinks the just-staged file — no orphan in staging."""
    def boom(cmd, **kwargs):
        raise server.WorkspaceBusyError(kwargs.get("dedup_key", "epub:x"), "job-x")
    monkeypatch.setattr(server.jobs, "spawn", boom)
    resp = client.post(
        "/api/pipeline/start",
        files={"epub": _epub("dup.epub")},
    )
    assert resp.status_code == 409
    assert "already being processed" in resp.json()["detail"].lower()
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_staging_dest_unique_for_same_name_same_second(client, monkeypatch):
    """Regression: two uploads of the SAME safe_name must stage to PHYSICALLY
    distinct paths even within the same wall-clock second. A second-resolution
    timestamp collided them, so the dedup loser's `unlink` deleted the file the
    winner's pipeline.py was reading in-place — corrupting the winner."""
    # Pin time to a single second to prove the uuid token (not the timestamp)
    # is what disambiguates concurrent same-name uploads.
    monkeypatch.setattr(server.time, "time", lambda: 1_700_000_000.0)
    a = server._staging_dest("same.epub")
    b = server._staging_dest("same.epub")
    assert a != b, "same-name uploads in the same second must not collide"
    assert a.name.endswith("_same.epub") and b.name.endswith("_same.epub")


def test_loser_cleanup_does_not_delete_winners_staged_input(client, monkeypatch):
    """The 409 loser unlinks ONLY its own staged handle. Because the winner and
    loser staged to distinct paths, the loser's cleanup leaves the winner's
    in-place pipeline input untouched."""
    monkeypatch.setattr(server.time, "time", lambda: 1_700_000_000.0)
    winner = server._staging_dest("dup.epub")
    winner.write_bytes(b"PKwinner-input")
    # The loser hits the content-hash guard and 409s; assert the winner's file,
    # staged at a distinct path, survives the whole request.
    def boom(cmd, **kwargs):
        raise server.WorkspaceBusyError(kwargs.get("dedup_key", "epub:x"), "job-x")
    monkeypatch.setattr(server.jobs, "spawn", boom)
    resp = client.post("/api/pipeline/start", files={"epub": _epub("dup.epub")})
    assert resp.status_code == 409
    assert winner.exists(), "loser's cleanup must not delete the winner's input"
    assert winner.read_bytes() == b"PKwinner-input"
    # The loser's OWN staged file is gone — no orphan besides the winner's.
    assert list(server.UPLOAD_STAGING.glob("*")) == [winner]


def test_start_saga_passes_content_hash_dedup_key(client, spawn):
    """start_saga hashes every staged EPUB (in reading order) into one combined
    dedup_key, so the same multi-book saga uploaded twice concurrently collides."""
    import hashlib

    a, b = b"PKsaga-book-a", b"PKsaga-book-b"
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "readalong"},
        files=[
            ("epubs", ("a.epub", io.BytesIO(a), "application/epub+zip")),
            ("epubs", ("b.epub", io.BytesIO(b), "application/epub+zip")),
        ],
    )
    assert resp.status_code == 200, resp.text
    h = hashlib.sha256()
    for chunk in (a, b):
        h.update(hashlib.sha256(chunk).digest())
    assert spawn.kwargs["dedup_key"] == f"epub:{h.hexdigest()}"
    assert spawn.kwargs.get("workspace") is None


def test_start_saga_book_order_changes_dedup_key(client, spawn):
    """Saga reading order is semantically meaningful — swapping book order must
    yield a different dedup key (different pipeline)."""
    a = ("a.epub", b"PKbook-a", "application/epub+zip")
    b = ("b.epub", b"PKbook-b", "application/epub+zip")

    def post(first, second):
        return client.post(
            "/api/pipeline/start-saga",
            data={"title": "S", "spoiler_mode": "readalong"},
            files=[("epubs", (first[0], io.BytesIO(first[1]), first[2])),
                   ("epubs", (second[0], io.BytesIO(second[1]), second[2]))],
        )

    post(a, b)
    k_ab = spawn.kwargs["dedup_key"]
    post(b, a)
    k_ba = spawn.kwargs["dedup_key"]
    assert k_ab != k_ba


def test_start_saga_busy_returns_409_and_cleans_up(client, monkeypatch):
    def boom(cmd, **kwargs):
        raise server.WorkspaceBusyError(kwargs.get("dedup_key", "epub:x"), "job-x")
    monkeypatch.setattr(server.jobs, "spawn", boom)
    resp = client.post(
        "/api/pipeline/start-saga",
        data={"title": "Saga", "spoiler_mode": "readalong"},
        files=[("epubs", _epub("a.epub")), ("epubs", _epub("b.epub"))],
    )
    assert resp.status_code == 409
    assert "already being processed" in resp.json()["detail"].lower()
    assert list(server.UPLOAD_STAGING.glob("*")) == []


def test_tts_allowlist_parity_frontend_backend():
    """The TTS allowlist lives in three places (tts_config.py SoT + app.js mirror
    + index.html <option>s). Guard against silent drift: a model added server-side
    but missing from the UI is unselectable; one removed server-side but left in
    the UI 422s on submit."""
    from tts_config import ALLOWED_TTS_MODELS

    static = Path(__file__).parent / "static"
    app_js = (static / "app.js").read_text()
    index_html = (static / "index.html").read_text()
    for model in ALLOWED_TTS_MODELS:
        assert f'"{model}"' in app_js, f"{model} missing from app.js ALLOWED_TTS_MODELS"
        assert f'value="{model}"' in index_html, f"{model} missing from index.html <option>"


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
