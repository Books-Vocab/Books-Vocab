"""Tests for Google Sign-In token validation (google_auth.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError

from kg import google_auth

CLIENT_ID = "test-client-id.apps.googleusercontent.com"


class TestVerifyGoogleToken:
    """Tests for verify_google_token."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Valid token returns sub."""
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "google-user-456",
                "email": "U@Gmail.com",
                "email_verified": True,
            }
            result = await google_auth.verify_google_token("valid.token", CLIENT_ID)
            assert result == ("google-user-456", "u@gmail.com", True)
            mock_verify.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        """Invalid token (ValueError) raises 401."""
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.side_effect = ValueError("Token is not valid")
            with pytest.raises(HTTPException) as exc_info:
                await google_auth.verify_google_token("invalid.token", CLIENT_ID)
            assert exc_info.value.status_code == 401
            assert "invalid" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_missing_sub_raises_401(self):
        """Decoded token without sub raises 401."""
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.return_value = {"email": "u@gmail.com"}  # no sub
            with pytest.raises(HTTPException) as exc_info:
                await google_auth.verify_google_token("no-sub.token", CLIENT_ID)
            assert exc_info.value.status_code == 401
            assert "sub" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_google_service_unavailable_raises_401(self):
        """Google service error (GoogleAuthError) raises 401."""
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.side_effect = GoogleAuthError("Service unavailable")
            with pytest.raises(HTTPException) as exc_info:
                await google_auth.verify_google_token("err.token", CLIENT_ID)
            assert exc_info.value.status_code == 401

    # --- Malformed claims / clock-skew regression tests ---

    @pytest.mark.asyncio
    async def test_google_token_with_unverified_email_returns_flag_false(self):
        """Unverified email must surface ``email_verified=False`` to caller.

        Contract: ``verify_google_token`` is non-opinionated — it returns
        the verification flag so handlers can decide whether to link.
        ``auth_handlers.auth_verify_response`` then sets ``link_email=None``
        when the flag is false, creating an independent account keyed by
        provider sub. The function MUST NOT silently treat unverified email
        as verified, and MUST NOT crash.
        """
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "google-unverified-1",
                "email": "spoof@evil.example",
                "email_verified": False,
            }
            sub, email, verified = await google_auth.verify_google_token(
                "unverified.token", CLIENT_ID
            )
            assert sub == "google-unverified-1"
            assert email == "spoof@evil.example"
            # CRITICAL: must report unverified so caller refuses to link.
            assert verified is False

    @pytest.mark.asyncio
    async def test_google_token_with_missing_email_verified_defaults_false(self):
        """Missing email_verified claim defaults to False (fail-closed)."""
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "google-missing-flag",
                "email": "user@example.com",
                # email_verified intentionally absent
            }
            _, _, verified = await google_auth.verify_google_token(
                "no-flag.token", CLIENT_ID
            )
            assert verified is False

    @pytest.mark.asyncio
    async def test_google_token_expired_at_boundary_raises_401(self):
        """exp = now - 1s → google-auth raises ValueError → 401."""
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.side_effect = ValueError("Token expired, 1234567890 < 1234567891")
            with pytest.raises(HTTPException) as exc_info:
                await google_auth.verify_google_token("expired.token", CLIENT_ID)
            assert exc_info.value.status_code == 401
            assert "invalid" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_google_token_with_future_iat_rejected(self):
        """iat 60s in the future → google-auth raises ValueError → 401.

        google-auth allows ~10min clock skew by default; a token 60s
        ahead is normally accepted. We assert that when google-auth
        does reject (signaling clock skew beyond its tolerance), we
        surface 401 cleanly rather than 500.
        """
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.side_effect = ValueError(
                "Token used too early, iat is in the future"
            )
            with pytest.raises(HTTPException) as exc_info:
                await google_auth.verify_google_token("future-iat.token", CLIENT_ID)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_google_token_with_empty_email_normalized_to_none(self):
        """Empty email string must not leak into _email_index as "".

        Returning "" would corrupt the email→user map. Defensive
        normalization: empty falsy email becomes None.
        """
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "google-empty-email",
                "email": "",
                "email_verified": True,
            }
            _, email, _ = await google_auth.verify_google_token(
                "empty.token", CLIENT_ID
            )
            assert email is None

    @pytest.mark.asyncio
    async def test_google_token_with_email_verified_string_true_accepted(self):
        """``email_verified`` may arrive as string ``"true"`` in some payloads.

        bool("true") is True regardless, but bool("false") is also True —
        the current implementation uses ``bool(...)`` which would misread
        the string "false" as verified. Guard against that footgun.
        """
        with patch("kg.google_auth.id_token.verify_oauth2_token") as mock_verify:
            mock_verify.return_value = {
                "sub": "google-strflag",
                "email": "u@example.com",
                "email_verified": "false",  # string false — must not become True
            }
            _, _, verified = await google_auth.verify_google_token(
                "strflag.token", CLIENT_ID
            )
            assert verified is False
