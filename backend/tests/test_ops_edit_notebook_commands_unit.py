"""Unit tests for kg.ops_edit_notebook_commands — direct function calls."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import kg.ops_edit_notebook_commands as nb_cmd
from kg.cards import CardStore
from kg.notebook import NotebookStore


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
        "name": "MyNB",
        "color": None,
        "cover": None,
        "sort_order": None,
        "cascade": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── cmd_notebook_create ──────────────────────────────────────────────────


class TestNotebookCreate:
    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_create(_make_args(name="TestNB"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_creates(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_create(_make_args(name="TestNB", commit=True))
        assert rc == 0
        store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            assert any(nb.name == "TestNB" for nb in store.all())
        finally:
            store.close()

    def test_duplicate_name_warns(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            store.create(name="TestNB")
        finally:
            store.close()
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_create(_make_args(name="TestNB", commit=True))
        assert rc == 0
        err = capsys.readouterr().err
        assert "已存在" in err or "exists" in err.lower()


# ── cmd_notebook_update ──────────────────────────────────────────────────


class TestNotebookUpdate:
    def _seed_nb(self, tmp_path: Path) -> str:
        store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            nb = store.create(name="OldName")
            return nb.id
        finally:
            store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_update(_make_args(notebook=nbid, name="NewName"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_rename(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_update(
            _make_args(notebook=nbid, name="NewName", commit=True)
        )
        assert rc == 0
        store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            nb = store.get(nbid)
            assert nb is not None
            assert nb.name == "NewName"
        finally:
            store.close()

    def test_no_updates_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            nb_cmd.cmd_notebook_update(_make_args(notebook=nbid, name=None))


# ── cmd_notebook_delete ──────────────────────────────────────────────────


class TestNotebookDelete:
    def _seed_nb(self, tmp_path: Path) -> str:
        store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            nb = store.create(name="ToDelete")
            return nb.id
        finally:
            store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_delete(_make_args(notebook=nbid))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_delete_empty(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_delete(_make_args(notebook=nbid, commit=True))
        assert rc == 0
        store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            assert not store.exists(nbid)
        finally:
            store.close()

    def test_default_not_deletable(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            nb_cmd.cmd_notebook_delete(_make_args(notebook="default"))

    def test_non_empty_without_cascade_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            store.add(content="hello", meaning="world", notebook_id=nbid)
        finally:
            store.close()
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            nb_cmd.cmd_notebook_delete(_make_args(notebook=nbid))

    def test_non_empty_with_cascade(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        nbid = self._seed_nb(tmp_path)
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            store.add(content="hello", meaning="world", notebook_id=nbid)
        finally:
            store.close()
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = nb_cmd.cmd_notebook_delete(_make_args(notebook=nbid, cascade=True, commit=True))
        assert rc == 0
        nb_store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        c_store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            assert not nb_store.exists(nbid)
            assert c_store.count(notebook_id=nbid) == 0
        finally:
            nb_store.close()
            c_store.close()
