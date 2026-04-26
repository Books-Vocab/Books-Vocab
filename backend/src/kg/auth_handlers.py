from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from .api_models import AuthVerifyRequest, AuthVerifyResponse

logger = logging.getLogger(__name__)


async def auth_verify_response(
    req: AuthVerifyRequest,
    *,
    google_client_id: str,
    apple_bundle_id: str,
    jwt_expiry_minutes: int,
    verify_google_token: Callable[[str, str], Awaitable[tuple[str, str | None, bool]]],
    verify_apple_token: Callable[[str, str], tuple[str, str | None, bool]],
    resolve_and_link_user: Callable[[str, str, str | None], str],
    create_jwt_token: Callable[[str, str], str],
) -> AuthVerifyResponse:
    if req.provider == "google":
        if not google_client_id:
            raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
        provider_user_id, token_email, email_verified = await verify_google_token(
            req.token, google_client_id
        )
    elif req.provider == "apple":
        provider_user_id, token_email, email_verified = verify_apple_token(
            req.token, apple_bundle_id
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")

    # SECURITY: client-supplied req.email is IGNORED entirely (C1 account
    # takeover). Only the verified, token-derived email is used to merge
    # accounts via _email_index. Unverified emails create independent
    # accounts keyed by provider sub.
    # Only warn when both sides are present and disagree. A missing
    # token_email is normal for Apple resign-ins, where the client may
    # legitimately still send the cached email — not a takeover signal.
    if (
        req.email is not None
        and token_email is not None
        and req.email.strip().lower() != token_email
    ):
        logger.warning(
            "auth.verify: client-supplied email differs from token email; "
            "ignoring client value (provider=%s)",
            req.provider,
        )

    link_email = token_email if email_verified else None
    canonical_user_id = resolve_and_link_user(provider_user_id, req.provider, link_email)
    access_token = create_jwt_token(canonical_user_id, req.provider)

    return AuthVerifyResponse(
        access_token=access_token,
        user_id=canonical_user_id,
        expires_in=jwt_expiry_minutes * 60,
    )
