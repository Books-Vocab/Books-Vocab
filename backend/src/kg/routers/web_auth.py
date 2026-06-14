"""Web OAuth flow for browser-based login.

Provides browser-based Google/Apple sign-in that passes JWT back to the extension.

CSRF protection: every login endpoint mints a `secrets.token_urlsafe(32)` nonce,
stores it in an HttpOnly Secure cookie (`oauth_state`, path `/auth/web/`, 10 min
TTL) and includes it in the upstream provider redirect / form. SameSite is
`Lax` for the Google flow (top-level GET callback) but `None` for the Apple flow
(`response_mode=form_post` → cross-site top-level POST, which a Lax cookie would
not accompany). The matching callback compares the cookie against the value
returned by the provider; mismatches return HTTP 400 and the cookie is cleared
on success.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..apple_auth import verify_apple_token
from ..deps import _create_jwt_token, _resolve_and_link_user
from ..google_auth import verify_google_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web-auth"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_OAUTH_STATE_COOKIE = "oauth_state"
_OAUTH_STATE_TTL_SECONDS = 600  # 10 min
_OAUTH_STATE_PATH = "/auth/web/"
_GOOGLE_TOKEN_RETRY_BACKOFF_SECONDS = (0.2, 0.5)


def _is_transient_status(status_code: int) -> bool:
    # Retry transient upstream failures only; authentication failures (4xx) should
    # fail fast so operators get immediate feedback.
    return status_code >= 500 or status_code == 429


def _set_state_cookie(response: Response, nonce: str, *, samesite: str = "lax") -> None:
    # Google's callback is a top-level GET redirect → SameSite=Lax suffices.
    # Apple uses response_mode=form_post → a cross-site top-level POST, to which
    # browsers do NOT attach a Lax cookie; those call sites pass samesite="none"
    # (still Secure + HttpOnly, so CSRF stays enforced via the nonce comparison).
    response.set_cookie(
        key=_OAUTH_STATE_COOKIE,
        value=nonce,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite=samesite,
        path=_OAUTH_STATE_PATH,
    )


def _clear_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_OAUTH_STATE_COOKIE,
        path=_OAUTH_STATE_PATH,
    )


def _verify_state(request: Request, provided: str | None) -> None:
    expected = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")


async def _exchange_google_code(data: dict[str, str]) -> httpx.Response:
    attempts = len(_GOOGLE_TOKEN_RETRY_BACKOFF_SECONDS) + 1
    last_resp: httpx.Response | None = None
    last_exc: httpx.HTTPError | None = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(attempts):
            try:
                resp = await client.post(GOOGLE_TOKEN_URL, data=data)
                if _is_transient_status(resp.status_code):
                    last_resp = resp
                    if attempt < attempts - 1:
                        await asyncio.sleep(_GOOGLE_TOKEN_RETRY_BACKOFF_SECONDS[attempt])
                        continue
                return resp
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(_GOOGLE_TOKEN_RETRY_BACKOFF_SECONDS[attempt])
    if last_resp is not None:
        # Exhausted transient HTTP retries on an upstream server-side issue.
        return last_resp
    if last_exc is not None:
        raise last_exc
    # Defensive fallback: should not happen, but keep behavior deterministic.
    raise RuntimeError("google token exchange failed with no response and no exception")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    settings = request.app.state.kg_settings
    nonce = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(request, "login.html", {
        "apple_service_id": settings.apple_service_id,
        "apple_redirect_uri": settings.apple_redirect_uri,
        "oauth_state": nonce,
    })
    _set_state_cookie(response, nonce, samesite="none")
    return response


@router.get("/auth/web/google/login")
async def google_login(request: Request):
    settings = request.app.state.kg_settings
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
    nonce = secrets.token_urlsafe(32)
    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "access_type": "offline",
        "prompt": "consent",
        "state": nonce,
    })
    response = RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{params}", status_code=307)
    _set_state_cookie(response, nonce)
    return response


@router.get("/auth/web/apple/login")
async def apple_login(request: Request):
    """Redirect to Apple's OAuth authorize endpoint with state nonce.

    Builds the Apple authorize URL (GET) so the browser initiates the flow
    directly, avoiding the 403 from a raw HTML form POST to appleid.apple.com.
    The state nonce is stored in an HttpOnly Secure cookie for the callback
    to validate. Apple uses response_mode=form_post → cross-site top-level
    POST callback, so the state cookie needs SameSite=None.
    """
    settings = request.app.state.kg_settings
    nonce = secrets.token_urlsafe(32)
    params = urlencode({
        "client_id": settings.apple_service_id,
        "redirect_uri": settings.apple_redirect_uri,
        "response_type": "code id_token",
        "scope": "email",
        "response_mode": "form_post",
        "state": nonce,
    })
    response = RedirectResponse(
        url=f"https://appleid.apple.com/auth/authorize?{params}", status_code=307
    )
    _set_state_cookie(response, nonce, samesite="none")
    return response


@router.get("/auth/web/google/callback", response_class=HTMLResponse)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        # Redact the upstream provider string from the client (it can carry
        # provider-internal hints); keep the raw value server-side only,
        # mirroring ExternalServiceError's redaction philosophy.
        logger.warning("Google OAuth callback returned provider error: %s", error)
        raise HTTPException(status_code=400, detail="Authentication failed")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    _verify_state(request, state)

    settings = request.app.state.kg_settings

    # Exchange code for tokens. Network failures (DNS, connect, timeout, read)
    # all subclass httpx.HTTPError; surface them as a 502 instead of a bare 500.
    try:
        resp = await _exchange_google_code({
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
    except httpx.HTTPError as exc:
        logger.warning("Google token exchange request failed: %s", exc, exc_info=True)
        raise HTTPException(  # noqa: B904
            status_code=502, detail="Failed to reach Google authentication service"
        )
    if resp.status_code != 200:
        logger.warning("Google token exchange failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=401, detail="Failed to exchange authorization code")

    token_data = resp.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=401, detail="No id_token in Google response")

    # Verify id_token and resolve user (reuse existing infra)
    provider_user_id, token_email, email_verified = await verify_google_token(
        id_token_str, settings.google_client_id
    )

    load_users_fn = request.app.state.load_users
    save_users_fn = request.app.state.save_users
    canonical_user_id = _resolve_and_link_user(
        provider_user_id, "google",
        email=token_email if email_verified else None,
        settings=settings, load_users_fn=load_users_fn, save_users_fn=save_users_fn,
    )
    jwt_token = _create_jwt_token(canonical_user_id, "google", settings=settings)

    response = templates.TemplateResponse(request, "login_success.html", {
        "token": jwt_token,
        "user_id": canonical_user_id,
    })
    _clear_state_cookie(response)
    return response


@router.post("/auth/web/apple/callback", response_class=HTMLResponse)
async def apple_callback(
    request: Request,
    id_token: str = Form(..., alias="id_token"),
    code: str = Form(None),
    state: str = Form(None),
    error: str = Form(None),
):
    if error:
        # Redact the upstream provider string from the client; keep raw value
        # server-side only (see google_callback above).
        logger.warning("Apple OAuth callback returned provider error: %s", error)
        raise HTTPException(status_code=400, detail="Authentication failed")

    _verify_state(request, state)

    settings = request.app.state.kg_settings

    # Verify Apple id_token (reuse existing infra)
    provider_user_id, token_email, email_verified = verify_apple_token(
        id_token, settings.apple_service_id
    )

    load_users_fn = request.app.state.load_users
    save_users_fn = request.app.state.save_users
    canonical_user_id = _resolve_and_link_user(
        provider_user_id, "apple",
        email=token_email if email_verified else None,
        settings=settings, load_users_fn=load_users_fn, save_users_fn=save_users_fn,
    )
    jwt_token = _create_jwt_token(canonical_user_id, "apple", settings=settings)

    response = templates.TemplateResponse(request, "login_success.html", {
        "token": jwt_token,
        "user_id": canonical_user_id,
    })
    _clear_state_cookie(response)
    return response
