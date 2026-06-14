"""Admin entitlement handlers — Pro grant/revoke, entitlement lookup, audit log."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from ..api_models import (
    AdminGrantRequest,
    AdminGrantStatusResponse,
    AdminUserEntitlementResponse,
    EntitlementsResponse,
)
from ..exceptions import NotFoundError
from ..types import AdminGrantRecord, StoredUserRecord, UsersPayload
from ..user_store import is_real_user


def admin_user_entitlement_response(
    user_id: str,
    *,
    load_users: Callable[[], UsersPayload],
    build_entitlements_response: Callable[[StoredUserRecord | None], EntitlementsResponse],
    current_admin_grant_record: Callable[[StoredUserRecord | None], AdminGrantRecord],
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
    load_users: Callable[[], UsersPayload],
    save_users: Callable[[UsersPayload], None],
    current_admin_grant_record: Callable[[StoredUserRecord | None], AdminGrantRecord],
    build_entitlements_response: Callable[[StoredUserRecord | None], EntitlementsResponse],
    grant_updates: AdminGrantRecord | None = None,
) -> AdminUserEntitlementResponse:
    """Shared logic for granting/revoking admin Pro access."""
    with FileLock(str(users_lock_file)):
        users = load_users()
        record = users.get(user_id)
        if not is_real_user(user_id, record):
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
    load_users: Callable[[], UsersPayload],
    save_users: Callable[[UsersPayload], None],
    current_admin_grant_record: Callable[[StoredUserRecord | None], AdminGrantRecord],
    build_entitlements_response: Callable[[StoredUserRecord | None], EntitlementsResponse],
    admin_uid: str | None = None,
) -> AdminUserEntitlementResponse:
    from ..admin_audit import record_audit

    now_iso = datetime.now(tz=UTC).isoformat()
    # Trust only the server-derived fingerprint for the actor; ignore any
    # client-supplied ``req.granted_by`` so the audit + grant record cannot
    # be spoofed from the request body.
    actor = (admin_uid or "admin").strip() or "admin"
    reason = req.reason.strip() if isinstance(req.reason, str) and req.reason.strip() else None
    resp = _mutate_admin_grant(
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
            "granted_by": actor,
            "reason": reason,
            "last_synced_at": now_iso,
        },
    )
    record_audit(
        admin_uid=actor,
        action="grant_pro",
        target_uid=user_id,
        payload={"expires_at": req.expires_at, "reason": reason},
    )
    return resp


def admin_revoke_pro_access_response(
    user_id: str,
    *,
    users_lock_file: Path,
    load_users: Callable[[], UsersPayload],
    save_users: Callable[[UsersPayload], None],
    current_admin_grant_record: Callable[[StoredUserRecord | None], AdminGrantRecord],
    build_entitlements_response: Callable[[StoredUserRecord | None], EntitlementsResponse],
    admin_uid: str | None = None,
) -> AdminUserEntitlementResponse:
    from ..admin_audit import record_audit

    now_iso = datetime.now(tz=UTC).isoformat()
    resp = _mutate_admin_grant(
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
    record_audit(
        admin_uid=admin_uid,
        action="revoke_pro",
        target_uid=user_id,
        payload={},
    )
    return resp


def admin_audit_response(
    *,
    since: str | None = None,
    limit: int = 100,
    action: str | None = None,
) -> dict[str, Any]:
    """Return recent admin audit log entries, newest-first.

    ``action`` optionally restricts rows to an exact action match
    (e.g. ``grant_pro`` / ``revoke_pro``); blank/omitted returns all actions.
    """
    from ..admin_audit import list_audit

    rows = list_audit(since=since, limit=limit, action=action)
    return {"audit": rows, "count": len(rows)}
