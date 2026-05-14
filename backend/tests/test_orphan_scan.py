"""Tests for kg.orphan_scan — data consistency scanner."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-orphan"


# ---------------------------------------------------------------------------
# Test fixture — isolates global SQLite logs + users dir under tmp_path.
# Mirrors test_admin_observability.py's pattern.
# ---------------------------------------------------------------------------

def _swap_settings(new_settings):
    from kg.billing import default_subscription_payload
    from kg.user_store import CachedUserStore, normalize_users_payload

    app.state.kg_settings = new_settings

    def _normalize(users):
        from kg.secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, default_subscription_payload, encrypt_fn=encrypt_fn)

    user_store = CachedUserStore(new_settings.users_file, _normalize)
    app.state.user_store = user_store
    app.state.load_users = lambda: user_store.load()
    app.state.save_users = lambda users: user_store.save(users)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Build an isolated data_dir with one user, one notebook, one card."""
    data_dir = tmp_path
    (data_dir / "users").mkdir()

    monkeypatch.setenv("KG_DATA_DIR", str(data_dir))
    import kg.judge_log as jl
    import kg.token_tracker as tt
    import kg.translate_log as tl
    jl.DATA_DIR = data_dir
    jl.DB_PATH = data_dir / "judge_log.db"
    tt.DATA_DIR = data_dir
    tt.DB_PATH = data_dir / "token_usage.db"
    jl._reset()
    tl._reset()
    if hasattr(tt, "_reset"):
        tt._reset()
    elif tt._conn is not None:
        tt._conn.close()
        tt._conn = None

    uid = "u_real"
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({uid: {"config": {}}, "_meta": {}}))

    # Build per-user dir + notebooks.db + cards.db with a real notebook+card
    user_dir = data_dir / "users" / uid
    user_dir.mkdir(parents=True, exist_ok=True)

    from kg.cards import CardStore
    from kg.notebook import NotebookStore

    nbs = NotebookStore(user_dir / "notebooks.db")
    nbs.ensure_default()
    real_nb = nbs.create(name="kept", color=None)
    cards = CardStore(user_dir / "cards.db")
    real_card = cards.add(
        content="apple", pos="n.", meaning="蘋果",
        notebook_id=real_nb.id,
    )

    original_settings = app.state.kg_settings
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            data_dir=data_dir,
            user_id=uid,
            user_dir=user_dir,
            real_notebook_id=real_nb.id,
            real_card_id=real_card.id,
        )
    finally:
        app.state.kg_settings = original_settings
        jl._reset()
        tl._reset()
        if tt._conn is not None:
            tt._conn.close()
            tt._conn = None


# ---------------------------------------------------------------------------
# Scanner module — pure functions
# ---------------------------------------------------------------------------

def test_scan_clean_env_returns_zero_orphans(env):
    from kg.orphan_scan import scan

    report = scan(data_dir=env.data_dir)
    assert report["cards_orphan_notebook"]["count"] == 0
    assert report["graph_links_orphan_card"]["count"] == 0
    assert report["translate_log_orphan_user"]["count"] == 0
    assert report["judge_log_orphan_card"]["count"] == 0
    assert report["token_usage_orphan_user"]["count"] == 0
    assert report["total"] == 0


def test_scan_detects_card_pointing_to_missing_notebook(env):
    """Inject a card whose notebook_id has no row in notebooks.db."""
    from kg.cards import CardStore
    from kg.orphan_scan import scan

    cards = CardStore(env.user_dir / "cards.db")
    bogus = cards.add(
        content="orphan_word",
        pos="n.",
        meaning="x",
        notebook_id="nb_does_not_exist",
    )

    report = scan(data_dir=env.data_dir)
    items = report["cards_orphan_notebook"]["items"]
    assert report["cards_orphan_notebook"]["count"] == 1
    assert any(it["card_id"] == bogus.id for it in items)


def test_scan_detects_graph_link_with_missing_card(env):
    """Write graph_<nb>.json with a link whose to_id is unknown."""
    from kg.orphan_scan import scan

    link = {
        "id": "lk_orphan",
        "from_id": env.real_card_id,
        "to_id": "card_ghost",
        "kind": "shares_usage",
        "confidence": 0.9,
        "reason": "test",
        "created_at": "2024-01-01T00:00:00+00:00",
        "status": "active",
    }
    graph_path = env.user_dir / f"graph_{env.real_notebook_id}.json"
    graph_path.write_text(json.dumps([link]))

    report = scan(data_dir=env.data_dir)
    assert report["graph_links_orphan_card"]["count"] == 1
    item = report["graph_links_orphan_card"]["items"][0]
    assert item["link_id"] == "lk_orphan"
    assert item["missing"] == ["card_ghost"]


