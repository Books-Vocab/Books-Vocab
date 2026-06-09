"""Unit tests for kg.ops_edit_link_commands — direct function calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import kg.ops_edit_link_commands as link_cmd
from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.service_factories import create_graph_store


def _setup_user(tmp_path: Path, uid: str = "u1") -> Path:
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    (data_dir / "users.json").write_text(f'{{"{uid}": {{"config": {{}}}}}}')
    user_dir = data_dir / "users" / uid
    user_dir.mkdir()
    CardStore(user_dir / "cards.db").close()
    NotebookStore(user_dir / "notebooks.db").close()
    return data_dir


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "uid": "u1",
        "commit": False,
        "json": True,
        "notebook": "default",
        "from_ref": "apple",
        "to_ref": "banana",
        "kind": "contrasts_with",
        "confidence": 0.8,
        "reason": "test",
        "if_exists": "keep",
        "link_id": "lk1",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── cmd_link_add ─────────────────────────────────────────────────────────


class TestLinkAdd:
    def _seed_cards(self, tmp_path: Path) -> tuple[str, str]:
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c1 = store.add(content="apple", meaning="A", notebook_id="default")
            c2 = store.add(content="banana", meaning="B", notebook_id="default")
            return c1.id, c2.id
        finally:
            store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        self._seed_cards(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_add(_make_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_adds_link(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        self._seed_cards(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_add(_make_args(commit=True))
        assert rc == 0
        graph = create_graph_store(tmp_path / "users" / "u1", "default")
        assert graph.link_count() == 1

    def test_invalid_kind_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        self._seed_cards(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            link_cmd.cmd_link_add(_make_args(kind="bogus"))

    def test_invalid_confidence_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        self._seed_cards(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            link_cmd.cmd_link_add(_make_args(confidence=1.5))


# ── cmd_link_delete ──────────────────────────────────────────────────────


class TestLinkDelete:
    def _seed_link(self, tmp_path: Path) -> str:
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c1 = store.add(content="apple", meaning="A", notebook_id="default")
            c2 = store.add(content="banana", meaning="B", notebook_id="default")
        finally:
            store.close()
        graph = create_graph_store(tmp_path / "users" / "u1", "default")
        lk = graph.add_link(
            from_id=c1.id, to_id=c2.id,
            kind="contrasts_with", confidence=0.8, reason="test",
            source="ops",
        )
        return lk.id

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        lid = self._seed_link(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_delete(_make_args(link_id=lid))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_deletes_link(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        lid = self._seed_link(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_delete(_make_args(link_id=lid, commit=True))
        assert rc == 0
        graph = create_graph_store(tmp_path / "users" / "u1", "default")
        assert graph.get_link(lid) is None


# ── cmd_link_list ────────────────────────────────────────────────────────


class TestLinkList:
    def test_empty(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_list(_make_args())
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["count"] == 0

    def test_with_link(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c1 = store.add(content="apple", meaning="A", notebook_id="default")
            c2 = store.add(content="banana", meaning="B", notebook_id="default")
        finally:
            store.close()
        graph = create_graph_store(tmp_path / "users" / "u1", "default")
        graph.add_link(
            from_id=c1.id, to_id=c2.id,
            kind="contrasts_with", confidence=0.8, reason="test",
            source="ops",
        )
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_list(_make_args())
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["count"] == 1


# ── cmd_link_update ──────────────────────────────────────────────────────


class TestLinkUpdate:
    def _seed_link(self, tmp_path: Path) -> str:
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c1 = store.add(content="apple", meaning="A", notebook_id="default")
            c2 = store.add(content="banana", meaning="B", notebook_id="default")
        finally:
            store.close()
        graph = create_graph_store(tmp_path / "users" / "u1", "default")
        lk = graph.add_link(
            from_id=c1.id, to_id=c2.id,
            kind="contrasts_with", confidence=0.8, reason="test",
            source="ops",
        )
        return lk.id

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        lid = self._seed_link(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_update(_make_args(link_id=lid, confidence=0.5))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_updates_confidence(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        lid = self._seed_link(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = link_cmd.cmd_link_update(
            _make_args(link_id=lid, confidence=0.5, commit=True)
        )
        assert rc == 0
        graph = create_graph_store(tmp_path / "users" / "u1", "default")
        lk = graph.get_link(lid)
        assert lk is not None
        assert lk.confidence == 0.5

    def test_no_updates_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        lid = self._seed_link(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            args = argparse.Namespace(
                uid="u1", commit=False, json=True, notebook="default",
                link_id=lid, confidence=None, reason=None, kind=None,
            )
            link_cmd.cmd_link_update(args)

    def test_invalid_confidence_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        lid = self._seed_link(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            link_cmd.cmd_link_update(_make_args(link_id=lid, confidence=1.5))
