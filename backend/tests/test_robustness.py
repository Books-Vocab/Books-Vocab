"""
Robustness integration tests for Batch A-D changes.

Design constraints:
- SQLModel Card(table=True) is a singleton per process. Modules MUST NOT be reloaded.
- All data I/O uses tmp_path (isolated per test).
- External APIs (Gemini) are mocked.
- FastAPI TestClient runs ASGI in-process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch


def _future_iso(days: int = 30) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=days)).isoformat()

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_JWT_SECRET, TEST_PRO_PRODUCT_ID, _swap_settings, make_jwt

# ---------------------------------------------------------------------------
# Import kg modules ONCE. SQLModel's MetaData is a process singleton;
# reimporting causes "Table 'card' already defined" errors.
# ---------------------------------------------------------------------------
os.environ["KG_DATA_DIR"] = "/tmp/kg_test_default"
os.environ["JWT_SECRET"] = "test-secret-key-for-ci-at-least-32-bytes"
os.environ["GEMINI_API_KEY"] = "fake-key"


import kg.api as api_mod
import kg.deps as deps_mod
import kg.embeddings as emb_mod
import kg.judge as judge_mod
from kg.api import app  # noqa: E402 — must come after env setup
from kg.settings import KGSettings

# ---------------------------------------------------------------------------
# Fixture: per-test isolated data directory
# ---------------------------------------------------------------------------

@pytest.fixture()
def user_env(tmp_path):
    """
    Swap app.state.kg_settings to point at tmp_path.
    Returns (client, user_id, auth_headers, tmp_path).
    """
    (tmp_path / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:6]
    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    users_file = tmp_path / "users.json"
    tmp_path / "users.json.lock"
    tmp_path / "app_store_notifications.ndjson"
    users_file.write_text(json.dumps({
        user_id: {
            "config": {},
            "subscription": {
                "is_active": True,
                "status": "active",
                "plan_name": "Books & Vocab Pro",
                "trial_days": 7,
                "will_renew": True,
            },
        }
    }))

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield client, user_id, headers, tmp_path
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


# ============================================================================
# BATCH A-1 — users.json FileLock
# ============================================================================


class TestBatchA_UsersJsonLock:

    def test_sequential_config_update_persists(self, user_env):
        """PUT /api/user/config should write and return the updated config."""
        client, user_id, headers, data_dir = user_env

        r = client.put("/api/user/config",
                       json={"translation": {"source_lang": "en", "target_lang": "zh-Hant"}},
                       headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["translation"]["source_lang"] == "en"
        assert body["translation"]["target_lang"] == "zh-Hant"

    def test_concurrent_writes_no_json_corruption(self, user_env):
        """10 concurrent PUT /api/user/config must not corrupt users.json."""
        client, user_id, headers, data_dir = user_env

        errors, statuses = [], []

        def do_put(i):
            try:
                r = client.put("/api/user/config",
                               json={"translation": {"source_lang": "en", "target_lang": "zh-Hant"}},
                               headers=headers)
                statuses.append(r.status_code)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=do_put, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert all(s == 200 for s in statuses), f"Non-200: {statuses}"

        # File must be valid JSON
        try:
            data = json.loads((data_dir / "users.json").read_text())
        except json.JSONDecodeError as e:
            pytest.fail(f"users.json corrupted: {e}")

        assert user_id in data

    def test_get_config_returns_current_value(self, user_env):
        """GET /api/user/config should reflect what was PUT."""
        client, user_id, headers, data_dir = user_env

        client.put("/api/user/config", json={"translation": {"source_lang": "en", "target_lang": "ja"}}, headers=headers)
        r = client.get("/api/user/config", headers=headers)
        assert r.status_code == 200
        assert r.json()["translation"]["target_lang"] == "ja"

    def test_get_entitlements_returns_default_subscription_snapshot(self, user_env):
        """GET /api/user/entitlements should return a stable default snapshot."""
        client, user_id, headers, data_dir = user_env

        users_data = json.loads((data_dir / "users.json").read_text())
        users_data[user_id].pop("subscription", None)
        (data_dir / "users.json").write_text(json.dumps(users_data))

        r = client.get("/api/user/entitlements", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pro"]["is_active"] is False
        assert body["pro"]["status"] == "inactive"
        assert body["pro"]["trial_days"] == 7

    def test_billing_sync_persists_subscription_snapshot(self, user_env):
        client, user_id, headers, data_dir = user_env

        r = client.post(
            "/api/billing/app-store/sync",
            json={
                "product_id": TEST_PRO_PRODUCT_ID,
                "transaction_id": "tx-1",
                "original_transaction_id": "otx-1",
                "environment": "production",
                "status": "trial",
                "is_trial": True,
                "expires_at": _future_iso(7),
                "will_renew": True,
                "price_display": "$1.00/month",
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()["pro"]
        assert body["is_active"] is True
        assert body["status"] == "trial"
        assert body["price_display"] == "$1.00/month"

        saved = json.loads((data_dir / "users.json").read_text())
        assert saved[user_id]["subscription"]["transaction_id"] == "tx-1"
        assert saved["_subscription_index"]["otx-1"] == user_id

    def test_app_store_notification_updates_subscription_by_index(self, user_env):
        client, user_id, headers, data_dir = user_env

        client.post(
            "/api/billing/app-store/sync",
            json={
                "product_id": TEST_PRO_PRODUCT_ID,
                "transaction_id": "tx-1",
                "original_transaction_id": "otx-1",
                "environment": "sandbox",
                "status": "active",
                "is_trial": False,
                "expires_at": _future_iso(30),
                "will_renew": True,
                "price_display": "$1.00/month",
            },
            headers=headers,
        )

        r = client.post(
            "/api/billing/app-store/notifications",
            json={
                "notification_type": "EXPIRED",
                "product_id": TEST_PRO_PRODUCT_ID,
                "transaction_id": "tx-2",
                "original_transaction_id": "otx-1",
                "environment": "production",
                "expires_at": _future_iso(37),
                "will_renew": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] is True
        assert body["user_id"] == user_id
        assert body["entitlements"]["pro"]["status"] == "expired"

        saved = json.loads((data_dir / "users.json").read_text())
        assert saved[user_id]["subscription"]["status"] == "expired"


# ============================================================================
# BATCH A-1b — account deletion
# ============================================================================

class TestBatchA_AccountDeletion:

    def test_delete_account_removes_user_record_and_directory(self, user_env):
        client, user_id, headers, data_dir = user_env

        user_dir = data_dir / "users" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "cards.db").write_text("dummy")

        r = client.delete("/api/user/account", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted_user_id"] == user_id
        assert user_id in body["deleted_dirs"]

        users_data = json.loads((data_dir / "users.json").read_text())
        assert user_id not in users_data
        assert user_id in users_data.get("_revoked_before", {})
        assert not user_dir.exists()

    def test_deleted_account_token_is_rejected(self, user_env):
        client, user_id, headers, data_dir = user_env

        r = client.delete("/api/user/account", headers=headers)
        assert r.status_code == 200, r.text

        r2 = client.get("/api/health", headers=headers)
        assert r2.status_code == 401, r2.text
        assert "deleted" in r2.text.lower()

    def test_delete_linked_account_removes_canonical_and_indexes(self, user_env):
        client, user_id, headers, data_dir = user_env
        canonical = "canonical_user"
        linked = "linked_user"
        linked_headers = {"Authorization": f"Bearer {make_jwt(linked)}"}

        users_data = {
            canonical: {
                "email": "x@example.com",
                "linked_ids": [linked],
                "config": {},
            },
            linked: {"_linked_to": canonical},
            "_email_index": {"x@example.com": canonical},
        }
        (data_dir / "users.json").write_text(json.dumps(users_data))

        (data_dir / "users" / canonical).mkdir(parents=True, exist_ok=True)
        (data_dir / "users" / linked).mkdir(parents=True, exist_ok=True)

        r = client.delete("/api/user/account", headers=linked_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted_user_id"] == canonical
        assert linked in body["linked_ids"]

        data_after = json.loads((data_dir / "users.json").read_text())
        assert canonical not in data_after
        assert linked not in data_after
        assert "_email_index" not in data_after
        assert canonical in data_after.get("_revoked_before", {})
        assert linked in data_after.get("_revoked_before", {})
        assert not (data_dir / "users" / canonical).exists()
        assert not (data_dir / "users" / linked).exists()


# ============================================================================
# BATCH A-2 — No print() in pipeline modules (AST check)
# ============================================================================

class TestBatchA_NoPrintInModules:

    def _find_print_calls(self, mod) -> list[int]:
        import ast
        import inspect
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        return [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]

    def test_api_module(self):
        lines = self._find_print_calls(api_mod)
        assert not lines, f"api.py still has print() at lines: {lines}"

    def test_judge_module(self):
        lines = self._find_print_calls(judge_mod)
        assert not lines, f"judge.py still has print() at lines: {lines}"

    def test_embeddings_module(self):
        lines = self._find_print_calls(emb_mod)
        assert not lines, f"embeddings.py still has print() at lines: {lines}"

    def test_pipeline_step_failure_emits_error_log(self, user_env, caplog):
        """A failing pipeline step must emit >=1 ERROR log record."""
        client, user_id, headers, data_dir = user_env

        # Force client_factory() to blow up inside pipeline steps
        import kg.routers.pipeline as pipeline_router_mod
        with patch.object(pipeline_router_mod, "create_client", side_effect=Exception("API down")):
            with caplog.at_level(logging.ERROR, logger="kg.api"):
                r = client.post("/api/pipeline", headers=headers)
                assert r.status_code == 200  # always returns "queued"
                time.sleep(0.8)  # let background task finish

        error_lines = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_lines, (
            "Expected >=1 ERROR log from failing pipeline step.\n"
            f"All records: {[(r.levelno, r.message) for r in caplog.records]}"
        )


# ============================================================================
# BATCH C-1 — CardStore.count() uses SQL COUNT(*)
# ============================================================================

class TestBatchC_CardStoreCount:

    def test_count_empty(self, tmp_path):
        from kg.cards import CardStore
        assert CardStore(tmp_path / "cards.db").count() == 0

    def test_count_correct(self, tmp_path):
        from kg.cards import CardStore
        s = CardStore(tmp_path / "cards.db")
        s.add("apple", "蘋果")
        s.add("banana", "香蕉")
        assert s.count() == 2

    def test_count_excludes_soft_deleted(self, tmp_path):
        from kg.cards import CardStore
        s = CardStore(tmp_path / "cards.db")
        c = s.add("apple", "蘋果")
        s.add("banana", "香蕉")
        s.delete(c.id)
        assert s.count() == 1

    def test_count_does_not_load_rows_into_memory(self, tmp_path):
        """count() must use COUNT(*), not len(all()). Verify by patching session.exec
        to detect whether full rows are fetched."""
        from sqlmodel import Session

        from kg.cards import CardStore

        s = CardStore(tmp_path / "cards.db")
        s.add("w1", "m1")
        s.add("w2", "m2")

        original_exec = Session.exec

        def spy_exec(self, statement, *args, **kwargs):
            result = original_exec(self, statement, *args, **kwargs)
            # If count() is implemented with COUNT(*), the result will be a scalar,
            # not a list of Card objects. We capture whether .all() is called.
            return result

        # Simpler: patch the scalar method and verify it's called
        from sqlmodel import Session as SM
        original_scalar = SM.scalar

        scalar_called = []

        def patched_scalar(self, statement, *args, **kwargs):
            scalar_called.append(True)
            return original_scalar(self, statement, *args, **kwargs)

        with patch.object(SM, "scalar", patched_scalar):
            count = s.count()

        assert count == 2
        assert scalar_called, "count() must call session.scalar() (COUNT(*)), not exec().all()"


# ============================================================================
# BATCH C-2 — Pipeline embedding backfill
# ============================================================================

class TestBatchC_EmbeddingBackfill:

    def test_backfill_detects_cards_without_embedding(self, tmp_path):
        """Cards added to DB but with no embedding must be found by backfill logic."""
        from kg.cards import CardStore
        from kg.embeddings import EmbeddingStore

        store = CardStore(tmp_path / "cards.db")
        card = store.add("orphan", "孤立")

        # _embed() calls self.llm.embed(...), not .embeddings.create. dim must
        # match the store's configured dim or the guard will raise.
        mock_client = MagicMock()
        mock_client.embed.return_value = MagicMock(
            data=[MagicMock(index=0, embedding=[0.1] * 768)]
        )
        emb = EmbeddingStore(
            tmp_path / "embeddings.npy",
            tmp_path / "card_ids.json",
            mock_client,
            dim=768,
        )

        missing = [c for c in store.all() if not emb.has(c.id)]
        assert len(missing) == 1 and missing[0].id == card.id
        assert not mock_client.embed.called, "Detect-only path must not invoke the embedding API"

    def test_backfill_adds_embedding(self, tmp_path):
        """After running backfill logic, card should have embedding."""
        from kg.cards import CardStore
        from kg.embeddings import EmbeddingStore

        store = CardStore(tmp_path / "cards.db")
        card = store.add("orphan", "孤立")

        mock_client = MagicMock()
        mock_client.embed.return_value = MagicMock(
            data=[MagicMock(index=0, embedding=[0.1] * 768)]
        )
        emb = EmbeddingStore(
            tmp_path / "embeddings.npy",
            tmp_path / "card_ids.json",
            mock_client,
            dim=768,
        )

        for c in store.all():
            if not emb.has(c.id):
                emb.add(c.id, c.embed_text())

        assert emb.has(card.id), "Embedding must exist after backfill"
        assert mock_client.embed.called, "Backfill must actually invoke the embedding API"

    def test_backfill_skips_cards_with_existing_embedding(self, tmp_path):
        """Cards that already have embeddings must not be re-embedded."""
        from kg.cards import CardStore
        from kg.embeddings import EmbeddingStore

        store = CardStore(tmp_path / "cards.db")
        card = store.add("known", "已知")

        call_count = {"n": 0}
        mock_client = MagicMock()

        def counting_embed(*args, **kwargs):
            call_count["n"] += 1
            texts = kwargs.get("input", [])
            return MagicMock(
                data=[MagicMock(index=i, embedding=[0.2] * 768) for i in range(len(texts))]
            )

        mock_client.embed.side_effect = counting_embed

        emb = EmbeddingStore(
            tmp_path / "embeddings.npy",
            tmp_path / "card_ids.json",
            mock_client,
            dim=768,
        )

        # First add
        emb.add(card.id, card.embed_text())
        first_count = call_count["n"]
        assert first_count == 1, "First add must call embedding API exactly once"

        # Backfill — should skip this card
        for c in store.all():
            if not emb.has(c.id):
                emb.add(c.id, c.embed_text())

        assert call_count["n"] == first_count, \
            "Backfill called embedding API again for card that already had embedding"


# ============================================================================
# BATCH D — async get_user_lock atomicity
# ============================================================================

class TestBatchD_UserLockAtomic:

    def test_get_user_lock_is_async(self):
        assert asyncio.iscoroutinefunction(api_mod.get_user_lock)

    def test_same_user_returns_same_lock_object(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            deps_mod._USER_LOCKS_MUTEX = None
            l1 = await api_mod.get_user_lock("alice")
            l2 = await api_mod.get_user_lock("alice")
            return l1 is l2

        assert asyncio.run(run())

    def test_different_users_return_different_locks(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            deps_mod._USER_LOCKS_MUTEX = None
            la = await api_mod.get_user_lock("alice")
            lb = await api_mod.get_user_lock("bob")
            return la is not lb

        assert asyncio.run(run())

    def test_concurrent_creation_no_duplicate_lock(self):
        """50 concurrent coroutines requesting the same user's lock must
        all receive the exact same Lock object (no race-created duplicates)."""
        async def run():
            api_mod._USER_LOCKS.clear()
            deps_mod._USER_LOCKS_MUTEX = None
            locks = await asyncio.gather(*[
                api_mod.get_user_lock("race_user") for _ in range(50)
            ])
            return len({id(lk) for lk in locks})

        unique = asyncio.run(run())
        assert unique == 1, f"Race condition: {unique} distinct Lock objects created"

    # NOTE: The old `test_pipeline_skips_if_lock_held` test pinned a bug in
    # place. After the 2026-04-11 incident fix (`pipeline_service.py` no
    # longer `if lock.locked(): return`), this integration-level test cannot
    # be rewritten via `FastAPI TestClient` because:
    #
    #   1. `TestClient` awaits `BackgroundTasks` before returning from
    #      `client.post(...)`.
    #   2. With the fix, the background task blocks on the user lock while
    #      we hold it — deadlock: POST waits for task, task waits for lock,
    #      test holds lock.
    #   3. `asyncio.Lock.release()` from a second thread does not actually
    #      wake waiters because the lock's state belongs to the event loop
    #      that acquired it (already closed in `asyncio.run(grab_lock())`).
    #
    # The behavior is correctly covered by unit tests that run everything
    # inside one event loop via `asyncio.gather` — see
    # `test_pipeline_service.py::test_pipeline_service_waits_when_lock_is_held`
    # and `::test_pipeline_service_concurrent_triggers_different_notebooks_all_run`.


# ============================================================================
# BATCH E — Vocab concurrent write integrity
# ============================================================================

class TestBatchE_VocabConcurrentWrite:

    def test_concurrent_cardstore_no_data_loss(self, tmp_path):
        """10 concurrent CardStore.add() threads must not lose any write (SQLite WAL safety).

        Uses a shared engine (single CardStore instance) so threads share the SQLAlchemy
        connection pool — each add() creates its own Session, which is the thread-safe pattern.
        """
        from kg.cards import CardStore

        store = CardStore(tmp_path / "cards.db")
        words = [f"word{i:02d}" for i in range(10)]
        errors = []

        def add_word(word):
            try:
                store.add(word, f"詞{word}")
            except Exception as e:
                errors.append(f"{word}: {e}")

        threads = [threading.Thread(target=add_word, args=(w,)) for w in words]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Write errors: {errors}"
        found = {c.content for c in store.all()}
        assert found == set(words), f"Missing words: {set(words) - found}"
