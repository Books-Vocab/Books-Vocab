from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from filelock import FileLock

logger = logging.getLogger(__name__)

from .api_models import (
    AppStoreNotificationRequest,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    EntitlementsResponse,
)
from .app_store import AppStoreConfigurationError, AppStoreVerificationError


def sync_app_store_subscription_response(
    req: AppStoreSyncRequest,
    user: dict[str, Any],
    *,
    allow_unsigned_sync: bool,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    decode_signed_transaction_info: Callable[[str], dict[str, Any]],
    write_subscription_snapshot: Callable[..., dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], EntitlementsResponse],
) -> EntitlementsResponse:
    try:
        if req.signed_transaction_info:
            snapshot = decode_signed_transaction_info(req.signed_transaction_info)
            if req.transaction_id and snapshot["transaction_id"] and req.transaction_id != snapshot["transaction_id"]:
                raise HTTPException(status_code=400, detail="transaction_id does not match signed_transaction_info")
            if req.original_transaction_id and snapshot["original_transaction_id"] and req.original_transaction_id != snapshot["original_transaction_id"]:
                raise HTTPException(status_code=400, detail="original_transaction_id does not match signed_transaction_info")
        else:
            if not allow_unsigned_sync:
                if req.environment.lower() == "xcode":
                    logger.warning(
                        "Rejected unsigned xcode sync for user %s — "
                        "enable APP_STORE_ALLOW_UNSIGNED_SYNC for dev/test",
                        user.get("id"),
                    )
                raise HTTPException(status_code=400, detail="signed_transaction_info is required for production App Store sync")
            snapshot = {
                "product_id": req.product_id,
                "transaction_id": req.transaction_id,
                "original_transaction_id": req.original_transaction_id,
                "environment": req.environment,
                "status": req.status,
                "is_trial": req.is_trial,
                "expires_at": req.expires_at,
                "will_renew": req.will_renew,
                "price_display": req.price_display,
            }
    except AppStoreConfigurationError as exc:
        logger.error("App Store configuration error: %s", exc)
        raise HTTPException(status_code=500, detail="App Store configuration error") from exc
    except AppStoreVerificationError as exc:
        logger.warning("App Store transaction verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Transaction verification failed") from exc

    with FileLock(str(users_lock_file)):
        users = load_users()
        record = write_subscription_snapshot(
            users,
            user["id"],
            product_id=snapshot["product_id"],
            status=snapshot["status"],
            is_trial=snapshot["is_trial"],
            expires_at=snapshot["expires_at"],
            will_renew=snapshot["will_renew"],
            environment=snapshot["environment"],
            transaction_id=snapshot["transaction_id"],
            original_transaction_id=snapshot["original_transaction_id"],
            price_display=snapshot["price_display"],
            source="app_store",
        )
        save_users(users)

    return build_entitlements_response(record)


def app_store_notifications_response(
    req: AppStoreNotificationRequest,
    *,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    decode_notification_payload: Callable[[AppStoreNotificationRequest], tuple[dict[str, Any], dict[str, Any] | None]],
    append_app_store_event: Callable[[dict[str, Any]], None],
    resolve_user_id_from_subscription_index: Callable[[dict[str, Any], str | None, str | None], str | None],
    write_subscription_snapshot: Callable[..., dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], EntitlementsResponse],
) -> dict[str, Any]:
    try:
        snapshot, decoded_payload = decode_notification_payload(req)
    except AppStoreConfigurationError as exc:
        logger.error("App Store configuration error: %s", exc)
        raise HTTPException(status_code=500, detail="App Store configuration error") from exc
    except AppStoreVerificationError as exc:
        logger.warning("App Store notification verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Transaction verification failed") from exc

    event = {
        "received_at": datetime.now(tz=UTC).isoformat(),
        "notification_type": req.notification_type,
        "subtype": req.subtype,
        "product_id": snapshot["product_id"],
        "transaction_id": snapshot["transaction_id"],
        "original_transaction_id": snapshot["original_transaction_id"],
        "environment": snapshot["environment"],
        "status": snapshot["status"],
        "is_trial": snapshot["is_trial"],
        "expires_at": snapshot["expires_at"],
        "will_renew": snapshot["will_renew"],
        "signed_payload": req.signed_payload,
        "raw_payload": decoded_payload or req.raw_payload,
    }
    append_app_store_event(event)

    with FileLock(str(users_lock_file)):
        users = load_users()
        user_id = resolve_user_id_from_subscription_index(
            users,
            snapshot["original_transaction_id"],
            snapshot["transaction_id"],
        )
        if not user_id:
            return {"status": "accepted", "updated": False, "reason": "unmapped_transaction"}
        record = write_subscription_snapshot(
            users,
            user_id,
            product_id=snapshot["product_id"],
            status=snapshot["status"],
            is_trial=snapshot["is_trial"],
            expires_at=snapshot["expires_at"],
            will_renew=snapshot["will_renew"],
            environment=snapshot["environment"],
            transaction_id=snapshot["transaction_id"],
            original_transaction_id=snapshot["original_transaction_id"],
            price_display=None,
            source="app_store_notification",
        )
        save_users(users)

    return {
        "status": "accepted",
        "updated": True,
        "user_id": user_id,
        "entitlements": build_entitlements_response(record).model_dump(),
    }


async def reconcile_app_store_subscription_response(
    req: AppStoreReconcileRequest,
    user: dict[str, Any],
    *,
    apple_bundle_id: str,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    fetch_transaction_info: Callable[..., Awaitable[dict[str, Any]]],
    decode_signed_transaction_info: Callable[[str], dict[str, Any]],
    resolve_user_id_from_subscription_index: Callable[[dict[str, Any], str | None, str | None], str | None],
    write_subscription_snapshot: Callable[..., dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], EntitlementsResponse],
) -> EntitlementsResponse:
    try:
        server_response = await fetch_transaction_info(
            req.transaction_id,
            bundle_id=apple_bundle_id,
            environment=req.environment,
        )
        signed_transaction_info = server_response.get("signedTransactionInfo")
        if not isinstance(signed_transaction_info, str) or not signed_transaction_info:
            raise HTTPException(status_code=502, detail="App Store transaction lookup did not return signedTransactionInfo")
        snapshot = decode_signed_transaction_info(signed_transaction_info)
    except AppStoreConfigurationError as exc:
        logger.error("App Store configuration error: %s", exc)
        raise HTTPException(status_code=500, detail="App Store configuration error") from exc
    except AppStoreVerificationError as exc:
        logger.warning("App Store transaction decode failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid transaction response") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"App Store API lookup failed: HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        logger.warning("App Store API network error: %s", exc)
        raise HTTPException(status_code=502, detail="App Store service unavailable") from exc

    with FileLock(str(users_lock_file)):
        users = load_users()
        resolved_user_id = resolve_user_id_from_subscription_index(
            users,
            snapshot["original_transaction_id"],
            snapshot["transaction_id"],
        ) or user["id"]
        record = write_subscription_snapshot(
            users,
            resolved_user_id,
            product_id=snapshot["product_id"],
            status=snapshot["status"],
            is_trial=snapshot["is_trial"],
            expires_at=snapshot["expires_at"],
            will_renew=snapshot["will_renew"],
            environment=snapshot["environment"],
            transaction_id=snapshot["transaction_id"],
            original_transaction_id=snapshot["original_transaction_id"],
            price_display=None,
            source="app_store_server_api",
        )
        save_users(users)

    return build_entitlements_response(record)
