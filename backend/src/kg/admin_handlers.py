from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from filelock import FileLock

from .api_models import AdminGrantRequest, AdminGrantStatusResponse, AdminUserEntitlementResponse
from .exceptions import NotFoundError


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
        path="/",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login</title>
<style>
body{{font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.card{{background:#fff;padding:2rem;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1);width:100%;max-width:360px}}
h1{{font-size:1.25rem;margin:0 0 1.5rem;text-align:center;color:#333}}
label{{display:block;margin-bottom:.5rem;font-size:.875rem;color:#555}}
input[type=password]{{width:100%;padding:.5rem;border:1px solid #ccc;border-radius:4px;font-size:1rem;box-sizing:border-box}}
button{{width:100%;padding:.625rem;margin-top:1rem;border:none;border-radius:4px;background:#333;color:#fff;font-size:1rem;cursor:pointer}}
button:hover{{background:#555}}
.error{{color:#c00;font-size:.875rem;margin-top:.75rem;text-align:center}}
.info{{color:#666;font-size:.875rem;margin-top:.75rem;text-align:center}}
</style></head><body>
<div class="card">
<h1>KG Admin</h1>
{content}
</div></body></html>"""


def admin_login_page(error: str = "", password_enabled: bool = True) -> HTMLResponse:
    """Render the admin login page."""
    if not password_enabled:
        content = '<p class="info">密碼登入未啟用，請使用 token 認證。</p>'
    else:
        import html as _html
        error_html = f'<p class="error">{_html.escape(error)}</p>' if error else ""
        content = (
            '<form method="post" action="/admin/login">'
            '<label for="password">管理員密碼</label>'
            '<input type="password" id="password" name="password" autofocus required>'
            '<button type="submit">登入</button>'
            f'{error_html}</form>'
        )
    return HTMLResponse(ADMIN_LOGIN_HTML.format(content=content))


def admin_login_post(password: str, *, admin_password: str, admin_token: str) -> HTMLResponse | RedirectResponse:
    """Verify password and redirect on success, or show error on failure."""
    if not admin_password:
        return HTMLResponse(
            ADMIN_LOGIN_HTML.format(content='<p class="error">密碼登入未啟用。</p>'),
            status_code=403,
        )
    if not hmac.compare_digest(password, admin_password):
        return admin_login_page(error="密碼錯誤，請重試。")
    resp = RedirectResponse("/admin", status_code=302)
    _set_admin_cookie(resp, admin_token)
    return resp


def check_admin_auth(
    *,
    token: str | None,
    authorization: str | None,
    cookie_token: str | None,
    admin_token: str,
) -> bool:
    """Return True if the request carries valid admin credentials, False otherwise."""
    if not admin_token:
        return False
    resolved = _resolve_admin_token(token, authorization)
    if resolved is not None:
        return hmac.compare_digest(resolved, admin_token)
    if cookie_token and _verify_cookie(cookie_token, admin_token):
        return True
    return False


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

    try:
        from .judge_log import get_acceptance_stats
        judge_stats = get_acceptance_stats()
    except Exception:
        judge_stats = {"total": 0, "accepted": 0, "rejected": 0, "rate": None}

    return {"users": result, "judge": judge_stats}


def admin_user_usage_response(user_id: str, range_: str = "24h") -> dict[str, Any]:
    """Return per-type usage (calls/cost/tokens) for a user, filtered by range.

    range_: "24h" | "7d" | "30d" | "all"
    """
    from .quota_service import get_user_usage_range

    range_seconds = {
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
        "all": None,
    }
    if range_ not in range_seconds:
        raise HTTPException(status_code=400, detail=f"invalid range: {range_}")

    secs = range_seconds[range_]
    if secs is None:
        since_iso = None
    else:
        cutoff = datetime.now(UTC).timestamp() - secs
        since_iso = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()

    data = get_user_usage_range(user_id, since_iso=since_iso)
    data["range"] = range_
    return data


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
