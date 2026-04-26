"""Apple JWT validation module for Sign in with Apple."""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

import httpx
import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from fastapi import HTTPException

APPLE_PUBLIC_KEY_URL = "https://appleid.apple.com/auth/keys"

# In-memory cache for Apple public keys (JWKS)
_apple_public_keys: dict[str, Any] = {}
_keys_last_fetched: float = 0
_CACHE_DURATION_SECONDS = 86400  # Cache keys for 24 hours


def _fetch_apple_public_keys() -> None:
    """Fetch public keys from Apple and update the cache."""
    global _apple_public_keys, _keys_last_fetched

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(APPLE_PUBLIC_KEY_URL)
            resp.raise_for_status()

            keys_data = resp.json()
            _apple_public_keys = {key["kid"]: key for key in keys_data.get("keys", [])}
            _keys_last_fetched = time.time()
    except (httpx.HTTPError, ValueError, KeyError) as e:
        # If cache exists and request fails, keeping old cache is safer
        if not _apple_public_keys:
            logger.error("Failed to fetch Apple public keys: %s", e)
            raise HTTPException(status_code=500, detail="Authentication service unavailable")  # noqa: B904


def _get_rsa_public_key(kid: str) -> str | bytes:
    """Convert a JWK to a PEM format public key."""
    # Refresh cache if needed or if kid is not in cache
    if time.time() - _keys_last_fetched > _CACHE_DURATION_SECONDS or kid not in _apple_public_keys:
        _fetch_apple_public_keys()

    jwk = _apple_public_keys.get(kid)
    if not jwk:
        raise HTTPException(status_code=401, detail="Invalid token kid (Key ID)")

    # Decode base64url encoded n and e
    def _base64url_decode(v: str) -> bytes:
        v = v + '=' * (4 - len(v) % 4)
        v = v.replace('-', '+').replace('_', '/')
        import base64
        return base64.b64decode(v)

    n_bytes = _base64url_decode(jwk["n"])
    e_bytes = _base64url_decode(jwk["e"])

    n = int.from_bytes(n_bytes, byteorder='big')
    e = int.from_bytes(e_bytes, byteorder='big')

    public_numbers = RSAPublicNumbers(e, n)
    public_key = public_numbers.public_key(default_backend())

    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return pem


def verify_apple_token(token: str, audience: str) -> tuple[str, str | None, bool]:
    """Validate Apple Identity Token and return ``(sub, email, email_verified)``.

    Apple only includes ``email`` / ``email_verified`` on the **first**
    sign-in; subsequent tokens carry ``sub`` only. Returning ``None`` for
    email is therefore a normal case — callers must fall back to ``sub``-only
    lookup. ``email_verified`` may be a string (``"true"``) or bool;
    normalized here.

    Client-supplied emails MUST NOT be trusted — see C1 takeover regression.
    """
    try:
        # 1. Fetch the completely unverified header to get the 'kid'
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Token missing kid")

        # 2. Get the corresponding public key
        public_key = _get_rsa_public_key(kid)

        # 3. Decode and verify the token
        # See https://developer.apple.com/documentation/sign_in_with_apple/sign_in_with_apple_rest_api/verifying_a_user
        decoded = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer="https://appleid.apple.com"
        )

        # 4. Extract subject (user ID)
        sub = decoded.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing subject (sub)")

        email_raw = decoded.get("email")
        email = str(email_raw).strip().lower() if email_raw else None
        # Apple may send "true" (str) or true (bool) — normalize.
        email_verified = str(decoded.get("email_verified", "")).strip().lower() == "true"

        return str(sub), email, email_verified

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")  # noqa: B904
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid audience (Bundle ID mismatch)")  # noqa: B904
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Invalid issuer")  # noqa: B904
    except jwt.PyJWTError as e:
        logger.warning("Apple JWT validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")  # noqa: B904
    except HTTPException:
        raise
    except (KeyError, ValueError, httpx.HTTPError) as e:
        logger.error("Apple token verification error: %s", e)
        raise HTTPException(status_code=401, detail="Authentication failed")  # noqa: B904
