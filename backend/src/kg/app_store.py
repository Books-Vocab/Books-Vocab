from __future__ import annotations

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa


class AppStoreVerificationError(ValueError):
    """Raised when a signed App Store payload cannot be verified."""


class AppStoreConfigurationError(RuntimeError):
    """Raised when server-side App Store credentials are incomplete."""


PRODUCTION_API_BASE_URL = "https://api.storekit.itunes.apple.com"
SANDBOX_API_BASE_URL = "https://api.storekit-sandbox.itunes.apple.com"


@dataclass(frozen=True)
class VerifiedAppStoreJWS:
    header: dict[str, Any]
    payload: dict[str, Any]
    certificates: tuple[x509.Certificate, ...]


def _b64url_decode(value: str) -> bytes:
    padding_len = (-len(value)) % 4
    return base64.urlsafe_b64decode(value + ("=" * padding_len))


def _load_trusted_root_certificates() -> list[x509.Certificate]:
    pem_sources: list[str] = []

    root_path = os.getenv("APP_STORE_ROOT_CA_PATH", "").strip()
    if root_path:
        pem_sources.append(Path(root_path).read_text(encoding="utf-8"))

    inline_pem = os.getenv("APP_STORE_ROOT_CA_PEM", "").strip()
    if inline_pem:
        pem_sources.append(inline_pem)

    if not pem_sources:
        raise AppStoreConfigurationError(
            "APP_STORE_ROOT_CA_PATH or APP_STORE_ROOT_CA_PEM is required for App Store JWS verification."
        )

    certs: list[x509.Certificate] = []
    for pem_blob in pem_sources:
        chunks = pem_blob.split("-----END CERTIFICATE-----")
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            pem = chunk + "\n-----END CERTIFICATE-----\n"
            certs.append(x509.load_pem_x509_certificate(pem.encode("utf-8")))
    if not certs:
        raise AppStoreConfigurationError("No trusted App Store root certificates were loaded.")
    return certs


def _verify_certificate_signature(child: x509.Certificate, issuer: x509.Certificate) -> None:
    public_key = issuer.public_key()
    signature_hash = child.signature_hash_algorithm

    if isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(
            child.signature,
            child.tbs_certificate_bytes,
            padding.PKCS1v15(),
            signature_hash,
        )
        return

    if isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(
            child.signature,
            child.tbs_certificate_bytes,
            ec.ECDSA(signature_hash),
        )
        return

    raise AppStoreVerificationError("Unsupported App Store certificate public key type.")


def _ensure_certificate_valid_now(cert: x509.Certificate) -> None:
    now = datetime.now(tz=UTC)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    if now < not_before or now > not_after:
        raise AppStoreVerificationError("App Store certificate is outside its validity period.")


def _verify_certificate_chain(certificates: list[x509.Certificate], trusted_roots: list[x509.Certificate]) -> None:
    if not certificates:
        raise AppStoreVerificationError("App Store JWS header is missing x5c certificates.")

    for cert in certificates:
        _ensure_certificate_valid_now(cert)

    for index in range(len(certificates) - 1):
        _verify_certificate_signature(certificates[index], certificates[index + 1])

    chain_root = certificates[-1]
    for trusted_root in trusted_roots:
        try:
            _ensure_certificate_valid_now(trusted_root)
            if chain_root.fingerprint(hashes.SHA256()) == trusted_root.fingerprint(hashes.SHA256()):
                return
            _verify_certificate_signature(chain_root, trusted_root)
            return
        except (AppStoreVerificationError, InvalidSignature):
            logger.debug("Trusted root candidate did not match chain root", exc_info=True)
            continue

    raise AppStoreVerificationError("App Store JWS chain does not terminate at a trusted root.")


def verify_and_decode_signed_jws(signed_jws: str, *, bundle_id: str | None = None) -> VerifiedAppStoreJWS:
    parts = signed_jws.split(".")
    if len(parts) != 3:
        raise AppStoreVerificationError("Malformed App Store JWS.")

    header = json.loads(_b64url_decode(parts[0]))
    x5c_entries = header.get("x5c")
    if not isinstance(x5c_entries, list) or not x5c_entries:
        raise AppStoreVerificationError("App Store JWS header missing x5c certificate chain.")

    certificates = tuple(
        x509.load_der_x509_certificate(base64.b64decode(cert_b64))
        for cert_b64 in x5c_entries
    )
    trusted_roots = _load_trusted_root_certificates()
    _verify_certificate_chain(list(certificates), trusted_roots)

    public_key = certificates[0].public_key()
    payload = jwt.decode(
        signed_jws,
        key=public_key,
        algorithms=[header.get("alg", "ES256")],
        options={
            "verify_signature": True,
            "verify_aud": False,
            "verify_iss": False,
            "verify_exp": False,
            "verify_nbf": False,
            "verify_iat": False,
        },
    )

    if bundle_id:
        candidate_bundle = payload.get("bundleId") or payload.get("bid")
        if candidate_bundle and candidate_bundle != bundle_id:
            raise AppStoreVerificationError("App Store JWS bundleId does not match this app.")

    return VerifiedAppStoreJWS(header=header, payload=payload, certificates=certificates)


def _load_private_key() -> tuple[str, str, str]:
    issuer_id = os.getenv("APP_STORE_CONNECT_ISSUER_ID", "").strip()
    key_id = os.getenv("APP_STORE_CONNECT_KEY_ID", "").strip()
    private_key_pem = os.getenv("APP_STORE_CONNECT_PRIVATE_KEY", "").strip()
    private_key_path = os.getenv("APP_STORE_CONNECT_PRIVATE_KEY_PATH", "").strip()

    if not private_key_pem and private_key_path:
        private_key_pem = Path(private_key_path).read_text(encoding="utf-8")

    if not issuer_id or not key_id or not private_key_pem:
        raise AppStoreConfigurationError(
            "APP_STORE_CONNECT_ISSUER_ID, APP_STORE_CONNECT_KEY_ID, and APP_STORE_CONNECT_PRIVATE_KEY(_PATH) are required."
        )

    return issuer_id, key_id, private_key_pem


def make_app_store_api_token(bundle_id: str) -> str:
    issuer_id, key_id, private_key_pem = _load_private_key()
    now = datetime.now(tz=UTC)
    payload = {
        "iss": issuer_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "aud": "appstoreconnect-v1",
        "bid": bundle_id,
    }
    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"})


def _validate_transaction_id(transaction_id: str) -> None:
    """Ensure transaction_id is numeric (Apple's format)."""
    import re
    if not re.match(r'^\d+$', transaction_id):
        raise ValueError(f"Invalid transaction_id: {transaction_id!r}")


def _base_url_for_environment(environment: str | None) -> str:
    env = (environment or "").lower()
    return SANDBOX_API_BASE_URL if env == "sandbox" else PRODUCTION_API_BASE_URL


async def fetch_transaction_info(
    transaction_id: str,
    *,
    bundle_id: str,
    environment: str | None = None,
) -> dict[str, Any]:
    _validate_transaction_id(transaction_id)
    token = make_app_store_api_token(bundle_id)
    base_url = _base_url_for_environment(environment)
    url = f"{base_url}/inApps/v1/transactions/{transaction_id}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    response.raise_for_status()
    return response.json()
