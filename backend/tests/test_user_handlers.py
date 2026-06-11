from __future__ import annotations

import json
from unittest.mock import MagicMock

from kg.api_models import (
    AutoLinkConfig,
    ReviewClockConfig,
    ReviewModeConfig,
    TranslationLanguageConfig,
    UserConfigRequest,
    VocabUIConfig,
)

# ===========================================================================
# _merge_user_config  (tested indirectly via module import)
# ===========================================================================
from kg.user_handlers import (
    _build_user_config_response,
    _merge_user_config,
    delete_user_account_response,
    health_response,
    update_user_config_response,
)
from kg.user_store import collect_account_ids_for_deletion


class TestMergeUserConfig:

    def test_translation_merge(self):
        config = {}
        req = UserConfigRequest(
            translation=TranslationLanguageConfig(source_lang="en", target_lang="ja")
        )
        _merge_user_config(config, req)
        assert config["translation"] == {"source_lang": "en", "target_lang": "ja", "updated_at": None}

    def test_no_update_when_translation_none(self):
        config = {"translation": {"source_lang": "en", "target_lang": "ja"}}
        req = UserConfigRequest(translation=None)
        _merge_user_config(config, req)
        assert config["translation"] == {"source_lang": "en", "target_lang": "ja"}

    def test_translation_overwrites_existing(self):
        config = {"translation": {"source_lang": "en", "target_lang": "ja"}}
        req = UserConfigRequest(
            translation=TranslationLanguageConfig(source_lang="en", target_lang="ko")
        )
        _merge_user_config(config, req)
        assert config["translation"] == {"source_lang": "en", "target_lang": "ko", "updated_at": None}

    def test_translation_merge_with_updated_at(self):
        # LWW 時戳隨 group 一起寫入（對齊 review_mode / vocab_ui 家族）。
        config = {}
        req = UserConfigRequest(
            translation=TranslationLanguageConfig(
                source_lang="en", target_lang="ja", updated_at=1717668000.0
            )
        )
        _merge_user_config(config, req)
        assert config["translation"] == {
            "source_lang": "en",
            "target_lang": "ja",
            "updated_at": 1717668000.0,
        }


class TestBuildUserConfigTranslation:
    """translation 三層後端化:source/target 偏好 + 單一 group updated_at 驅動整組 LWW。"""

    def test_build_includes_translation_updated_at(self):
        config = {"translation": {"source_lang": "en", "target_lang": "ja", "updated_at": 3.0}}
        resp = _build_user_config_response(config)
        assert resp.translation.source_lang == "en"
        assert resp.translation.target_lang == "ja"
        assert resp.translation.updated_at == 3.0

    def test_build_translation_default_updated_at_none(self):
        # 向後相容:既有 users.json 的 translation blob 無 updated_at → None,不炸。
        resp = _build_user_config_response({"translation": {"source_lang": "en", "target_lang": "ja"}})
        assert resp.translation.updated_at is None
        # 完全無 translation 時亦回 default config + updated_at None。
        assert _build_user_config_response({}).translation.updated_at is None


class TestMergeUserConfigReviewClock:
    """review_clock 後端化:per-user 全局複習時鐘暫停態(is_paused + paused_at 複合,
    單一 updated_at 驅動 LWW)。merge 正規化保證原子一致:resume 時 paused_at 清空。"""

    def test_merge_paused(self):
        config = {}
        req = UserConfigRequest(
            review_clock=ReviewClockConfig(
                is_paused=True, paused_at="2026-06-06T10:00:00Z", updated_at=1717668000.0
            )
        )
        _merge_user_config(config, req)
        assert config["review_clock"] == {
            "is_paused": True,
            "paused_at": "2026-06-06T10:00:00Z",
            "updated_at": 1717668000.0,
        }

    def test_resume_normalizes_paused_at_to_none(self):
        # is_paused=False 時 paused_at 必須被正規化清空,否則儲存層自相矛盾。
        config = {}
        req = UserConfigRequest(
            review_clock=ReviewClockConfig(
                is_paused=False, paused_at="2026-06-06T10:00:00Z", updated_at=1717668100.0
            )
        )
        _merge_user_config(config, req)
        assert config["review_clock"]["is_paused"] is False
        assert config["review_clock"]["paused_at"] is None
        assert config["review_clock"]["updated_at"] == 1717668100.0

    def test_none_preserves_existing(self):
        existing = {"is_paused": True, "paused_at": "2026-06-06T10:00:00Z", "updated_at": 1.0}
        config = {"review_clock": dict(existing)}
        _merge_user_config(config, UserConfigRequest(review_clock=None))
        assert config["review_clock"] == existing

    def test_independent_of_translation(self):
        config = {}
        req = UserConfigRequest(
            translation=TranslationLanguageConfig(source_lang="en", target_lang="ja"),
            review_clock=ReviewClockConfig(
                is_paused=True, paused_at="2026-06-06T10:00:00Z", updated_at=2.0
            ),
        )
        _merge_user_config(config, req)
        assert config["translation"] == {"source_lang": "en", "target_lang": "ja", "updated_at": None}
        assert config["review_clock"]["is_paused"] is True


