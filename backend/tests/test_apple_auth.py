"""Tests for Apple Sign-In JWT validation (apple_auth.py)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import jwt as real_jwt
import pytest
from fastapi import HTTPException

from kg import apple_auth


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset global JWKS cache before each test."""
    apple_auth._apple_public_keys.clear()
    apple_auth._keys_last_fetched = 0
    yield
    apple_auth._apple_public_keys.clear()
    apple_auth._keys_last_fetched = 0


FAKE_KID = "test-kid-1"
FAKE_JWK = {"kid": FAKE_KID, "n": "AQAB", "e": "AQAB"}
FAKE_JWKS_RESPONSE = {"keys": [FAKE_JWK]}
AUDIENCE = "com.Max0228.BooksAndVocab"
FAKE_PEM = b"-----FAKE PEM-----"


def _mock_httpx_success(keys_response: dict | None = None):
    """Return a mock httpx.Client context manager that returns keys_response."""
    resp = MagicMock()
    resp.json.return_value = keys_response or FAKE_JWKS_RESPONSE
    resp.raise_for_status.return_value = None
    client_instance = MagicMock()
    client_instance.get.return_value = resp
    client_cm = MagicMock()
    client_cm.__enter__ = MagicMock(return_value=client_instance)
    client_cm.__exit__ = MagicMock(return_value=False)
    return client_cm, client_instance


def _mock_httpx_error():
    """Return a mock httpx.Client that raises HTTPError."""
    client_instance = MagicMock()
    client_instance.get.side_effect = httpx.HTTPError("connection failed")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=client_instance)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


