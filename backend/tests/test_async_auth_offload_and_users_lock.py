"""#2060: async handlers must not block the event loop on users-lock / Apple IO,
and every users.json lock acquirer must give up after a bounded wait.

The production server runs ``--workers 1``: one blocking call inside an
``async def`` freezes every in-flight request, and an unbounded FileLock wait
turns one slow holder into a full outage.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from filelock import FileLock

import kg.routers.web_auth as web_auth
from conftest import TEST_GOOGLE_REDIRECT_URI, TEST_JWT_SECRET, _swap_settings
from kg import users_lock
from kg.api import app
from kg.api_models import (
    AppStoreNotificationRequest,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    AuthVerifyRequest,
    EntitlementsResponse,
    SubscriptionStatusResponse,
    UserConfigRequest,
)
from kg.auth_handlers import auth_verify_response
from kg.auth_service import resolve_and_link_user
from kg.auth_types import VerifiedIdentity
from kg.billing_handlers import (
    app_store_notifications_response,
    reconcile_app_store_subscription_response,
    sync_app_store_subscription_response,
)
from kg.routers.library import _library_s3_client
from kg.settings import KGSettings
from kg.user_handlers import delete_user_account_response, update_user_config_response
from kg.user_store import collect_account_ids_for_deletion


def _assert_event_loop_free(loop: asyncio.AbstractEventLoop) -> None:
    """Return only if ``loop`` can still run callbacks while the caller blocks.

    From a worker thread the scheduled callback runs at once. Called on the
    loop thread itself, the loop is stuck inside this very call, the callback
    never runs and the wait times out: the caller is blocking the event loop.
    """
    ran = threading.Event()
    loop.call_soon_threadsafe(ran.set)
    if not ran.wait(timeout=1.0):
        raise AssertionError("blocking call executed on the event-loop thread")


async def _no_google(token: str, client_id: str) -> VerifiedIdentity:
    raise AssertionError("google verification must not run for this request")


# ── /auth/verify ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_verify_apple_runs_token_check_and_user_linking_off_the_event_loop():
    loop = asyncio.get_running_loop()
    calls: list[str] = []

    def verify_apple(token: str, audience: str) -> VerifiedIdentity:
        _assert_event_loop_free(loop)
        calls.append("verify")
        return VerifiedIdentity("apple-sub", None, False)

    def link(provider_user_id: str, provider: str, email: str | None) -> str:
        _assert_event_loop_free(loop)
        calls.append("link")
        return provider_user_id

    resp = await auth_verify_response(
        AuthVerifyRequest(provider="apple", token="apple.jwt"),
        google_client_id="",
        apple_bundle_id="com.example.app",
        jwt_expiry_minutes=5,
        verify_google_token=_no_google,
        verify_apple_token=verify_apple,
        resolve_and_link_user=link,
        create_jwt_token=lambda uid, provider: f"jwt-{uid}",
    )

    assert calls == ["verify", "link"]
    assert resp.user_id == "apple-sub"
    assert resp.access_token == "jwt-apple-sub"


@pytest.mark.asyncio
async def test_auth_verify_google_links_user_off_the_event_loop():
    loop = asyncio.get_running_loop()

    async def verify_google(token: str, client_id: str) -> VerifiedIdentity:
        return VerifiedIdentity("google-sub", "g@example.com", True)

    def link(provider_user_id: str, provider: str, email: str | None) -> str:
        _assert_event_loop_free(loop)
        assert email == "g@example.com"
        return provider_user_id

    resp = await auth_verify_response(
        AuthVerifyRequest(provider="google", token="google.jwt"),
        google_client_id="client-id",
        apple_bundle_id="com.example.app",
        jwt_expiry_minutes=5,
        verify_google_token=verify_google,
        verify_apple_token=lambda token, audience: pytest.fail("apple verification must not run"),
        resolve_and_link_user=link,
        create_jwt_token=lambda uid, provider: "jwt",
    )

    assert resp.user_id == "google-sub"


# ── web OAuth callbacks ───────────────────────────────────────────────────────


@pytest.fixture()
def web_app_state(tmp_path):
    (tmp_path / "users").mkdir()
    (tmp_path / "users.json").write_text(json.dumps({}))
    original = (app.state.kg_settings, app.state.load_users, app.state.save_users)
    _swap_settings(
        KGSettings(
            data_dir=tmp_path,
            jwt_secret=TEST_JWT_SECRET,
            google_client_id="test-google-client-id",
            google_client_secret="test-google-client-secret",
            google_redirect_uri=TEST_GOOGLE_REDIRECT_URI,
        )
    )
    try:
        yield
    finally:
        app.state.kg_settings, app.state.load_users, app.state.save_users = original


def _asgi_client() -> httpx.AsyncClient:
    # ASGITransport runs the app on the test's own event loop, so a blocking
    # call inside an async route is observable by _assert_event_loop_free.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver")


@pytest.mark.asyncio
async def test_web_apple_callback_verifies_and_links_off_the_event_loop(web_app_state, monkeypatch):
    loop = asyncio.get_running_loop()
    calls: list[str] = []

    def verify_apple(token: str, audience: str) -> VerifiedIdentity:
        _assert_event_loop_free(loop)
        calls.append("verify")
        return VerifiedIdentity("apple-web-sub", None, False)

    def link(provider_user_id, provider, email=None, **kwargs):
        _assert_event_loop_free(loop)
        calls.append("link")
        return provider_user_id

    monkeypatch.setattr(web_auth, "verify_apple_token", verify_apple)
    monkeypatch.setattr(web_auth, "_resolve_and_link_user", link)

    async with _asgi_client() as client:
        resp = await client.post(
            "/auth/web/apple/callback",
            data={"id_token": "apple.jwt", "state": "nonce-1"},
            headers={"cookie": "oauth_state=nonce-1"},
        )

    assert resp.status_code == 200, resp.text
    assert calls == ["verify", "link"]


@pytest.mark.asyncio
async def test_web_google_callback_links_off_the_event_loop(web_app_state, monkeypatch):
    loop = asyncio.get_running_loop()
    calls: list[str] = []

    async def exchange(data):
        return httpx.Response(
            200,
            json={"id_token": "google.jwt"},
            request=httpx.Request("POST", web_auth.GOOGLE_TOKEN_URL),
        )

    async def verify_google(token: str, client_id: str) -> VerifiedIdentity:
        return VerifiedIdentity("google-web-sub", "g@example.com", True)

    def link(provider_user_id, provider, email=None, **kwargs):
        _assert_event_loop_free(loop)
        calls.append("link")
        return provider_user_id

    monkeypatch.setattr(web_auth, "_exchange_google_code", exchange)
    monkeypatch.setattr(web_auth, "verify_google_token", verify_google)
    monkeypatch.setattr(web_auth, "_resolve_and_link_user", link)

    async with _asgi_client() as client:
        resp = await client.get(
            "/auth/web/google/callback?code=c&state=nonce-2",
            headers={"cookie": "oauth_state=nonce-2"},
        )

    assert resp.status_code == 200, resp.text
    assert calls == ["link"]


# ── billing reconcile ─────────────────────────────────────────────────────────


def _snapshot() -> dict:
    return {
        "product_id": "pro_monthly",
        "transaction_id": "txn-1",
        "original_transaction_id": "orig-1",
        "environment": "sandbox",
        "status": "active",
        "is_trial": False,
        "expires_at": None,
        "will_renew": True,
        "price_display": None,
    }


def _entitlements(record) -> EntitlementsResponse:
    return EntitlementsResponse(pro=SubscriptionStatusResponse(is_active=True, status="active"))


def _write_snapshot(users, user_id, **kwargs):
    record = {"subscription": {"status": kwargs["status"]}}
    users[user_id] = record
    return record


async def _signed_txn(*args, **kwargs):
    return {"signedTransactionInfo": "signed.jws"}


@pytest.mark.asyncio
async def test_reconcile_holds_users_lock_off_the_event_loop(tmp_path):
    loop = asyncio.get_running_loop()
    saved: list[dict] = []

    def load_users():
        _assert_event_loop_free(loop)
        return {}

    result = await reconcile_app_store_subscription_response(
        AppStoreReconcileRequest(transaction_id="txn-1", environment="production"),
        {"id": "u1"},
        apple_bundle_id="com.example.app",
        users_lock_file=tmp_path / "users.json.lock",
        load_users=load_users,
        save_users=saved.append,
        fetch_transaction_info=_signed_txn,
        decode_signed_transaction_info=lambda signed: _snapshot(),
        resolve_user_id_from_subscription_index=lambda *a: None,
        write_subscription_snapshot=_write_snapshot,
        build_entitlements_response=_entitlements,
    )

    assert isinstance(result, EntitlementsResponse)
    assert saved == [{"u1": {"subscription": {"status": "active"}}}]


# ── bounded users-lock wait ───────────────────────────────────────────────────

_LOCK_TIMEOUT = 0.2
# Generous upper bound for "gave up": far above the patched timeout, far below
# "blocked until the holder lets go" (the holder never does during the call).
_GAVE_UP_WITHIN = 5.0


def _acquirers(tmp_path, lock_path) -> dict[str, Callable[[], object]]:
    def no_users():
        return {}

    def ignore(users):
        return None

    return {
        "resolve_and_link_user": lambda: resolve_and_link_user(
            "apple-sub", "apple", users_lock_file=str(lock_path), load_users_fn=no_users, save_users_fn=ignore
        ),
        "update_user_config": lambda: update_user_config_response(
            UserConfigRequest(), {"id": "u1"}, users_lock_file=lock_path, load_users=no_users, save_users=ignore
        ),
        "delete_user_account": lambda: delete_user_account_response(
            {"id": "u1"},
            users_lock_file=lock_path,
            load_users=lambda: {"u1": {"config": {}}},
            save_users=ignore,
            collect_account_ids_for_deletion=collect_account_ids_for_deletion,
            data_dir=tmp_path,
            logger=MagicMock(),
        ),
        "billing_sync": lambda: sync_app_store_subscription_response(
            AppStoreSyncRequest(product_id="pro_monthly"),
            {"id": "u1"},
            allow_unsigned_sync=True,
            users_lock_file=lock_path,
            load_users=no_users,
            save_users=ignore,
            decode_signed_transaction_info=lambda signed: _snapshot(),
            write_subscription_snapshot=_write_snapshot,
            build_entitlements_response=_entitlements,
        ),
        "billing_notification": lambda: app_store_notifications_response(
            AppStoreNotificationRequest(notification_type="DID_RENEW", signed_payload="s"),
            users_lock_file=lock_path,
            load_users=no_users,
            save_users=ignore,
            decode_notification_payload=lambda req: (_snapshot(), None),
            append_app_store_event=ignore,
            resolve_user_id_from_subscription_index=lambda *a: "u1",
            write_subscription_snapshot=_write_snapshot,
            build_entitlements_response=_entitlements,
        ),
        "billing_reconcile": lambda: asyncio.run(
            reconcile_app_store_subscription_response(
                AppStoreReconcileRequest(transaction_id="txn-1", environment="production"),
                {"id": "u1"},
                apple_bundle_id="com.example.app",
                users_lock_file=lock_path,
                load_users=no_users,
                save_users=ignore,
                fetch_transaction_info=_signed_txn,
                decode_signed_transaction_info=lambda signed: _snapshot(),
                resolve_user_id_from_subscription_index=lambda *a: None,
                write_subscription_snapshot=_write_snapshot,
                build_entitlements_response=_entitlements,
            )
        ),
    }


@pytest.mark.parametrize(
    "acquirer",
    [
        "resolve_and_link_user",
        "update_user_config",
        "delete_user_account",
        "billing_sync",
        "billing_notification",
        "billing_reconcile",
    ],
)
def test_users_lock_acquirers_give_up_with_503_while_lock_is_held(tmp_path, monkeypatch, acquirer):
    monkeypatch.setattr(users_lock, "USERS_LOCK_TIMEOUT_SECONDS", _LOCK_TIMEOUT)
    lock_path = tmp_path / "users.json.lock"
    call = _acquirers(tmp_path, lock_path)[acquirer]
    outcome: dict[str, BaseException | object] = {}

    def run():
        try:
            outcome["value"] = call()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the assertion below
            outcome["error"] = exc

    holder = FileLock(str(lock_path))
    holder.acquire()
    worker = threading.Thread(target=run, daemon=True)
    try:
        worker.start()
        worker.join(_GAVE_UP_WITHIN)
        still_waiting = worker.is_alive()
    finally:
        holder.release()
        worker.join(_GAVE_UP_WITHIN)

    assert not still_waiting, f"{acquirer} waited on the users lock without a timeout"
    error = outcome.get("error")
    assert isinstance(error, HTTPException), outcome
    assert error.status_code == 503


# ── library object storage client ─────────────────────────────────────────────


def test_library_s3_client_has_bounded_network_timeouts(tmp_path):
    settings = KGSettings(data_dir=tmp_path, jwt_secret=TEST_JWT_SECRET, library_bucket="library-test")
    client = _library_s3_client(settings)
    config = client.meta.config
    assert config.connect_timeout <= 5
    assert config.read_timeout <= 10
    assert config.retries["total_max_attempts"] <= 3
