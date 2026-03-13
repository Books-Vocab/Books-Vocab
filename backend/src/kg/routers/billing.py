from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ..api_models import (
    AppStoreNotificationRequest,
    AppStoreNotificationResponse,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    EntitlementsResponse,
)
from ..app_store import fetch_transaction_info, verify_and_decode_signed_jws
from ..billing import (
    append_app_store_event,
    decode_notification_payload,
    decode_signed_transaction_info,
)
from ..billing_handlers import (
    app_store_notifications_response,
    reconcile_app_store_subscription_response,
    sync_app_store_subscription_response,
)
from ..deps import (
    _build_entitlements_response,
    _parse_datetime,
    _resolve_user_id_from_subscription_index,
    _write_subscription_snapshot,
    get_current_user,
)

router = APIRouter()


@router.post("/api/billing/app-store/sync", response_model=EntitlementsResponse)
def sync_app_store_subscription(req: AppStoreSyncRequest, request: Request, user: dict = Depends(get_current_user)):
    settings = request.app.state.kg_settings

    def _decode_signed_txn(signed_transaction_info: str) -> dict[str, Any]:
        return decode_signed_transaction_info(
            signed_transaction_info, bundle_id=settings.apple_bundle_id,
            parse_datetime_fn=_parse_datetime, verify_signed_jws=verify_and_decode_signed_jws,
        )

    return sync_app_store_subscription_response(
        req, user,
        allow_unsigned_sync=settings.app_store_allow_unsigned_sync,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users, save_users=request.app.state.save_users,
        decode_signed_transaction_info=_decode_signed_txn,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


@router.post("/api/billing/app-store/notifications", response_model=AppStoreNotificationResponse)
def app_store_notifications(req: AppStoreNotificationRequest, request: Request):
    settings = request.app.state.kg_settings

    def _decode_notif_payload(r: AppStoreNotificationRequest) -> tuple[dict[str, Any], dict[str, Any] | None]:
        return decode_notification_payload(
            r, bundle_id=settings.apple_bundle_id,
            allow_unsigned_notifications=settings.app_store_allow_unsigned_notifications,
            parse_datetime_fn=_parse_datetime, verify_signed_jws=verify_and_decode_signed_jws,
        )

    def _append_event(payload: dict[str, Any]) -> None:
        append_app_store_event(settings.app_store_notifications_file, payload)

    return app_store_notifications_response(
        req,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users, save_users=request.app.state.save_users,
        decode_notification_payload=_decode_notif_payload,
        append_app_store_event=_append_event,
        resolve_user_id_from_subscription_index=_resolve_user_id_from_subscription_index,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


@router.post("/api/billing/app-store/reconcile", response_model=EntitlementsResponse)
async def reconcile_app_store_subscription(
    req: AppStoreReconcileRequest, request: Request, user: dict = Depends(get_current_user),
):
    settings = request.app.state.kg_settings

    def _decode_signed_txn(signed_transaction_info: str) -> dict[str, Any]:
        return decode_signed_transaction_info(
            signed_transaction_info, bundle_id=settings.apple_bundle_id,
            parse_datetime_fn=_parse_datetime, verify_signed_jws=verify_and_decode_signed_jws,
        )

    return await reconcile_app_store_subscription_response(
        req, user,
        apple_bundle_id=settings.apple_bundle_id,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users, save_users=request.app.state.save_users,
        fetch_transaction_info=fetch_transaction_info,
        decode_signed_transaction_info=_decode_signed_txn,
        resolve_user_id_from_subscription_index=_resolve_user_id_from_subscription_index,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )
