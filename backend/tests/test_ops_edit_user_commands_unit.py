"""Unit tests for kg.ops_edit_user_commands — direct function calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import kg.ops_edit_user_commands as user_cmd
from kg.user_store import load_users_from


def _setup_data_dir(tmp_path: Path) -> Path:
    return tmp_path


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "uid": "u1",
        "commit": False,
        "json": True,
        "provider": "google",
        "email": "u1@test.com",
        "allow_existing": False,
        "translation_source": None,
        "translation_target": None,
        "review_clock": None,
        "paused_at": None,
        "review_mode": None,
        "custom_initial_interval_hours": None,
        "custom_remembered_multiplier": None,
        "custom_forgot_multiplier": None,
        "custom_minimum_interval_hours": None,
        "custom_maximum_interval_hours": None,
        "active_notebook": None,
        "auto_link": None,
        "backup": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── cmd_user_create ──────────────────────────────────────────────────────


class TestUserCreate:
    def test_dry_run_new_user(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_create(_make_args(uid="newuser"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_creates_user(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_create(_make_args(uid="newuser", commit=True))
        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        assert "newuser" in users
        assert (tmp_path / "users" / "newuser").exists()

    def test_existing_without_allow_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_cmd.cmd_user_create(_make_args(uid="newuser", commit=True))
        rc = user_cmd.cmd_user_create(_make_args(uid="newuser"))
        assert rc == 1

    def test_allow_existing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_cmd.cmd_user_create(_make_args(uid="newuser", commit=True))
        rc = user_cmd.cmd_user_create(
            _make_args(uid="newuser", allow_existing=True, commit=True)
        )
        assert rc == 0


# ── cmd_user_delete ──────────────────────────────────────────────────────


class TestUserDelete:
    def test_dry_run_keeps_user(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_cmd.cmd_user_create(
            _make_args(uid="doomed", email="doomed@test.com", commit=True)
        )
        capsys.readouterr()

        rc = user_cmd.cmd_user_delete(_make_args(uid="doomed"))

        assert rc == 0
        assert "dry-run" in capsys.readouterr().out
        assert (tmp_path / "users" / "doomed").exists()

    def test_commit_removes_dir_record_and_email_index(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_cmd.cmd_user_create(
            _make_args(uid="doomed", email="doomed@test.com", commit=True)
        )

        rc = user_cmd.cmd_user_delete(_make_args(uid="doomed", commit=True))

        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        assert "doomed" not in users
        assert not (tmp_path / "users" / "doomed").exists()
        assert "doomed@test.com" not in users.get("_email_index", {})

    def test_commit_scrubs_subscription_index_and_spares_others(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_cmd.cmd_user_create(
            _make_args(uid="doomed", email="doomed@test.com", commit=True)
        )
        user_cmd.cmd_user_create(
            _make_args(uid="keeper", email="keeper@test.com", commit=True)
        )
        users_path = tmp_path / "users.json"
        payload = json.loads(users_path.read_text())
        payload["_subscription_index"] = {
            "txn-doomed": "doomed",
            "txn-keep": "keeper",
        }
        users_path.write_text(json.dumps(payload))

        rc = user_cmd.cmd_user_delete(_make_args(uid="doomed", commit=True))

        assert rc == 0
        users = json.loads(users_path.read_text())
        assert users["_subscription_index"] == {"txn-keep": "keeper"}
        assert "keeper" in users
        assert (tmp_path / "users" / "keeper").exists()

    def test_absent_uid_raises(self, tmp_path, monkeypatch):
        from kg.ops_edit_support import EditError

        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))

        with pytest.raises(EditError):
            user_cmd.cmd_user_delete(_make_args(uid="ghost", commit=True))

    def test_delete_then_restore_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_cmd.cmd_user_create(
            _make_args(uid="doomed", email="doomed@test.com", commit=True)
        )
        user_cmd.cmd_user_delete(_make_args(uid="doomed", commit=True))

        rc = user_cmd.cmd_restore(_make_args(uid="doomed", commit=True))

        assert rc == 0
        assert (tmp_path / "users" / "doomed" / "notebooks.db").exists()
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        assert "doomed" in users

    def test_parser_registers_user_delete(self):
        from kg.ops_edit_parser import build_parser

        ns = build_parser().parse_args(["user-delete", "u1", "--commit"])

        assert ns.func is user_cmd.cmd_user_delete
        assert ns.uid == "u1"
        assert ns.commit is True


# ── cmd_user_config_set ──────────────────────────────────────────────────


class TestUserConfigSet:
    def _setup_user(self, tmp_path: Path, uid: str = "u1") -> Path:
        data_dir = tmp_path
        (data_dir / "users").mkdir()
        (data_dir / "users.json").write_text(
            f'{{"{uid}": {{"config": {{}}, "email": "{uid}@test.com"}}}}'
        )
        user_dir = data_dir / "users" / uid
        user_dir.mkdir()
        from kg.notebook import NotebookStore
        NotebookStore(user_dir / "notebooks.db").close()
        return data_dir

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_config_set(
            _make_args(translation_source="en", translation_target="zh-Hant")
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_translation(self, tmp_path, monkeypatch, capsys):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_config_set(
            _make_args(
                translation_source="en", translation_target="zh-Hant", commit=True
            )
        )
        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        cfg = users["u1"]["config"]
        assert cfg["translation"]["source_lang"] == "en"
        assert cfg["translation"]["target_lang"] == "zh-Hant"

    def test_commit_review_clock_paused(self, tmp_path, monkeypatch, capsys):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_config_set(
            _make_args(review_clock="paused", commit=True)
        )
        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        assert users["u1"]["config"]["review_clock"]["is_paused"] is True

    def test_commit_review_mode(self, tmp_path, monkeypatch, capsys):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_config_set(
            _make_args(review_mode="intensive", custom_initial_interval_hours=6, commit=True)
        )
        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        rm = users["u1"]["config"]["review_mode"]
        assert rm["mode"] == "intensive"
        assert rm["custom_initial_interval_hours"] == 6

    def test_commit_auto_link_off(self, tmp_path, monkeypatch, capsys):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_config_set(
            _make_args(auto_link="off", commit=True)
        )
        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        al = users["u1"]["config"]["auto_link"]
        assert al["enabled"] is False
        assert al["updated_at"] is not None

    def test_commit_auto_link_on(self, tmp_path, monkeypatch, capsys):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_user_config_set(
            _make_args(auto_link="on", commit=True)
        )
        assert rc == 0
        users = load_users_from(tmp_path / "users.json", lambda x: (x, False))
        assert users["u1"]["config"]["auto_link"]["enabled"] is True

    def test_no_updates_raises(self, tmp_path, monkeypatch):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            user_cmd.cmd_user_config_set(_make_args())

    def test_paused_at_without_clock_raises(self, tmp_path, monkeypatch):
        self._setup_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            user_cmd.cmd_user_config_set(
                _make_args(paused_at="2024-01-01T00:00:00Z")
            )


# ── cmd_list_backups ─────────────────────────────────────────────────────


class TestListBackups:
    def test_empty(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_list_backups(_make_args(uid="u1"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "count" in out

    def test_with_backup(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        backup_dir = tmp_path / "_ops_backups"
        backup_dir.mkdir()
        (backup_dir / "u1__20240101T000000Z.tar.gz").write_text("fake")
        rc = user_cmd.cmd_list_backups(_make_args(uid="u1"))
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["count"] == 1


# ── cmd_restore ──────────────────────────────────────────────────────────


class TestRestore:
    def _create_backup(self, tmp_path: Path, uid: str = "u1") -> Path:
        import tarfile
        backup_dir = tmp_path / "_ops_backups"
        backup_dir.mkdir()
        dest = backup_dir / f"{uid}__20240101T000000Z.tar.gz"
        with tarfile.open(dest, "w:gz") as tar:
            # Add minimal user dir content
            user_dir = tmp_path / "users" / uid
            user_dir.mkdir(parents=True)
            (user_dir / "notebooks.db").write_text("")
            tar.add(user_dir, arcname=uid)
        return dest

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        self._create_backup(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_restore(_make_args(uid="u1"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_restore(self, tmp_path, monkeypatch, capsys):
        self._create_backup(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        rc = user_cmd.cmd_restore(_make_args(uid="u1", commit=True))
        assert rc == 0
        assert (tmp_path / "users" / "u1" / "notebooks.db").exists()

    def test_no_backup_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        from kg.ops_edit_support import EditError
        with pytest.raises(EditError):
            user_cmd.cmd_restore(_make_args(uid="u1"))
