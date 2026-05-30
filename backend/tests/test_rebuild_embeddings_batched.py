"""rebuild_embeddings must batch the embedding API call per chunk, not per card.

Regression guard for the O(N) API-call + O(N) full-file-save pattern: the old
loop called `emb.add(id, text)` once per card, and each `add` did one API round
trip + one full embeddings.npy rewrite. The batched path collapses a whole chunk
into a single `add_batch` (one API call, one save)."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rebuild_embeddings import rebuild_user_embeddings  # noqa: E402


class _FakeCard:
    def __init__(self, cid: str) -> None:
        self.id = cid

    def embed_text(self) -> str:
        return f"text-{self.id}"


class _RecordingEmb:
    """Stand-in for EmbeddingStore that records how it was driven."""

    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str]]] = []
        self.per_card_calls = 0

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        self.batches.append(list(items))

    def add(self, card_id: str, text: str) -> None:  # must never be used
        self.per_card_calls += 1


def test_rebuild_uses_single_batch_under_chunk_size():
    emb = _RecordingEmb()
    cards = [_FakeCard(str(i)) for i in range(50)]

    n = rebuild_user_embeddings(emb, cards, chunk_size=100)

    assert n == 50
    assert emb.per_card_calls == 0, "must not fall back to per-card add()"
    assert len(emb.batches) == 1, "50 cards under one chunk = exactly one API call"
    assert [cid for cid, _ in emb.batches[0]] == [str(i) for i in range(50)]
    assert emb.batches[0][0] == ("0", "text-0")


def test_rebuild_chunks_large_card_sets():
    emb = _RecordingEmb()
    cards = [_FakeCard(str(i)) for i in range(250)]

    n = rebuild_user_embeddings(emb, cards, chunk_size=100)

    assert n == 250
    assert emb.per_card_calls == 0
    assert [len(b) for b in emb.batches] == [100, 100, 50]


def test_rebuild_empty_does_nothing():
    emb = _RecordingEmb()
    assert rebuild_user_embeddings(emb, [], chunk_size=100) == 0
    assert emb.batches == []
    assert emb.per_card_calls == 0