class TestBuildUserConfigReviewClock:

    def test_build_includes_review_clock(self):
        config = {"review_clock": {
            "is_paused": True, "paused_at": "2026-06-06T10:00:00Z", "updated_at": 3.0,
        }}
        resp = _build_user_config_response(config)
        assert resp.review_clock is not None
        assert resp.review_clock.is_paused is True
        assert resp.review_clock.paused_at == "2026-06-06T10:00:00Z"
        assert resp.review_clock.updated_at == 3.0

    def test_build_defaults_when_absent(self):
        resp = _build_user_config_response({})
        assert resp.review_clock is not None
        assert resp.review_clock.is_paused is False
        assert resp.review_clock.paused_at is None


class TestUpdateUserConfigReviewClockRoundTrip:

    def test_persists_review_clock_alongside_translation(self, tmp_path):
        import copy

        # store 模擬持久層:load 回獨立副本、save 寫回,避免 handler 直接 mutate
        # 持久 dict(真實 load_users 從 users.json 反序列化,本就是新物件)。
        store = {"u1": {"config": {"translation": {"source_lang": "en", "target_lang": "ja"}}}}

        def load_users():
            return copy.deepcopy(store)

        def save_users(updated):
            store.clear()
            store.update(copy.deepcopy(updated))

        req = UserConfigRequest(
            review_clock=ReviewClockConfig(
                is_paused=True, paused_at="2026-06-06T10:00:00Z", updated_at=5.0
            )
        )
        resp = update_user_config_response(
            req, {"id": "u1"},
            users_lock_file=tmp_path / "users.json.lock",
            load_users=load_users,
            save_users=save_users,
        )
        assert resp.review_clock.is_paused is True
        assert resp.translation.target_lang == "ja"  # 既有 translation 不被破壞
        assert store["u1"]["config"]["review_clock"]["is_paused"] is True


class TestMergeUserConfigReviewMode:
    """review_mode 後端化:複習模式 + 自訂 SRS 參數(mode + 5 custom_* 複合,單一
    updated_at 驅動 LWW)。custom 值即使非 custom 模式仍保存;非法 mode 正規化為 relaxed。"""

    def test_merge_custom(self):
        config = {}
        req = UserConfigRequest(
            review_mode=ReviewModeConfig(
                mode="custom",
                custom_initial_interval_hours=10.0,
                custom_remembered_multiplier=2.2,
                custom_forgot_multiplier=0.4,
                custom_minimum_interval_hours=5.0,
                custom_maximum_interval_hours=2000.0,
                updated_at=1717668000.0,
            )
        )
        _merge_user_config(config, req)
        assert config["review_mode"] == {
            "mode": "custom",
            "custom_initial_interval_hours": 10.0,
            "custom_remembered_multiplier": 2.2,
            "custom_forgot_multiplier": 0.4,
            "custom_minimum_interval_hours": 5.0,
            "custom_maximum_interval_hours": 2000.0,
            "updated_at": 1717668000.0,
        }

    def test_invalid_mode_normalized_to_relaxed(self):
        # 非法 mode 由 validator 正規化,避免儲存層留下 client 不認得的值。
        config = {}
        req = UserConfigRequest(review_mode=ReviewModeConfig(mode="garbage", updated_at=1.0))
        _merge_user_config(config, req)
        assert config["review_mode"]["mode"] == "relaxed"

    def test_none_preserves_existing(self):
        existing = {
            "mode": "intensive",
            "custom_initial_interval_hours": 8.0,
            "custom_remembered_multiplier": 1.5,
            "custom_forgot_multiplier": 0.4,
            "custom_minimum_interval_hours": 4.0,
            "custom_maximum_interval_hours": 1440.0,
            "updated_at": 1.0,
        }
        config = {"review_mode": dict(existing)}
        _merge_user_config(config, UserConfigRequest(review_mode=None))
        assert config["review_mode"] == existing

    def test_independent_of_other_config(self):
        config = {}
        req = UserConfigRequest(
            translation=TranslationLanguageConfig(source_lang="en", target_lang="ja"),
            review_clock=ReviewClockConfig(
                is_paused=True, paused_at="2026-06-06T10:00:00Z", updated_at=2.0
            ),
            review_mode=ReviewModeConfig(mode="intensive", updated_at=3.0),
        )
        _merge_user_config(config, req)
        assert config["translation"]["target_lang"] == "ja"
        assert config["review_clock"]["is_paused"] is True
        assert config["review_mode"]["mode"] == "intensive"


