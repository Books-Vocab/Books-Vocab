"""Tests for EmbeddingStore caching in service_factories and dirty-write deferral."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from kg.embeddings import EMBEDDING_DIM, EmbeddingStore
from kg.service_factories import (
    _get_cached,
    clear_store_cache,
    create_embedding_store,
    evict_notebook_cache,
)
from kg.tracked_llm import TrackedLLM


def _mock_llm(n: int = 1):
    """Return a mock LLM client whose embeddings.create returns n embeddings."""
    client = MagicMock()
    resp = MagicMock()
    resp.usage = MagicMock(prompt_tokens=10 * n, total_tokens=10 * n)
    resp.data = []
    for i in range(n):
        item = MagicMock()
        item.index = i
        item.embedding = np.random.rand(EMBEDDING_DIM).tolist()
        resp.data.append(item)
    client.embeddings.create.return_value = resp
    return client


def _make_tracked_llm(n: int = 1):
    client = _mock_llm(n)
    return TrackedLLM(client, "test_user"), client


# ---------------------------------------------------------------------------
# 1. create_embedding_store 快取行為
# ---------------------------------------------------------------------------


class TestEmbeddingStoreCache:
    def test_eviction_discards_inflight_store(self, tmp_path: Path):
        """Notebook eviction must not let a blocked builder repopulate cache."""
        import kg.service_factories as sf

        clear_store_cache()
        key = f"embedding:{tmp_path}:default:test-model:8"
        started = threading.Event()
        release = threading.Event()
        late_store = MagicMock(name="late_store")
        result: list[object] = []
        errors: list[BaseException] = []

        def factory():
            started.set()
            assert release.wait(timeout=5), "timed out waiting for builder release"
            return late_store

        def worker():
            try:
                result.append(_get_cached(key, factory))
            except BaseException as exc:  # pragma: no cover - diagnostic handoff
                errors.append(exc)

        thread = threading.Thread(target=worker)
        try:
            thread.start()
            assert started.wait(timeout=5), "builder did not start"

            evict_notebook_cache(tmp_path, "default")
            with sf._STORE_CACHE_LOCK:
                assert key not in sf._STORE_CACHE

            release.set()
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert errors == []
            assert result == [late_store]
            late_store.close.assert_called_once()
            with sf._STORE_CACHE_LOCK:
                assert key not in sf._STORE_CACHE
        finally:
            release.set()
            thread.join(timeout=5)
            clear_store_cache()

    def test_evict_notebook_removes_all_model_dim_variants_only(self, tmp_path: Path):
        """Eviction drops every model/dim entry for the notebook; neighbours stay."""
        import kg.service_factories as sf

        clear_store_cache()
        user_a, user_b = tmp_path / "a", tmp_path / "b"
        user_a.mkdir()
        user_b.mkdir()
        try:
            create_embedding_store(user_a, llm=None, notebook_id="X", model="m1", dim=8)
            create_embedding_store(user_a, llm=None, notebook_id="X", model="m2", dim=16)
            create_embedding_store(user_a, llm=None, notebook_id="Xa", model="m1", dim=8)
            create_embedding_store(user_b, llm=None, notebook_id="X", model="m1", dim=8)
            with sf._STORE_CACHE_LOCK:
                assert len(sf._STORE_CACHE) == 4
            closed: list[object] = []
            with patch.object(sf, "_close_store", closed.append):
                evict_notebook_cache(user_a, "X")
            with sf._STORE_CACHE_LOCK:
                after = set(sf._STORE_CACHE)
            assert after == {
                f"embedding:{user_a}:Xa:m1:8",
                f"embedding:{user_b}:X:m1:8",
            }
            assert len(closed) == 2
        finally:
            clear_store_cache()

    def test_same_user_dir_notebook_returns_same_instance(self, tmp_path: Path):
        """同一 user_dir + notebook_id 應回傳相同 instance（快取命中）。"""
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            store1 = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            store2 = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store1.store is store2.store, "Expected cached instance, got two different objects"
        finally:
            clear_store_cache()

    def test_different_notebook_id_returns_different_instance(self, tmp_path: Path):
        """不同 notebook_id 應產生不同 instance。"""
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            store1 = create_embedding_store(tmp_path, llm=llm, notebook_id="nb1")
            store2 = create_embedding_store(tmp_path, llm=llm, notebook_id="nb2")
            assert store1.store is not store2.store
        finally:
            clear_store_cache()

    def test_different_user_dir_returns_different_instance(self, tmp_path: Path):
        """不同 user_dir 應產生不同 instance。"""
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            dir_a = tmp_path / "user_a"
            dir_b = tmp_path / "user_b"
            dir_a.mkdir()
            dir_b.mkdir()
            store1 = create_embedding_store(dir_a, llm=llm, notebook_id="default")
            store2 = create_embedding_store(dir_b, llm=llm, notebook_id="default")
            assert store1.store is not store2.store
        finally:
            clear_store_cache()

    def test_npy_not_loaded_twice_on_cache_hit(self, tmp_path: Path):
        """快取命中時不應重新讀取 .npy 檔案（np.load 只應在 miss 時呼叫一次）。"""
        clear_store_cache()
        # Pre-create npy + ids so _load actually calls np.load
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        np.save(emb_path, np.random.rand(2, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))

        try:
            llm, _ = _make_tracked_llm()
            with patch("kg.embeddings.np.load", wraps=np.load) as mock_np_load:
                create_embedding_store(tmp_path, llm=llm, notebook_id="default")
                create_embedding_store(tmp_path, llm=llm, notebook_id="default")
                assert mock_np_load.call_count == 1, (
                    f"np.load called {mock_np_load.call_count} times; expected 1 (cache hit should skip reload)"
                )
        finally:
            clear_store_cache()


class TestEmbeddingStoreCallerBinding:
    """#2058: the cache shares vectors per notebook, never a caller's LLM.

    The cached store used to keep whichever ``llm`` its *first* caller passed.
    Callers bind different identities and quota policies to that llm (intake:
    ``reserve_quota=False`` under an outer reservation; pipeline:
    ``enforce_quota=True`` + per-call reservation; external delete:
    ``llm=None``), so every later caller silently ran under the first
    caller's policy — or crashed on ``None``.
    """

    @pytest.fixture
    def reservations(self, monkeypatch):
        import contextlib

        calls: list[dict] = []

        @contextlib.contextmanager
        def fake_reserve(user_id, estimated_usd, *, enforce=False, is_pro=False):
            calls.append({"user_id": user_id, "usd": estimated_usd, "enforce": enforce, "is_pro": is_pro})
            yield

        monkeypatch.setattr("kg.tracked_llm.reserve", fake_reserve)
        monkeypatch.setattr("kg.tracked_llm.record", lambda *a, **k: None)
        return calls

    def test_later_caller_quota_flags_are_not_frozen_by_cache(self, tmp_path: Path, reservations):
        clear_store_cache()
        try:
            intake_client = _mock_llm(1)
            pipeline_client = _mock_llm(1)
            # First caller: intake-style binding (no per-call reservation).
            create_embedding_store(
                tmp_path,
                llm=TrackedLLM(intake_client, "u1", reserve_quota=False),
                notebook_id="default",
            )
            # Second caller: pipeline-style binding (enforced, reserved, pro).
            pipeline_store = create_embedding_store(
                tmp_path,
                llm=TrackedLLM(pipeline_client, "u1", enforce_quota=True, is_pro=True),
                notebook_id="default",
            )
            pipeline_store.add("c1", "hello")

            pipeline_client.embeddings.create.assert_called_once()
            intake_client.embeddings.create.assert_not_called()
            assert len(reservations) == 1
            assert reservations[0]["enforce"] is True
            assert reservations[0]["is_pro"] is True
            assert reservations[0]["usd"] > 0
        finally:
            clear_store_cache()

    def test_llm_none_first_caller_does_not_break_later_embeds(self, tmp_path: Path, reservations):
        clear_store_cache()
        try:
            # External-API delete path binds llm=None (it only evicts vectors).
            create_embedding_store(tmp_path, llm=None, notebook_id="default").remove("missing")
            client = _mock_llm(1)
            store = create_embedding_store(tmp_path, llm=TrackedLLM(client, "u1"), notebook_id="default")
            store.add("c1", "hello")
            assert store.has("c1")
            client.embeddings.create.assert_called_once()
        finally:
            clear_store_cache()

    def test_update_uses_its_own_binding_llm(self, tmp_path: Path, reservations):
        """update() (not just add) embeds through the calling binding's llm."""
        clear_store_cache()
        try:
            client_a = _mock_llm(1)
            client_b = _mock_llm(1)
            writer = create_embedding_store(tmp_path, llm=TrackedLLM(client_a, "u1"), notebook_id="default")
            writer.add("c1", "hello")
            client_a.embeddings.create.reset_mock()
            before = writer.store._embeddings[0].copy()

            updater = create_embedding_store(
                tmp_path,
                llm=TrackedLLM(client_b, "u2", enforce_quota=True, is_pro=True),
                notebook_id="default",
            )
            updater.update("c1", "changed")

            client_b.embeddings.create.assert_called_once()
            client_a.embeddings.create.assert_not_called()
            assert not np.array_equal(writer.store._embeddings[0], before)
            assert reservations[-1]["is_pro"] is True
        finally:
            clear_store_cache()

    @pytest.mark.parametrize("op", ["add", "add_batch", "update_new", "update_existing"])
    def test_write_without_llm_raises_before_mutating_state(self, tmp_path: Path, reservations, op):
        """A llm=None binding that must embed fails loudly and leaves no trace."""
        clear_store_cache()
        try:
            seeded = create_embedding_store(tmp_path, llm=TrackedLLM(_mock_llm(1), "u1"), notebook_id="default")
            seeded.add("c1", "hello")
            seeded.flush()
            emb_path, ids_path = seeded.embeddings_path, seeded.ids_path
            emb_bytes, ids_bytes = emb_path.read_bytes(), ids_path.read_bytes()
            vectors_before = seeded.store._embeddings.copy()

            unbound = create_embedding_store(tmp_path, llm=None, notebook_id="default")
            with pytest.raises(RuntimeError, match="no LLM bound"):
                if op == "add":
                    unbound.add("c2", "new")
                elif op == "add_batch":
                    unbound.add_batch([("c2", "new"), ("c3", "newer")])
                elif op == "update_new":
                    unbound.update("c2", "new")
                else:
                    unbound.update("c1", "changed")

            assert unbound.count() == 1
            assert unbound.store._ids == ["c1"]
            assert not unbound.has("c2")
            np.testing.assert_array_equal(unbound.store._embeddings, vectors_before)
            assert emb_path.read_bytes() == emb_bytes
            assert ids_path.read_bytes() == ids_bytes
            assert len(reservations) == 1  # only the seeding call reserved quota
        finally:
            clear_store_cache()

    def test_write_without_llm_on_empty_store_writes_nothing(self, tmp_path: Path):
        clear_store_cache()
        try:
            unbound = create_embedding_store(tmp_path, llm=None, notebook_id="default")
            with pytest.raises(RuntimeError, match="no LLM bound"):
                unbound.add_batch([("c1", "x")])
            assert unbound.count() == 0
            assert unbound.store._embeddings is None
            assert not unbound.embeddings_path.exists()
            assert not unbound.ids_path.exists()
        finally:
            clear_store_cache()

    def test_unbound_binding_still_serves_reads_and_evictions(self, tmp_path: Path):
        clear_store_cache()
        try:
            seeded = create_embedding_store(tmp_path, llm=TrackedLLM(_mock_llm(1), "u1"), notebook_id="default")
            seeded.add("c1", "hello")
            unbound = create_embedding_store(tmp_path, llm=None, notebook_id="default")
            assert unbound.has("c1")
            assert unbound.remove("c1") is True
            assert unbound.count() == 0
        finally:
            clear_store_cache()

    def test_bindings_share_cached_vectors(self, tmp_path: Path, reservations):
        clear_store_cache()
        try:
            writer_client = _mock_llm(1)
            writer = create_embedding_store(tmp_path, llm=TrackedLLM(writer_client, "u1"), notebook_id="default")
            reader = create_embedding_store(tmp_path, llm=None, notebook_id="default")
            writer.add("c1", "hello")
            assert reader.has("c1")
            assert reader.count() == 1
            assert reader.remove("c1") is True
            assert not writer.has("c1")
        finally:
            clear_store_cache()


