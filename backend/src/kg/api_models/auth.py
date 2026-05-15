from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kg.api_models.translate import TranslationLanguageConfig


class AuthVerifyRequest(BaseModel):
    provider: Literal["apple", "google"]
    token: str = Field(max_length=10000)
    # NOTE: client-supplied `email` field is intentionally accepted-and-ignored
    # (Pydantic drops unknown fields by default). Server trusts ONLY the
    # provider-token-derived email for account linkage; see C1 takeover
    # regression in tests/test_auth_takeover.py.
    email: str | None = None


class AuthVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    expires_in: int  # seconds


class UserConfigRequest(BaseModel):
    translation: TranslationLanguageConfig | None = None


class UserConfigResponse(BaseModel):
    translation: TranslationLanguageConfig | None = None


class DeleteAccountResponse(BaseModel):
    deleted_user_id: str
    linked_ids: list[str]
    deleted_dirs: list[str]
