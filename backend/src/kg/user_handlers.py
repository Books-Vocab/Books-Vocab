from __future__ import annotations

import contextlib
import shutil
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from filelock import FileLock

from .api_models import (
    AutoLinkConfig,
    DeleteAccountResponse,
    EntitlementsResponse,
    HealthResponse,
    ReviewClockConfig,
    ReviewModeConfig,
    TranslationLanguageConfig,
    UserConfigRequest,
    UserConfigResponse,
    VocabUIConfig,
)
from .types import StoredUserRecord, UserRecord, UsersPayload


def _build_user_config_response(config: dict[str, Any]) -> UserConfigResponse:
    translation_data = config.get("translation")
    if isinstance(translation_data, dict):
        translation = TranslationLanguageConfig(
            source_lang=translation_data.get("source_lang", "en"),
            target_lang=translation_data.get("target_lang", "zh-Hant"),
            updated_at=translation_data.get("updated_at"),
        )
    else:
        translation = TranslationLanguageConfig()

    clock_data = config.get("review_clock")
    if isinstance(clock_data, dict):
        review_clock = ReviewClockConfig(
            is_paused=bool(clock_data.get("is_paused", False)),
            paused_at=clock_data.get("paused_at"),
            updated_at=clock_data.get("updated_at"),
        )
    else:
        review_clock = ReviewClockConfig()

    mode_data = config.get("review_mode")
    if isinstance(mode_data, dict):
        review_mode = ReviewModeConfig(
            mode=mode_data.get("mode", "relaxed"),
            custom_initial_interval_hours=mode_data.get("custom_initial_interval_hours", 12),
            custom_remembered_multiplier=mode_data.get("custom_remembered_multiplier", 1.9),
            custom_forgot_multiplier=mode_data.get("custom_forgot_multiplier", 0.45),
            custom_minimum_interval_hours=mode_data.get("custom_minimum_interval_hours", 6),
            custom_maximum_interval_hours=mode_data.get("custom_maximum_interval_hours", 1440),
            updated_at=mode_data.get("updated_at"),
        )
    else:
        review_mode = ReviewModeConfig()

    vu_data = config.get("vocab_ui")
    if isinstance(vu_data, dict):
        vocab_ui = VocabUIConfig(
            active_notebook_id=vu_data.get("active_notebook_id", "default"),
            updated_at=vu_data.get("updated_at"),
        )
    else:
        vocab_ui = VocabUIConfig()

    al_data = config.get("auto_link")
    if isinstance(al_data, dict):
        auto_link = AutoLinkConfig(
            enabled=bool(al_data.get("enabled", True)),
            updated_at=al_data.get("updated_at"),
        )
    else:
        auto_link = AutoLinkConfig()

    return UserConfigResponse(
        translation=translation,
        review_clock=review_clock,
        review_mode=review_mode,
        vocab_ui=vocab_ui,
        auto_link=auto_link,
    )


def _merge_user_config(config: dict[str, Any], req: UserConfigRequest) -> None:
    # Translation config（source+target 偏好 + 單一 group updated_at 整組 LWW）。
    # 用 `is not None` 對齊其他 group（有送=更新, None=不動既有）；統一語意並消除
    # 「未來 model 變得可 falsy 就誤略過」的隱患（現 model 全 default 不會 falsy）。
    if req.translation is not None:
        config["translation"] = {
            "source_lang": req.translation.source_lang,
            "target_lang": req.translation.target_lang,
            "updated_at": req.translation.updated_at,
        }
    # Review clock (pause state). 複合原子;resume 時 paused_at 已由 ReviewClockConfig
    # validator 正規化為 None。只在 client 有送 review_clock 時更新(None = 不動既有)。
    if req.review_clock is not None:
        rc = req.review_clock
        config["review_clock"] = {
            "is_paused": rc.is_paused,
            "paused_at": rc.paused_at,
            "updated_at": rc.updated_at,
        }
    # Review mode + 自訂 SRS 參數。複合原子(mode + 5 custom_* 共用單一 updated_at);
    # 非法 mode 已由 ReviewModeConfig validator 正規化。只在 client 有送時更新(None = 不動既有)。
    if req.review_mode is not None:
        rm = req.review_mode
        config["review_mode"] = {
            "mode": rm.mode,
            "custom_initial_interval_hours": rm.custom_initial_interval_hours,
            "custom_remembered_multiplier": rm.custom_remembered_multiplier,
            "custom_forgot_multiplier": rm.custom_forgot_multiplier,
            "custom_minimum_interval_hours": rm.custom_minimum_interval_hours,
            "custom_maximum_interval_hours": rm.custom_maximum_interval_hours,
            "updated_at": rm.updated_at,
        }
    # Vocab UI(目前僅全域 active notebook 游標)。決定新選詞歸屬;單一 updated_at 驅動
    # 整組跨裝置 LWW。只在 client 有送時更新(None = 不動既有);stale id 由各 client
    # reconcile(後端此階段 passthrough,不驗 notebook 存在性,與其他 group 一致)。
    if req.vocab_ui is not None:
        vu = req.vocab_ui
        config["vocab_ui"] = {
            "active_notebook_id": vu.active_notebook_id,
            "updated_at": vu.updated_at,
        }
    # Auto-link(judge pipeline 自動連結)開關。單一 updated_at 驅動整組 LWW。
    # 只在 client 有送時更新(None = 不動既有);缺省讀取端 fallback enabled=True。
    if req.auto_link is not None:
        config["auto_link"] = {
            "enabled": req.auto_link.enabled,
            "updated_at": req.auto_link.updated_at,
        }