class TestBuildUserConfigReviewMode:

    def test_build_includes_review_mode(self):
        config = {"review_mode": {
            "mode": "custom",
            "custom_initial_interval_hours": 10.0,
            "custom_remembered_multiplier": 2.2,
            "custom_forgot_multiplier": 0.4,
            "custom_minimum_interval_hours": 5.0,
            "custom_maximum_interval_hours": 2000.0,
            "updated_at": 3.0,
        }}
        resp = _build_user_config_response(config)
        assert resp.review_mode is not None
        assert resp.review_mode.mode == "custom"
        assert resp.review_mode.custom_initial_interval_hours == 10.0
        assert resp.review_mode.custom_maximum_interval_hours == 2000.0
        assert resp.review_mode.updated_at == 3.0

    def test_build_defaults_when_absent(self):
        resp = _build_user_config_response({})
        assert resp.review_mode is not None
        assert resp.review_mode.mode == "relaxed"
        assert resp.review_mode.custom_initial_interval_hours == 12
        assert resp.review_mode.updated_at is None


class TestUpdateUserConfigReviewModeRoundTrip:

    def test_persists_review_mode_alongside_translation(self, tmp_path):
        import copy

        store = {"u1": {"config": {"translation": {"source_lang": "en", "target_lang": "ja"}}}}

        def load_users():
            return copy.deepcopy(store)

        def save_users(updated):
            store.clear()
            store.update(copy.deepcopy(updated))

        req = UserConfigRequest(
            review_mode=ReviewModeConfig(mode="intensive", updated_at=5.0)
        )
        resp = update_user_config_response(
            req, {"id": "u1"},
            users_lock_file=tmp_path / "users.json.lock",
            load_users=load_users,
            save_users=save_users,
        )
        assert resp.review_mode.mode == "intensive"
        assert resp.translation.target_lang == "ja"  # 既有 translation 不被破壞
        assert store["u1"]["config"]["review_mode"]["mode"] == "intensive"


class TestMergeUserConfigVocabUI:
    """vocab_ui 後端化:全域 active notebook 游標(active_notebook_id + updated_at 驅動
    跨裝置 LWW),決定新選詞的預設歸屬。對 client 寬鬆:stale id(指向已刪 notebook)由各
    client 自行 reconcile,後端此階段 passthrough 不驗存在性(與其他 group 一致)。"""

    def test_merge(self):
        config = {}
        req = UserConfigRequest(
            vocab_ui=VocabUIConfig(active_notebook_id="nb-42", updated_at=1717668000.0)
        )
        _merge_user_config(config, req)
        assert config["vocab_ui"] == {
            "active_notebook_id": "nb-42",
            "updated_at": 1717668000.0,
        }

    def test_none_preserves_existing(self):
        existing = {"active_notebook_id": "nb-7", "updated_at": 1.0}
        config = {"vocab_ui": dict(existing)}
        _merge_user_config(config, UserConfigRequest(vocab_ui=None))
        assert config["vocab_ui"] == existing

    def test_independent_of_other_config(self):
        config = {}
        req = UserConfigRequest(
            translation=TranslationLanguageConfig(source_lang="en", target_lang="ja"),
            review_mode=ReviewModeConfig(mode="intensive", updated_at=3.0),
            vocab_ui=VocabUIConfig(active_notebook_id="nb-9", updated_at=4.0),
        )
        _merge_user_config(config, req)
        assert config["translation"]["target_lang"] == "ja"
        assert config["review_mode"]["mode"] == "intensive"
        assert config["vocab_ui"]["active_notebook_id"] == "nb-9"


class TestBuildUserConfigVocabUI:

    def test_build_includes_vocab_ui(self):
        config = {"vocab_ui": {"active_notebook_id": "nb-42", "updated_at": 3.0}}
        resp = _build_user_config_response(config)
        assert resp.vocab_ui is not None
        assert resp.vocab_ui.active_notebook_id == "nb-42"
        assert resp.vocab_ui.updated_at == 3.0

    def test_build_defaults_when_absent(self):
        resp = _build_user_config_response({})
        assert resp.vocab_ui is not None
        assert resp.vocab_ui.active_notebook_id == "default"
        assert resp.vocab_ui.updated_at is None


