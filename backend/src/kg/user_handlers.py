from __future__ import annotations

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
    DeleteAccountResponse,
    EntitlementsResponse,
    HealthResponse,
    MochiIntegrationResponseConfig,
    TranslationLanguageConfig,
    UserConfigRequest,
    UserConfigResponse,
    UserIntegrationsResponseConfig,
)
from .user_store import resolve_mochi_api_key_from_config


def _build_user_config_response(config: dict[str, Any], jwt_secret: str = "") -> UserConfigResponse:
    mochi_api_key = resolve_mochi_api_key_from_config(config, jwt_secret)

    translation_data = config.get("translation")
    translation = None
    if isinstance(translation_data, dict):
        translation = TranslationLanguageConfig(
            source_lang=translation_data.get("source_lang", "en"),
            target_lang=translation_data.get("target_lang", "zh-Hant"),
        )

    return UserConfigResponse(
        integrations=UserIntegrationsResponseConfig(
            mochi=MochiIntegrationResponseConfig(has_api_key=True)
        ) if mochi_api_key else None,
        translation=translation,
    )


def _merge_user_config(config: dict[str, Any], req: UserConfigRequest) -> None:
    if req.integrations and req.integrations.mochi and req.integrations.mochi.api_key is not None:
        integrations = config.get("integrations")
        if not isinstance(integrations, dict):
            integrations = {}

        mochi = integrations.get("mochi")
        if not isinstance(mochi, dict):
            mochi = {}

        resolved_key = req.integrations.mochi.api_key.strip()
        if resolved_key:
            mochi["api_key"] = resolved_key
            integrations["mochi"] = mochi
            config["integrations"] = integrations
        else:
            mochi.pop("api_key", None)
            integrations.pop("mochi", None)
            if integrations:
                config["integrations"] = integrations
            else:
                config.pop("integrations", None)

    # Translation config
    if req.translation:
        config["translation"] = {
            "source_lang": req.translation.source_lang,
            "target_lang": req.translation.target_lang,
        }


def get_user_config_response(user: dict[str, Any], jwt_secret: str = "") -> UserConfigResponse:
    return _build_user_config_response(user["config"], jwt_secret)


def get_user_entitlements_response(
    user: dict[str, Any],
    *,
    build_entitlements_response: Callable[[dict[str, Any] | None], EntitlementsResponse],
) -> EntitlementsResponse:
    return build_entitlements_response(user.get("record"))


def update_user_config_response(
    req: UserConfigRequest,
    user: dict[str, Any],
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    jwt_secret: str = "",
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

    return _build_user_config_response(users[user_id]["config"], jwt_secret)


def delete_user_account_response(
    user: dict[str, Any],
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    collect_account_ids_for_deletion: Callable[[dict[str, dict[str, Any]], str], tuple[str, list[str]]],
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
    try:
        disk_free_mb = shutil.disk_usage(user_dir).free // (1024 * 1024)
    except OSError:
        pass

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
