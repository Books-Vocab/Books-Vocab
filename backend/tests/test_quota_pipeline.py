"""Quota gating + notebook_id validation for pipeline / vocab routers.

P0-1: Pipeline trigger and vocab batch must enforce daily USD quota
      (previously only translate routes were guarded → users could burn
      LLM tokens via repeated pipeline triggers).
P1:   notebook_id Query parameter must be regex-validated (422) instead
      of falling through to handler with malformed input.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


# ── Helpers ────────────────────────────────────────────────────────


def _force_quota_exceeded(user_id: str) -> None:
    """Insert enough token usage for `user_id` to bust the pro daily limit."""
    import kg.token_tracker as tt

    # Pro limit is 0.30 USD; output @ 0.40/M → 1M output tokens = $0.40 (>limit).
    now = datetime.now(UTC).isoformat()
    with tt._lock:
        conn = tt._get_conn()
        conn.execute(
            "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, "translate_quick", 0, 1_000_000, now),
        )
        conn.commit()


@pytest.fixture()
def fresh_token_db(tmp_path, monkeypatch):
    """Force token_tracker to use a clean DB for this test (isolated from others)."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import importlib
    import kg.token_tracker as tt
    importlib.reload(tt)
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    yield tt
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    importlib.reload(tt)


# ── Quota gating ───────────────────────────────────────────────────


def test_pipeline_trigger_returns_429_when_quota_exceeded(isolated_api, fresh_token_db):
    _force_quota_exceeded(isolated_api.user_id)
    r = isolated_api.client.post("/api/pipeline", headers=isolated_api.headers)
    assert r.status_code == 429, r.text


def test_vocab_add_returns_429_when_quota_exceeded(isolated_api, fresh_token_db):
    _force_quota_exceeded(isolated_api.user_id)
    entries = [{"word": "evoke", "translation": "喚起"}]
    r = isolated_api.client.post("/api/vocab", json=entries, headers=isolated_api.headers)
    assert r.status_code == 429, r.text


# ── notebook_id regex validation ───────────────────────────────────


@pytest.mark.parametrize("bad_id", ["foo/bar", "../etc", "a" * 65, "has space", "x;y"])
def test_pipeline_rejects_malformed_notebook_id(isolated_api, bad_id):
    r = isolated_api.client.post(
        "/api/pipeline",
        params={"notebook_id": bad_id},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, f"Expected 422 for {bad_id!r}, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("bad_id", ["foo/bar", "../etc", "a" * 65, "has space"])
def test_vocab_add_rejects_malformed_notebook_id(isolated_api, bad_id):
    entries = [{"word": "evoke", "translation": "喚起"}]
    r = isolated_api.client.post(
        "/api/vocab",
        params={"notebook_id": bad_id},
        json=entries,
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, f"Expected 422 for {bad_id!r}, got {r.status_code}: {r.text}"


def test_vocab_get_rejects_malformed_notebook_id(isolated_api):
    r = isolated_api.client.get(
        "/api/vocab",
        params={"notebook_id": "foo/bar"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, r.text


def test_default_notebook_id_still_valid(isolated_api):
    """The default value 'default' must still pass the new regex."""
    r = isolated_api.client.get(
        "/api/vocab",
        params={"notebook_id": "default"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text


def test_alphanumeric_underscore_dash_notebook_id_valid(isolated_api):
    """Allowed chars: letters, digits, underscore, dash, up to 64 chars."""
    # Notebook does not need to exist for vocab GET (returns empty list).
    r = isolated_api.client.get(
        "/api/vocab",
        params={"notebook_id": "nb_2024-q1"},
        headers=isolated_api.headers,
    )
    # 200 (handler resolves) or 403 (notebook missing) both prove the regex passed;
    # 422 would mean the regex failed.
    assert r.status_code != 422, r.text
