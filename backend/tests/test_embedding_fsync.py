"""Tests for kg.embeddings.EmbeddingStore._save durability (fsync).

The matrix (.npy) and id list (.json) are written to temp files and swapped
into place with ``replace()``. Without fsync, an OS/power crash can persist
the rename ahead of the data, surfacing a zero-length / torn primary file on
next boot — the same window the graph persistence layer closes via
``_atomic_json_write`` (``f.flush(); os.fsync(...)`` before the rename).

These tests assert ``_save`` fsyncs *both* temp files (matrix + ids) before
the swap, mirroring ``kg.graph.persistence._atomic_json_write``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from kg.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, EmbeddingStore
from kg.tracked_llm import TrackedLLM


def _make_store(tmp_path: Path):
    emb_path = tmp_path / "embeddings_default.npy"
    ids_path = tmp_path / "card_ids_default.json"
    client = MagicMock()
    llm = TrackedLLM(client, "test_user")
    store = EmbeddingStore(emb_path, ids_path, llm)
    return store, client, emb_path, ids_path


def _resp(n: int):
    resp = MagicMock()
    resp.usage = MagicMock(prompt_tokens=10 * n, total_tokens=10 * n)
    resp.data = []
    for i in range(n):
        item = MagicMock()
        item.index = i
        item.embedding = np.random.rand(EMBEDDING_DIM).astype(np.float32).tolist()
        resp.data.append(item)
    return resp


def test_save_fsyncs_both_tmp_files_before_replace(tmp_path: Path, monkeypatch):
    """_save must fsync the matrix tmp and the ids tmp before swapping.

    We spy on os.fsync (as seen by kg.embeddings) and capture which on-disk
    paths each synced fd points at. A correct durable save fsyncs both the
    .npy tmp and the .json tmp; the pre-fix implementation fsyncs neither.
    """
    store, client, emb_path, ids_path = _make_store(tmp_path)

    synced_paths: list[str] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        # Resolve the fd back to its on-disk path so we can assert *which*
        # files were synced (a bare call count would not distinguish the
        # matrix tmp from the ids tmp, nor a stray dir fsync).
        try:
            synced_paths.append(os.readlink(f"/dev/fd/{fd}"))
        except OSError:
            synced_paths.append(repr(fd))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    client.embeddings.create.return_value = _resp(2)
    # add_batch -> _save. (embed() goes through the tracked llm client.)
    store.add_batch([("c1", "alpha"), ("c2", "beta")])

    # Both temp files must have been fsynced before the replace().
    emb_tmp = str(emb_path.with_name(emb_path.stem + "_tmp.npy"))
    ids_tmp = str(ids_path.with_suffix(".json.tmp"))
    assert emb_tmp in synced_paths, (
        f"matrix tmp {emb_tmp!r} was not fsynced; synced={synced_paths}"
    )
    assert ids_tmp in synced_paths, (
        f"ids tmp {ids_tmp!r} was not fsynced; synced={synced_paths}"
    )

    # And the data actually landed correctly.
    assert json.loads(ids_path.read_text()) == ["c1", "c2"]
    assert np.load(emb_path).shape == (2, EMBEDDING_DIM)


def test_save_without_embeddings_still_fsyncs_ids(tmp_path: Path, monkeypatch):
    """remove_batch down to empty (or any save where the matrix is present)
    still fsyncs the ids tmp. Guards the ``tmp_emb is None``-style branches so
    the ids durability is never skipped."""
    store, client, emb_path, ids_path = _make_store(tmp_path)
    client.embeddings.create.return_value = _resp(1)
    store.add_batch([("only", "x")])

    synced_paths: list[str] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        try:
            synced_paths.append(os.readlink(f"/dev/fd/{fd}"))
        except OSError:
            synced_paths.append(repr(fd))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    # remove the only card -> empty store -> _save still runs.
    store.remove_batch(["only"])

    ids_tmp = str(ids_path.with_suffix(".json.tmp"))
    assert ids_tmp in synced_paths, (
        f"ids tmp {ids_tmp!r} was not fsynced on empty-store save; "
        f"synced={synced_paths}"
    )
    assert json.loads(ids_path.read_text()) == []
