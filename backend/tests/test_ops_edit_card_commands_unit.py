"""Unit tests for kg.ops_edit_card_commands — direct function calls.

Covers all cmd_* functions with dry-run + commit paths using real CardStore.
"""
from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

import kg.ops_edit_card_commands as cards_cmd
from kg.cards import CardStore
from kg.notebook import NotebookStore


def _setup_user(tmp_path: Path, uid: str = "u1") -> Path:
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    (data_dir / "users.json").write_text(f'{{"{uid}": {{"config": {{}}}}}}')
    user_dir = data_dir / "users" / uid
    user_dir.mkdir()
    # Seed stores so _resolve_notebook_id and _card_store work
    CardStore(user_dir / "cards.db").close()
    NotebookStore(user_dir / "notebooks.db").close()
    return data_dir


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "uid": "u1",
        "commit": False,
        "json": True,
        "notebook": "default",
        "content": "apple",
        "meaning": "蘋果",
        "pos": None,
        "mode": None,
        "example": None,
        "collocation": None,
        "review": None,
        "note": None,
        "difficulty": None,
        "interval": None,
        "card": "c1",
        "set": None,
        "state": "new",
        "csv": None,
        "to_notebook": "default",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── cmd_card_add ─────────────────────────────────────────────────────────


class TestCmdCardAdd:
    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_add(_make_args(content="hello", meaning="world"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_creates_card(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_add(
            _make_args(content="hello", meaning="world", commit=True)
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "commit" in out
        # Verify card exists
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.find_by_content("hello", notebook_id="default")
            assert c is not None
            assert c.meaning == "world"
        finally:
            store.close()

    def test_commit_with_review_new(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_add(
            _make_args(
                content="hello", meaning="world", commit=True,
                review="new", interval=12.0,
            )
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.find_by_content("hello", notebook_id="default")
            assert c is not None
            assert c.review_count == 0
            assert c.next_review_at is None
        finally:
            store.close()

    def test_commit_with_note_and_difficulty(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_add(
            _make_args(
                content="hello", meaning="world", commit=True,
                note="a note", difficulty=3,
            )
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.find_by_content("hello", notebook_id="default")
            assert c is not None
            assert c.note == "a note"
            assert c.difficulty == 3
        finally:
            store.close()


# ── cmd_card_update ──────────────────────────────────────────────────────


class TestCmdCardUpdate:
    def _seed_card(self, tmp_path: Path, uid: str = "u1") -> str:
        store = CardStore(tmp_path / "users" / uid / "cards.db")
        try:
            c = store.add(content="apple", meaning="蘋果", notebook_id="default")
            return c.id
        finally:
            store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_update(
            _make_args(card=cid, set=["meaning=updated"])
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_updates_meaning(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_update(
            _make_args(card=cid, set=["meaning=updated"], commit=True)
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is not None
            assert c.meaning == "updated"
        finally:
            store.close()

    def test_commit_updates_content(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_update(
            _make_args(card=cid, set=["content=banana"], commit=True)
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is not None
            assert c.content == "banana"
        finally:
            store.close()

    def test_invalid_set_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            cards_cmd.cmd_card_update(_make_args(card=cid, set=["badfield=1"]))

    def test_empty_set_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            cards_cmd.cmd_card_update(_make_args(card=cid, set=[]))

    def test_content_clash_returns_1(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c1 = store.add(content="apple", meaning="A", notebook_id="default")
            store.add(content="banana", meaning="B", notebook_id="default")
        finally:
            store.close()
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_update(
            _make_args(card=c1.id, set=['content="banana"'], commit=True)
        )
        assert rc == 1


# ── cmd_card_set_review ──────────────────────────────────────────────────


class TestCmdCardSetReview:
    def _seed_card(self, tmp_path: Path) -> str:
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.add(content="apple", meaning="蘋果", notebook_id="default")
            return c.id
        finally:
            store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_set_review(_make_args(card=cid, state="due", interval=12.0))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_new(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_set_review(
            _make_args(card=cid, state="new", interval=12.0, commit=True)
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is not None
            assert c.review_count == 0
            assert c.next_review_at is None
        finally:
            store.close()

    def test_commit_due(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_set_review(
            _make_args(card=cid, state="due", interval=12.0, commit=True)
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is not None
            assert c.review_count == 1
            assert c.next_review_at is not None
            assert c.next_review_at.replace(tzinfo=UTC) < datetime.now(UTC)
        finally:
            store.close()

    def test_commit_reviewed(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_set_review(
            _make_args(card=cid, state="reviewed", interval=24.0, commit=True)
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is not None
            assert c.review_count == 2
            assert c.next_review_at is not None
            assert c.next_review_at.replace(tzinfo=UTC) > datetime.now(UTC)
        finally:
            store.close()

    def test_invalid_state_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            cards_cmd.cmd_card_set_review(_make_args(card=cid, state="bogus"))


# ── cmd_card_delete ──────────────────────────────────────────────────────


class TestCmdCardDelete:
    def _seed_card(self, tmp_path: Path) -> str:
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.add(content="apple", meaning="蘋果", notebook_id="default")
            return c.id
        finally:
            store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_delete(_make_args(card=cid))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_soft_delete(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid = self._seed_card(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_delete(_make_args(card=cid, commit=True))
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is None or c.is_deleted
        finally:
            store.close()


# ── cmd_card_import ──────────────────────────────────────────────────────


class TestCmdCardImport:
    def _make_csv(self, tmp_path: Path, rows: list[dict]) -> Path:
        p = tmp_path / "import.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["content", "meaning", "pos"])
            w.writeheader()
            w.writerows(rows)
        return p

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        p = self._make_csv(tmp_path, [{"content": "hello", "meaning": "world", "pos": ""}])
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_import(_make_args(csv=str(p)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_imports_rows(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        p = self._make_csv(
            tmp_path,
            [
                {"content": "hello", "meaning": "world", "pos": "n"},
                {"content": "goodbye", "meaning": "再見", "pos": "v"},
            ],
        )
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_import(_make_args(csv=str(p), commit=True))
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            assert store.find_by_content("hello", notebook_id="default") is not None
            assert store.find_by_content("goodbye", notebook_id="default") is not None
        finally:
            store.close()

    def test_missing_csv_raises(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            cards_cmd.cmd_card_import(_make_args(csv="/nonexistent.csv"))

    def test_blank_meaning_returns_1(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        p = self._make_csv(tmp_path, [{"content": "hello", "meaning": "", "pos": ""}])
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_import(_make_args(csv=str(p), commit=True))
        assert rc == 1


# ── cmd_card_move ────────────────────────────────────────────────────────


class TestCmdCardMove:
    def _seed_card_and_nb(self, tmp_path: Path) -> tuple[str, str]:
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        nb_store = NotebookStore(tmp_path / "users" / "u1" / "notebooks.db")
        try:
            nb = nb_store.create(name="DestNB")
            c = store.add(content="apple", meaning="蘋果", notebook_id="default")
            return c.id, nb.id
        finally:
            store.close()
            nb_store.close()

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid, nbid = self._seed_card_and_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_move(_make_args(card=cid, to_notebook=nbid))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_moves_card(self, tmp_path, monkeypatch, capsys):
        _setup_user(tmp_path)
        cid, nbid = self._seed_card_and_nb(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_move(
            _make_args(card=cid, to_notebook=nbid, commit=True)
        )
        assert rc == 0
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.get(cid)
            assert c is not None
            assert c.notebook_id == nbid
        finally:
            store.close()

    def test_same_notebook_returns_1(self, tmp_path, monkeypatch):
        _setup_user(tmp_path)
        store = CardStore(tmp_path / "users" / "u1" / "cards.db")
        try:
            c = store.add(content="apple", meaning="蘋果", notebook_id="default")
        finally:
            store.close()
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = cards_cmd.cmd_card_move(
            _make_args(card=c.id, to_notebook="default", commit=True)
        )
        assert rc == 1
