from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from .api_models import AuthVerifyRequest, AuthVerifyResponse


async def auth_verify_response(
    req: AuthVerifyRequest,
    *,
    google_client_id: str,
    apple_bundle_id: str,
    jwt_expiry_minutes: int,
    verify_google_token: Callable[[str, str], Awaitable[str]],
    verify_apple_token: Callable[[str, str], str],
    resolve_and_link_user: Callable[[str, str, str | None], str],
    create_jwt_token: Callable[[str, str], str],
) -> AuthVerifyResponse:
    if req.provider == "google":
        if not google_client_id:
            raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
        provider_user_id = await verify_google_token(req.token, google_client_id)
    elif req.provider == "apple":
        provider_user_id = verify_apple_token(req.token, apple_bundle_id)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")

    canonical_user_id = resolve_and_link_user(provider_user_id, req.provider, req.email)
    access_token = create_jwt_token(canonical_user_id, req.provider)

    return AuthVerifyResponse(
        access_token=access_token,
        user_id=canonical_user_id,
        expires_in=jwt_expiry_minutes * 60,
    )
