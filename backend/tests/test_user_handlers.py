from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kg.api_models import (
    MochiIntegrationConfig,
    UserConfigRequest,
    UserIntegrationsConfig,
)
from kg.user_handlers import delete_user_account_response, health_response
from kg.user_store import collect_account_ids_for_deletion


# ===========================================================================
# _merge_user_config  (tested indirectly via module import)
# ===========================================================================

from kg.user_handlers import _merge_user_config


class TestMergeUserConfig:

    def _req(self, api_key):
        return UserConfigRequest(
            integrations=UserIntegrationsConfig(
                mochi=MochiIntegrationConfig(api_key=api_key)
            )
        )

    def test_normal_merge_mochi_api_key(self):
        config = {}
        _merge_user_config(config, self._req("mk_abc"))
        assert config["integrations"]["mochi"]["api_key"] == "mk_abc"

    def test_whitespace_trimmed(self):
        config = {}
        _merge_user_config(config, self._req("  mk_trimmed  "))
        assert config["integrations"]["mochi"]["api_key"] == "mk_trimmed"

    def test_empty_string_deletes_key(self):
        config = {"integrations": {"mochi": {"api_key": "mk_old"}}}
        _merge_user_config(config, self._req(""))
        assert "mochi" not in config.get("integrations", {})

    def test_whitespace_only_string_deletes_key(self):
        config = {"integrations": {"mochi": {"api_key": "mk_old"}}}
        _merge_user_config(config, self._req("   "))
        assert "mochi" not in config.get("integrations", {})

    def test_no_update_when_integrations_none(self):
        config = {"integrations": {"mochi": {"api_key": "mk_keep"}}}
        req = UserConfigRequest(integrations=None)
        _merge_user_config(config, req)
        assert config["integrations"]["mochi"]["api_key"] == "mk_keep"

    def test_no_update_when_api_key_is_none(self):
        config = {"integrations": {"mochi": {"api_key": "mk_keep"}}}
        req = UserConfigRequest(
            integrations=UserIntegrationsConfig(
                mochi=MochiIntegrationConfig(api_key=None)
            )
        )
        _merge_user_config(config, req)
        assert config["integrations"]["mochi"]["api_key"] == "mk_keep"


# ===========================================================================
# delete_user_account_response
# ===========================================================================

class TestDeleteUserAccountResponse:

    def _make_users_file(self, tmp_path, data):
        f = tmp_path / "users.json"
        f.write_text(json.dumps(data))
        return f

    def _call_delete(self, tmp_path, user, users_data):
        users_file = self._make_users_file(tmp_path, users_data)
        lock_file = tmp_path / "users.json.lock"
        logger = MagicMock()

        def load_users():
            return json.loads(users_file.read_text())

        def save_users(u):
            users_file.write_text(json.dumps(u))

        return delete_user_account_response(
            user,
            users_lock_file=lock_file,
            load_users=load_users,
            save_users=save_users,
            collect_account_ids_for_deletion=collect_account_ids_for_deletion,
            data_dir=tmp_path,
            logger=logger,
        )

    def test_single_account_deletion_clears_user_and_email_index(self, tmp_path):
        user_dir = tmp_path / "users" / "u1"
        user_dir.mkdir(parents=True)
        (user_dir / "cards.db").write_text("dummy")

        users_data = {
            "u1": {"config": {}},
            "_email_index": {"user@example.com": "u1"},
        }
        user = {"id": "u1"}
        resp = self._call_delete(tmp_path, user, users_data)

        assert resp.deleted_user_id == "u1"
        assert "u1" in resp.deleted_dirs
        assert not user_dir.exists()

        saved = json.loads((tmp_path / "users.json").read_text())
        assert "u1" not in saved
        assert "_email_index" not in saved
        assert "u1" in saved["_revoked_before"]

    def test_linked_account_deletion_removes_all_related(self, tmp_path):
        for uid in ("canonical", "linked1"):
            (tmp_path / "users" / uid).mkdir(parents=True)

        users_data = {
            "canonical": {"linked_ids": ["linked1"], "config": {}},
            "linked1": {"_linked_to": "canonical"},
            "_email_index": {"x@example.com": "canonical"},
        }
        user = {"id": "linked1"}
        resp = self._call_delete(tmp_path, user, users_data)

        assert resp.deleted_user_id == "canonical"
        assert "linked1" in resp.linked_ids

        saved = json.loads((tmp_path / "users.json").read_text())
        assert "canonical" not in saved
        assert "linked1" not in saved
        assert "_email_index" not in saved
        assert "canonical" in saved["_revoked_before"]
        assert "linked1" in saved["_revoked_before"]
        assert not (tmp_path / "users" / "canonical").exists()
        assert not (tmp_path / "users" / "linked1").exists()

    def test_missing_directory_completes_normally(self, tmp_path):
        users_data = {"u1": {"config": {}}}
        user = {"id": "u1"}
        # 不建立 user_dir，確認不 crash
        resp = self._call_delete(tmp_path, user, users_data)
        assert resp.deleted_user_id == "u1"
        assert resp.deleted_dirs == []

    def test_revoked_before_timestamp_written(self, tmp_path):
        users_data = {"u1": {"config": {}}}
        user = {"id": "u1"}
        self._call_delete(tmp_path, user, users_data)

        saved = json.loads((tmp_path / "users.json").read_text())
        revoked = saved.get("_revoked_before", {})
        assert "u1" in revoked
        # 應為 ISO 格式字串
        from datetime import datetime
        dt = datetime.fromisoformat(revoked["u1"].replace("Z", "+00:00"))
        assert dt.year >= 2024


# ===========================================================================
# health_response
# ===========================================================================

class TestHealthResponse:

    def test_health_returns_correct_stats(self, tmp_path):
        cards_mock = MagicMock()
        cards_mock.count.return_value = 42
        graph_mock = MagicMock()
        graph_mock.link_count.return_value = 10
        graph_mock.candidate_count.return_value = 3

        user_dir = tmp_path / "user1"
        user_dir.mkdir()
        cards_path = user_dir / "cards.json"
        cards_path.write_text("{}")

        user = {"dir": user_dir}

        resp = health_response(
            user,
            card_store_factory=lambda d: cards_mock,
            graph_store_factory=lambda d: graph_mock,
        )

        assert resp.status == "ok"
        assert resp.cards == 42
        assert resp.links == 10
        assert resp.pendingCandidates == 3
        assert resp.lastModified is not None

    def test_health_last_modified_none_when_no_cards_file(self, tmp_path):
        cards_mock = MagicMock()
        cards_mock.count.return_value = 0
        graph_mock = MagicMock()
        graph_mock.link_count.return_value = 0
        graph_mock.candidate_count.return_value = 0

        user_dir = tmp_path / "user2"
        user_dir.mkdir()
        user = {"dir": user_dir}

        resp = health_response(
            user,
            card_store_factory=lambda d: cards_mock,
            graph_store_factory=lambda d: graph_mock,
        )

        assert resp.lastModified is None