def test_scan_detects_translate_log_for_ghost_user(env):
    import kg.translate_log as tl
    from kg.orphan_scan import scan

    tl.record(
        user_id="ghost_user",
        operation="translate_quick",
        word="x", context="", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw="{}", latency_ms=1,
    )
    tl.record(
        user_id=env.user_id,  # real user — must NOT be flagged
        operation="translate_quick",
        word="y", context="", context_hash="h2",
        source_lang="en", target_lang="zh-Hant",
        response_raw="{}", latency_ms=1,
    )

    report = scan(data_dir=env.data_dir)
    m = report["translate_log_orphan_user"]
    assert m["count"] == 1
    assert m["items"][0]["user_id"] == "ghost_user"


def test_scan_detects_judge_log_with_ghost_card(env):
    import kg.judge_log as jl
    from kg.orphan_scan import scan

    jl.record(
        user_id=env.user_id,
        notebook_id=env.real_notebook_id,
        from_id=env.real_card_id,
        to_id="card_ghost",
        similarity=0.7,
        verdict="accept",
        confidence=0.9,
        accepted=True,
    )

    report = scan(data_dir=env.data_dir)
    assert report["judge_log_orphan_card"]["count"] == 1
    item = report["judge_log_orphan_card"]["items"][0]
    assert "card_ghost" in item["missing"]


def test_scan_detects_token_usage_for_ghost_user(env):
    import kg.token_tracker as tt
    from kg.orphan_scan import scan

    tt.record("ghost_user", "translate_quick", 1, 1)
    tt.record(env.user_id, "translate_quick", 1, 1)

    report = scan(data_dir=env.data_dir)
    m = report["token_usage_orphan_user"]
    assert m["count"] == 1
    assert m["items"][0]["user_id"] == "ghost_user"


# ---------------------------------------------------------------------------
# Fix — must require explicit confirm=True, dry_run gives counts only.
# ---------------------------------------------------------------------------

def test_fix_requires_explicit_confirm(env):
    """Calling fix() without confirm=True must raise."""
    from kg.orphan_scan import fix

    with pytest.raises(ValueError):
        fix(data_dir=env.data_dir)


def test_fix_dry_run_reports_but_does_not_mutate(env):
    import kg.translate_log as tl
    from kg.orphan_scan import fix, scan

    tl.record(
        user_id="ghost_user",
        operation="translate_quick",
        word="x", context="", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw="{}", latency_ms=1,
    )

    summary = fix(data_dir=env.data_dir, confirm=True, dry_run=True)
    assert summary["translate_log_orphan_user"]["would_delete"] == 1

    # Still present after dry-run.
    after = scan(data_dir=env.data_dir)
    assert after["translate_log_orphan_user"]["count"] == 1


