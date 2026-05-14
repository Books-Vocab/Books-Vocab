"""Google Sign-In token validation module."""

import logging

import requests as _requests
from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)

_session = _requests.Session()
_session.timeout = 10


async def verify_google_token(token: str, client_id: str) -> tuple[str, str | None, bool]:
    """Validate Google ID Token and return ``(sub, email, email_verified)``.

    Returns the token-derived email and verification flag so callers can
    safely link accounts by email (only when verified). Client-supplied
    emails MUST NOT be trusted — see C1 account-takeover regression.
    """
    try:
        # Verify the token using Google's official validation
        request_adapter = google_requests.Request(session=_session)
        idinfo = id_token.verify_oauth2_token(token, request_adapter, client_id)

        # Token is valid, extract user ID
        sub = idinfo.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing subject (sub)")

        email_raw = idinfo.get("email")
        email = str(email_raw).strip().lower() if email_raw else None
        # Some providers (and some google-auth payloads from test/proxy
        # environments) deliver email_verified as a string ("true"/"false")
        # rather than a bool. bool("false") is truthy in Python, so we
        # cannot rely on plain bool() coercion — normalize explicitly.
        raw_verified = idinfo.get("email_verified", False)
        if isinstance(raw_verified, str):
            email_verified = raw_verified.strip().lower() == "true"
        else:
            email_verified = bool(raw_verified)

        return str(sub), email, email_verified

    except ValueError as e:
        # Invalid token signature or claims
        logger.warning("Google token validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token") from e
    except (GoogleAuthError, OSError) as e:
        logger.error("Google token verification error: %s", e)
        raise HTTPException(status_code=401, detail="Google authentication failed") from e
