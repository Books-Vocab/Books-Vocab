from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from filelock import FileLock

from .api_models import AdminGrantRequest, AdminGrantStatusResponse, AdminUserEntitlementResponse
from .exceptions import NotFoundError
from .user_store import resolve_mochi_api_key_from_config


ADMIN_COOKIE_NAME = "admin_session"


def _sign_cookie(admin_token: str) -> str:
    return hmac.new(admin_token.encode(), b"admin_session", "sha256").hexdigest()


def _verify_cookie(cookie_value: str, admin_token: str) -> bool:
    if not admin_token or not cookie_value:
        return False
    return hmac.compare_digest(cookie_value, _sign_cookie(admin_token))


def _resolve_admin_token(token: str | None, authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if token:
        logger.warning("Admin token via URL query param is deprecated, use Authorization header")
        return token
    return None


def require_admin(
    token: str | None,
    *,
    admin_token: str,
    authorization: str | None = None,
    cookie_token: str | None = None,
) -> None:
    if not admin_token:
        raise HTTPException(403, "ADMIN_TOKEN not configured")
    resolved = _resolve_admin_token(token, authorization)
    if resolved is not None:
        if not hmac.compare_digest(resolved, admin_token):
            raise HTTPException(403, "Forbidden")
        return
    if cookie_token and _verify_cookie(cookie_token, admin_token):
        return
    raise HTTPException(403, "Forbidden")


def _set_admin_cookie(response: HTMLResponse, admin_token: str) -> HTMLResponse:
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=_sign_cookie(admin_token),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/admin",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


def admin_ui_response(
    *,
    admin_token: str,
    admin_html: str,
) -> HTMLResponse:
    return _set_admin_cookie(HTMLResponse(admin_html), admin_token)


def admin_stats_response(
    *,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    get_all_stats: Callable[[], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    data_dir: Any,
    card_store_factory: Callable[[Any], Any],
    jwt_secret: str = "",
) -> dict[str, Any]:
    from .quota_service import get_all_quota_usage, token_cost_usd

    users_data = load_users()
    token_stats = get_all_stats()
    quota_usage = get_all_quota_usage()

    result = []
    for uid, info in users_data.items():
        if uid.startswith("_"):
            continue

        user_dir = data_dir / "users" / uid
        vocab_count = 0
        try:
            store = card_store_factory(user_dir)
            vocab_count = store.count()
        except (OSError, ValueError):
            logger.warning("Failed to load card store for user %s", uid, exc_info=True)

        utoken = token_stats.get(uid, {})
        total_input = sum(d["input_tokens"] for d in utoken.values())
        total_output = sum(d["output_tokens"] for d in utoken.values())

        est_cost = sum(
            token_cost_usd(call_type, data["input_tokens"], data["output_tokens"])
            for call_type, data in utoken.items()
        )

        config = info.get("config", {}) if isinstance(info, dict) else {}
        entitlements = build_entitlements_response(info if isinstance(info, dict) else None)
        admin_grant = current_admin_grant_record(info if isinstance(info, dict) else None)
        result.append(
            {
                "user_id": uid,
                "email": info.get("email") if isinstance(info, dict) else None,
                "provider": info.get("provider") if isinstance(info, dict) else None,
                "last_login": info.get("last_login") if isinstance(info, dict) else None,
                "vocab_count": vocab_count,
                "has_mochi": bool(resolve_mochi_api_key_from_config(config, jwt_secret)),
                "tokens": utoken,
                "total_input": total_input,
                "total_output": total_output,
                "est_cost_usd": round(est_cost, 6),
                "pro": entitlements.pro.model_dump(),
                "admin_grant": admin_grant,
                "quota": quota_usage.get(uid, {"used_usd": 0.0, "limit_usd": 0.30, "fraction_used": 0.0, "calls": {}}),
            }
        )

    result.sort(key=lambda item: item["vocab_count"], reverse=True)
    return {"users": result}


def admin_logs_response(
    *,
    log_getter: Callable[..., list[dict[str, Any]]],
    n: int,
    level: str | None,
) -> dict[str, Any]:
    return {"logs": log_getter(n=n, level=level or None)}


def admin_run_tests_response(
    *,
    req: Any,
    run_pytest_matrix: Callable[..., dict[str, Any]],
    store_last_test_run: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    selected = req.itemIds if req else []
    return store_last_test_run(run_pytest_matrix(selected_items=selected))


def admin_last_test_run_response(
    *,
    get_last_test_run: Callable[[], dict[str, Any] | None],
) -> dict[str, Any]:
    last_run = get_last_test_run()
    if last_run is None:
        return {"status": "idle"}
    return last_run


def admin_test_catalog_response(
    *,
    build_test_catalog: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    return build_test_catalog()


def admin_tests_ui_response(
    *,
    admin_token: str,
    admin_tests_html: str,
) -> HTMLResponse:
    return _set_admin_cookie(HTMLResponse(admin_tests_html), admin_token)


def admin_user_entitlement_response(
    user_id: str,
    *,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
) -> AdminUserEntitlementResponse:
    users = load_users()
    record = users.get(user_id)
    if not isinstance(record, dict) or user_id.startswith("_"):
        raise NotFoundError("User", user_id)
    return AdminUserEntitlementResponse(
        user_id=user_id,
        pro=build_entitlements_response(record).pro,
        admin_grant=AdminGrantStatusResponse(**current_admin_grant_record(record)),
    )


def _mutate_admin_grant(
    user_id: str,
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    grant_updates: dict[str, Any] | None = None,
) -> AdminUserEntitlementResponse:
    """Shared logic for granting/revoking admin Pro access."""
    with FileLock(str(users_lock_file)):
        users = load_users()
        record = users.get(user_id)
        if not isinstance(record, dict) or user_id.startswith("_"):
            raise NotFoundError("User", user_id)

        admin_grant = current_admin_grant_record(record)
        if grant_updates:
            admin_grant.update(grant_updates)
        record["admin_grant"] = admin_grant
        save_users(users)

    return AdminUserEntitlementResponse(
        user_id=user_id,
        pro=build_entitlements_response(record).pro,
        admin_grant=AdminGrantStatusResponse(**admin_grant),
    )


def admin_grant_pro_access_response(
    user_id: str,
    req: AdminGrantRequest,
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
) -> AdminUserEntitlementResponse:
    now_iso = datetime.now(tz=UTC).isoformat()
    return _mutate_admin_grant(
        user_id,
        users_lock_file=users_lock_file,
        load_users=load_users, save_users=save_users,
        current_admin_grant_record=current_admin_grant_record,
        build_entitlements_response=build_entitlements_response,
        grant_updates={
            "is_active": True,
            "plan_name": "Books & Vocab Pro",
            "status": "active",
            "source": "admin",
            "expires_at": req.expires_at,
            "granted_at": now_iso,
            "granted_by": (req.granted_by or "admin").strip() or "admin",
            "reason": req.reason.strip() if isinstance(req.reason, str) and req.reason.strip() else None,
            "last_synced_at": now_iso,
        },
    )


def admin_revoke_pro_access_response(
    user_id: str,
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
) -> AdminUserEntitlementResponse:
    now_iso = datetime.now(tz=UTC).isoformat()
    return _mutate_admin_grant(
        user_id,
        users_lock_file=users_lock_file,
        load_users=load_users, save_users=save_users,
        current_admin_grant_record=current_admin_grant_record,
        build_entitlements_response=build_entitlements_response,
        grant_updates={
            "is_active": False,
            "status": "inactive",
            "source": "admin",
            "last_synced_at": now_iso,
        },
    )