def test_fix_confirm_true_actually_removes_orphans(env):
    """Inject orphans across all 5 categories; fix() should drop them all."""
    import kg.judge_log as jl
    import kg.token_tracker as tt
    import kg.translate_log as tl
    from kg.cards import CardStore
    from kg.orphan_scan import fix, scan

    # 1. orphan card→notebook
    cards = CardStore(env.user_dir / "cards.db")
    bogus_card = cards.add(content="o1", pos="n.", meaning="x", notebook_id="nb_missing")

    # 2. orphan graph_link
    graph_path = env.user_dir / f"graph_{env.real_notebook_id}.json"
    graph_path.write_text(json.dumps([{
        "id": "lk_orphan", "from_id": env.real_card_id, "to_id": "card_ghost",
        "kind": "shares_usage", "confidence": 0.9, "reason": "test",
        "created_at": "2024-01-01T00:00:00+00:00", "status": "active",
    }]))

    # 3. translate_log ghost user
    tl.record(user_id="ghost_user", operation="translate_quick", word="x", context="",
              context_hash="h", source_lang="en", target_lang="zh-Hant",
              response_raw="{}", latency_ms=1)

    # 4. judge_log ghost card
    jl.record(user_id=env.user_id, notebook_id=env.real_notebook_id,
              from_id=env.real_card_id, to_id="card_ghost", similarity=0.7,
              verdict="accept", confidence=0.9, accepted=True)

    # 5. token_usage ghost user
    tt.record("ghost_user", "translate_quick", 1, 1)

    before = scan(data_dir=env.data_dir)
    assert before["total"] == 5

    summary = fix(data_dir=env.data_dir, confirm=True, dry_run=False)
    assert summary["total_deleted"] == 5

    after = scan(data_dir=env.data_dir)
    assert after["total"] == 0

    # Soft-deleted card stays in db but is_deleted=1.
    with sqlite3.connect(str(env.user_dir / "cards.db")) as conn:
        row = conn.execute(
            "SELECT is_deleted FROM card WHERE id = ?", (bogus_card.id,)
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 1


# ---------------------------------------------------------------------------
# Admin endpoint — read-only, requires admin token.
# ---------------------------------------------------------------------------

def test_admin_orphans_endpoint_requires_auth(env):
    resp = env.client.get("/api/admin/orphans/scan")
    assert resp.status_code == 403


def test_admin_orphans_endpoint_returns_report(env):
    import kg.translate_log as tl
    tl.record(user_id="ghost_user", operation="translate_quick", word="x", context="",
              context_hash="h", source_lang="en", target_lang="zh-Hant",
              response_raw="{}", latency_ms=1)

    resp = env.client.get(
        "/api/admin/orphans/scan",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "translate_log_orphan_user" in body
    assert body["translate_log_orphan_user"]["count"] == 1
    assert body["total"] >= 1


# ---------------------------------------------------------------------------
# Regression — perf / concurrency hardening for review PR #436
# ---------------------------------------------------------------------------

def test_admin_orphans_endpoint_does_not_block_event_loop(env):
    """The endpoint must hand the sync scan off to a thread so concurrent
    requests overlap instead of serialising on the event loop."""
    import asyncio
    import time

    import httpx

    import kg.translate_log as tl

    # Inject enough orphans that scan does measurable real work.
    for i in range(5):
        tl.record(user_id=f"ghost_{i}", operation="translate_quick", word=str(i),
                  context="", context_hash=f"h{i}", source_lang="en",
                  target_lang="zh-Hant", response_raw="{}", latency_ms=1)

    transport = httpx.ASGITransport(app=app)

    async def hit():
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as client:
            r = await client.get(
                "/api/admin/orphans/scan",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            )
            assert r.status_code == 200
            return r.json()["total"]

    async def run_parallel():
        # 4 concurrent calls — if scan ran on the event loop they would
        # serialise; running via run_in_threadpool lets them overlap.
        return await asyncio.gather(hit(), hit(), hit(), hit())

    t0 = time.monotonic()
    totals = asyncio.run(asyncio.wait_for(run_parallel(), timeout=10.0))
    elapsed = time.monotonic() - t0

    assert all(t >= 5 for t in totals)
    # Generous bound — purely there to catch a regression where someone
    # removes run_in_threadpool and the endpoint goes back to blocking.
    assert elapsed < 10.0, f"endpoint serialised requests ({elapsed:.2f}s)"


def test_scan_judge_log_uses_cached_live_cards(env, monkeypatch):
    """``_live_cards`` should be invoked at most once per user — the old code
    re-scanned cards.db a second time to rebuild ``user_live_cards`` for the
    judge_log pass. Regression: keep it to one call."""
    import kg.judge_log as jl
    from kg import orphan_scan

    jl.record(user_id=env.user_id, notebook_id=env.real_notebook_id,
              from_id=env.real_card_id, to_id="card_ghost", similarity=0.7,
              verdict="accept", confidence=0.9, accepted=True)

    call_count = {"n": 0}
    real_live = orphan_scan._live_cards
    real_all = orphan_scan._all_cards_with_state

    def counting_live(db):
        call_count["n"] += 1
        return real_live(db)

    def counting_all(db):
        call_count["n"] += 1
        return real_all(db)

    monkeypatch.setattr(orphan_scan, "_live_cards", counting_live)
    monkeypatch.setattr(orphan_scan, "_all_cards_with_state", counting_all)

    report = orphan_scan.scan(data_dir=env.data_dir)

    # One user → at most one cards.db read (via _all_cards_with_state); the
    # judge_log pass must reuse the cached set, never call _live_cards again.
    assert call_count["n"] <= 1, f"cards.db scanned {call_count['n']} times"
    # Functional regression check — result unaffected by the refactor.
    assert report["judge_log_orphan_card"]["count"] == 1


def test_fix_aborts_when_graph_file_mutated_mid_run(env, monkeypatch):
    """If a concurrent writer rewrites graph_*.json between mtime snapshot and
    rewrite, fix() must raise OrphanFixAborted rather than clobber the file."""
    from kg.orphan_scan import OrphanFixAborted, fix

    # Set up an orphan link so fix() reaches the graph-rewrite branch.
    graph_path = env.user_dir / f"graph_{env.real_notebook_id}.json"
    graph_path.write_text(json.dumps([{
        "id": "lk_orphan", "from_id": env.real_card_id, "to_id": "card_ghost",
        "kind": "shares_usage", "confidence": 0.9, "reason": "test",
        "created_at": "2024-01-01T00:00:00+00:00", "status": "active",
    }]))

    # Patch Path.stat so the second observation of ``graph_path`` (the in-loop
    # comparison) reports a different mtime, mimicking a concurrent writer
    # touching the file between snapshot and rewrite.
    real_stat = Path.stat
    stat_calls = {"n": 0}

    def drift_stat(self, *a, **kw):
        result = real_stat(self, *a, **kw)
        if self == graph_path:
            stat_calls["n"] += 1
            if stat_calls["n"] >= 2:
                class _FakeStat:
                    def __init__(self, base, bumped_ns):
                        self._base = base
                        self.st_mtime_ns = bumped_ns

                    def __getattr__(self, name):
                        return getattr(self._base, name)

                return _FakeStat(result, result.st_mtime_ns + 1)
        return result

    monkeypatch.setattr(Path, "stat", drift_stat)

    with pytest.raises(OrphanFixAborted):
        fix(data_dir=env.data_dir, confirm=True, dry_run=False)
