"""Tests for EmbeddingStore caching in service_factories and dirty-write deferral."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from kg.embeddings import EMBEDDING_DIM, EmbeddingStore
from kg.service_factories import clear_store_cache, create_embedding_store
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
    def test_same_user_dir_notebook_returns_same_instance(self, tmp_path: Path):
        """同一 user_dir + notebook_id 應回傳相同 instance（快取命中）。"""
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            store1 = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            store2 = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store1 is store2, "Expected cached instance, got two different objects"
        finally:
            clear_store_cache()

    def test_different_notebook_id_returns_different_instance(self, tmp_path: Path):
        """不同 notebook_id 應產生不同 instance。"""
        clear_store_cache()
        try:
            llm, _ = _make_tracked_llm()
            store1 = create_embedding_store(tmp_path, llm=llm, notebook_id="nb1")
            store2 = create_embedding_store(tmp_path, llm=llm, notebook_id="nb2")
            assert store1 is not store2
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
            assert store1 is not store2
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
                tmp_path, llm=llm, notebook_id="default",
                model="explicit-model", dim=512,
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
            assert s1 is not s2
        finally:
            clear_store_cache()
