"""Web OAuth flow for Chrome extension login.

Provides browser-based Google/Apple sign-in that passes JWT back to the extension.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
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
    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "access_type": "offline",
        "prompt": "consent",
    })
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{params}", status_code=307)


@router.get("/auth/web/google/callback", response_class=HTMLResponse)
async def google_callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Google auth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

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

    return templates.TemplateResponse(request, "login_success.html", {
        "token": jwt_token,
        "extension_id": settings.chrome_extension_id,
    })


@router.post("/auth/web/apple/callback", response_class=HTMLResponse)
async def apple_callback(
    request: Request,
    id_token: str = Form(..., alias="id_token"),
    code: str = Form(None),
    error: str = Form(None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Apple auth error: {error}")

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

    return templates.TemplateResponse(request, "login_success.html", {
        "token": jwt_token,
        "extension_id": settings.chrome_extension_id,
    })