def get_user_config_response(user: UserRecord) -> UserConfigResponse:
    return _build_user_config_response(user["config"])


def get_user_entitlements_response(
    user: UserRecord,
    *,
    build_entitlements_response: Callable[[StoredUserRecord | None], EntitlementsResponse],
) -> EntitlementsResponse:
    return build_entitlements_response(user.get("record"))


def update_user_config_response(
    req: UserConfigRequest,
    user: UserRecord,
    *,
    users_lock_file: Path,
    load_users: Callable[[], UsersPayload],
    save_users: Callable[[UsersPayload], None],
) -> UserConfigResponse:
    with FileLock(str(users_lock_file)):
        users = load_users()
        user_id = user["id"]

        if user_id not in users:
            users[user_id] = {}

        if "config" not in users[user_id]:
            users[user_id]["config"] = {}

        _merge_user_config(users[user_id]["config"], req)

        save_users(users)

    return _build_user_config_response(users[user_id]["config"])


def delete_user_account_response(
    user: UserRecord,
    *,
    users_lock_file: Path,
    load_users: Callable[[], UsersPayload],
    save_users: Callable[[UsersPayload], None],
    collect_account_ids_for_deletion: Callable[[UsersPayload, str], tuple[str, list[str]]],
    data_dir: Path,
    logger: Logger,
) -> DeleteAccountResponse:
    now_iso = datetime.now(tz=UTC).isoformat()
    user_id = user["id"]

    with FileLock(str(users_lock_file)):
        users = load_users()
        canonical_id, ids_to_delete = collect_account_ids_for_deletion(users, user_id)

        revoked_before = users.get("_revoked_before")
        if not isinstance(revoked_before, dict):
            revoked_before = {}
        for uid in ids_to_delete:
            revoked_before[uid] = now_iso
        users["_revoked_before"] = revoked_before

        # Mark every purged id as permanently terminated. This makes the
        # revocation watermark irreversible: a later login (even with the
        # same sub, or the same email via another provider) must NOT be able
        # to clear `_revoked_before` for these ids — see resolve_and_link_user.
        terminated = users.get("_terminated")
        terminated_ids = set(terminated) if isinstance(terminated, list) else set()
        terminated_ids.update(ids_to_delete)
        users["_terminated"] = sorted(terminated_ids)

        email_index = users.get("_email_index")
        if isinstance(email_index, dict):
            stale_emails = [email for email, mapped_uid in email_index.items() if mapped_uid in ids_to_delete]
            for email in stale_emails:
                email_index.pop(email, None)
            if not email_index:
                users.pop("_email_index", None)

        for uid in ids_to_delete:
            users.pop(uid, None)

        save_users(users)

    deleted_dirs: list[str] = []
    for uid in ids_to_delete:
        user_dir = data_dir / "users" / uid
        if not user_dir.exists():
            continue
        try:
            shutil.rmtree(user_dir)
            deleted_dirs.append(uid)
        except OSError as exc:
            logger.exception("Failed to delete user directory %s: %s", user_dir, exc)
            raise HTTPException(status_code=500, detail=f"Failed to remove user data for {uid}") from exc

    logger.warning(
        "Account deletion: uid=%s canonical=%s ids=%s dirs=%s",
        user_id,
        canonical_id,
        ids_to_delete,
        deleted_dirs,
    )

    return DeleteAccountResponse(
        deleted_user_id=canonical_id,
        linked_ids=[uid for uid in ids_to_delete if uid != canonical_id],
        deleted_dirs=deleted_dirs,
    )


def health_response(
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[[Path], Any],
) -> HealthResponse:
    user_dir: Path = user["dir"]
    cards = card_store_factory(user_dir)
    graph = graph_store_factory(user_dir)

    cards_path = user_dir / "cards.db"
    last_mod = None
    if cards_path.exists():
        ts = cards_path.stat().st_mtime
        last_mod = datetime.fromtimestamp(ts, tz=UTC).isoformat()

    db_ok = True
    try:
        cards.count()
    except (OSError, sqlite3.DatabaseError):
        db_ok = False

    data_dir_exists = user_dir.exists()

    disk_free_mb: int | None = None
    with contextlib.suppress(OSError):
        disk_free_mb = shutil.disk_usage(user_dir).free // (1024 * 1024)

    return HealthResponse(
        status="ok",
        cards=cards.count(),
        links=graph.link_count(),
        pendingCandidates=graph.candidate_count(),
        lastModified=last_mod,
        db_ok=db_ok,
        disk_free_mb=disk_free_mb,
        data_dir_exists=data_dir_exists,
    )
