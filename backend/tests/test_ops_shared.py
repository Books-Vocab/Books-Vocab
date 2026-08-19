"""kg.ops_shared — 共用唯讀 ops infra 單元測試。"""

import sqlite3

import pytest

from kg.ops_shared import (
    assert_readonly_sql,
    connect_ro,
    data_dir,
    notebook_files,
    print_table,
    provider_column_expr,
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

    @pytest.mark.parametrize(
        "unsafe_uid", ["", ".", "..", "../outside", "nested/user", "nested\\user"]
    )
    def test_rejects_path_traversal_and_separators(self, tmp_path, unsafe_uid):
        _mk_users(tmp_path, ["abc123"])
        with pytest.raises(ValueError):
            resolve_uid(unsafe_uid, tmp_path)

    def test_rejects_absolute_path(self, tmp_path):
        _mk_users(tmp_path, ["abc123"])
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(ValueError):
            resolve_uid(str(outside), tmp_path)

    def test_rejects_path_traversal_without_users_dir(self, tmp_path):
        with pytest.raises(ValueError):
            resolve_uid("../outside", tmp_path)

    def test_rejects_symlink_escape(self, tmp_path):
        _mk_users(tmp_path, ["abc123"])
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "users" / "escaped").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError):
            resolve_uid("escaped", tmp_path)

    def test_rejects_symlink_escape_during_partial_match(self, tmp_path):
        _mk_users(tmp_path, ["abc123"])
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "users" / "escaped").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError):
            resolve_uid("esc", tmp_path)


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


class TestProviderColumnExpr:
    def _conn(self, tmp_path, with_provider):
        db = tmp_path / "t.db"
        c = sqlite3.connect(str(db))
        cols = "id INTEGER" + (", provider TEXT" if with_provider else "")
        c.execute(f"CREATE TABLE token_usage ({cols})")
        c.commit()
        c.close()
        return connect_ro(db)

    def test_present(self, tmp_path):
        ro = self._conn(tmp_path, with_provider=True)
        assert provider_column_expr(ro) == "provider"
        ro.close()

    def test_legacy_missing(self, tmp_path):
        ro = self._conn(tmp_path, with_provider=False)
        assert provider_column_expr(ro) == "NULL"
        ro.close()


class TestAssertReadonlySql:
    @pytest.mark.parametrize("sql", [
        "SELECT * FROM cards",
        "  select id from cards where word = 'x'  ",
        "WITH t AS (SELECT 1) SELECT * FROM t",
        "EXPLAIN QUERY PLAN SELECT * FROM cards",
        "SELECT 1;",  # trailing ; tolerated
    ])
    def test_allows_readonly(self, sql):
        assert assert_readonly_sql(sql) is None  # no raise

    @pytest.mark.parametrize("sql", [
        "DELETE FROM cards",
        "UPDATE cards SET word = 'x'",
        "ATTACH DATABASE '/etc/passwd' AS p",
        "PRAGMA table_info(cards)",
        "SELECT 1; DROP TABLE cards",  # statement stacking
        "DROP TABLE cards",
    ])
    def test_rejects_non_readonly(self, sql):
        with pytest.raises(ValueError):
            assert_readonly_sql(sql)


class TestNotebookFiles:
    def test_default_suffix(self, tmp_path):
        files = notebook_files(tmp_path, "default")
        assert files["graph"] == tmp_path / "graph_default.json"
        assert files["candidates"] == tmp_path / "candidates_default.json"
        assert files["embeddings"] == tmp_path / "embeddings_default.npy"
        assert files["card_ids"] == tmp_path / "card_ids_default.json"
        # The embeddings meta sidecar (model/dim guard) is a real per-notebook
        # artifact — it must be in the SoT so notebook deletion cleans it up.
        assert files["embeddings_meta"] == tmp_path / "embeddings_meta_default.json"

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
