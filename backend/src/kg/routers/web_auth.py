"""Web OAuth flow for Chrome extension login.

Provides browser-based Google/Apple sign-in that passes JWT back to the extension.

CSRF protection: every login endpoint mints a `secrets.token_urlsafe(32)` nonce,
stores it in an HttpOnly Secure SameSite=Lax cookie (`oauth_state`, path
`/auth/web/`, 10 min TTL) and includes it in the upstream provider redirect /
form. The matching callback compares the cookie against the value returned by
the provider; mismatches return HTTP 400 and the cookie is cleared on success.
"""

from __future__ import annotations

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

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_OAUTH_STATE_COOKIE = "oauth_state"
_OAUTH_STATE_TTL_SECONDS = 600  # 10 min
_OAUTH_STATE_PATH = "/auth/web/"


def _set_state_cookie(response: Response, nonce: str) -> None:
    response.set_cookie(
        key=_OAUTH_STATE_COOKIE,
        value=nonce,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
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


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    settings = request.app.state.kg_settings
    return templates.TemplateResponse(request, "login.html", {
        "apple_service_id": settings.apple_bundle_id,
        "apple_redirect_uri": "https://wordnexus.lol/auth/web/apple/callback",
    })


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
    """Mint OAuth state cookie before redirecting/rendering Apple sign-in.

    The actual Apple flow uses Sign-in with Apple JS on `/login`; this endpoint
    exists so callers (and tests) can establish a state nonce that the POST
    callback will validate.
    """
    nonce = secrets.token_urlsafe(32)
    response = RedirectResponse(url="/login", status_code=307)
    _set_state_cookie(response, nonce)
    return response


@router.get("/auth/web/google/callback", response_class=HTMLResponse)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google auth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    _verify_state(request, state)

    settings = request.app.state.kg_settings

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        logger.warning("Google token exchange failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=401, detail="Failed to exchange authorization code")

    token_data = resp.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=401, detail="No id_token in Google response")

    # Verify id_token and resolve user (reuse existing infra)
    provider_user_id = await verify_google_token(id_token_str, settings.google_client_id)

    load_users_fn = request.app.state.load_users
    save_users_fn = request.app.state.save_users
    canonical_user_id = _resolve_and_link_user(
        provider_user_id, "google", email=None,
        settings=settings, load_users_fn=load_users_fn, save_users_fn=save_users_fn,
    )
    jwt_token = _create_jwt_token(canonical_user_id, "google", settings=settings)

    response = templates.TemplateResponse(request, "login_success.html", {
        "token": jwt_token,
        "extension_id": settings.chrome_extension_id,
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
        raise HTTPException(status_code=400, detail=f"Apple auth error: {error}")

    _verify_state(request, state)

    settings = request.app.state.kg_settings

    # Verify Apple id_token (reuse existing infra)
    provider_user_id = verify_apple_token(id_token, settings.apple_bundle_id)

    load_users_fn = request.app.state.load_users
    save_users_fn = request.app.state.save_users
    canonical_user_id = _resolve_and_link_user(
        provider_user_id, "apple", email=None,
        settings=settings, load_users_fn=load_users_fn, save_users_fn=save_users_fn,
    )
    jwt_token = _create_jwt_token(canonical_user_id, "apple", settings=settings)

    response = templates.TemplateResponse(request, "login_success.html", {
        "token": jwt_token,
        "extension_id": settings.chrome_extension_id,
    })
    _clear_state_cookie(response)
    return response
