"""HTTP-level smoke tests for admin user-activity + translate-history endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ADMIN_TOKEN, make_admin_client


@pytest.fixture()
def admin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.translate_log as tl

    def setup_logs(data_dir, mp):
        mp.setattr(pl, "DATA_DIR", data_dir, raising=True)
        mp.setattr(pl, "DB_PATH", data_dir / "pipeline_runs.db", raising=True)
        mp.setattr(jl, "DATA_DIR", data_dir, raising=True)
        mp.setattr(jl, "DB_PATH", data_dir / "judge_log.db", raising=True)
        tl._reset()
        pl._reset()
        jl._reset()

    def teardown_logs():
        tl._reset()
        pl._reset()
        jl._reset()

    yield from make_admin_client(
        tmp_path, monkeypatch, setup_logs=setup_logs, teardown_logs=teardown_logs
    )


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _seed_translate(user_id: str, *, word: str, op: str = "translate_quick") -> None:
    import kg.translate_log as tl

    tl.record(
        user_id=user_id, operation=op, word=word, context="",
        context_hash="h_" + word, source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"x"}', latency_ms=8,
    )


def test_translate_history_no_filter(admin_client):
    _seed_translate("u1", word="apple")
    _seed_translate("u1", word="banana")

    r = admin_client.client.get(
        "/api/admin/translate-history?user_id=u1",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert {row["word"] for row in body["history"]} == {"apple", "banana"}


def test_translate_history_q_filter(admin_client):
    _seed_translate("u1", word="apple")
    _seed_translate("u1", word="pineapple")
    _seed_translate("u1", word="banana")

    r = admin_client.client.get(
        "/api/admin/translate-history?user_id=u1&q=apple",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    words = {row["word"] for row in r.json()["history"]}
    assert words == {"apple", "pineapple"}


def test_translate_history_op_filter(admin_client):
    _seed_translate("u1", word="apple", op="translate_quick")
    _seed_translate("u1", word="banana", op="translate_explain")

    r = admin_client.client.get(
        "/api/admin/translate-history?user_id=u1&op=translate_explain",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["op"] == "translate_explain"
    assert [row["word"] for row in body["history"]] == ["banana"]


def test_translate_history_requires_admin(admin_client):
    r = admin_client.client.get("/api/admin/translate-history?user_id=u1")
    assert r.status_code in (401, 403)


def test_user_activity_empty(admin_client):
    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=24",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["hours"] == 24
    assert body["events"] == []
    assert body["counts"] == {"translate": 0, "pipeline": 0, "judge": 0}


def test_user_activity_returns_translate_event(admin_client):
    _seed_translate("u1", word="hello")
    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=24",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["translate"] == 1
    assert body["events"][0]["type"] == "translate"
    assert body["events"][0]["word"] == "hello"


def test_user_activity_requires_admin(admin_client):
    r = admin_client.client.get("/api/admin/user-activity?user_id=u1")
    assert r.status_code in (401, 403)


def test_user_activity_hours_clamped(admin_client):
    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=99999",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["hours"] == 168


def test_user_activity_isolates_user(admin_client):
    _seed_translate("u1", word="apple")
    _seed_translate("other", word="banana")

    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=24",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["word"] == "apple"