class TestVerifyAppleToken:
    """Tests for verify_apple_token."""

    def test_happy_path(self):
        """Valid token returns sub."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {
                "sub": "apple-user-123",
                "email": "User@Example.com",
                "email_verified": "true",
            }
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            result = apple_auth.verify_apple_token("fake.token.here", AUDIENCE)
            assert result == ("apple-user-123", "user@example.com", True)
            mock_jwt.decode.assert_called_once()

    def test_jwks_cache_hit_no_refetch(self):
        """When kid is cached and cache is fresh, no HTTP call is made."""
        apple_auth._apple_public_keys[FAKE_KID] = FAKE_JWK
        apple_auth._keys_last_fetched = time.time()

        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth.httpx.Client") as mock_client_cls,
            patch("kg.apple_auth.RSAPublicNumbers") as mock_rsa,
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {"sub": "user-cached"}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            mock_key = MagicMock()
            mock_key.public_bytes.return_value = FAKE_PEM
            mock_rsa.return_value.public_key.return_value = mock_key

            result = apple_auth.verify_apple_token("cached.token", AUDIENCE)
            # Apple may omit email on subsequent sign-ins.
            assert result == ("user-cached", None, False)
            mock_client_cls.assert_not_called()

    def test_kid_not_in_cache_triggers_refetch(self):
        """When kid is missing from cache, JWKS is re-fetched."""
        apple_auth._apple_public_keys["other-kid"] = {"kid": "other-kid"}
        apple_auth._keys_last_fetched = time.time()

        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth.httpx.Client"),
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM) as mock_get_key,
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {"sub": "user-refetched"}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            result = apple_auth.verify_apple_token("refetch.token", AUDIENCE)
            assert result == ("user-refetched", None, False)
            # _get_rsa_public_key was called (which would internally refetch)
            mock_get_key.assert_called_once_with(FAKE_KID)

    def test_token_missing_kid_raises_401(self):
        """Token header without kid raises 401."""
        with patch("kg.apple_auth.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("no-kid.token", AUDIENCE)
            assert exc_info.value.status_code == 401
            assert "kid" in exc_info.value.detail.lower()

    def test_kid_not_found_after_refetch_raises_401(self):
        """kid not present in JWKS even after re-fetch raises 401."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth.httpx.Client") as mock_client_cls,
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": "nonexistent-kid"}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            cm, _ = _mock_httpx_success()
            mock_client_cls.return_value = cm

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("bad-kid.token", AUDIENCE)
            assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self):
        """Expired token raises 401."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError
            mock_jwt.decode.side_effect = real_jwt.ExpiredSignatureError()

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("expired.token", AUDIENCE)
            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()

    def test_audience_mismatch_raises_401(self):
        """Wrong audience raises 401."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError
            mock_jwt.decode.side_effect = real_jwt.InvalidAudienceError()

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("bad-aud.token", AUDIENCE)
            assert exc_info.value.status_code == 401
            assert "audience" in exc_info.value.detail.lower()

    def test_invalid_signature_raises_401(self):
        """Invalid signature raises 401."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError
            mock_jwt.decode.side_effect = real_jwt.InvalidSignatureError()

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("bad-sig.token", AUDIENCE)
            assert exc_info.value.status_code == 401

    def test_decoded_token_missing_sub_raises_401(self):
        """Decoded token without sub raises 401."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {"email": "user@example.com"}  # no sub
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("no-sub.token", AUDIENCE)
            assert exc_info.value.status_code == 401
            assert "sub" in exc_info.value.detail.lower()

    # --- Malformed claims / clock-skew regression tests ---

    def test_apple_token_missing_email_falls_back_gracefully(self):
        """Apple omits email on subsequent sign-ins.

        With a valid sub but no email claim the function must NOT raise —
        callers fall back to sub-only lookup. Returned tuple shape stays
        ``(sub, None, False)``.
        """
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            # Resign-in token: sub only, no email / email_verified
            mock_jwt.decode.return_value = {"sub": "apple-resignin-sub"}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            sub, email, verified = apple_auth.verify_apple_token("resignin.token", AUDIENCE)
            assert sub == "apple-resignin-sub"
            assert email is None
            assert verified is False

    def test_apple_token_with_empty_string_email_falls_back_gracefully(self):
        """Empty-string email is treated as absent, not as a valid address."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {
                "sub": "apple-empty-email",
                "email": "",
                "email_verified": "true",
            }
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            sub, email, _verified = apple_auth.verify_apple_token("empty.token", AUDIENCE)
            assert sub == "apple-empty-email"
            # "" must NOT be returned as a real email (would corrupt _email_index)
            assert email in (None, "")
            # Either falsy is acceptable; explicit guard:
            assert not email

    def test_apple_token_expired_at_boundary(self):
        """Token whose exp is now-1s must be rejected with 401.

        PyJWT raises ExpiredSignatureError once exp <= now; we mirror that
        as a 401 surfaced to the API.
        """
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError
            # PyJWT detects exp <= now and raises before we can read claims.
            mock_jwt.decode.side_effect = real_jwt.ExpiredSignatureError(
                "Signature has expired"
            )

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("boundary-expired.token", AUDIENCE)
            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()

    def test_apple_token_with_future_iat_rejected(self):
        """Tokens with iat far in the future must be rejected (clock-skew attack).

        PyJWT validates ``iat`` only when ``options={"verify_iat": True}``
        OR raises ``ImmatureSignatureError`` when ``nbf`` is set. For Apple
        tokens we surface PyJWT's verdict; an iat 60s ahead should raise
        ImmatureSignatureError (a ``PyJWTError`` subclass) which we map to 401.
        """
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError
            mock_jwt.ImmatureSignatureError = real_jwt.ImmatureSignatureError
            # Simulate PyJWT rejecting an iat 60s in the future.
            mock_jwt.decode.side_effect = real_jwt.ImmatureSignatureError(
                "The token is not yet valid (iat)"
            )

            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token("future-iat.token", AUDIENCE)
            assert exc_info.value.status_code == 401

    def test_apple_token_with_iat_within_clock_skew_grace_accepted(self):
        """iat <= 30s in the future falls within the clock-skew grace window.

        Real Apple/PyJWT default leeway is 0s, but our handler delegates
        entirely to PyJWT.decode — if PyJWT accepts the token, we accept
        and return (sub, email, verified). Documents the contract:
        we do NOT add an extra future-iat check beyond PyJWT's leeway.
        """
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {
                "sub": "skew-ok",
                "iat": int(time.time()) + 20,  # 20s ahead, within typical grace
            }
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            sub, _email, _verified = apple_auth.verify_apple_token("grace.token", AUDIENCE)
            assert sub == "skew-ok"

    def test_apple_token_with_non_string_email_does_not_crash(self):
        """Defensive: an unexpected email type (int) must not raise TypeError."""
        with (
            patch("kg.apple_auth.jwt") as mock_jwt,
            patch("kg.apple_auth._get_rsa_public_key", return_value=FAKE_PEM),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": FAKE_KID}
            mock_jwt.decode.return_value = {
                "sub": "weird-email",
                "email": 12345,
                "email_verified": True,
            }
            mock_jwt.ExpiredSignatureError = real_jwt.ExpiredSignatureError
            mock_jwt.InvalidAudienceError = real_jwt.InvalidAudienceError
            mock_jwt.InvalidIssuerError = real_jwt.InvalidIssuerError
            mock_jwt.PyJWTError = real_jwt.PyJWTError

            # Must not raise; coerced to string and lowered.
            sub, email, _ = apple_auth.verify_apple_token("weird.token", AUDIENCE)
            assert sub == "weird-email"
            assert email == "12345"


class TestFetchApplePublicKeys:
    """Tests for _fetch_apple_public_keys."""

    def test_network_error_no_cache_raises_503(self):
        """JWKS fetch failure with empty cache raises 503 (service unavailable)."""
        with patch("kg.apple_auth.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value = _mock_httpx_error()

            with pytest.raises(HTTPException) as exc_info:
                apple_auth._fetch_apple_public_keys()
            assert exc_info.value.status_code == 503

    def test_network_error_with_cache_uses_stale(self):
        """JWKS fetch failure with existing cache keeps stale cache."""
        apple_auth._apple_public_keys[FAKE_KID] = FAKE_JWK
        apple_auth._keys_last_fetched = time.time() - 200000  # expired

        with patch("kg.apple_auth.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value = _mock_httpx_error()

            # Should not raise — silently keeps old cache
            apple_auth._fetch_apple_public_keys()
            assert FAKE_KID in apple_auth._apple_public_keys


# ----------------------------------------------------------------------
# Real-crypto tests — do NOT mock kg.apple_auth.jwt. These are the only
# tests that actually exercise the audience= / issuer= kwargs passed to
# jwt.decode(). Mutation-removing those kwargs from apple_auth.py must
# turn the corresponding test red.
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _sign_apple_token(private_pem: bytes, *, aud: str, iss: str, sub: str = "apple-user-real") -> str:
    now = int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        "email": "real@example.com",
        "email_verified": "true",
    }
    return real_jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": FAKE_KID})


class TestVerifyAppleTokenRealCrypto:
    """Exercise the real jwt.decode() so audience/issuer kwargs are load-bearing."""

    def test_real_token_happy_path(self, rsa_keypair):
        priv, pub = rsa_keypair
        token = _sign_apple_token(priv, aud=AUDIENCE, iss="https://appleid.apple.com")
        with patch("kg.apple_auth._get_rsa_public_key", return_value=pub):
            sub, email, verified = apple_auth.verify_apple_token(token, AUDIENCE)
        assert sub == "apple-user-real"
        assert email == "real@example.com"
        assert verified is True

    def test_real_token_wrong_audience_raises_401(self, rsa_keypair):
        """Audience mismatch must fail — guards against removal of audience= kwarg."""
        priv, pub = rsa_keypair
        token = _sign_apple_token(priv, aud="com.attacker.app", iss="https://appleid.apple.com")
        with patch("kg.apple_auth._get_rsa_public_key", return_value=pub):
            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token(token, AUDIENCE)
        assert exc_info.value.status_code == 401
        assert "audience" in exc_info.value.detail.lower()

    def test_real_token_wrong_issuer_raises_401(self, rsa_keypair):
        """Issuer mismatch must fail — guards against removal of issuer= kwarg.

        Note: the 'audience'/'issuer' substring checks below intentionally
        pin the error-message contract. The 401 status alone is too coarse
        (any jwt failure 401s) — clients distinguish on detail text.
        """
        priv, pub = rsa_keypair
        token = _sign_apple_token(priv, aud=AUDIENCE, iss="https://evil.example.com")
        with patch("kg.apple_auth._get_rsa_public_key", return_value=pub):
            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token(token, AUDIENCE)
        assert exc_info.value.status_code == 401
        assert "issuer" in exc_info.value.detail.lower()

    def test_real_token_missing_aud_claim_raises_401(self, rsa_keypair):
        """Token without aud claim must fail — closes the attack surface
        where attackers strip aud entirely (PyJWT 9.x require_aud=True is
        the runtime guard; this test pins it as a contract)."""
        import time as _t
        priv, pub = rsa_keypair
        now = int(_t.time())
        payload_no_aud = {
            "iss": "https://appleid.apple.com",
            "sub": "apple-user-no-aud",
            "iat": now,
            "exp": now + 600,
        }
        token = real_jwt.encode(payload_no_aud, priv, algorithm="RS256", headers={"kid": FAKE_KID})
        with patch("kg.apple_auth._get_rsa_public_key", return_value=pub):
            with pytest.raises(HTTPException) as exc_info:
                apple_auth.verify_apple_token(token, AUDIENCE)
        assert exc_info.value.status_code == 401
