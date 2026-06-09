"""Unit tests for kg.ops_edit_support — pure functions and helpers."""
from __future__ import annotations

import json
import sqlite3
import tarfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import kg.ops_edit_support as support
from kg.cards import CardStore
from kg.notebook import NotebookStore


# ── _split_multi ─────────────────────────────────────────────────────────


class TestSplitMulti:
    def test_empty(self):
        assert support._split_multi("") == []
        assert support._split_multi(None) == []

    def test_simple(self):
        assert support._split_multi("a|b|c") == ["a", "b", "c"]

    def test_whitespace_trim(self):
        assert support._split_multi(" a | b | c ") == ["a", "b", "c"]

    def test_empty_parts_skipped(self):
        assert support._split_multi("a||b") == ["a", "b"]


# ── _assert_clean_notebook_name ──────────────────────────────────────────


class TestAssertCleanNotebookName:
    def test_valid(self):
        support._assert_clean_notebook_name("Hello World")

    def test_empty_raises(self):
        with pytest.raises(support.EditError):
            support._assert_clean_notebook_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(support.EditError):
            support._assert_clean_notebook_name("   ")

    def test_control_char_raises(self):
        with pytest.raises(support.EditError):
            support._assert_clean_notebook_name("hello\nworld")

    def test_path_char_raises(self):
        with pytest.raises(support.EditError):
            support._assert_clean_notebook_name("foo/bar")

    def test_too_long_raises(self):
        with pytest.raises(support.EditError):
            support._assert_clean_notebook_name("x" * 101)


# ── _review_fields ───────────────────────────────────────────────────────


class TestReviewFields:
    def test_new(self):
        now = datetime.now(UTC)
        fields = support._review_fields("new", None, now)
        assert fields["review_count"] == 0
        assert fields["next_review_at"] is None
        assert fields["review_interval_hours"] == 12.0

    def test_new_with_interval(self):
        now = datetime.now(UTC)
        fields = support._review_fields("new", 24.0, now)
        assert fields["review_interval_hours"] == 24.0

    def test_due(self):
        now = datetime.now(UTC)
        fields = support._review_fields("due", 12.0, now)
        assert fields["review_count"] == 1
        assert fields["next_review_at"] < now

    def test_reviewed(self):
        now = datetime.now(UTC)
        fields = support._review_fields("reviewed", 24.0, now)
        assert fields["review_count"] == 2
        assert fields["next_review_at"] > now

    def test_invalid_state_raises(self):
        now = datetime.now(UTC)
        with pytest.raises(support.EditError):
            support._review_fields("bogus", 12.0, now)

    def test_non_positive_interval_raises(self):
        now = datetime.now(UTC)
        with pytest.raises(support.EditError):
            support._review_fields("due", 0, now)
        with pytest.raises(support.EditError):
            support._review_fields("due", -1, now)


# ── _as_utc ──────────────────────────────────────────────────────────────


class TestAsUtc:
    def test_aware_unchanged(self):
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert support._as_utc(dt) is dt

    def test_naive_gets_utc(self):
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = support._as_utc(dt)
        assert result.tzinfo is UTC


# ── _parse_db_dt ─────────────────────────────────────────────────────────


class TestParseDbDt:
    def test_none(self):
        assert support._parse_db_dt(None) is None

    def test_naive_string(self):
        dt = support._parse_db_dt("2024-01-15 08:30:00")
        assert dt is not None
        assert dt.tzinfo is UTC
        assert dt.year == 2024

    def test_iso_string(self):
        dt = support._parse_db_dt("2024-01-15T08:30:00")
        assert dt is not None
        assert dt.tzinfo is UTC

    def test_z_suffix(self):
        dt = support._parse_db_dt("2024-01-15T08:30:00Z")
        assert dt is not None
        assert dt.tzinfo is UTC

    def test_invalid(self):
        assert support._parse_db_dt("not-a-date") is None


# ── _is_vocab_file ───────────────────────────────────────────────────────


class TestIsVocabFile:
    def test_cards_db(self):
        assert support._is_vocab_file("cards.db")
        assert support._is_vocab_file("cards.db-wal")
        assert support._is_vocab_file("cards.db-shm")

    def test_graph_json(self):
        assert support._is_vocab_file("graph_default.json")

    def test_embeddings(self):
        assert support._is_vocab_file("embeddings_default.npy")

    def test_not_vocab(self):
        assert not support._is_vocab_file("readme.txt")
        assert not support._is_vocab_file("foo.clone-tmp")


# ── _source_to_json ──────────────────────────────────────────────────────


