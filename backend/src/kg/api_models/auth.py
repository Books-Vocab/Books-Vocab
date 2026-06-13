from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kg.api_models.graph import AutoLinkConfig
from kg.api_models.notebook import VocabUIConfig
from kg.api_models.review import ReviewClockConfig, ReviewModeConfig
from kg.api_models.translate import TranslationLanguageConfig


class AuthVerifyRequest(BaseModel):
    provider: Literal["apple", "google"]
    token: str = Field(min_length=1, max_length=10000)
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
    review_clock: ReviewClockConfig | None = None
    review_mode: ReviewModeConfig | None = None
    vocab_ui: VocabUIConfig | None = None
    auto_link: AutoLinkConfig | None = None


class UserConfigResponse(BaseModel):
    translation: TranslationLanguageConfig | None = None
    review_clock: ReviewClockConfig | None = None
    review_mode: ReviewModeConfig | None = None
    vocab_ui: VocabUIConfig | None = None
    auto_link: AutoLinkConfig | None = None


class UserProfileResponse(BaseModel):
    """Read-only identity face (GET /api/user/profile).

    Derived from the stored user record (provider/email set at login by
    auth_service.resolve_and_link_user). Distinct from UserConfigResponse,
    which is the mutable, LWW-synced settings bundle. `displayName` prefers an
    explicit stored name, falls back to the email local-part, else null (no
    fabrication when neither is known).
    """

    displayName: str | None = None
    email: str | None = None
    provider: str | None = None


class DeleteAccountResponse(BaseModel):
    deleted_user_id: str
    linked_ids: list[str]
    deleted_dirs: list[str]
