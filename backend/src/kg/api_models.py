from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VocabEntry(BaseModel):
    """A vocabulary entry from BooksBrowser."""

    word: str = Field(max_length=200)
    translation: str = Field(max_length=1000)
    context: str = Field(default="", max_length=5000)
    root_form: str | None = None  # AI-determined lemma from translate/quick
    pronunciation: str | None = None  # IPA phonetic transcription


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
    db_ok: bool = True
    disk_free_mb: int | None = None
    data_dir_exists: bool = True


class CardResponse(BaseModel):
    id: str
    content: str
    meaning: str
    pos: str | None
    difficulty: float | None
    difficultyTier: str | None
    note: str | None
    collocations: list[str] = []
    examples: list[str]
    mode: str
    isDeleted: bool
    isArchived: bool = False
    pronunciation: str | None = None
    inflections: list[str] = []
    linksByKind: dict[str, list[CardLinkSummaryResponse]] = Field(default_factory=dict)
    updatedAt: str | None = None
    # Review state
    reviewIntervalHours: float = 12.0
    nextReviewAt: str | None = None
    lastReviewedAt: str | None = None
    reviewCount: int = 0
    lapseCount: int = 0
    reviewStreak: int = 0
    lastReviewFeedback: int = -1


class CardLinkSummaryResponse(BaseModel):
    id: str
    cardId: str
    word: str
    kind: str
    label: str
    confidence: float
    reason: str


class TranslationLanguageConfig(BaseModel):
    source_lang: str = "en"
    target_lang: str = "zh-Hant"


class TranslateRequest(BaseModel):
    word: str = Field(max_length=500)
    context: str = Field(max_length=5000)
    source_lang: str | None = None
    target_lang: str | None = None


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
    token: str = Field(max_length=10000)
    email: str | None = None  # Optional: email from provider


class AuthVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    expires_in: int  # seconds


class MochiIntegrationConfig(BaseModel):
    api_key: str | None = None


class MochiIntegrationResponseConfig(BaseModel):
    has_api_key: bool = False


class UserIntegrationsConfig(BaseModel):
    mochi: MochiIntegrationConfig | None = None


class UserIntegrationsResponseConfig(BaseModel):
    mochi: MochiIntegrationResponseConfig | None = None


class UserConfigRequest(BaseModel):
    integrations: UserIntegrationsConfig | None = None
    translation: TranslationLanguageConfig | None = None


class UserConfigResponse(BaseModel):
    integrations: UserIntegrationsResponseConfig | None = None
    translation: TranslationLanguageConfig | None = None


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


class AdminGrantStatusResponse(BaseModel):
    is_active: bool
    status: str
    plan_name: str | None = None
    source: str = "admin"
    expires_at: str | None = None
    granted_at: str | None = None
    granted_by: str | None = None
    reason: str | None = None
    last_synced_at: str | None = None


class AdminGrantRequest(BaseModel):
    reason: str | None = None
    expires_at: str | None = None
    granted_by: str | None = None


class AdminUserEntitlementResponse(BaseModel):
    user_id: str
    pro: SubscriptionStatusResponse
    admin_grant: AdminGrantStatusResponse


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


class ArchiveWordRequest(BaseModel):
    archived: bool


class DeleteWordResponse(BaseModel):
    deleted: str
    id: str


class PhraseTranslateResponse(BaseModel):
    t: str


class PipelineQueueResponse(BaseModel):
    status: str
    message: str


class AppStoreNotificationResponse(BaseModel):
    status: str
    updated: bool
    reason: str | None = None
    user_id: str | None = None
    entitlements: dict[str, Any] | None = None


class ReviewStateEntry(BaseModel):
    word: str
    review_interval_hours: float
    next_review_at: str  # ISO8601
    last_reviewed_at: str  # ISO8601
    review_count: int
    lapse_count: int
    review_streak: int
    last_review_feedback: int


class ReviewStatePushRequest(BaseModel):
    entries: list[ReviewStateEntry]


class ReviewStatePushResponse(BaseModel):
    updated: int
    skipped: int


class DailyReviewStatEntry(BaseModel):
    day_key: str  # "yyyy-MM-dd"
    total: int
    remembered: int
    forgot: int


class DailyReviewStatsPushRequest(BaseModel):
    entries: list[DailyReviewStatEntry]


class DailyReviewStatsPushResponse(BaseModel):
    upserted: int


class DailyReviewStatsResponse(BaseModel):
    entries: list[DailyReviewStatEntry]
