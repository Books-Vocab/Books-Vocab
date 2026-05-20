"""kg.ops_shared — 共用唯讀 ops infra 單元測試。"""

import sqlite3

import pytest

from kg.ops_shared import (
    connect_ro,
    data_dir,
    notebook_files,
    print_table,
    resolve_uid,
    table_columns,
)


def _mk_users(tmp_path, names):
    for n in names:
        (tmp_path / "users" / n).mkdir(parents=True)


class TestResolveUid:
    def test_exact(self, tmp_path):
        _mk_users(tmp_path, ["abc123", "def456"])
        assert resolve_uid("abc123", tmp_path) == "abc123"

    def test_prefix(self, tmp_path):
        _mk_users(tmp_path, ["abc123", "def456"])
        assert resolve_uid("abc", tmp_path) == "abc123"

    def test_substring(self, tmp_path):
        _mk_users(tmp_path, ["abc123xyz", "def456"])
        assert resolve_uid("123", tmp_path) == "abc123xyz"

    def test_ambiguous_exits(self, tmp_path):
        _mk_users(tmp_path, ["abc1", "abc2"])
        with pytest.raises(SystemExit):
            resolve_uid("abc", tmp_path)

    def test_no_match_returns_partial(self, tmp_path):
        _mk_users(tmp_path, ["abc1"])
        assert resolve_uid("zzz", tmp_path) == "zzz"

    def test_no_users_dir_returns_partial(self, tmp_path):
        assert resolve_uid("anything", tmp_path) == "anything"


class TestConnectRo:
    def test_read_works(self, tmp_path):
        db = tmp_path / "t.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE t (x INTEGER)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        c.close()
        ro = connect_ro(db)
        assert ro.execute("SELECT x FROM t").fetchone()[0] == 1
        ro.close()

    def test_insert_rejected(self, tmp_path):
        db = tmp_path / "t.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE t (x INTEGER)")
        c.commit()
        c.close()
        ro = connect_ro(db)
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO t VALUES (9)")
        ro.close()

    def test_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            connect_ro(tmp_path / "nope.db")


class TestTableColumns:
    def test_columns(self, tmp_path):
        db = tmp_path / "t.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE t (a INTEGER, b TEXT)")
        c.commit()
        c.close()
        ro = connect_ro(db)
        assert table_columns(ro, "t") == {"a", "b"}
        ro.close()


class TestNotebookFiles:
    def test_default_suffix(self, tmp_path):
        files = notebook_files(tmp_path, "default")
        assert files["graph"] == tmp_path / "graph_default.json"
        assert files["candidates"] == tmp_path / "candidates_default.json"
        assert files["embeddings"] == tmp_path / "embeddings_default.npy"
        assert files["card_ids"] == tmp_path / "card_ids_default.json"

    def test_named_notebook(self, tmp_path):
        files = notebook_files(tmp_path, "nb7")
        assert files["graph"] == tmp_path / "graph_nb7.json"


class TestDataDir:
    def test_respects_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        assert data_dir() == tmp_path


class TestPrintTable:
    def test_renders(self, capsys):
        print_table(["Name", "Cost"], [["alice", "1.5"], ["bob", "2.0"]])
        out = capsys.readouterr().out
        assert "Name" in out and "alice" in out and "2.0" in out

    def test_empty(self, capsys):
        print_table(["A"], [])
        assert "no data" in capsys.readouterr().out.lower()
