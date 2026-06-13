from __future__ import annotations

from fastapi import APIRouter, Request

from ..api_models import (
    DeleteAccountResponse,
    EntitlementsResponse,
    HealthResponse,
    QuotaResponse,
    UserConfigRequest,
    UserConfigResponse,
    UserProfileResponse,
)
from ..deps import (
    CurrentUser,
    _build_entitlements_response,
    _card_store,
    _collect_account_ids_for_deletion,
    _graph_store,
    _is_pro,
    logger,
)
from ..user_handlers import (
    delete_user_account_response,
    get_user_config_response,
    get_user_entitlements_response,
    get_user_profile_response,
    health_response,
    update_user_config_response,
)

router = APIRouter(tags=["user"])


@router.get("/api/user/config", response_model=UserConfigResponse)
def get_user_config(user: CurrentUser):
    return get_user_config_response(user)


@router.get("/api/user/profile", response_model=UserProfileResponse)
def get_user_profile(user: CurrentUser):
    return get_user_profile_response(user)


@router.get("/api/user/entitlements", response_model=EntitlementsResponse)
def get_user_entitlements(user: CurrentUser):
    return get_user_entitlements_response(user, build_entitlements_response=_build_entitlements_response)


@router.get("/api/user/quota", response_model=QuotaResponse)
def get_user_quota(user: CurrentUser):
    from ..quota_service import get_quota_state
    return get_quota_state(user["id"], is_pro=_is_pro(user))


@router.put("/api/user/config", response_model=UserConfigResponse)
def update_user_config(req: UserConfigRequest, request: Request, user: CurrentUser):
    settings = request.app.state.kg_settings
    return update_user_config_response(
        req, user,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
    )


@router.delete("/api/user/account", response_model=DeleteAccountResponse)
def delete_user_account(request: Request, user: CurrentUser):
    settings = request.app.state.kg_settings
    return delete_user_account_response(
        user,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
        collect_account_ids_for_deletion=_collect_account_ids_for_deletion,
        data_dir=settings.data_dir,
        logger=logger,
    )


@router.get("/api/health", response_model=HealthResponse)
def health(user: CurrentUser):
    return health_response(user, card_store_factory=_card_store, graph_store_factory=_graph_store)