class TestSourceToJson:
    def test_none(self):
        assert support._source_to_json(None, "label") is None

    def test_empty_string(self):
        assert support._source_to_json("", "label") is None

    def test_dict(self):
        result = support._source_to_json({"type": "book", "title": "t1"}, "label")
        assert result is not None
        data = json.loads(result)
        assert data["type"] == "book"

    def test_json_string(self):
        result = support._source_to_json('{"type": "web", "url": "http://x"}', "label")
        assert result is not None
        data = json.loads(result)
        assert data["type"] == "web"

    def test_invalid_json_raises(self):
        with pytest.raises(support.EditError):
            support._source_to_json("not json", "label")

    def test_invalid_dict_raises(self):
        with pytest.raises(support.EditError):
            support._source_to_json({"bogus": "x"}, "label")


# ── _card_brief ──────────────────────────────────────────────────────────


class TestCardBrief:
    def test_fields(self):
        card = MagicMock()
        card.id = "c1"
        card.content = "hello"
        card.meaning = "world"
        card.pos = "n"
        card.notebook_id = "nb1"
        card.review_count = 3
        card.next_review_at = None
        card.last_review_feedback = 1
        brief = support._card_brief(card)
        assert brief["id"] == "c1"
        assert brief["content"] == "hello"
        assert brief["review_count"] == 3


# ── _resolve_notebook_id ─────────────────────────────────────────────────


class TestResolveNotebookId:
    def test_default(self, tmp_path):
        assert support._resolve_notebook_id(tmp_path, "default") == "default"

    def test_by_id(self, tmp_path):
        store = NotebookStore(tmp_path / "notebooks.db")
        try:
            nb = store.create(name="Test")
            assert support._resolve_notebook_id(tmp_path, nb.id) == nb.id
        finally:
            store.close()

    def test_by_name(self, tmp_path):
        store = NotebookStore(tmp_path / "notebooks.db")
        try:
            nb = store.create(name="MyNotebook")
            assert support._resolve_notebook_id(tmp_path, "MyNotebook") == nb.id
        finally:
            store.close()

    def test_not_found_raises(self, tmp_path):
        with pytest.raises(support.EditError):
            support._resolve_notebook_id(tmp_path, "nonexistent")


# ── _resolve_card_id ─────────────────────────────────────────────────────


