from __future__ import annotations

import shutil
from datetime import datetime, timezone
from logging import Logger
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from filelock import FileLock

from .api_models import DeleteAccountResponse, EntitlementsResponse, HealthResponse, UserConfigRequest, UserConfigResponse


def _resolve_mochi_api_key(config: dict[str, Any]) -> str | None:
    integrations = config.get("integrations", {})
    if isinstance(integrations, dict):
        mochi = integrations.get("mochi", {})
        if isinstance(mochi, dict):
            nested = mochi.get("api_key")
            if isinstance(nested, str):
                nested = nested.strip()
                if nested:
                    return nested

    legacy = config.get("mochi_api_key")
    if isinstance(legacy, str):
        legacy = legacy.strip()
        if legacy:
            return legacy
    return None


def _build_user_config_response(config: dict[str, Any]) -> UserConfigResponse:
    mochi_api_key = _resolve_mochi_api_key(config)
    return UserConfigResponse(
        mochi_api_key=mochi_api_key,
        integrations={
            "mochi": {
                "api_key": mochi_api_key,
            }
        },
    )


def _merge_user_config(config: dict[str, Any], req: UserConfigRequest) -> None:
    integrations = config.get("integrations")
    if not isinstance(integrations, dict):
        integrations = {}

    mochi = integrations.get("mochi")
    if not isinstance(mochi, dict):
        mochi = {}

    nested_request_key = None
    if req.integrations and req.integrations.mochi:
        nested_request_key = req.integrations.mochi.api_key

    if req.mochi_api_key is not None:
        resolved_key = req.mochi_api_key.strip()
    elif nested_request_key is not None:
        resolved_key = nested_request_key.strip()
    else:
        config["integrations"] = integrations
        return

    config["mochi_api_key"] = resolved_key
    mochi["api_key"] = resolved_key
    integrations["mochi"] = mochi
    config["integrations"] = integrations


def get_user_config_response(user: dict[str, Any]) -> UserConfigResponse:
    return _build_user_config_response(user["config"])


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
    user: dict[str, Any],
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    collect_account_ids_for_deletion: Callable[[dict[str, dict[str, Any]], str], tuple[str, list[str]]],
    data_dir: Path,
    logger: Logger,
) -> DeleteAccountResponse:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
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
        except Exception as exc:
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
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"])

    cards_path = user["dir"] / "cards.json"
    last_mod = None
    if cards_path.exists():
        ts = cards_path.stat().st_mtime
        last_mod = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    return HealthResponse(
        status="ok",
        cards=cards.count(),
        links=graph.link_count(),
        pendingCandidates=graph.candidate_count(),
        lastModified=last_mod,
    )
