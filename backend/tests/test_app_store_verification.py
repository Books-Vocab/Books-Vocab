from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

import kg.api as api_mod
from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _build_certificate(subject_cn: str, issuer_cert=None, issuer_key=None):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    issuer = issuer_cert.subject if issuer_cert else subject
    signer_key = issuer_key or key
    now = datetime.now(tz=UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=issuer_cert is None or issuer_key is not None, path_length=None), critical=True)
    )
    cert = builder.sign(private_key=signer_key, algorithm=hashes.SHA256())
    return key, cert


def _certificate_chain():
    root_key, root_cert = _build_certificate("Test Apple Root")
    intermediate_key, intermediate_cert = _build_certificate(
        "Test Apple Intermediate",
        issuer_cert=root_cert,
        issuer_key=root_key,
    )
    leaf_key, leaf_cert = _build_certificate(
        "Test Apple Leaf",
        issuer_cert=intermediate_cert,
        issuer_key=intermediate_key,
    )
    return {
        "root_key": root_key,
        "root_cert": root_cert,
        "intermediate_key": intermediate_key,
        "intermediate_cert": intermediate_cert,
        "leaf_key": leaf_key,
        "leaf_cert": leaf_cert,
    }


def _sign_jws(payload: dict, leaf_key, chain: list[x509.Certificate]) -> str:
    x5c = [
        base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii")
        for cert in chain
    ]
    return pyjwt.encode(payload, leaf_key, algorithm="ES256", headers={"alg": "ES256", "x5c": x5c})


def _swap_settings(new_settings):
    from kg.user_store import load_users_from, save_users_to, normalize_users_payload
    from kg.billing import default_subscription_payload

    app.state.kg_settings = new_settings

    def _normalize(users):
        from kg.secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, default_subscription_payload, encrypt_fn=encrypt_fn)

    app.state.load_users = lambda: load_users_from(app.state.kg_settings.users_file, _normalize)
    app.state.save_users = lambda users: save_users_to(app.state.kg_settings.users_file, users, _normalize)
    app.state.normalize_users_payload = _normalize


@pytest.fixture()
def signed_app_store_env(tmp_path, monkeypatch):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({user_id: {"config": {}}}))

    chain = _certificate_chain()
    root_pem_path = data_dir / "apple_root.pem"
    root_pem_path.write_text(
        chain["root_cert"].public_bytes(serialization.Encoding.PEM).decode("utf-8"),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_STORE_ROOT_CA_PATH", str(root_pem_path))
    monkeypatch.delenv("APP_STORE_ROOT_CA_PEM", raising=False)

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=False,
        app_store_allow_unsigned_notifications=False,
    )
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        api_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
            users_file=users_file,
            chain=chain,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def _transaction_payload(*, transaction_id: str, original_transaction_id: str, status: str = "active") -> dict:
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    expires_at = now_ms + (7 * 24 * 60 * 60 * 1000)
    if status == "expired":
        expires_at = now_ms - 1000
    payload = {
        "bundleId": app.state.kg_settings.apple_bundle_id,
        "productId": "com.wordnexus.pro.monthly",
        "transactionId": transaction_id,
        "originalTransactionId": original_transaction_id,
        "environment": "Sandbox",
        "expiresDate": expires_at,
    }
    if status == "trial":
        payload["offerType"] = 1
    return payload


def test_signed_sync_verifies_jws_and_persists_subscription(signed_app_store_env):
    env = signed_app_store_env
    signed_transaction = _sign_jws(
        _transaction_payload(transaction_id="tx-signed-1", original_transaction_id="otx-signed-1", status="trial"),
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )

    r = env.client.post(
        "/api/billing/app-store/sync",
        json={
            "product_id": "com.wordnexus.pro.monthly",
            "environment": "sandbox",
            "price_display": "$1.00/month",
            "signed_transaction_info": signed_transaction,
        },
        headers=env.headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()["pro"]
    assert body["is_active"] is True
    assert body["status"] == "trial"
    assert body["product_id"] == "com.wordnexus.pro.monthly"

    saved = json.loads(Path(env.users_file).read_text())
    assert saved[env.user_id]["subscription"]["transaction_id"] == "tx-signed-1"
    assert saved["_subscription_index"]["otx-signed-1"] == env.user_id


def test_signed_notification_verifies_nested_jws_and_updates_subscription(signed_app_store_env):
    env = signed_app_store_env
    sync_signed_transaction = _sign_jws(
        _transaction_payload(transaction_id="tx-signed-2", original_transaction_id="otx-signed-2"),
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )
    sync_response = env.client.post(
        "/api/billing/app-store/sync",
        json={
            "product_id": "com.wordnexus.pro.monthly",
            "environment": "sandbox",
            "signed_transaction_info": sync_signed_transaction,
        },
        headers=env.headers,
    )
    assert sync_response.status_code == 200, sync_response.text

    signed_transaction_info = _sign_jws(
        _transaction_payload(transaction_id="tx-signed-3", original_transaction_id="otx-signed-2", status="expired"),
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )
    signed_renewal_info = _sign_jws(
        {
            "bundleId": app.state.kg_settings.apple_bundle_id,
            "productId": "com.wordnexus.pro.monthly",
            "originalTransactionId": "otx-signed-2",
            "autoRenewStatus": 0,
        },
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )
    signed_payload = _sign_jws(
        {
            "notificationType": "EXPIRED",
            "subtype": None,
            "bundleId": app.state.kg_settings.apple_bundle_id,
            "data": {
                "bundleId": app.state.kg_settings.apple_bundle_id,
                "signedTransactionInfo": signed_transaction_info,
                "signedRenewalInfo": signed_renewal_info,
            },
        },
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )

    r = env.client.post(
        "/api/billing/app-store/notifications",
        json={"signed_payload": signed_payload},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] is True
    assert body["user_id"] == env.user_id
    assert body["entitlements"]["pro"]["status"] == "expired"


def test_reconcile_uses_app_store_server_lookup_and_updates_subscription(signed_app_store_env):
    env = signed_app_store_env
    signed_transaction = _sign_jws(
        _transaction_payload(transaction_id="tx-reconcile-1", original_transaction_id="otx-reconcile-1"),
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )

    with patch.object(
        api_mod,
        "fetch_transaction_info",
        new=AsyncMock(return_value={"signedTransactionInfo": signed_transaction}),
    ):
        r = env.client.post(
            "/api/billing/app-store/reconcile",
            json={"transaction_id": "tx-reconcile-1", "environment": "sandbox"},
            headers=env.headers,
        )

    assert r.status_code == 200, r.text
    body = r.json()["pro"]
    assert body["is_active"] is True
    assert body["product_id"] == "com.wordnexus.pro.monthly"


def test_signed_sync_rejects_bundle_id_mismatch(signed_app_store_env):
    env = signed_app_store_env
    signed_transaction = _sign_jws(
        {
            **_transaction_payload(transaction_id="tx-bad-1", original_transaction_id="otx-bad-1"),
            "bundleId": "com.other.bundle",
        },
        env.chain["leaf_key"],
        [env.chain["leaf_cert"], env.chain["intermediate_cert"], env.chain["root_cert"]],
    )

    r = env.client.post(
        "/api/billing/app-store/sync",
        json={
            "product_id": "com.wordnexus.pro.monthly",
            "environment": "sandbox",
            "signed_transaction_info": signed_transaction,
        },
        headers=env.headers,
    )
    assert r.status_code == 400, r.text
    assert "bundleId" in r.text