# ---------------------------------------------------------------------------
# 2. update() dirty-write 延遲：不應在 update 時立即重寫全矩陣
# ---------------------------------------------------------------------------


class TestUpdateDirtyWrite:
    def _make_store_with_data(self, tmp_path: Path):
        """建一個有 3 筆資料的 store，並重載以確保從磁碟讀取。"""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        n = 3
        np.save(emb_path, np.random.rand(n, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_text(json.dumps(["c1", "c2", "c3"]))

        client = _mock_llm(1)
        llm = TrackedLLM(client, "test_user")
        store = EmbeddingStore(emb_path, ids_path, llm)
        return store, client

    def test_update_does_not_call_save_immediately(self, tmp_path: Path):
        """update() 應只更新記憶體向量，不應立即呼叫 _save()。"""
        store, client = self._make_store_with_data(tmp_path)
        with patch.object(store, "_save") as mock_save:
            store.update("c1", "new text")
            mock_save.assert_not_called(), "update() should defer _save, not call it immediately"

    def test_update_marks_dirty(self, tmp_path: Path):
        """update() 後 store 應標記為 dirty。"""
        store, client = self._make_store_with_data(tmp_path)
        store.update("c1", "new text")
        assert store._dirty is True, "store should be marked dirty after update()"

    def test_flush_writes_to_disk(self, tmp_path: Path):
        """flush() 應寫入磁碟並清除 dirty 標記。"""
        store, client = self._make_store_with_data(tmp_path)
        store.update("c1", "new text")
        assert store._dirty is True

        with patch.object(store, "_save", wraps=store._save) as mock_save:
            store.flush()
            mock_save.assert_called_once()

        assert store._dirty is False, "dirty flag should be cleared after flush()"

    def test_flush_noop_when_not_dirty(self, tmp_path: Path):
        """若未 dirty，flush() 不應呼叫 _save()。"""
        store, _ = self._make_store_with_data(tmp_path)
        with patch.object(store, "_save") as mock_save:
            store.flush()
            mock_save.assert_not_called()

    def test_update_in_memory_immediately(self, tmp_path: Path):
        """update() 應立即更新記憶體中的向量（不等 flush）。"""
        store, client = self._make_store_with_data(tmp_path)
        old_vec = store._embeddings[0].copy()
        store.update("c1", "new text")
        new_vec = store._embeddings[0]
        # 向量應已在記憶體中更新
        assert not np.allclose(old_vec, new_vec), "embedding vector should be updated in memory after update()"

    def test_add_batch_still_saves_immediately(self, tmp_path: Path):
        """add_batch() 新增 embedding 仍應立即持久化（行為不變）。"""
        store, client = self._make_store_with_data(tmp_path)
        # reset client to return 1 new embedding
        resp = MagicMock()
        resp.usage = MagicMock(prompt_tokens=10, total_tokens=10)
        item = MagicMock()
        item.index = 0
        item.embedding = np.random.rand(EMBEDDING_DIM).tolist()
        resp.data = [item]
        client.embeddings.create.return_value = resp

        with patch.object(store, "_save", wraps=store._save) as mock_save:
            store.add_batch([("c_new", "hello")])
            mock_save.assert_called_once(), "add_batch should still save immediately"


# ---------------------------------------------------------------------------
# 3. settings wiring — model/dim must flow from KGSettings into EmbeddingStore
# ---------------------------------------------------------------------------


class TestEmbeddingSettingsWiring:
    def test_factory_reads_model_and_dim_from_settings(self, tmp_path: Path, monkeypatch):
        """Regression: factory previously never passed settings.embedding_model /
        settings.embedding_dim to EmbeddingStore. Env var was dead config."""
        clear_store_cache()
        monkeypatch.setenv("EMBEDDING_MODEL", "custom-test-model")
        monkeypatch.setenv("EMBEDDING_DIM", "768")
        try:
            llm, _ = _make_tracked_llm()
            store = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store.model == "custom-test-model"
            assert store.dim == 768
        finally:
            clear_store_cache()

    def test_explicit_args_override_settings(self, tmp_path: Path):
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            store = create_embedding_store(
                tmp_path,
                llm=llm,
                notebook_id="default",
                model="explicit-model",
                dim=512,
            )
            assert store.model == "explicit-model"
            assert store.dim == 512
        finally:
            clear_store_cache()

    def test_cache_key_distinguishes_model(self, tmp_path: Path):
        """Different model should return different cached instances."""
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            s1 = create_embedding_store(tmp_path, llm=llm, model="m1", dim=768)
            s2 = create_embedding_store(tmp_path, llm=llm, model="m2", dim=768)
            assert s1.store is not s2.store
        finally:
            clear_store_cache()


class TestEmbeddingModelDimSidecar:
    """Persisted sidecar (`embeddings_meta_{nb}.json`) must invalidate the
    on-disk vectors when the active model or dim no longer match. Without it
    the store loads stale vectors and crashes deep inside _embed() / vstack()
    on the next add."""

    def _seed_disk(self, tmp_path: Path, *, n: int, dim: int):
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        np.save(emb_path, np.random.rand(n, dim).astype(np.float32))
        ids_path.write_text(json.dumps([f"c{i}" for i in range(n)]))
        return emb_path, ids_path

    def test_legacy_disk_files_without_sidecar_are_adopted(self, tmp_path: Path):
        """Existing deployments have .npy + .json on disk but no sidecar yet.
        Loading must assume they match the current model/dim and write the
        sidecar in-place (one-shot migration)."""
        emb_path, ids_path = self._seed_disk(tmp_path, n=2, dim=768)
        sidecar = tmp_path / "embeddings_meta_default.json"
        assert not sidecar.exists()

        llm, _ = _make_tracked_llm()
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-current", dim=768)

        # Migration: sidecar should now exist, recording current model/dim,
        # and the original vectors should still be loaded.
        assert sidecar.exists(), "legacy load must write the sidecar in-place"
        meta = json.loads(sidecar.read_text())
        assert meta["model"] == "m-current"
        assert meta["dim"] == 768
        assert store.count() == 2
        assert store._embeddings.shape == (2, 768)

    def test_sidecar_match_loads_normally(self, tmp_path: Path):
        """Matching sidecar → vectors load, no rebuild."""
        emb_path, ids_path = self._seed_disk(tmp_path, n=3, dim=512)
        sidecar = tmp_path / "embeddings_meta_default.json"
        sidecar.write_text(json.dumps({"model": "m-x", "dim": 512}))

        llm, _ = _make_tracked_llm()
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-x", dim=512)
        assert store.count() == 3

    def test_dim_mismatch_invalidates_disk_files(self, tmp_path: Path):
        """Sidecar dim != active dim → quarantine stale files, start empty."""
        emb_path, ids_path = self._seed_disk(tmp_path, n=2, dim=768)
        sidecar = tmp_path / "embeddings_meta_default.json"
        sidecar.write_text(json.dumps({"model": "m-old", "dim": 768}))

        llm, _ = _make_tracked_llm()
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-new", dim=1024)

        assert store.count() == 0, "stale store must reset to empty"
        # Legacy files quarantined (renamed away) so a re-embed cycle
        # writes fresh data without colliding.
        legacy_emb = tmp_path / "embeddings_default.npy.legacy_m-old_768"
        legacy_ids = tmp_path / "card_ids_default.json.legacy_m-old_768"
        assert legacy_emb.exists(), "stale .npy must be quarantined, not deleted"
        assert legacy_ids.exists(), "stale ids must be quarantined, not deleted"
        # Sidecar now reflects active model/dim.
        meta = json.loads(sidecar.read_text())
        assert meta["model"] == "m-new"
        assert meta["dim"] == 1024

    def test_model_mismatch_invalidates_disk_files(self, tmp_path: Path):
        """Sidecar model != active model (same dim) → still invalidate."""
        emb_path, ids_path = self._seed_disk(tmp_path, n=1, dim=768)
        sidecar = tmp_path / "embeddings_meta_default.json"
        sidecar.write_text(json.dumps({"model": "m-A", "dim": 768}))

        llm, _ = _make_tracked_llm()
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-B", dim=768)
        assert store.count() == 0

    def test_after_invalidation_add_does_not_raise(self, tmp_path: Path):
        """Regression: previously, after model/dim swap the next add() blew
        up inside _embed when it tried to vstack vectors of different shapes
        (the old vectors were still loaded). After invalidation, add must
        proceed normally and write the new model/dim sidecar."""
        emb_path, ids_path = self._seed_disk(tmp_path, n=2, dim=512)
        (tmp_path / "embeddings_meta_default.json").write_text(json.dumps({"model": "m-old", "dim": 512}))

        client = MagicMock()
        resp = MagicMock()
        resp.usage = MagicMock(prompt_tokens=10, total_tokens=10)
        item = MagicMock()
        item.index = 0
        item.embedding = np.random.rand(1024).tolist()
        resp.data = [item]
        client.embeddings.create.return_value = resp
        llm = TrackedLLM(client, "test_user")

        store = EmbeddingStore(emb_path, ids_path, llm, model="m-new", dim=1024)
        # Must NOT raise — old (n,512) vectors must have been dropped.
        store.add("c_new", "hello")
        assert store.count() == 1
        assert store._embeddings.shape == (1, 1024)


class TestEmbeddingDimGuard:
    def test_dim_mismatch_raises_valueerror(self, tmp_path: Path):
        """If upstream returns wrong dim, fail loudly instead of later
        crashing in np.vstack / dot-product with a cryptic error."""
        client = MagicMock()
        resp = MagicMock()
        resp.usage = MagicMock(prompt_tokens=10, total_tokens=10)
        item = MagicMock()
        item.index = 0
        item.embedding = np.random.rand(1024).tolist()  # wrong dim
        resp.data = [item]
        client.embeddings.create.return_value = resp
        llm = TrackedLLM(client, "test_user")

        store = EmbeddingStore(
            embeddings_path=tmp_path / "emb.npy",
            ids_path=tmp_path / "ids.json",
            llm=llm,
            model="test-model",
            dim=3072,
        )
        with pytest.raises(ValueError, match="Embedding dim mismatch"):
            store.add("c1", "hello")
