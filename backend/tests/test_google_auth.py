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
            mock_verify.return_value = {"sub": "google-user-456", "email": "u@gmail.com"}
            result = await google_auth.verify_google_token("valid.token", CLIENT_ID)
            assert result == "google-user-456"
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
