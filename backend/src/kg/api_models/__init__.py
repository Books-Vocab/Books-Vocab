"""API request/response Pydantic models.

Split by domain into submodules; this package re-exports every model so that
existing ``from kg.api_models import X`` callers remain unchanged.
"""

from __future__ import annotations

from kg.api_models.auth import (
    AuthVerifyRequest,
    AuthVerifyResponse,
    DeleteAccountResponse,
    UserConfigRequest,
    UserConfigResponse,
)
from kg.api_models.billing import (
    AdminGrantRequest,
    AdminGrantStatusResponse,
    AdminUserEntitlementResponse,
    AppStoreNotificationRequest,
    AppStoreNotificationResponse,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    EntitlementsResponse,
    QuotaResponse,
    SubscriptionStatusResponse,
)
from kg.api_models.cards import CardLinkSummaryResponse, CardResponse
from kg.api_models.common import VocabSource, _normalize_context
from kg.api_models.graph import GraphLinkResponse, ManualLinkRequest
from kg.api_models.notebook import (
    VALID_COVER_PATTERNS,
    NotebookCreateRequest,
    NotebookResponse,
    NotebookUpdateRequest,
)
from kg.api_models.review import (
    DailyReviewStatEntry,
    DailyReviewStatsPushRequest,
    DailyReviewStatsPushResponse,
    DailyReviewStatsResponse,
    ReviewStateEntry,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
)
from kg.api_models.system import (
    AdminTestRunRequest,
    HealthResponse,
    PipelineQueueResponse,
)
from kg.api_models.translate import (
    ExplainResponse,
    PhraseTranslateResponse,
    QuickTranslateResponse,
    TranslateRequest,
    TranslationLanguageConfig,
)
from kg.api_models.vocab import (
    ArchiveWordRequest,
    ArchiveWordResponse,
    BatchArchiveRequest,
    BatchArchiveResponse,
    BatchDeleteRequest,
    BatchDeleteResponse,
    DeleteWordResponse,
    VocabAddResponse,
    VocabEntry,
)

__all__ = [
    "VALID_COVER_PATTERNS",
    "AdminGrantRequest",
    "AdminGrantStatusResponse",
    "AdminTestRunRequest",
    "AdminUserEntitlementResponse",
    "AppStoreNotificationRequest",
    "AppStoreNotificationResponse",
    "AppStoreReconcileRequest",
    "AppStoreSyncRequest",
    "ArchiveWordRequest",
    "ArchiveWordResponse",
    "AuthVerifyRequest",
    "AuthVerifyResponse",
    "BatchArchiveRequest",
    "BatchArchiveResponse",
    "BatchDeleteRequest",
    "BatchDeleteResponse",
    "CardLinkSummaryResponse",
    "CardResponse",
    "DailyReviewStatEntry",
    "DailyReviewStatsPushRequest",
    "DailyReviewStatsPushResponse",
    "DailyReviewStatsResponse",
    "DeleteAccountResponse",
    "DeleteWordResponse",
    "EntitlementsResponse",
    "ExplainResponse",
    "GraphLinkResponse",
    "HealthResponse",
    "ManualLinkRequest",
    "NotebookCreateRequest",
    "NotebookResponse",
    "NotebookUpdateRequest",
    "PhraseTranslateResponse",
    "PipelineQueueResponse",
    "QuickTranslateResponse",
    "QuotaResponse",
    "ReviewStateEntry",
    "ReviewStatePushRequest",
    "ReviewStatePushResponse",
    "SubscriptionStatusResponse",
    "TranslateRequest",
    "TranslationLanguageConfig",
    "UserConfigRequest",
    "UserConfigResponse",
    "VocabAddResponse",
    "VocabEntry",
    "VocabSource",
    "_normalize_context",
]
