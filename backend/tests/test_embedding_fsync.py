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

import fcntl
import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from kg.embeddings import EMBEDDING_DIM, EmbeddingStore
from kg.tracked_llm import TrackedLLM


def _fd_to_path(fd: int) -> str:
    """Resolve an open fd back to its on-disk path, cross-platform.

    Linux exposes ``/dev/fd/N`` as a readable symlink; macOS does not, so we
    prefer ``fcntl.F_GETPATH`` there. Falls back to the raw fd repr if neither
    works (still lets the assertion fail loudly rather than silently pass).
    """
    try:
        return fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).rstrip(b"\0").decode()
    except (OSError, AttributeError, ValueError):
        pass
    try:
        return os.readlink(f"/dev/fd/{fd}")
    except OSError:
        return repr(fd)


def _synced_tmp_for(target: Path, synced_paths: list[str]) -> list[str]:
    """Synced paths that are a per-save temp of ``target``.

    Temps are uniquely named per save (``.<target>.<16 hex>.tmp`` beside the
    target, #2061). An fd resolves to the temp's name only while the temp has
    not been renamed yet, so a match also proves fsync happened *before* the
    replace() swapped it in.
    """
    pattern = re.compile(rf"\.{re.escape(target.name)}\.[0-9a-f]{{16}}\.tmp")
    parent = target.parent.resolve()
    return [p for p in synced_paths if pattern.fullmatch(Path(p).name) and Path(p).parent.resolve() == parent]


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
        synced_paths.append(_fd_to_path(fd))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    client.embeddings.create.return_value = _resp(2)
    # add_batch -> _save. (embed() goes through the tracked llm client.)
    store.add_batch([("c1", "alpha"), ("c2", "beta")])

    # Both temp files must have been fsynced before the replace().
    assert _synced_tmp_for(emb_path, synced_paths), f"matrix tmp was not fsynced; synced={synced_paths}"
    assert _synced_tmp_for(ids_path, synced_paths), f"ids tmp was not fsynced; synced={synced_paths}"

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
        synced_paths.append(_fd_to_path(fd))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    # remove the only card -> empty store -> _save still runs.
    store.remove_batch(["only"])

    assert _synced_tmp_for(ids_path, synced_paths), (
        f"ids tmp was not fsynced on empty-store save; synced={synced_paths}"
    )
    assert json.loads(ids_path.read_text()) == []


def test_write_meta_fsyncs_tmp_before_replace(tmp_path: Path, monkeypatch):
    """The model/dim sidecar must mirror _save's durability contract: fsync the
    temp file before replace(), else an OS crash can persist a torn/zero-length
    meta that misattributes the store's model on next boot. _write_meta runs on
    a fresh store's first save (no sidecar yet)."""
    store, client, emb_path, ids_path = _make_store(tmp_path)

    synced_paths: list[str] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        synced_paths.append(_fd_to_path(fd))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    client.embeddings.create.return_value = _resp(1)
    # Fresh store → first _save writes the sidecar via _write_meta.
    store.add_batch([("c1", "alpha")])

    assert _synced_tmp_for(store._meta_path, synced_paths), f"meta tmp was not fsynced; synced={synced_paths}"
    # And the sidecar landed intact.
    assert json.loads(store._meta_path.read_text())["dim"] == EMBEDDING_DIM
