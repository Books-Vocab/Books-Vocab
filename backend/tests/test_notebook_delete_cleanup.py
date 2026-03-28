"""Tests for notebook deletion graph/embedding cleanup.

When a notebook is deleted, its cards are reassigned to 'default'.
The source notebook's graph links, candidates, and embeddings must be
merged into the default notebook — not abandoned as orphan files.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from kg.graph import GraphStore, LinkKind


# ---------------------------------------------------------------------------
# GraphStore.merge_from
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_pair(tmp_path):
    """Create source and target GraphStores in tmp_path."""
    src = GraphStore(
        tmp_path / "graph_src.json",
        tmp_path / "candidates_src.json",
    )
    tgt = GraphStore(
        tmp_path / "graph_default.json",
        tmp_path / "candidates_default.json",
    )
    return src, tgt


def test_merge_links_into_target(graph_pair):
    src, tgt = graph_pair
    # Add links in source
    src.add_link("c1", "c2", LinkKind.CONTRASTS_WITH, 0.9, "reason1")
    src.add_link("c3", "c4", LinkKind.SHARES_USAGE, 0.8, "reason2")

    assert src.link_count() == 2
    assert tgt.link_count() == 0

    tgt.merge_from(src)

    assert tgt.link_count() == 2
    assert len(tgt.get_links_for("c1")) == 1
    assert len(tgt.get_links_for("c3")) == 1


def test_merge_candidates_into_target(graph_pair):
    src, tgt = graph_pair
    src.add_candidate("c1", "c2", 0.95)
    src.add_candidate("c3", "c4", 0.85)

    assert src.candidate_count() == 2
    assert tgt.candidate_count() == 0

    tgt.merge_from(src)

    assert tgt.candidate_count() == 2


def test_merge_skips_duplicate_links(graph_pair):
    src, tgt = graph_pair
    # Same pair exists in both
    src.add_link("c1", "c2", LinkKind.CONTRASTS_WITH, 0.9, "from src")
    tgt.add_link("c1", "c2", LinkKind.CONTRASTS_WITH, 0.85, "from tgt")

    tgt.merge_from(src)

    # Should not duplicate — target already has the link
    assert tgt.link_count() == 1


def test_merge_clears_source(graph_pair):
    src, tgt = graph_pair
    src.add_link("c1", "c2", LinkKind.CONTRASTS_WITH, 0.9, "reason")
    src.add_candidate("c3", "c4", 0.8)

    tgt.merge_from(src)

    assert src.link_count() == 0
    assert src.candidate_count() == 0


# ---------------------------------------------------------------------------
# EmbeddingStore.merge_from
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_pair(tmp_path):
    """Create source and target EmbeddingStores with a dummy client."""
    from kg.embeddings import EmbeddingStore

    class FakeClient:
        class embeddings:
            @staticmethod
            def create(input, model):
                raise RuntimeError("Should not call API during merge")

    src = EmbeddingStore(
        tmp_path / "embeddings_src.npy",
        tmp_path / "card_ids_src.json",
        FakeClient(),
    )
    tgt = EmbeddingStore(
        tmp_path / "embeddings_default.npy",
        tmp_path / "card_ids_default.json",
        FakeClient(),
    )
    return src, tgt


def _inject_embeddings(store, card_ids: list[str], dim: int = 3072):
    """Directly inject embeddings without API call."""
    n = len(card_ids)
    store._embeddings = np.random.randn(n, dim).astype(np.float32)
    store._ids = list(card_ids)
    store._id_set = set(card_ids)
    store._invalidate_norms()
    store._save()


def test_merge_embeddings_into_target(embedding_pair):
    src, tgt = embedding_pair
    _inject_embeddings(src, ["c1", "c2"])
    _inject_embeddings(tgt, ["c3"])

    assert src.count() == 2
    assert tgt.count() == 1

    tgt.merge_from(src)

    assert tgt.count() == 3
    assert tgt.has("c1")
    assert tgt.has("c2")
    assert tgt.has("c3")


def test_merge_embeddings_skips_duplicates(embedding_pair):
    src, tgt = embedding_pair
    _inject_embeddings(src, ["c1", "c2"])
    _inject_embeddings(tgt, ["c2", "c3"])

    tgt.merge_from(src)

    # c2 already in target — should not duplicate
    assert tgt.count() == 3
    assert tgt.has("c1")


def test_merge_embeddings_clears_source(embedding_pair):
    src, tgt = embedding_pair
    _inject_embeddings(src, ["c1"])

    tgt.merge_from(src)

    assert src.count() == 0


def test_merge_embeddings_into_empty_target(embedding_pair):
    src, tgt = embedding_pair
    _inject_embeddings(src, ["c1", "c2"])

    assert tgt.count() == 0

    tgt.merge_from(src)

    assert tgt.count() == 2
    assert tgt.has("c1")
    assert tgt.has("c2")
