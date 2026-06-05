"""Tests for the workspace↔S3 reconcile endpoint.

The closed-loop publish stage auto-uploads, but an upload can still silently
fail (network / race). This endpoint surfaces workspaces that have synthesized
audio yet are absent from the S3 catalog — the forward-looking drift net.

Run:
    cd lab/podcast && uv run --with fastapi --with 'uvicorn[standard]' \
        --with python-multipart --with httpx --with pytest \
        pytest monitor/test_reconcile.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

import server  # noqa: E402


def _ws_with_audio(root: Path, name: str) -> Path:
    ws = root / name
    (ws / "scripts").mkdir(parents=True)
    (ws / "scripts" / "ep_1_pro.mp3").write_bytes(b"\x00")
    return ws


def _ws_without_audio(root: Path, name: str) -> Path:
    ws = root / name
    (ws / "scripts").mkdir(parents=True)
    (ws / "scripts" / "ep_1_script.md").write_text("x")  # script only, no audio
    return ws


# --- pure helper -----------------------------------------------------------

def test_reconcile_flags_synthesized_not_published(tmp_path):
    _ws_with_audio(tmp_path, "flow_x")
    drifted = server.reconcile_workspaces(tmp_path, published_ids={"other"})
    assert len(drifted) == 1
    assert drifted[0]["workspace"] == "flow_x"
    assert drifted[0]["reason"] == "synthesized_not_published"


def test_reconcile_ignores_published(tmp_path):
    _ws_with_audio(tmp_path, "flow_x")
    drifted = server.reconcile_workspaces(tmp_path, published_ids={"flow_x"})
    assert drifted == []


def test_reconcile_ignores_workspaces_without_audio(tmp_path):
    _ws_without_audio(tmp_path, "draft_only")
    drifted = server.reconcile_workspaces(tmp_path, published_ids=set())
    assert drifted == []


def test_reconcile_ignores_intermediate_audio_not_staged_by_upload(tmp_path):
    """A workspace with only intermediate audio (ep_1_raw.mp3 — NOT
    ep_*_{pro,flash}) must not be flagged: upload.sh would stage nothing, so
    flagging it strands it as permanently drifted."""
    ws = tmp_path / "raw_only"
    (ws / "scripts").mkdir(parents=True)
    (ws / "scripts" / "ep_1_raw.mp3").write_bytes(b"\x00")
    (ws / "scripts" / "ep_1_tts.m4a").write_bytes(b"\x00")
    drifted = server.reconcile_workspaces(tmp_path, published_ids=set())
    assert drifted == []


def test_reconcile_nonexistent_dir_returns_empty(tmp_path):
    assert server.reconcile_workspaces(tmp_path / "nope", published_ids=set()) == []


def test_reconcile_detects_m4a_audio(tmp_path):
    ws = tmp_path / "flow_m4a"
    (ws / "scripts").mkdir(parents=True)
    (ws / "scripts" / "ep_1_pro.m4a").write_bytes(b"\x00")
    drifted = server.reconcile_workspaces(tmp_path, published_ids=set())
    assert [d["workspace"] for d in drifted] == ["flow_m4a"]


# --- endpoint --------------------------------------------------------------

def test_reconcile_endpoint(monkeypatch, tmp_path):
    _ws_with_audio(tmp_path, "flow_x")
    _ws_with_audio(tmp_path, "flow_y")
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(
        server.remote_ops, "list_remote_series",
        lambda: [{"id": "flow_x", "title": "X"}],  # only flow_x published
    )
    resp = TestClient(server.app).get("/api/remote/reconcile")
    assert resp.status_code == 200
    body = resp.json()
    assert [d["workspace"] for d in body["drifted"]] == ["flow_y"]


def test_reconcile_endpoint_orphan_counts_as_published(monkeypatch, tmp_path):
    """An orphan entry (in bucket, not in index) means audio reached S3 →
    must NOT be flagged as drift."""
    _ws_with_audio(tmp_path, "flow_orphan")
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(
        server.remote_ops, "list_remote_series",
        lambda: [{"id": "flow_orphan", "orphan": True, "sizeBytes": 123}],
    )
    resp = TestClient(server.app).get("/api/remote/reconcile")
    assert resp.status_code == 200
    assert resp.json()["drifted"] == []


def test_reconcile_endpoint_propagates_remote_error(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)

    def _boom():
        raise server.remote_ops.RemoteError(1, "s3 down", ["list"])

    monkeypatch.setattr(server.remote_ops, "list_remote_series", _boom)
    resp = TestClient(server.app).get("/api/remote/reconcile")
    assert resp.status_code == 502
