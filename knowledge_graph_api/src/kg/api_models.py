from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VocabEntry(BaseModel):
    """A vocabulary entry from BooksBrowser."""

    word: str
    translation: str
    context: str = ""
    root_form: str | None = None  # AI-determined lemma from translate/quick


class VocabAddResponse(BaseModel):
    created: int
    skipped: int
    duplicates: list[str]
    cardIds: dict[str, str]  # word -> card_id


class HealthResponse(BaseModel):
    status: str
    cards: int
    links: int
    pendingCandidates: int
    lastModified: str | None


class CardResponse(BaseModel):
    id: str
    content: str
    meaning: str
    pos: str | None
    difficulty: float | None
    difficultyTier: str | None
    note: str | None
    examples: list[str]
    mode: str
    isDeleted: bool
    inflections: list[str] = []
    linksByKind: dict[str, list["CardLinkSummaryResponse"]] = Field(default_factory=dict)


class CardLinkSummaryResponse(BaseModel):
    id: str
    cardId: str
    word: str
    kind: str
    label: str
    confidence: float
    reason: str


class TranslateRequest(BaseModel):
    word: str
    context: str


class GraphLinkResponse(BaseModel):
    id: str
    fromId: str
    toId: str
    kind: str
    confidence: float
    reason: str


class QuickTranslateResponse(BaseModel):
    t: str
    p: str | None = None
    r: str | None = None  # root form (lemma)


class ExplainResponse(BaseModel):
    e: str


class AuthVerifyRequest(BaseModel):
    provider: str  # "apple" or "google"
    token: str
    email: str | None = None  # Optional: email from provider


class AuthVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    expires_in: int  # seconds


class MochiIntegrationConfig(BaseModel):
    api_key: str | None = None


class UserIntegrationsConfig(BaseModel):
    mochi: MochiIntegrationConfig | None = None


class UserConfigRequest(BaseModel):
    mochi_api_key: str | None = None
    integrations: UserIntegrationsConfig | None = None


class UserConfigResponse(BaseModel):
    mochi_api_key: str | None = None
    integrations: UserIntegrationsConfig | None = None


class SubscriptionStatusResponse(BaseModel):
    is_active: bool
    product_id: str | None = None
    plan_name: str | None = None
    price_display: str | None = None
    status: str
    is_trial: bool = False
    trial_days: int | None = None
    will_renew: bool = False
    expires_at: str | None = None
    source: str = "app_store"
    last_synced_at: str | None = None


class EntitlementsResponse(BaseModel):
    pro: SubscriptionStatusResponse


class AppStoreSyncRequest(BaseModel):
    product_id: str
    transaction_id: str | None = None
    original_transaction_id: str | None = None
    environment: str = "sandbox"
    status: str = "active"
    is_trial: bool = False
    expires_at: str | None = None
    will_renew: bool = True
    price_display: str | None = None
    signed_transaction_info: str | None = None


class AppStoreNotificationRequest(BaseModel):
    notification_type: str | None = None
    subtype: str | None = None
    product_id: str | None = None
    transaction_id: str | None = None
    original_transaction_id: str | None = None
    environment: str = "production"
    status: str | None = None
    is_trial: bool = False
    expires_at: str | None = None
    will_renew: bool | None = None
    signed_payload: str | None = None
    raw_payload: dict[str, Any] | None = None


class AppStoreReconcileRequest(BaseModel):
    transaction_id: str
    environment: str = "production"


class DeleteAccountResponse(BaseModel):
    deleted_user_id: str
    linked_ids: list[str]
    deleted_dirs: list[str]


class AdminTestRunRequest(BaseModel):
    itemIds: list[str] = []