class TestUpdateUserConfigVocabUIRoundTrip:

    def test_persists_vocab_ui_alongside_translation(self, tmp_path):
        import copy

        store = {"u1": {"config": {"translation": {"source_lang": "en", "target_lang": "ja"}}}}

        def load_users():
            return copy.deepcopy(store)

        def save_users(updated):
            store.clear()
            store.update(copy.deepcopy(updated))

        req = UserConfigRequest(
            vocab_ui=VocabUIConfig(active_notebook_id="nb-99", updated_at=5.0)
        )
        resp = update_user_config_response(
            req, {"id": "u1"},
            users_lock_file=tmp_path / "users.json.lock",
            load_users=load_users,
            save_users=save_users,
        )
        assert resp.vocab_ui.active_notebook_id == "nb-99"
        assert resp.translation.target_lang == "ja"  # 既有 translation 不被破壞
        assert store["u1"]["config"]["vocab_ui"]["active_notebook_id"] == "nb-99"


class TestMergeUserConfigAutoLink:
    """auto_link 後端化:judge pipeline 自動連結開關(enabled + updated_at 驅動跨裝置
    LWW)。預設 enabled=True 向後相容:既有帳號無此 group 視同開啟。"""

    def test_merge_disabled(self):
        config = {}
        req = UserConfigRequest(
            auto_link=AutoLinkConfig(enabled=False, updated_at=1717668000.0)
        )
        _merge_user_config(config, req)
        assert config["auto_link"] == {
            "enabled": False,
            "updated_at": 1717668000.0,
        }

    def test_none_preserves_existing(self):
        existing = {"enabled": False, "updated_at": 1.0}
        config = {"auto_link": dict(existing)}
        _merge_user_config(config, UserConfigRequest(auto_link=None))
        assert config["auto_link"] == existing

    def test_independent_of_other_config(self):
        config = {}
        req = UserConfigRequest(
            vocab_ui=VocabUIConfig(active_notebook_id="nb-9", updated_at=4.0),
            auto_link=AutoLinkConfig(enabled=False, updated_at=5.0),
        )
        _merge_user_config(config, req)
        assert config["vocab_ui"]["active_notebook_id"] == "nb-9"
        assert config["auto_link"]["enabled"] is False


class TestBuildUserConfigAutoLink:

    def test_build_includes_auto_link(self):
        config = {"auto_link": {"enabled": False, "updated_at": 3.0}}
        resp = _build_user_config_response(config)
        assert resp.auto_link is not None
        assert resp.auto_link.enabled is False
        assert resp.auto_link.updated_at == 3.0

    def test_build_defaults_enabled_when_absent(self):
        # 向後相容:既有帳號 config 無 auto_link → 預設開啟。
        resp = _build_user_config_response({})
        assert resp.auto_link is not None
        assert resp.auto_link.enabled is True
        assert resp.auto_link.updated_at is None

    def test_non_dict_auto_link_returns_default(self):
        for bad_value in [42, "broken", True, [], None]:
            resp = _build_user_config_response({"auto_link": bad_value})
            assert resp.auto_link is not None, f"Failed for auto_link={bad_value!r}"
            assert resp.auto_link.enabled is True


class TestUpdateUserConfigAutoLinkRoundTrip:

    def test_persists_auto_link_alongside_translation(self, tmp_path):
        import copy

        store = {"u1": {"config": {"translation": {"source_lang": "en", "target_lang": "ja"}}}}

        def load_users():
            return copy.deepcopy(store)

        def save_users(updated):
            store.clear()
            store.update(copy.deepcopy(updated))

        req = UserConfigRequest(
            auto_link=AutoLinkConfig(enabled=False, updated_at=5.0)
        )
        resp = update_user_config_response(
            req, {"id": "u1"},
            users_lock_file=tmp_path / "users.json.lock",
            load_users=load_users,
            save_users=save_users,
        )
        assert resp.auto_link.enabled is False
        assert resp.translation.target_lang == "ja"  # 既有 translation 不被破壞
        assert store["u1"]["config"]["auto_link"]["enabled"] is False


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

    def test_deletion_marks_ids_terminated(self, tmp_path):
        """Account deletion must mark every purged id in `_terminated` so the
        revocation watermark becomes irreversible (cannot be cleared by a
        later login)."""
        users_data = {
            "canonical": {"linked_ids": ["linked1"], "config": {}},
            "linked1": {"_linked_to": "canonical"},
        }
        user = {"id": "linked1"}
        self._call_delete(tmp_path, user, users_data)

        saved = json.loads((tmp_path / "users.json").read_text())
        terminated = set(saved.get("_terminated", []))
        assert {"canonical", "linked1"}.issubset(terminated)


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
        cards_path = user_dir / "cards.db"
        cards_path.write_bytes(b"")

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
