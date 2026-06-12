"""Unit tests for kg.ops_edit_shared — EditContext, backup, audit, emit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import kg.ops_edit_shared as shared

# ── assert_safe_uid ──────────────────────────────────────────────────────


class TestAssertSafeUid:
    def test_valid(self):
        shared.assert_safe_uid("user123")
        shared.assert_safe_uid("user.name")
        shared.assert_safe_uid("user-name")

    def test_empty_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid("")

    def test_dot_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid(".")

    def test_dotdot_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid("..")

    def test_double_dot_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid("a/../b")

    def test_leading_dot_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid(".hidden")

    def test_slash_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid("a/b")

    def test_too_long_raises(self):
        with pytest.raises(shared.EditError):
            shared.assert_safe_uid("x" * 201)


# ── path helpers ─────────────────────────────────────────────────────────


class TestPathHelpers:
    def test_users_file(self, tmp_path):
        assert shared.users_file(tmp_path) == tmp_path / "users.json"

    def test_users_lock_file(self, tmp_path):
        assert shared.users_lock_file(tmp_path) == tmp_path / "users.json.lock"

    def test_user_dir_for(self, tmp_path):
        assert shared.user_dir_for(tmp_path, "u1") == tmp_path / "users" / "u1"


# ── _load_users_json_raw ─────────────────────────────────────────────────


class TestLoadUsersJsonRaw:
    def test_missing(self, tmp_path):
        assert shared._load_users_json_raw(tmp_path / "no.json") == {}

    def test_valid(self, tmp_path):
        p = tmp_path / "users.json"
        p.write_text('{"u1": {}}')
        assert shared._load_users_json_raw(p) == {"u1": {}}

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "users.json"
        p.write_text("not json")
        assert shared._load_users_json_raw(p) == {}

    def test_non_dict(self, tmp_path):
        p = tmp_path / "users.json"
        p.write_text("[1, 2, 3]")
        assert shared._load_users_json_raw(p) == {}


# ── backup_user_dir ──────────────────────────────────────────────────────


class TestBackupUserDir:
    def test_missing_user_dir(self, tmp_path):
        assert shared.backup_user_dir(tmp_path, "u1") is None

    def test_creates_backup(self, tmp_path):
        user_dir = tmp_path / "users" / "u1"
        user_dir.mkdir(parents=True)
        (user_dir / "cards.db").write_text("")
        (tmp_path / "users.json").write_text('{"u1": {"email": "u1@test.com"}}')

        path = shared.backup_user_dir(tmp_path, "u1")
        assert path is not None
        assert path.exists()
        assert path.name.startswith("u1__")

    def test_collision_avoidance(self, tmp_path):
        user_dir = tmp_path / "users" / "u1"
        user_dir.mkdir(parents=True)
        (tmp_path / "users.json").write_text('{}')

        p1 = shared.backup_user_dir(tmp_path, "u1")
        p2 = shared.backup_user_dir(tmp_path, "u1")
        assert p1 != p2
        assert p1.exists()
        assert p2.exists()


# ── backup_world ─────────────────────────────────────────────────────────


class TestBackupWorld:
    def test_backup(self, tmp_path):
        (tmp_path / "users.json").write_text("{}")
        path = shared.backup_world(tmp_path)
        assert path.exists()
        assert path.name.startswith("world__")

    def test_label_sanitization(self, tmp_path):
        (tmp_path / "users.json").write_text("{}")
        path = shared.backup_world(tmp_path, label="hello world!!")
        assert "hello-world" in path.name


# ── list_user_backups ────────────────────────────────────────────────────


class TestListUserBackups:
    def test_empty(self, tmp_path):
        assert shared.list_user_backups(tmp_path, "u1") == []

    def test_with_backups(self, tmp_path):
        backup_dir = tmp_path / "_ops_backups"
        backup_dir.mkdir()
        (backup_dir / "u1__20240101T000000Z.tar.gz").write_text("fake")
        (backup_dir / "u2__20240101T000000Z.tar.gz").write_text("fake")
        result = shared.list_user_backups(tmp_path, "u1")
        assert len(result) == 1
        assert result[0]["size"] == 4


# ── append_audit ─────────────────────────────────────────────────────────


class TestAppendAudit:
    def test_appends(self, tmp_path):
        shared.append_audit(tmp_path, {"action": "test"})
        audit_path = tmp_path / "_ops_edit_audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["action"] == "test"
        assert "ts" in data

    def test_multiple(self, tmp_path):
        shared.append_audit(tmp_path, {"action": "a"})
        shared.append_audit(tmp_path, {"action": "b"})
        audit_path = tmp_path / "_ops_edit_audit.jsonl"
        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) == 2


# ── emit / _print_human ──────────────────────────────────────────────────


class TestEmit:
    def test_json_mode(self, capsys):
        shared.emit({"key": "value"}, json_mode=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["key"] == "value"

    def test_human_mode_dry_run(self, capsys):
        shared.emit({"mode": "dry-run", "action": "test", "plan": {"x": 1}}, json_mode=False)
        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "test" in out

    def test_human_mode_error(self, capsys):
        shared.emit({"mode": "error", "action": "test", "error": "boom"}, json_mode=False)
        out = capsys.readouterr().out
        assert "boom" in out

    def test_human_mode_non_dict(self, capsys):
        shared.emit("plain string", json_mode=False)
        out = capsys.readouterr().out
        assert "plain string" in out


# ── EditContext ──────────────────────────────────────────────────────────


class TestEditContext:
    def _setup(self, tmp_path: Path, uid: str = "u1") -> Path:
        data_dir = tmp_path
        (data_dir / "users").mkdir()
        (data_dir / "users.json").write_text(f'{{"{uid}": {{}}}}')
        user_dir = data_dir / "users" / uid
        user_dir.mkdir()
        return data_dir

    def test_dry_run(self, tmp_path, capsys):
        dd = self._setup(tmp_path)
        ctx = shared.EditContext(data_dir=dd, uid="u1", commit=False, json_mode=True)
        rc = ctx.run(action="test", plan={"x": 1}, apply_fn=lambda: {"result": "ok"})
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_commit_success(self, tmp_path, capsys):
        dd = self._setup(tmp_path)
        ctx = shared.EditContext(data_dir=dd, uid="u1", commit=True, json_mode=True)
        rc = ctx.run(action="test", plan={"x": 1}, apply_fn=lambda: {"result": "ok"})
        assert rc == 0
        out = capsys.readouterr().out
        assert "commit" in out

    def test_commit_verify_fails(self, tmp_path, capsys):
        dd = self._setup(tmp_path)
        ctx = shared.EditContext(data_dir=dd, uid="u1", commit=True, json_mode=True)
        rc = ctx.run(
            action="test", plan={"x": 1},
            apply_fn=lambda: {"result": "ok"},
            verify_fn=lambda: {"ok": False},
        )
        assert rc == 1

    def test_commit_apply_raises(self, tmp_path, capsys):
        dd = self._setup(tmp_path)
        ctx = shared.EditContext(data_dir=dd, uid="u1", commit=True, json_mode=True)
        rc = ctx.run(
            action="test", plan={"x": 1},
            apply_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "error" in out

    def test_user_not_found(self, tmp_path):
        dd = tmp_path
        (dd / "users").mkdir()
        (dd / "users.json").write_text('{}')
        with pytest.raises(shared.EditError):
            shared.EditContext(data_dir=dd, uid="ghost", commit=False, json_mode=True)

    def test_require_user_false(self, tmp_path):
        dd = tmp_path
        (dd / "users").mkdir()
        (dd / "users.json").write_text('{}')
        ctx = shared.EditContext(data_dir=dd, uid="newuser", commit=False, json_mode=True, require_user=False)
        assert ctx.user_dir == dd / "users" / "newuser"

    def test_backup_created_on_commit(self, tmp_path):
        dd = self._setup(tmp_path)
        ctx = shared.EditContext(data_dir=dd, uid="u1", commit=True, json_mode=True)
        ctx.run(action="test", plan={}, apply_fn=lambda: {"ok": True})
        backup_dir = dd / "_ops_backups"
        assert backup_dir.exists()
        assert any(backup_dir.iterdir())


# ── _world_snapshot_members ──────────────────────────────────────────────


class TestWorldSnapshotMembers:
    def test_excludes(self, tmp_path):
        (tmp_path / "users.json").write_text("{}")
        (tmp_path / "_ops_backups").mkdir()
        (tmp_path / "_ops_world_backups").mkdir()
        (tmp_path / "_ops_edit_audit.jsonl").write_text("")
        (tmp_path / "users.json.lock").write_text("")
        members = shared._world_snapshot_members(tmp_path)
        names = {m.name for m in members}
        assert "_ops_backups" not in names
        assert "_ops_world_backups" not in names
        assert "users.json" in names


# ── _read_json_member ────────────────────────────────────────────────────


class TestReadJsonMember:
    def test_missing(self, tmp_path):
        import tarfile
        from io import BytesIO
        p = tmp_path / "test.tar"
        with tarfile.open(p, "w") as tar:
            data = b"hello"
            info = tarfile.TarInfo(name="a.txt")
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
        with tarfile.open(p, "r") as tar:
            assert shared._read_json_member(tar, "no.json") is None

    def test_valid(self, tmp_path):
        import tarfile
        from io import BytesIO
        p = tmp_path / "test.tar"
        with tarfile.open(p, "w") as tar:
            data = json.dumps({"key": "val"}).encode()
            info = tarfile.TarInfo(name="data.json")
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
        with tarfile.open(p, "r") as tar:
            result = shared._read_json_member(tar, "data.json")
            assert result == {"key": "val"}