class TestResolveCardId:
    def test_by_id(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            c = store.add(content="apple", meaning="A", notebook_id="default")
            assert support._resolve_card_id(store, c.id).id == c.id
        finally:
            store.close()

    def test_by_content(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            c = store.add(content="apple", meaning="A", notebook_id="default")
            assert support._resolve_card_id(store, "apple").id == c.id
        finally:
            store.close()

    def test_deleted_raises(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            c = store.add(content="apple", meaning="A", notebook_id="default")
            store.delete(c.id)
            with pytest.raises(support.EditError):
                support._resolve_card_id(store, c.id)
        finally:
            store.close()

    def test_not_found_raises(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            with pytest.raises(support.EditError):
                support._resolve_card_id(store, "ghost")
        finally:
            store.close()


# ── _resolve_card_in_notebook ────────────────────────────────────────────


class TestResolveCardInNotebook:
    def test_same_notebook(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            c = store.add(content="apple", meaning="A", notebook_id="nb1")
            assert support._resolve_card_in_notebook(store, "apple", "nb1").id == c.id
        finally:
            store.close()

    def test_different_notebook_raises(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            store.add(content="apple", meaning="A", notebook_id="nb2")
            with pytest.raises(support.EditError) as ei:
                support._resolve_card_in_notebook(store, "apple", "nb1")
            assert "別的 notebook" in str(ei.value)
        finally:
            store.close()

    def test_not_found_raises(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        try:
            with pytest.raises(support.EditError):
                support._resolve_card_in_notebook(store, "ghost", "nb1")
        finally:
            store.close()


# ── _link_on_disk ────────────────────────────────────────────────────────


class TestLinkOnDisk:
    def test_missing_file(self, tmp_path):
        graph = MagicMock()
        graph.links_path = tmp_path / "no.json"
        assert not support._link_on_disk(graph, "lk1")

    def test_list_format(self, tmp_path):
        graph = MagicMock()
        graph.links_path = tmp_path / "links.json"
        graph.links_path.write_text(json.dumps([{"id": "lk1", "status": "active"}]))
        assert support._link_on_disk(graph, "lk1")
        assert not support._link_on_disk(graph, "lk2")

    def test_dict_format(self, tmp_path):
        graph = MagicMock()
        graph.links_path = tmp_path / "links.json"
        graph.links_path.write_text(json.dumps({"lk1": {"id": "lk1"}}))
        assert support._link_on_disk(graph, "lk1")

    def test_invalid_json(self, tmp_path):
        graph = MagicMock()
        graph.links_path = tmp_path / "links.json"
        graph.links_path.write_text("not json")
        assert not support._link_on_disk(graph, "lk1")


# ── _count_active_cards ──────────────────────────────────────────────────


class TestCountActiveCards:
    def test_missing_db(self, tmp_path):
        assert support._count_active_cards(tmp_path / "no.db") == 0

    def test_with_cards(self, tmp_path):
        db = tmp_path / "cards.db"
        store = CardStore(db)
        try:
            store.add(content="a", meaning="A", notebook_id="default")
            store.add(content="b", meaning="B", notebook_id="default")
        finally:
            store.close()
        assert support._count_active_cards(db) == 2


# ── _count_graph_links ───────────────────────────────────────────────────


class TestCountGraphLinks:
    def test_empty(self, tmp_path):
        assert support._count_graph_links(tmp_path) == 0

    def test_with_links(self, tmp_path):
        (tmp_path / "graph_default.json").write_text(
            json.dumps([
                {"id": "l1", "status": "active"},
                {"id": "l2", "status": "deleted"},
            ])
        )
        assert support._count_graph_links(tmp_path) == 1

    def test_invalid_json_skipped(self, tmp_path):
        (tmp_path / "graph_broken.json").write_text("bad")
        assert support._count_graph_links(tmp_path) == 0


# ── _sqlite_online_backup ────────────────────────────────────────────────


class TestSqliteOnlineBackup:
    def test_backup(self, tmp_path):
        src = tmp_path / "src.db"
        dst = tmp_path / "dst.db"
        conn = sqlite3.connect(str(src))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
        conn.close()

        support._sqlite_online_backup(src, dst)
        conn2 = sqlite3.connect(str(dst))
        val = conn2.execute("SELECT x FROM t").fetchone()[0]
        conn2.close()
        assert val == 42


# ── _clone_source_files ──────────────────────────────────────────────────


class TestCloneSourceFiles:
    def test_empty(self, tmp_path):
        sqlite_files, others = support._clone_source_files(tmp_path)
        assert sqlite_files == []
        assert others == []

    def test_with_files(self, tmp_path):
        (tmp_path / "cards.db").write_text("")
        (tmp_path / "notebooks.db").write_text("")
        (tmp_path / "graph_default.json").write_text("{}")
        sqlite_files, others = support._clone_source_files(tmp_path)
        assert len(sqlite_files) == 2
        assert len(others) == 1


# ── _list_world_backups ──────────────────────────────────────────────────


class TestListWorldBackups:
    def test_empty(self, tmp_path):
        assert support._list_world_backups(tmp_path) == []

    def test_with_backups(self, tmp_path):
        root = tmp_path / "_ops_world_backups"
        root.mkdir()
        (root / "world__20240101T000000Z.tar.gz").write_text("fake")
        backups = support._list_world_backups(tmp_path)
        assert len(backups) == 1
        assert backups[0]["size"] == 4


# ── _world_members ───────────────────────────────────────────────────────


class TestWorldMembers:
    def test_excludes(self, tmp_path):
        (tmp_path / "users.json").write_text("{}")
        (tmp_path / "_ops_backups").mkdir()
        (tmp_path / "_ops_world_backups").mkdir()
        (tmp_path / "users.json.lock").write_text("")
        (tmp_path / "_ops_edit_audit.jsonl").write_text("")
        members = support._world_members(tmp_path)
        assert all(m.name not in {"_ops_backups", "_ops_world_backups"} for m in members)


# ── _extract_user_backup_members ─────────────────────────────────────────


class TestExtractUserBackupMembers:
    def test_extraction(self, tmp_path):
        tar_path = tmp_path / "backup.tar.gz"
        user_dir = tmp_path / "users" / "u1"
        user_dir.mkdir(parents=True)
        (user_dir / "cards.db").write_text("")
        meta_dir = user_dir / ".ops_meta"
        meta_dir.mkdir()
        (meta_dir / "user_record.json").write_text('{"email": "u1@test.com"}')
        (meta_dir / "email_index.json").write_text('{"u1@test.com": "u1"}')

        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(user_dir, arcname="u1")

        with tarfile.open(tar_path, "r:gz") as tar:
            record, email_index = support._extract_user_backup_members(
                tar, "u1", tmp_path / "dest"
            )
        assert record is not None
        assert record["email"] == "u1@test.com"
        assert email_index is not None
        assert email_index["u1@test.com"] == "u1"


# ── _passthrough_normalize ───────────────────────────────────────────────


class TestPassthroughNormalize:
    def test_identity(self):
        users = {"u1": {"config": {}}}
        result, changed = support._passthrough_normalize(users)
        assert result is users
        assert not changed
