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
from .user_store import resolve_mochi_api_key_from_config


def _resolve_admin_token(token: str | None, authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if token:
        logger.warning("Admin token via URL query param is deprecated, use Authorization header")
        return token
    return None


def require_admin(token: str | None, *, admin_token: str, authorization: str | None = None) -> None:
    resolved = _resolve_admin_token(token, authorization)
    if not admin_token:
        raise HTTPException(403, "ADMIN_TOKEN not configured")
    if not hmac.compare_digest(resolved or "", admin_token):
        raise HTTPException(403, "Forbidden")


def admin_ui_response(token: str | None, *, admin_token: str, admin_html: str, authorization: str | None = None) -> HTMLResponse:
    # HTML shell pages are served without auth — all data requires authenticated API calls.
    # The token is passed via URL on initial visit and stored in sessionStorage by the JS.
    return HTMLResponse(admin_html)


def admin_stats_response(
    token: str | None,
    *,
    admin_token: str,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    get_all_stats: Callable[[], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    data_dir: Any,
    card_store_factory: Callable[[Any], Any],
    authorization: str | None = None,
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token, authorization=authorization)

    from .quota_service import get_all_quota_usage

    users_data = load_users()
    token_stats = get_all_stats()
    quota_usage = get_all_quota_usage()

    in_per_m = 0.10
    out_per_m = 0.40
    emb_per_m = 0.00025

    result = []
    for uid, info in users_data.items():
        if uid.startswith("_"):
            continue

        user_dir = data_dir / "users" / uid
        vocab_count = 0
        try:
            store = card_store_factory(user_dir)
            vocab_count = sum(1 for card in store.all() if not card.is_deleted)
        except (OSError, ValueError):
            logger.warning("Failed to load card store for user %s", uid, exc_info=True)

        utoken = token_stats.get(uid, {})
        total_input = sum(d["input_tokens"] for d in utoken.values())
        total_output = sum(d["output_tokens"] for d in utoken.values())

        est_cost = 0.0
        for call_type, data in utoken.items():
            if call_type == "embed":
                est_cost += (data["input_tokens"] / 1_000_000) * emb_per_m
            else:
                est_cost += (data["input_tokens"] / 1_000_000) * in_per_m
                est_cost += (data["output_tokens"] / 1_000_000) * out_per_m

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
                "has_mochi": bool(resolve_mochi_api_key_from_config(config)),
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
    token: str | None,
    *,
    admin_token: str,
    log_getter: Callable[..., list[dict[str, Any]]],
    n: int,
    level: str | None,
    authorization: str | None = None,
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    return {"logs": log_getter(n=n, level=level or None)}


def admin_run_tests_response(
    token: str | None,
    *,
    admin_token: str,
    req: Any,
    run_pytest_matrix: Callable[..., dict[str, Any]],
    store_last_test_run: Callable[[dict[str, Any]], dict[str, Any]],
    authorization: str | None = None,
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    selected = req.itemIds if req else []
    return store_last_test_run(run_pytest_matrix(selected_items=selected))


def admin_last_test_run_response(
    token: str | None,
    *,
    admin_token: str,
    get_last_test_run: Callable[[], dict[str, Any] | None],
    authorization: str | None = None,
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    last_run = get_last_test_run()
    if last_run is None:
        return {"status": "idle"}
    return last_run


def admin_test_catalog_response(
    token: str | None,
    *,
    admin_token: str,
    build_test_catalog: Callable[[], dict[str, Any]],
    authorization: str | None = None,
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    return build_test_catalog()


def admin_tests_ui_response(token: str | None, *, admin_token: str, admin_tests_html: str, authorization: str | None = None) -> HTMLResponse:
    return HTMLResponse(admin_tests_html)


def admin_user_entitlement_response(
    token: str | None,
    user_id: str,
    *,
    admin_token: str,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    authorization: str | None = None,
) -> AdminUserEntitlementResponse:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    users = load_users()
    record = users.get(user_id)
    if not isinstance(record, dict) or user_id.startswith("_"):
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserEntitlementResponse(
        user_id=user_id,
        pro=build_entitlements_response(record).pro,
        admin_grant=AdminGrantStatusResponse(**current_admin_grant_record(record)),
    )


def admin_grant_pro_access_response(
    token: str | None,
    user_id: str,
    req: AdminGrantRequest,
    *,
    admin_token: str,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    authorization: str | None = None,
) -> AdminUserEntitlementResponse:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    now_iso = datetime.now(tz=UTC).isoformat()

    with FileLock(str(users_lock_file)):
        users = load_users()
        record = users.get(user_id)
        if not isinstance(record, dict) or user_id.startswith("_"):
            raise HTTPException(status_code=404, detail="User not found")

        admin_grant = current_admin_grant_record(record)
        admin_grant.update(
            {
                "is_active": True,
                "plan_name": admin_grant.get("plan_name") or "Books & Vocab Pro",
                "status": "active",
                "source": "admin",
                "expires_at": req.expires_at,
                "granted_at": now_iso,
                "granted_by": (req.granted_by or "admin").strip() or "admin",
                "reason": req.reason.strip() if isinstance(req.reason, str) and req.reason.strip() else None,
                "last_synced_at": now_iso,
            }
        )
        record["admin_grant"] = admin_grant
        save_users(users)

    return AdminUserEntitlementResponse(
        user_id=user_id,
        pro=build_entitlements_response(record).pro,
        admin_grant=AdminGrantStatusResponse(**admin_grant),
    )


def admin_revoke_pro_access_response(
    token: str | None,
    user_id: str,
    *,
    admin_token: str,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    authorization: str | None = None,
) -> AdminUserEntitlementResponse:
    require_admin(token, admin_token=admin_token, authorization=authorization)
    now_iso = datetime.now(tz=UTC).isoformat()

    with FileLock(str(users_lock_file)):
        users = load_users()
        record = users.get(user_id)
        if not isinstance(record, dict) or user_id.startswith("_"):
            raise HTTPException(status_code=404, detail="User not found")

        admin_grant = current_admin_grant_record(record)
        admin_grant.update(
            {
                "is_active": False,
                "status": "inactive",
                "source": "admin",
                "last_synced_at": now_iso,
            }
        )
        record["admin_grant"] = admin_grant
        save_users(users)

    return AdminUserEntitlementResponse(
        user_id=user_id,
        pro=build_entitlements_response(record).pro,
        admin_grant=AdminGrantStatusResponse(**admin_grant),
    )
