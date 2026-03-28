"""Embedding storage and similarity search."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
from openai import OpenAI, OpenAIError

EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIM = 3072


class EmbeddingStore:
    """Numpy-based embedding storage with similarity search."""

    def __init__(self, embeddings_path: Path, ids_path: Path, client: OpenAI, user_id: str | None = None) -> None:
        self.embeddings_path = embeddings_path
        self.ids_path = ids_path
        self.client = client
        self.user_id = user_id
        self._embeddings: np.ndarray | None = None
        self._ids: list[str] = []
        self._id_set: set[str] = set()
        self._norms: np.ndarray | None = None  # cached L2 norms
        self._load()

    def _load(self) -> None:
        if self.embeddings_path.exists() and self.ids_path.exists():
            self._embeddings = np.load(self.embeddings_path)
            self._ids = json.loads(self.ids_path.read_text())
            self._id_set = set(self._ids)
            self._invalidate_norms()

    def _invalidate_norms(self) -> None:
        self._norms = None

    def _get_norms(self) -> np.ndarray:
        if self._norms is None and self._embeddings is not None:
            self._norms = np.linalg.norm(self._embeddings, axis=1)
        return self._norms

    def _save(self) -> None:
        self.embeddings_path.parent.mkdir(parents=True, exist_ok=True)
        if self._embeddings is not None:
            # np.save() auto-appends .npy if missing, so tmp must already end in .npy
            tmp_emb = self.embeddings_path.with_name(self.embeddings_path.stem + "_tmp.npy")
            np.save(tmp_emb, self._embeddings)
            tmp_emb.replace(self.embeddings_path)

        tmp_ids = self.ids_path.with_suffix(".json.tmp")
        tmp_ids.write_text(json.dumps(self._ids))
        tmp_ids.replace(self.ids_path)

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Get embeddings for one or more texts via a single API call.

        Returns an (N, EMBEDDING_DIM) float32 array.
        """
        import time
        for attempt in range(3):
            try:
                response = self.client.embeddings.create(
                    input=texts,
                    model=EMBEDDING_MODEL
                )
                if self.user_id and response.usage:
                    from .token_tracker import record
                    record(self.user_id, "embed",
                           getattr(response.usage, "prompt_tokens", 0) or getattr(response.usage, "total_tokens", 0) or 0,
                           0)
                # response.data may not be sorted by index; sort to match input order
                sorted_data = sorted(response.data, key=lambda d: d.index)
                vecs = np.array([d.embedding for d in sorted_data], dtype=np.float32)
                return vecs
            except OpenAIError as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                logger.error("Embedding API error: %s", e)
                raise e

    def add(self, card_id: str, text: str) -> None:
        """Add embedding for a single card (delegates to add_batch)."""
        self.add_batch([(card_id, text)])

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        """Add embeddings for multiple cards in a single API call.

        Items already present are silently skipped. Performs one API call,
        one np.vstack, and one disk save for the entire batch.
        """
        # Filter out already-embedded cards
        new_items = [(cid, text) for cid, text in items if cid not in self._id_set]
        if not new_items:
            return

        new_ids = [cid for cid, _ in new_items]
        new_texts = [text for _, text in new_items]

        vecs = self._embed(new_texts)  # single API call

        if self._embeddings is None:
            self._embeddings = vecs
        else:
            self._embeddings = np.vstack([self._embeddings, vecs])

        self._ids.extend(new_ids)
        self._id_set.update(new_ids)
        self._invalidate_norms()
        self._save()

    def update(self, card_id: str, text: str) -> None:
        """Update existing embedding."""
        if card_id not in self._id_set:
            self.add(card_id, text)
            return

        idx = self._ids.index(card_id)
        vecs = self._embed([text])
        self._embeddings[idx] = vecs[0]
        self._invalidate_norms()
        self._save()

    def find_similar(self, card_id: str, k: int = 10) -> list[tuple[str, float]]:
        """Find k most similar cards (excluding self).

        Returns list of (card_id, similarity_score) sorted by similarity descending.
        """
        if self._embeddings is None or card_id not in self._id_set:
            return []

        idx = self._ids.index(card_id)
        query_vec = self._embeddings[idx]

        # Cosine similarity with cached norms
        norms = self._get_norms()
        query_norm = norms[idx]
        similarities = (self._embeddings @ query_vec) / (norms * query_norm + 1e-9)

        # Get top k+1 (including self), then filter
        top_indices = np.argsort(similarities)[::-1][: k + 1]
        results = []
        for i in top_indices:
            if self._ids[i] != card_id:
                results.append((self._ids[i], float(similarities[i])))
        return results[:k]

    def has(self, card_id: str) -> bool:
        return card_id in self._id_set

    def count(self) -> int:
        return len(self._ids)

    def merge_from(self, source: "EmbeddingStore") -> None:
        """Merge embeddings from *source* into this store.

        Cards already present in target are skipped. Source is emptied after merge.
        No API calls — only existing vectors are moved.
        """
        if source._embeddings is None or not source._ids:
            return

        # Find new IDs (in source but not in target)
        new_indices = [i for i, cid in enumerate(source._ids) if cid not in self._id_set]
        if new_indices:
            new_vecs = source._embeddings[new_indices]
            new_ids = [source._ids[i] for i in new_indices]

            if self._embeddings is None:
                self._embeddings = new_vecs
            else:
                self._embeddings = np.vstack([self._embeddings, new_vecs])

            self._ids.extend(new_ids)
            self._id_set.update(new_ids)
            self._invalidate_norms()
            self._save()

        # Clear source
        source._embeddings = None
        source._ids = []
        source._id_set = set()
        source._invalidate_norms()
        source._save()
