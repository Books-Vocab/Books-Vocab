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


async def verify_google_token(token: str, client_id: str) -> str:
    """Validate Google ID Token and return the user ID (sub).

    Args:
        token: The ID token from Google Sign-In
        client_id: Your Google OAuth 2.0 Client ID (from Google Cloud Console)

    Returns:
        The Google User ID (sub) string.
    """
    try:
        # Verify the token using Google's official validation
        request_adapter = google_requests.Request(session=_session)
        idinfo = id_token.verify_oauth2_token(token, request_adapter, client_id)

        # Token is valid, extract user ID
        sub = idinfo.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing subject (sub)")

        return str(sub)

    except ValueError as e:
        # Invalid token signature or claims
        logger.warning("Google token validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")  # noqa: B904
    except (GoogleAuthError, OSError) as e:
        logger.error("Google token verification error: %s", e)
        raise HTTPException(status_code=401, detail="Google authentication failed")  # noqa: B904
