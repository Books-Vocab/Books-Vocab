"""Edge tests for EmbeddingStore — dim mismatch, cache key, factory env wiring.

Complements:
  * test_embeddings.py — _load/_embed/update/find_similar branches
  * test_embedding_store_cache.py — factory caching + sidecar migration
  * test_embedding_batch.py — batch add path

Focuses on the remaining gaps:
  1. Stale on-disk vectors slip past the sidecar guard when the sidecar
     itself lies (corruption / hand-edited deployment); the dim mismatch
     must surface as a clear, actionable error at query/use time — not
     a cryptic numpy stack trace.
  2. The factory cache key must include BOTH model AND dim so that an
     env-driven dim change does not accidentally hand back a store
     pointing at the old vectors.
  3. The factory must re-read settings on each call (env-driven), so a
     redeploy with new EMBEDDING_MODEL / EMBEDDING_DIM picks up the new
     values once the cache is cleared.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from kg.embeddings import EmbeddingStore
from kg.service_factories import clear_store_cache, create_embedding_store
from kg.tracked_llm import TrackedLLM


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _mock_client_with_dim(dim: int, n: int = 1):
    """LLM client whose embed() returns n vectors of the given dim."""
    client = MagicMock()
    resp = MagicMock()
    resp.usage = MagicMock(prompt_tokens=10 * n, total_tokens=10 * n)
    resp.data = []
    for i in range(n):
        item = MagicMock()
        item.index = i
        item.embedding = np.random.rand(dim).astype(np.float32).tolist()
        resp.data.append(item)
    client.embeddings.create.return_value = resp
    return client


# --------------------------------------------------------------------- #
# 1. dim mismatch must raise a clear, diagnostic error
# --------------------------------------------------------------------- #
class TestEmbeddingDimMismatchClearError:
    """When the active EMBEDDING_DIM disagrees with what the upstream
    returns (or with what's already in the store), the error message must
    name the conflict — not crash inside numpy with a shape mismatch.
    """

    def test_embedding_dim_mismatch_raises_clear_error(self, tmp_path: Path):
        """Active dim=768 + upstream returns 1536-dim vector → ValueError
        whose message clearly diagnoses the dim mismatch."""
        client = _mock_client_with_dim(dim=1536)
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(
            embeddings_path=tmp_path / "embeddings_default.npy",
            ids_path=tmp_path / "card_ids_default.json",
            llm=llm,
            model="m-active",
            dim=768,
        )
        with pytest.raises(ValueError) as exc_info:
            store.add("c1", "hello")
        msg = str(exc_info.value)
        # Must name the active dim, the offending dim, and hint at the env var.
        assert "dim mismatch" in msg.lower(), f"error must mention dim mismatch, got: {msg!r}"
        assert "768" in msg, f"error must mention expected dim, got: {msg!r}"
        assert "1536" in msg, f"error must mention actual dim, got: {msg!r}"
        assert "EMBEDDING_DIM" in msg, f"error must hint at env var, got: {msg!r}"

    def test_sidecar_lies_about_dim_load_degrades_to_empty(self, tmp_path: Path):
        """A corrupted/hand-edited sidecar claims dim=768, matching the
        active config, but the .npy on disk is actually 1536-dim. ``_load``
        must NOT silently load the stale matrix (corrupts find_similar /
        cosine math) — but it must NOT raise either: a hard ``__init__``
        failure 500s every embedding request for the notebook. It degrades:
        quarantine the corrupt files, log, start empty."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        # Disk vectors are 1536-dim …
        np.save(emb_path, np.random.rand(2, 1536).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))
        # … but the sidecar (incorrectly) declares 768.
        meta_path.write_text(json.dumps({"model": "m-active", "dim": 768, "created_at": "x"}))

        client = _mock_client_with_dim(dim=768)
        llm = TrackedLLM(client, "u")
        # Construction triggers _load → must degrade, not raise.
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-active", dim=768)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()
        assert list(tmp_path.glob("*.corrupt_*"))

    def test_load_degrades_on_shape_mismatch(self, tmp_path: Path):
        """Front-loaded guard: when on-disk .npy shape disagrees with the
        active ``dim``, ``_load`` must degrade to an empty store (quarantine
        + re-embed) — without waiting for the next add_batch/vstack to expose
        corruption, and without raising and wedging the notebook."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        # Real disk shape is 1536, sidecar lies and says 768.
        np.save(emb_path, np.random.rand(3, 1536).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b", "c"]))
        meta_path.write_text(json.dumps({"model": "m-active", "dim": 768, "created_at": "x"}))

        client = _mock_client_with_dim(dim=768)
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-active", dim=768)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()
        assert list(tmp_path.glob("*.corrupt_*"))

    def test_load_degrades_on_shape_mismatch_legacy_no_sidecar(self, tmp_path: Path):
        """Legacy path (no sidecar) must also degrade on a shape mismatch
        before adopting the on-disk vectors as the active store."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        # No sidecar — legacy deployment.
        np.save(emb_path, np.random.rand(2, 1536).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))

        client = _mock_client_with_dim(dim=768)
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-active", dim=768)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_load_allows_empty_npy(self, tmp_path: Path):
        """An empty (0, dim) .npy must not trip the shape guard — the
        store is effectively unpopulated and any dim claim is moot
        until the first add."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        # 0 rows; the trailing dim is "wrong" on paper but harmless.
        np.save(emb_path, np.zeros((0, 1536), dtype=np.float32))
        ids_path.write_text(json.dumps([]))
        meta_path.write_text(json.dumps({"model": "m-active", "dim": 768, "created_at": "x"}))

        client = _mock_client_with_dim(dim=768)
        llm = TrackedLLM(client, "u")
        # A 0-row matrix is the legal empty store: load as-is, no quarantine.
        store = EmbeddingStore(emb_path, ids_path, llm, model="m-active", dim=768)
        assert store.count() == 0
        assert emb_path.exists() and ids_path.exists()


# --------------------------------------------------------------------- #
# 1b. empty / malformed upstream response must raise — not poison state
# --------------------------------------------------------------------- #
class TestEmbeddingEmptyResponseRaises:
    """When the upstream returns an empty ``response.data`` (provider hiccup,
    truncated batch, OpenAI-compat quirk), ``np.array([...])`` collapses to a
    1-D ``shape (0,)`` array that slips past the ``ndim >= 2`` dim guard.
    Returning it lets ``add_batch`` assign a 1-D matrix to ``_embeddings``,
    which later detonates cryptically inside ``np.vstack`` / ``find_similar`` /
    ``_get_norms``. ``_embed`` must reject it up front with a clear message and
    leave the store's state untouched (the id list extends *after* ``_embed``).
    """

    def test_empty_response_data_raises_clear_error(self, tmp_path: Path):
        """resp.data == [] → ValueError naming an empty/malformed response,
        NOT a silent 1-D array return."""
        client = _mock_client_with_dim(dim=768, n=0)  # resp.data == []
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(
            embeddings_path=tmp_path / "embeddings_default.npy",
            ids_path=tmp_path / "card_ids_default.json",
            llm=llm,
            model="m-active",
            dim=768,
        )
        with pytest.raises(ValueError) as exc_info:
            store.add("c1", "hello")
        msg = str(exc_info.value).lower()
        assert "empty" in msg or "malformed" in msg, (
            f"error must flag empty/malformed embedding response, got: {msg!r}"
        )

    def test_empty_response_leaves_state_clean(self, tmp_path: Path):
        """After the raise, the store stays pristine: no ids leaked into
        ``_ids``, ``_embeddings`` still ``None``, ``count() == 0``. A retry /
        next request must see a clean store, never a half-populated one."""
        client = _mock_client_with_dim(dim=768, n=0)
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(
            embeddings_path=tmp_path / "embeddings_default.npy",
            ids_path=tmp_path / "card_ids_default.json",
            llm=llm,
            model="m-active",
            dim=768,
        )
        with pytest.raises(ValueError):
            store.add("c1", "hello")
        assert store.count() == 0
        assert store._embeddings is None
        assert store._ids == []
        assert "c1" not in store._id_set


# --------------------------------------------------------------------- #
# 2. cache key must include BOTH model AND dim
# --------------------------------------------------------------------- #
class TestCacheKeyIncludesModelAndDim:
    def test_cache_key_includes_model(self, tmp_path: Path):
        """Same user + notebook + dim, different model → different instance."""
        clear_store_cache()
        try:
            client = _mock_client_with_dim(dim=768)
            llm = TrackedLLM(client, "u")
            s1 = create_embedding_store(tmp_path, llm=llm, model="m-A", dim=768)
            s2 = create_embedding_store(tmp_path, llm=llm, model="m-B", dim=768)
            assert s1 is not s2, "different model must yield different cached instance"
        finally:
            clear_store_cache()

    def test_cache_key_includes_dim(self, tmp_path: Path):
        """Same user + notebook + model, different dim → different instance.
        Regression: if cache key drops `dim`, a dim swap silently returns
        the stale-dim store."""
        clear_store_cache()
        try:
            client = _mock_client_with_dim(dim=768)
            llm = TrackedLLM(client, "u")
            s1 = create_embedding_store(tmp_path, llm=llm, model="m-X", dim=768)
            s2 = create_embedding_store(tmp_path, llm=llm, model="m-X", dim=1536)
            assert s1 is not s2, "different dim must yield different cached instance"
            assert s1.dim == 768 and s2.dim == 1536
        finally:
            clear_store_cache()

    def test_same_model_same_dim_returns_same_instance(self, tmp_path: Path):
        """Cache must still hit when nothing changed."""
        clear_store_cache()
        try:
            client = _mock_client_with_dim(dim=768)
            llm = TrackedLLM(client, "u")
            s1 = create_embedding_store(tmp_path, llm=llm, model="m-X", dim=768)
            s2 = create_embedding_store(tmp_path, llm=llm, model="m-X", dim=768)
            assert s1 is s2
        finally:
            clear_store_cache()


# --------------------------------------------------------------------- #
# 3. factory picks up env changes between (cache-cleared) calls
# --------------------------------------------------------------------- #
class TestFactoryPicksUpEnvChanges:
    def test_factory_picks_up_env_changes(self, tmp_path: Path, monkeypatch):
        """Simulate redeploy: EMBEDDING_MODEL=foo → build store, clear
        cache, EMBEDDING_MODEL=bar → next build must reflect bar (the
        cache key namespace shifts as well, so the old store is not
        accidentally surfaced)."""
        clear_store_cache()
        try:
            monkeypatch.setenv("EMBEDDING_MODEL", "foo")
            monkeypatch.setenv("EMBEDDING_DIM", "768")
            llm = TrackedLLM(_mock_client_with_dim(dim=768), "u")
            store_foo = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store_foo.model == "foo"
            assert store_foo.dim == 768

            # Simulate a redeploy: env var changes, cache is purged.
            clear_store_cache()
            monkeypatch.setenv("EMBEDDING_MODEL", "bar")
            store_bar = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store_bar.model == "bar", "factory must re-read EMBEDDING_MODEL"
            assert store_bar.dim == 768
            assert store_bar is not store_foo
        finally:
            clear_store_cache()

    def test_env_change_without_cache_clear_keeps_old_via_key(self, tmp_path: Path, monkeypatch):
        """If env changes but the cache is *not* cleared, the new call
        builds under a new key (model is part of the key) and therefore
        does NOT return the stale instance — this is the safety net that
        protects a half-finished deploy."""
        clear_store_cache()
        try:
            monkeypatch.setenv("EMBEDDING_MODEL", "foo")
            monkeypatch.setenv("EMBEDDING_DIM", "768")
            llm = TrackedLLM(_mock_client_with_dim(dim=768), "u")
            store_foo = create_embedding_store(tmp_path, llm=llm, notebook_id="default")

            # Env mutates without cache clear (worst-case: rolling reload).
            monkeypatch.setenv("EMBEDDING_MODEL", "bar")
            store_bar = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store_bar.model == "bar"
            assert store_bar is not store_foo, (
                "stale instance leak — cache key must namespace by model"
            )
        finally:
            clear_store_cache()

    def test_env_dim_change_namespaces_separately(self, tmp_path: Path, monkeypatch):
        """Dim swap mid-life: even without explicit clear, the new dim
        opens a fresh cache slot and never reuses the 768-dim store."""
        clear_store_cache()
        try:
            monkeypatch.setenv("EMBEDDING_MODEL", "m")
            monkeypatch.setenv("EMBEDDING_DIM", "768")
            llm = TrackedLLM(_mock_client_with_dim(dim=768), "u")
            store_768 = create_embedding_store(tmp_path, llm=llm, notebook_id="default")

            monkeypatch.setenv("EMBEDDING_DIM", "1536")
            store_1536 = create_embedding_store(tmp_path, llm=llm, notebook_id="default")
            assert store_768.dim == 768
            assert store_1536.dim == 1536
            assert store_768 is not store_1536
        finally:
            clear_store_cache()
