#!/usr/bin/env -S uv run --python 3.13 python
"""Validate UI World v2 manifest files before a tool launches the app."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCHEMA = "kg.fixture.dataset.v2"
FIXTURE_TOP_LEVEL_KEYS = {
    "schema",
    "datasetID",
    "assets",
    "preferences",
    "auth",
    "entitlements",
    "settings",
    "bookshelf",
    "todayReview",
    "notebook",
    "podcast",
    "runtimePodcast",
    "reader",
    "vocabulary",
    "reviewDeck",
    "syncPresenter",
    # Optional cross-domain state for scenarios that need one coherent clock or
    # content projection. It is not a fixture-id dictionary, so it is validated
    # separately from FIXTURE_DOMAIN_IDS.
    "scenarioContext",
}
OPTIONAL_TOP_LEVEL_KEYS = {"scenarioContext"}
REQUIRED_TOP_LEVEL_KEYS = FIXTURE_TOP_LEVEL_KEYS - OPTIONAL_TOP_LEVEL_KEYS
SCENARIO_CONTEXT_KEYS = {"reviewClock", "readerPassage", "wordDetail"}
REVIEW_CLOCK_FIELD_KEYS = {"frozenNow", "frozenEpoch", "anchorDay", "source"}
READER_PASSAGE_KEYS = {
    "bookTitle", "activeWord", "activePartOfSpeech", "activeTranslation",
    "activeExplanation", "activeContext", "paragraphs", "vocabWords", "activeWords",
}
FIXTURE_DOMAIN_IDS = {
    "auth": {"guest", "guestAuthenticating", "guestError", "signedIn", "settingsSignedIn", "longIdentity"},
    "entitlements": {"adminGranted", "cancelledButActive", "free", "pro"},
    "settings": {
        "logged_out",
        "account_logged_out_error",
        "preferences_auto_sync_off",
        "preferences_logged_out_no_sync",
        "subscribed_active",
        "account_long_identity",
        "subscription_free",
        "subscription_loading",
        "deleting_account",
        "pricing_unavailable",
        "debug_backend_local",
    },
    "bookshelf": {
        "book_card_complete",
        "book_card_long_title",
        "book_card_mid_progress",
        "book_card_pdf_format",
        "book_card_placeholder_epub",
        "progress_card",
        "placeholder_card",
        "reader_notebook_bound",
        "reader_notebook_empty",
        "reader_notebook_long_bound",
        "reader_notebook_unbound",
        "empty_library",
        "with_books_library",
        "loading_overlay",
    },
    "todayReview": {
        "front",
        "back",
        "completed",
        "autoplay",
        "autoplayPaused",
        "productionFront",
        "productionBack",
        "longContent",
    },
    "notebook": {
        "cardGallery",
        "coverGallery",
        "editGallery",
        "empty",
        "populated",
        "readerPickerMany",
        "readerPickerPopulated",
        "single",
    },
    "podcast": {"shelf_continue", "shelf_single"},
    "runtimePodcast": {"playablePreview", "tieredCatalog"},
    "reader": {"realBookLibrary"},
    "vocabulary": {
        "archivedEmpty",
        "archivedLong",
        "archivedPopulated",
        "archivedSingle",
        "knowledgeGraphEmpty",
        "knowledgeGraphPopulated",
        "kgVocabRow",
        "reviewCalendarDense",
        "searchVocabNotebook",
        "shellNavigation",
        "statsEmpty",
        "statsPopulated",
        "syncEmpty",
        "syncPendingMixed",
        "syncPendingSingle",
        "vocabLinkedCards",
        "vocabListEmpty",
        "vocabListLong",
        "vocabListPopulated",
        "vocabListSingle",
        "vocabListSyncing",
        "wordDetail",
        "wordEdit",
    },
    "reviewDeck": {"phaseLongContent", "phaseMulti", "phaseSingle", "probe", "notebookReviewDeck"},
    "syncPresenter": {"ready", "running", "completed", "partialFailure", "fullFailure"},
}
ASSET_BUCKETS = {"books", "audio", "images", "subtitles", "text"}
ASSET_REQUIRED_KEYS = {"sourcePath", "sha256", "installAs", "byteSize", "contentType"}
ASSET_CONTENT_TYPES_BY_BUCKET = {
    "books": {"application/epub+zip", "application/pdf", "text/markdown; charset=utf-8", "text/plain; charset=utf-8"},
    "audio": {"audio/mp4", "audio/mpeg"},
    "subtitles": {"application/x-subrip; charset=utf-8", "text/vtt; charset=utf-8"},
    "text": {"text/markdown; charset=utf-8", "text/plain; charset=utf-8"},
    "images": {"image/png", "image/jpeg"},
}
ASSET_CONTENT_TYPES_BY_EXTENSION = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
PREFERENCES_KEYS = {"userDefaults", "ubiquitousKeyValueStore"}
PREFERENCE_DOMAIN_KEYS = {
    "userDefaults": {
        "activeNotebookId",
        "active_notebook_updated_at",
        "app_appearance_selection",
        "app_language_selection",
        "auto_sync_enabled",
        "hasSeenWelcome",
        "kg_last_incremental_sync",
        "kg_review_payload_version",
        "podcast.autoPauseOnLookup",
        "podcast.subtitleSize",
        "podcast.wordFollowEnabled",
        "reader_settings_font",
        "reader_settings_fontSize",
        "reader_settings_lineHeight",
        "reader_settings_scrollMode",
        "reader_settings_showHitTestingDebug",
        "reader_settings_underlineOpacity",
        "review_settings_autoplay_sound_enabled",
        "review_settings_autoplay_speed",
        "review_settings_custom_params",
        "review_settings_mode",
        "review_settings_mode_updated_at",
        "review_settings_progress_paused",
        "review_settings_progress_paused_at",
        "review_settings_progress_updated_at",
        "translation_source_lang",
        "translation_source_lang_updated_at",
        "translation_target_lang",
        "translation_target_lang_updated_at",
        "vocab_highlight_colorPreset",
        "vocab_highlight_opacity",
    },
    "ubiquitousKeyValueStore": {
        "activeNotebookId",
        "active_notebook_updated_at",
        "app_appearance_selection",
        "app_language_selection",
        "reader_settings_font",
        "reader_settings_fontSize",
        "reader_settings_lineHeight",
        "reader_settings_scrollMode",
        "reader_settings_underlineOpacity",
        "review_settings_custom_params",
        "review_settings_mode",
        "review_settings_mode_updated_at",
        "review_settings_progress_paused",
        "review_settings_progress_paused_at",
        "review_settings_progress_updated_at",
        "translation_source_lang",
        "translation_source_lang_updated_at",
        "translation_target_lang",
        "translation_target_lang_updated_at",
        "vocab_highlight_colorPreset",
        "vocab_highlight_opacity",
    },
}
RUNTIME_PODCAST_DOWNLOAD_KEYS = {
    "audioAssetRef",
    "subtitleAssetRef",
    "localAudioPath",
    "localSubtitlePath",
}
BOOKSHELF_SEED_KEYS = {"books", "referenceDate"}
BOOKSHELF_BOOK_KEYS = {
    "title",
    "author",
    "fileName",
    "format",
    "bookAssetRef",
    "progression",
    "preferredNotebookId",
    "dateAdded",
    "dateLastRead",
}
NOTEBOOK_SEED_KEYS = {"notebooks", "editStates"}
NOTEBOOK_ROW_KEYS = {
    "remoteId",
    "name",
    "color",
    "coverPattern",
    "coverImageAssetRef",
    "cardState",
    "syncStatus",
    "isDefault",
    "sortOrder",
    "entries",
}
NOTEBOOK_CARD_STATE_KEYS = {
    "cardCount",
    "dueCount",
    "unlearnedCount",
    "reviewedCount",
    "pendingCount",
    "lastActivity",
    "isActive",
}
NOTEBOOK_EDIT_STATE_KEYS = {"id", "mode", "name", "color", "coverPattern", "coverImageAssetRef"}
# Optional review scheduling 欄位（Swift NotebookEntrySeed decodeIfPresent 對齊）：
# baseline-kept notebook fixture 可不帶；帶了才餵 NotebookStatsCalculator 的
# due/unlearned/reviewed 徽章與進度條。
NOTEBOOK_ENTRY_OPTIONAL_REVIEW_KEYS = {
    "reviewIntervalHours",
    "nextReviewAt",
    "lastReviewedAt",
    "reviewCount",
}
NOTEBOOK_ENTRY_KEYS = {
    "word",
    "translation",
    "syncStatus",
    "actionType",
    "isArchived",
    "isExcludedFromReader",
    "context",
    "explanation",
    "partOfSpeech",
    "bookTitle",
    "chapterTitle",
    *NOTEBOOK_ENTRY_OPTIONAL_REVIEW_KEYS,
}
VOCABULARY_SEED_KEYS = {"notebookRemoteId", "notebookName", "notebookSyncStatus", "bookTitle", "entries", "reviewHistory"}
REVIEW_DECK_SEED_KEYS = {"notebookRemoteId", "notebookName", "notebookSyncStatus", "entries"}
REVIEW_HISTORY_KEYS = {"word", "feedback", "reviewedAt"}
SYNC_PRESENTER_SEED_KEYS = {
    "isLoggedIn",
    "isConnected",
    "phase",
    "failureKind",
    "pendingCount",
    "addCount",
    "deleteCount",
    "steps",
    "summaryText",
    "pendingRows",
}
SYNC_PRESENTER_STEP_KEYS = {"id", "label", "status", "current", "total", "detail"}
SYNC_PRESENTER_PENDING_ROW_KEYS = {
    "id",
    "word",
    "partOfSpeech",
    "translation",
    "wordTone",
    "isStrikethrough",
    "actionSystemImage",
    "actionTone",
    "actionAccessibilityLabel",
}
VALID_SYNC_PHASES = {"ready", "running", "completed", "failed"}
VALID_SYNC_FAILURE_KINDS = {"partial", "full", "cancelled"}
VALID_SYNC_STEP_STATUSES = {"waiting", "running", "retry", "done", "skipped", "error"}
VALID_WORD_ROW_TONES = {"primary", "secondary", "tertiary", "quaternary", "destructive", "reviewDue"}
UI_WORLD_ENTRY_KEYS = {
    "word",
    "translation",
    "context",
    "explanation",
    "partOfSpeech",
    "bookTitle",
    "chapterTitle",
    "kgCardId",
    "difficultyTier",
    "reviewMode",
    "reviewExamples",
    "collocations",
    "rootForm",
    "inflections",
    "syncStatus",
    "actionType",
    "isArchived",
    "isExcludedFromReader",
    "reviewIntervalHours",
    "nextReviewAt",
    "lastReviewedAt",
    "reviewCount",
    "reviewStreak",
    "lastReviewFeedbackRaw",
    "graphLinksByKind",
}
VALID_REVIEW_MODES = {"recognition", "production"}
AUTH_REQUIRED_KEYS = {
    "isLoggedIn",
    "userId",
    "token",
    "keychainTokenState",
    "displayName",
    "email",
    "authError",
    "isAuthenticating",
    "provider",
    "providerUserId",
}
ENTITLEMENTS_SEED_KEYS = {"pro"}
ENTITLEMENTS_PRO_KEYS = {
    "is_active",
    "product_id",
    "plan_name",
    "price_display",
    "status",
    "is_trial",
    "trial_days",
    "will_renew",
    "expires_at",
    "source",
    "last_synced_at",
}
VALID_ENTITLEMENT_STATUSES = {"active", "trial", "grace_period", "inactive", "expired"}
ACTIVE_ENTITLEMENT_STATUSES = {"active", "trial", "grace_period"}
VALID_ENTITLEMENT_SOURCES = {"app_store", "admin"}
SETTINGS_SEED_KEYS = {
    "auth",
    "authFixtureRef",
    "entitlementsFixtureRef",
    "preferences",
    "reviewSettings",
    "kg",
    "subscription",
    "syncSummary",
    "bookSync",
    "about",
    "danger",
    "manualLoginUserId",
    "debugLocalServerURL",
}
SETTINGS_AUTH_KEYS = {
    "isLoggedIn",
    "userInitials",
    "avatarURL",
    "displayName",
    "email",
    "authError",
    "isAuthenticating",
    "iconBreathing",
    "manualLoginHint",
}
SETTINGS_PREFERENCES_KEYS = {
    "selectedLanguage",
    "selectedAppearance",
    "translationSource",
    "translationTarget",
    "selectedReviewMode",
    "autoSyncEnabled",
    "showAutoSync",
}
SETTINGS_KG_KEYS = {
    "serverURL",
    "isConnected",
    "connectionPulse",
    "serverCardCount",
    "lastSyncDescription",
    "isUsingLocalServer",
    "localServerURL",
    "observation",
}
SETTINGS_KG_OBSERVATION_KEYS = {"previewLines", "totalCount"}
SETTINGS_SUBSCRIPTION_KEYS = {
    "isActive",
    "planName",
    "badgeText",
    "badgeTone",
    "summary",
    "detail",
    "sourceLabel",
    "managementNote",
    "pricingUnavailableMessage",
    "restoreLabel",
    "restoreDescription",
    "isRestoreAvailable",
    "ctaTitle",
    "isRefreshing",
}
SETTINGS_REVIEW_KEYS = {
    "mode",
    "customInitialIntervalHours",
    "customRememberedMultiplier",
    "customForgotMultiplier",
    "customMinimumIntervalHours",
    "customMaximumIntervalHours",
    "isProgressPaused",
    "progressPausedAt",
    "autoplaySpeed",
    "autoplaySoundEnabled",
}
SETTINGS_SYNC_SUMMARY_KEYS = {"isConnected", "isSyncing", "summaryText", "lastSyncedText"}
SETTINGS_ABOUT_KEYS = {"version", "developerName"}
SETTINGS_DANGER_KEYS = {"isDeletingAccount"}
SETTINGS_BOOK_SYNC_KEYS = {"text", "detail", "tone"}
VALID_SETTINGS_REVIEW_MODES = {"relaxed", "intensive", "custom"}
VALID_SETTINGS_AUTOPLAY_SPEEDS = {"slow", "normal", "fast"}
VALID_SETTINGS_BADGE_TONES = {"neutral", "accent", "success"}
VALID_SETTINGS_BOOK_SYNC_TONES = {"progress", "success", "warning"}
TODAY_REVIEW_SESSION_KEYS = {
    "progressText",
    "currentCard",
    "nextCard",
    "revealStage",
    "canShuffle",
    "canGoPrevious",
    "canGoNext",
    "remainingCount",
    "forgotCount",
    "rememberedCount",
    "rememberedFeedbackTrigger",
    "forgotFeedbackTrigger",
    "isAutoPlaying",
    "isAutoPlayPaused",
    "autoplayProgress",
    "autoplaySpeed",
    "autoplaySoundEnabled",
    "showFirstRunHint",
}
TODAY_REVIEW_CARD_KEYS = {
    "word",
    "translation",
    "context",
    "explanation",
    "partOfSpeech",
    "bookTitle",
    "chapterTitle",
    "dateAdded",
    "difficultyTier",
    "reviewMode",
    "reviewExamples",
    "rootForm",
    "inflections",
    "graphLinksByKind",
}
TODAY_REVIEW_LINK_KEYS = {
    "id",
    "cardId",
    "word",
    "kind",
    "label",
    "confidence",
    "reason",
    "hidden",
}
VALID_TODAY_REVIEW_REVEAL_STAGES = {"front", "back"}
PODCAST_SEED_KEYS = {"series", "episodes"}
PODCAST_SERIES_KEYS = {"remoteId", "title", "hostNames", "colorHex", "coverPattern"}
PODCAST_EPISODE_KEYS = {"episodeNumber", "title", "durationSec", "lastPlayedTime"}
BOOK_FORMAT_CONTENT_TYPES = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "md": "text/markdown",
}


class UIWorldManifestError(ValueError):
    pass


def _ensure_str(raw: Any, *, field: str, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise UIWorldManifestError(f"{label} {field} 必須是非空字串")
    return raw


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_install_as(value: str, *, field: str, label: str) -> None:
    path = Path(value)
    parts = path.parts
    if path.is_absolute() or value in {"", ".", ".."} or any(part in {"", ".", ".."} for part in parts):
        raise UIWorldManifestError(f"{label} {field}.installAs 必須是安全相對路徑")
    if "/" not in value:
        raise UIWorldManifestError(f"{label} {field}.installAs 必須含安裝目錄")


def _require_mapping(raw: Any, *, field: str, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise UIWorldManifestError(f"{label} {field} 必須是 object")
    return raw


def _require_list(raw: Any, *, field: str, label: str) -> list[Any]:
    if not isinstance(raw, list):
        raise UIWorldManifestError(f"{label} {field} 必須是 array")
    return raw


def _require_ref(ref: Any, *, prefix: str, refs: set[str], owner: str, label: str) -> str:
    value = _ensure_str(ref, field=owner, label=label).strip()
    if not value.startswith(prefix):
        raise UIWorldManifestError(f"{label} {owner} must reference {prefix}*, got {value}")
    if value not in refs:
        raise UIWorldManifestError(f"{label} {owner} references missing {value}")
    return value


def _validate_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    optional: set[str] | None = None,
    owner: str,
    label: str,
) -> None:
    """`expected` 是允許的完整 key set；`optional`（⊆ expected）可缺席但不可未知。"""
    keys = set(value)
    missing = sorted(expected - (optional or set()) - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise UIWorldManifestError(f"{label} {owner} keys 不符合 UI World v2: extra={extra} missing={missing}")


def _validate_download_local_path(
    raw: Any,
    *,
    expected_install_as: str | None,
    owner: str,
    label: str,
) -> None:
    if expected_install_as is None:
        if raw is not None:
            raise UIWorldManifestError(f"{label} {owner} must be null when subtitleAssetRef is null")
        return
    local_path = _ensure_str(raw, field=owner, label=label).strip()
    _validate_install_as(local_path, field=owner, label=label)
    if local_path != expected_install_as:
        raise UIWorldManifestError(
            f"{label} {owner} must match asset installAs {expected_install_as}, got {local_path}"
        )


def _validate_optional_progression(raw: Any, *, owner: str, label: str) -> None:
    if raw is None:
        return
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise UIWorldManifestError(f"{label} {owner} must be null or a number between 0 and 1")
    if raw < 0 or raw > 1:
        raise UIWorldManifestError(f"{label} {owner} must be between 0 and 1, got {raw}")


def _parse_iso8601(raw: Any, *, owner: str, label: str) -> datetime:
    value = _ensure_str(raw, field=owner, label=label).strip()
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UIWorldManifestError(f"{label} {owner} must be ISO8601, got {value}") from exc


def _validate_optional_iso8601(raw: Any, *, owner: str, label: str) -> datetime | None:
    if raw is None:
        return None
    return _parse_iso8601(raw, owner=owner, label=label)


def _validate_optional_fixture_date(raw: Any, *, owner: str, label: str) -> None:
    if raw is None:
        return
    if isinstance(raw, str):
        _parse_iso8601(raw, owner=owner, label=label)
        return
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise UIWorldManifestError(f"{label} {owner} must be ISO8601 string or epoch seconds")
    if raw < 0:
        raise UIWorldManifestError(f"{label} {owner} epoch seconds must be non-negative")


def _validate_required_fixture_date(raw: Any, *, owner: str, label: str) -> None:
    """Swift 端以 `decode(Date.self)` 讀取（非 optional）的 fixture date：null 會在
    app 內 preconditionFailure，validator 必須 fail-fast。格式同 optional 版
    （ISO8601 字串或 epoch seconds，對齊 FixtureDatasetStore 的 Date decoder）。"""
    if raw is None:
        raise UIWorldManifestError(
            f"{label} {owner} must be a non-null date (Swift decoder requires Date)"
        )
    _validate_optional_fixture_date(raw, owner=owner, label=label)


def _ensure_int(raw: Any, *, field: str, label: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise UIWorldManifestError(f"{label} {field} 必須是 int")
    return raw


def _ensure_bool(raw: Any, *, field: str, label: str) -> bool:
    if not isinstance(raw, bool):
        raise UIWorldManifestError(f"{label} {field} 必須是 bool")
    return raw


def _ensure_string(raw: Any, *, field: str, label: str) -> str:
    if not isinstance(raw, str):
        raise UIWorldManifestError(f"{label} {field} 必須是 string")
    return raw


def _ensure_number(raw: Any, *, field: str, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise UIWorldManifestError(f"{label} {field} 必須是 number")
    return float(raw)


def _ensure_non_negative_int(raw: Any, *, field: str, label: str) -> int:
    value = _ensure_int(raw, field=field, label=label)
    if value < 0:
        raise UIWorldManifestError(f"{label} {field} must be non-negative")
    return value


def _validate_notebook_sync_status(raw: Any, *, owner: str, label: str) -> None:
    value = _ensure_int(raw, field=owner, label=label)
    if value not in {0, 1}:
        raise UIWorldManifestError(f"{label} {owner} must be valid Notebook.syncStatus (0=pending, 1=synced)")


def _validate_vocabulary_row_state(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    sync_status = _ensure_int(seed.get("syncStatus"), field=f"{owner}.syncStatus", label=label)
    if sync_status not in {0, 1, 2}:
        raise UIWorldManifestError(
            f"{label} {owner}.syncStatus must be valid VocabularyEntry.syncStatus (0=pending, 1=synced, 2=failed)"
        )
    action_type = _ensure_str(seed.get("actionType"), field=f"{owner}.actionType", label=label)
    if action_type not in {"add", "delete", "edit"}:
        raise UIWorldManifestError(f"{label} {owner}.actionType must be add/delete/edit")
    _ensure_bool(seed.get("isArchived"), field=f"{owner}.isArchived", label=label)
    _ensure_bool(seed.get("isExcludedFromReader"), field=f"{owner}.isExcludedFromReader", label=label)


def _validate_unique(values: list[str], *, owner: str, label: str) -> None:
    if len(set(values)) != len(values):
        raise UIWorldManifestError(f"{label} {owner} must not contain duplicate values")


def _validate_fixture_domain_ids(data: dict[str, Any], *, label: str) -> None:
    for domain, known_ids in sorted(FIXTURE_DOMAIN_IDS.items()):
        seeds = _require_mapping(data.get(domain), field=domain, label=label)
        unknown = sorted(set(seeds) - known_ids)
        if unknown:
            raise UIWorldManifestError(
                f"{label} {domain} fixture ids {unknown} have no matching app fixture ID"
            )


def _validate_optional_string_list(raw: Any, *, owner: str, label: str) -> None:
    if raw is None:
        return
    values = _require_list(raw, field=owner, label=label)
    for index, value in enumerate(values):
        _ensure_str(value, field=f"{owner}[{index}]", label=label)


def _validate_ui_world_entry(seed: Mapping[str, Any], *, owner: str, label: str) -> str:
    _validate_exact_keys(seed, expected=UI_WORLD_ENTRY_KEYS, owner=owner, label=label)
    word = _ensure_str(seed.get("word"), field=f"{owner}.word", label=label).strip()
    _ensure_str(seed.get("translation"), field=f"{owner}.translation", label=label)
    _ensure_str(seed.get("context"), field=f"{owner}.context", label=label)
    _ensure_str(seed.get("bookTitle"), field=f"{owner}.bookTitle", label=label)
    for field in ("explanation", "partOfSpeech", "chapterTitle", "kgCardId", "difficultyTier", "rootForm"):
        value = seed.get(field)
        if value is not None:
            _ensure_str(value, field=f"{owner}.{field}", label=label)
    review_mode = _ensure_str(seed.get("reviewMode"), field=f"{owner}.reviewMode", label=label)
    if review_mode not in VALID_REVIEW_MODES:
        raise UIWorldManifestError(f"{label} {owner}.reviewMode 不支援: {review_mode}")
    review_examples = _require_list(seed.get("reviewExamples"), field=f"{owner}.reviewExamples", label=label)
    for index, value in enumerate(review_examples):
        _ensure_str(value, field=f"{owner}.reviewExamples[{index}]", label=label)
    _validate_optional_string_list(seed.get("collocations"), owner=f"{owner}.collocations", label=label)
    _validate_optional_string_list(seed.get("inflections"), owner=f"{owner}.inflections", label=label)
    for field in ("reviewIntervalHours",):
        value = seed.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            raise UIWorldManifestError(f"{label} {owner}.{field} must be null or a non-negative number")
    for field in ("nextReviewAt", "lastReviewedAt"):
        _validate_optional_iso8601(seed.get(field), owner=f"{owner}.{field}", label=label)
    for field in ("reviewCount", "reviewStreak", "lastReviewFeedbackRaw"):
        value = seed.get(field)
        if value is not None:
            int_value = _ensure_int(value, field=f"{owner}.{field}", label=label)
            if field != "lastReviewFeedbackRaw" and int_value < 0:
                raise UIWorldManifestError(f"{label} {owner}.{field} must be non-negative")
    graph_links = _require_mapping(seed.get("graphLinksByKind"), field=f"{owner}.graphLinksByKind", label=label)
    for kind, links in graph_links.items():
        _ensure_str(kind, field=f"{owner}.graphLinksByKind key", label=label)
        _require_list(links, field=f"{owner}.graphLinksByKind.{kind}", label=label)
    _validate_vocabulary_row_state(seed, owner=owner, label=label)
    return word


def _validate_seed_graph_links(
    entries: list[Mapping[str, Any]],
    entry_word_set: set[str],
    *,
    owner_prefix: str,
    label: str,
) -> None:
    """vocabulary / reviewDeck seed 是自足宇宙：graphLinksByKind 的 target 必須
    resolve 到同 seed entries。對齊並「刻意嚴於」Swift KnowledgeGraphViewScenarios
    的 `Set(entries.kgCardId)` 檢查（Swift 豁免 isHidden / nil-source 且只驗
    cardId；validator 全驗 word+cardId，fail-fast 方向安全）——dangling link 在
    app 內是 preconditionFailure。todayReview 卡刻意不適用（baseline 語意容許
    cross-seed chips）。"""
    card_ids = {
        entry.get("kgCardId")
        for entry in entries
        if isinstance(entry.get("kgCardId"), str)
    }
    for index, entry in enumerate(entries):
        graph_links = entry.get("graphLinksByKind")
        if not isinstance(graph_links, Mapping):
            continue  # 頂層形狀由 _validate_ui_world_entry 擋；link 元素層 schema 驗證是 pre-existing 缺口（backlog IMP-0021），此處只驗 resolve
        for kind, links in graph_links.items():
            if not isinstance(links, list):
                continue
            for link_index, link in enumerate(links):
                if not isinstance(link, Mapping):
                    continue
                owner = f"{owner_prefix}.entries[{index}].graphLinksByKind.{kind}[{link_index}]"
                word = link.get("word")
                if isinstance(word, str) and word not in entry_word_set:
                    raise UIWorldManifestError(
                        f"{label} {owner}.word {word!r} must resolve to an in-seed entry"
                    )
                card_id = link.get("cardId")
                if isinstance(card_id, str) and card_id not in card_ids:
                    raise UIWorldManifestError(
                        f"{label} {owner}.cardId {card_id!r} must resolve to an in-seed entry kgCardId"
                    )


def _validate_notebook_entry(seed: Mapping[str, Any], *, owner: str, label: str) -> str:
    _validate_exact_keys(
        seed,
        expected=NOTEBOOK_ENTRY_KEYS,
        optional=NOTEBOOK_ENTRY_OPTIONAL_REVIEW_KEYS,
        owner=owner,
        label=label,
    )
    word = _ensure_str(seed.get("word"), field=f"{owner}.word", label=label).strip()
    _ensure_str(seed.get("translation"), field=f"{owner}.translation", label=label)
    _ensure_str(seed.get("context"), field=f"{owner}.context", label=label)
    _ensure_str(seed.get("bookTitle"), field=f"{owner}.bookTitle", label=label)
    for field in ("explanation", "partOfSpeech", "chapterTitle"):
        value = seed.get(field)
        if value is not None:
            _ensure_str(value, field=f"{owner}.{field}", label=label)
    interval = seed.get("reviewIntervalHours")
    if interval is not None and (isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 0):
        raise UIWorldManifestError(f"{label} {owner}.reviewIntervalHours must be null or a non-negative number")
    for field in ("nextReviewAt", "lastReviewedAt"):
        _validate_optional_iso8601(seed.get(field), owner=f"{owner}.{field}", label=label)
    review_count = seed.get("reviewCount")
    if review_count is not None and _ensure_int(review_count, field=f"{owner}.reviewCount", label=label) < 0:
        raise UIWorldManifestError(f"{label} {owner}.reviewCount must be non-negative")
    _validate_vocabulary_row_state(seed, owner=owner, label=label)
    return word


def _validate_notebook_card_state(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=NOTEBOOK_CARD_STATE_KEYS, owner=owner, label=label)
    counts = {
        field: _ensure_int(seed.get(field), field=f"{owner}.{field}", label=label)
        for field in ("cardCount", "dueCount", "unlearnedCount", "reviewedCount", "pendingCount")
    }
    for field, value in counts.items():
        if value < 0:
            raise UIWorldManifestError(f"{label} {owner}.{field} must be non-negative")
    if counts["cardCount"] != counts["dueCount"] + counts["unlearnedCount"] + counts["reviewedCount"]:
        raise UIWorldManifestError(f"{label} {owner}.cardCount must equal dueCount + unlearnedCount + reviewedCount")
    if _ensure_bool(seed.get("isActive"), field=f"{owner}.isActive", label=label) and counts["cardCount"] <= 0:
        raise UIWorldManifestError(f"{label} {owner} active card must not be empty")
    _validate_optional_iso8601(seed.get("lastActivity"), owner=f"{owner}.lastActivity", label=label)


def _validate_notebook_edit_state(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=NOTEBOOK_EDIT_STATE_KEYS, owner=owner, label=label)
    _ensure_str(seed.get("id"), field=f"{owner}.id", label=label)
    mode = _ensure_str(seed.get("mode"), field=f"{owner}.mode", label=label)
    if mode not in {"create", "edit"}:
        raise UIWorldManifestError(f"{label} {owner}.mode must be create or edit")
    name = seed.get("name")
    if not isinstance(name, str):
        raise UIWorldManifestError(f"{label} {owner}.name 必須是 string")
    for field in ("color", "coverPattern", "coverImageAssetRef"):
        value = seed.get(field)
        if value is not None:
            _ensure_str(value, field=f"{owner}.{field}", label=label)
    if mode == "create" and (name or seed.get("color") is not None or seed.get("coverPattern") is not None or seed.get("coverImageAssetRef") is not None):
        raise UIWorldManifestError(f"{label} {owner} create mode must have empty name and null appearance")


def _validate_uuid(raw: Any, *, owner: str, label: str) -> None:
    value = _ensure_str(raw, field=owner, label=label).strip()
    try:
        UUID(value)
    except ValueError as exc:
        raise UIWorldManifestError(f"{label} {owner} must be UUID") from exc


def _validate_nullable_string(raw: Any, *, owner: str, label: str) -> None:
    if raw is not None:
        _ensure_str(raw, field=owner, label=label)


def _validate_optional_url(raw: Any, *, owner: str, label: str) -> None:
    if raw is None:
        return
    value = _ensure_str(raw, field=owner, label=label)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UIWorldManifestError(f"{label} {owner} must be http(s) URL")


def _validate_entitlements(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("entitlements"), field="entitlements", label=label).items():
        seed_obj = _require_mapping(seed, field=f"entitlements.{fixture_id}", label=label)
        owner = f"entitlements.{fixture_id}"
        _validate_exact_keys(seed_obj, expected=ENTITLEMENTS_SEED_KEYS, owner=owner, label=label)
        pro = _require_mapping(seed_obj.get("pro"), field=f"{owner}.pro", label=label)
        pro_owner = f"{owner}.pro"
        _validate_exact_keys(pro, expected=ENTITLEMENTS_PRO_KEYS, owner=pro_owner, label=label)
        is_active = _ensure_bool(pro.get("is_active"), field=f"{pro_owner}.is_active", label=label)
        status = _ensure_str(pro.get("status"), field=f"{pro_owner}.status", label=label)
        if status not in VALID_ENTITLEMENT_STATUSES:
            raise UIWorldManifestError(f"{label} {pro_owner}.status is invalid")
        expected_active = status in ACTIVE_ENTITLEMENT_STATUSES
        if is_active != expected_active:
            raise UIWorldManifestError(f"{label} {pro_owner}.is_active must match entitlement-bearing status")
        source = _ensure_str(pro.get("source"), field=f"{pro_owner}.source", label=label)
        if source not in VALID_ENTITLEMENT_SOURCES:
            raise UIWorldManifestError(f"{label} {pro_owner}.source is invalid")
        is_trial = _ensure_bool(pro.get("is_trial"), field=f"{pro_owner}.is_trial", label=label)
        if is_trial != (status == "trial"):
            raise UIWorldManifestError(f"{label} {pro_owner}.is_trial must match status=trial")
        will_renew = _ensure_bool(pro.get("will_renew"), field=f"{pro_owner}.will_renew", label=label)
        if status in {"inactive", "expired"} and will_renew:
            raise UIWorldManifestError(f"{label} {pro_owner}.will_renew must be false for inactive/expired status")
        trial_days = pro.get("trial_days")
        if trial_days is not None and _ensure_int(trial_days, field=f"{pro_owner}.trial_days", label=label) < 0:
            raise UIWorldManifestError(f"{label} {pro_owner}.trial_days must be non-negative")
        for field in ("product_id", "plan_name", "price_display"):
            _validate_nullable_string(pro.get(field), owner=f"{pro_owner}.{field}", label=label)
        if source == "app_store" and is_active:
            _ensure_str(pro.get("product_id"), field=f"{pro_owner}.product_id", label=label)
        if source == "admin":
            if not is_active or status != "active":
                raise UIWorldManifestError(f"{label} {pro_owner} admin source must be active")
            if pro.get("product_id") is not None or pro.get("price_display") is not None:
                raise UIWorldManifestError(f"{label} {pro_owner} admin source must not carry App Store product or price")
            if trial_days is not None or is_trial or will_renew:
                raise UIWorldManifestError(f"{label} {pro_owner} admin source must not carry trial or renewal state")
        for field in ("expires_at", "last_synced_at"):
            _validate_optional_iso8601(pro.get(field), owner=f"{pro_owner}.{field}", label=label)


def _validate_settings_auth(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=SETTINGS_AUTH_KEYS, owner=owner, label=label)
    _ensure_bool(seed.get("isLoggedIn"), field=f"{owner}.isLoggedIn", label=label)
    _ensure_str(seed.get("displayName"), field=f"{owner}.displayName", label=label)
    _ensure_bool(seed.get("isAuthenticating"), field=f"{owner}.isAuthenticating", label=label)
    _ensure_bool(seed.get("iconBreathing"), field=f"{owner}.iconBreathing", label=label)
    for field in ("userInitials", "email", "authError", "manualLoginHint"):
        _validate_nullable_string(seed.get(field), owner=f"{owner}.{field}", label=label)
    _validate_optional_url(seed.get("avatarURL"), owner=f"{owner}.avatarURL", label=label)


def _validate_settings_preferences(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=SETTINGS_PREFERENCES_KEYS, owner=owner, label=label)
    for field in (
        "selectedLanguage",
        "selectedAppearance",
        "translationSource",
        "translationTarget",
        "selectedReviewMode",
    ):
        _ensure_str(seed.get(field), field=f"{owner}.{field}", label=label)
    _ensure_bool(seed.get("autoSyncEnabled"), field=f"{owner}.autoSyncEnabled", label=label)
    _ensure_bool(seed.get("showAutoSync"), field=f"{owner}.showAutoSync", label=label)
    if seed.get("autoSyncEnabled") and not seed.get("showAutoSync"):
        raise UIWorldManifestError(f"{label} {owner}.autoSyncEnabled requires showAutoSync=true")


def _validate_settings_kg(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=SETTINGS_KG_KEYS, owner=owner, label=label)
    _validate_optional_url(seed.get("serverURL"), owner=f"{owner}.serverURL", label=label)
    _ensure_bool(seed.get("isConnected"), field=f"{owner}.isConnected", label=label)
    _ensure_bool(seed.get("connectionPulse"), field=f"{owner}.connectionPulse", label=label)
    server_card_count = _ensure_int(seed.get("serverCardCount"), field=f"{owner}.serverCardCount", label=label)
    if server_card_count < 0:
        raise UIWorldManifestError(f"{label} {owner}.serverCardCount must be non-negative")
    _validate_nullable_string(seed.get("lastSyncDescription"), owner=f"{owner}.lastSyncDescription", label=label)
    is_using_local = _ensure_bool(seed.get("isUsingLocalServer"), field=f"{owner}.isUsingLocalServer", label=label)
    local_server_url = seed.get("localServerURL")
    observation = seed.get("observation")
    if is_using_local:
        _validate_optional_url(local_server_url, owner=f"{owner}.localServerURL", label=label)
        if local_server_url is None:
            raise UIWorldManifestError(f"{label} {owner}.localServerURL is required when isUsingLocalServer=true")
        if observation is None:
            raise UIWorldManifestError(f"{label} {owner}.observation is required when isUsingLocalServer=true")
    else:
        if local_server_url is not None or observation is not None:
            raise UIWorldManifestError(f"{label} {owner} non-local server must not declare localServerURL or observation")
    if observation is not None:
        observation_obj = _require_mapping(observation, field=f"{owner}.observation", label=label)
        _validate_exact_keys(
            observation_obj,
            expected=SETTINGS_KG_OBSERVATION_KEYS,
            owner=f"{owner}.observation",
            label=label,
        )
        lines = _require_list(observation_obj.get("previewLines"), field=f"{owner}.observation.previewLines", label=label)
        for index, value in enumerate(lines):
            _ensure_str(value, field=f"{owner}.observation.previewLines[{index}]", label=label)
        total_count = _ensure_int(observation_obj.get("totalCount"), field=f"{owner}.observation.totalCount", label=label)
        if total_count < len(lines):
            raise UIWorldManifestError(f"{label} {owner}.observation.totalCount must cover previewLines")


def _validate_settings_subscription(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=SETTINGS_SUBSCRIPTION_KEYS, owner=owner, label=label)
    _ensure_bool(seed.get("isActive"), field=f"{owner}.isActive", label=label)
    for field in (
        "planName",
        "badgeText",
        "summary",
        "detail",
        "sourceLabel",
        "managementNote",
        "restoreLabel",
        "restoreDescription",
        "ctaTitle",
    ):
        _ensure_str(seed.get(field), field=f"{owner}.{field}", label=label)
    badge_tone = _ensure_str(seed.get("badgeTone"), field=f"{owner}.badgeTone", label=label)
    if badge_tone not in VALID_SETTINGS_BADGE_TONES:
        raise UIWorldManifestError(f"{label} {owner}.badgeTone is invalid")
    _validate_nullable_string(
        seed.get("pricingUnavailableMessage"),
        owner=f"{owner}.pricingUnavailableMessage",
        label=label,
    )
    _ensure_bool(seed.get("isRestoreAvailable"), field=f"{owner}.isRestoreAvailable", label=label)
    _ensure_bool(seed.get("isRefreshing"), field=f"{owner}.isRefreshing", label=label)


def _validate_settings_review(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=SETTINGS_REVIEW_KEYS, owner=owner, label=label)
    mode = _ensure_str(seed.get("mode"), field=f"{owner}.mode", label=label)
    if mode not in VALID_SETTINGS_REVIEW_MODES:
        raise UIWorldManifestError(f"{label} {owner}.mode is invalid")
    autoplay_speed = _ensure_str(seed.get("autoplaySpeed"), field=f"{owner}.autoplaySpeed", label=label)
    if autoplay_speed not in VALID_SETTINGS_AUTOPLAY_SPEEDS:
        raise UIWorldManifestError(f"{label} {owner}.autoplaySpeed is invalid")
    intervals = {
        field: _ensure_number(seed.get(field), field=f"{owner}.{field}", label=label)
        for field in (
            "customInitialIntervalHours",
            "customRememberedMultiplier",
            "customForgotMultiplier",
            "customMinimumIntervalHours",
            "customMaximumIntervalHours",
        )
    }
    for field, value in intervals.items():
        if value <= 0:
            raise UIWorldManifestError(f"{label} {owner}.{field} must be positive")
    if intervals["customMaximumIntervalHours"] < intervals["customMinimumIntervalHours"]:
        raise UIWorldManifestError(f"{label} {owner}.customMaximumIntervalHours must be >= customMinimumIntervalHours")
    _ensure_bool(seed.get("isProgressPaused"), field=f"{owner}.isProgressPaused", label=label)
    _validate_optional_fixture_date(seed.get("progressPausedAt"), owner=f"{owner}.progressPausedAt", label=label)
    _ensure_bool(seed.get("autoplaySoundEnabled"), field=f"{owner}.autoplaySoundEnabled", label=label)


def _validate_settings_seed(seed: Mapping[str, Any], *, owner: str, label: str) -> None:
    _validate_exact_keys(seed, expected=SETTINGS_SEED_KEYS, owner=owner, label=label)
    _ensure_str(seed.get("authFixtureRef"), field=f"{owner}.authFixtureRef", label=label)
    entitlements_ref = seed.get("entitlementsFixtureRef")
    if entitlements_ref is not None:
        _ensure_str(entitlements_ref, field=f"{owner}.entitlementsFixtureRef", label=label)
    _validate_settings_auth(_require_mapping(seed.get("auth"), field=f"{owner}.auth", label=label), owner=f"{owner}.auth", label=label)
    _validate_settings_preferences(
        _require_mapping(seed.get("preferences"), field=f"{owner}.preferences", label=label),
        owner=f"{owner}.preferences",
        label=label,
    )
    kg = seed.get("kg")
    if kg is not None:
        _validate_settings_kg(_require_mapping(kg, field=f"{owner}.kg", label=label), owner=f"{owner}.kg", label=label)
    subscription = seed.get("subscription")
    if subscription is not None:
        _validate_settings_subscription(
            _require_mapping(subscription, field=f"{owner}.subscription", label=label),
            owner=f"{owner}.subscription",
            label=label,
        )
    review = seed.get("reviewSettings")
    if review is not None:
        _validate_settings_review(
            _require_mapping(review, field=f"{owner}.reviewSettings", label=label),
            owner=f"{owner}.reviewSettings",
            label=label,
        )
    sync_summary = seed.get("syncSummary")
    if sync_summary is not None:
        sync_obj = _require_mapping(sync_summary, field=f"{owner}.syncSummary", label=label)
        _validate_exact_keys(sync_obj, expected=SETTINGS_SYNC_SUMMARY_KEYS, owner=f"{owner}.syncSummary", label=label)
        _ensure_bool(sync_obj.get("isConnected"), field=f"{owner}.syncSummary.isConnected", label=label)
        _ensure_bool(sync_obj.get("isSyncing"), field=f"{owner}.syncSummary.isSyncing", label=label)
        _ensure_string(sync_obj.get("summaryText"), field=f"{owner}.syncSummary.summaryText", label=label)
        # Nullable: a device that has never synced (or is offline) has no
        # last-sync time, and the row omits the line rather than inventing one.
        _validate_nullable_string(
            sync_obj.get("lastSyncedText"), owner=f"{owner}.syncSummary.lastSyncedText", label=label
        )
    about = _require_mapping(seed.get("about"), field=f"{owner}.about", label=label)
    _validate_exact_keys(about, expected=SETTINGS_ABOUT_KEYS, owner=f"{owner}.about", label=label)
    _ensure_str(about.get("version"), field=f"{owner}.about.version", label=label)
    _ensure_str(about.get("developerName"), field=f"{owner}.about.developerName", label=label)
    danger = seed.get("danger")
    if danger is not None:
        danger_obj = _require_mapping(danger, field=f"{owner}.danger", label=label)
        _validate_exact_keys(danger_obj, expected=SETTINGS_DANGER_KEYS, owner=f"{owner}.danger", label=label)
        _ensure_bool(danger_obj.get("isDeletingAccount"), field=f"{owner}.danger.isDeletingAccount", label=label)
    book_sync = seed.get("bookSync")
    if book_sync is not None:
        book_sync_obj = _require_mapping(book_sync, field=f"{owner}.bookSync", label=label)
        _validate_exact_keys(book_sync_obj, expected=SETTINGS_BOOK_SYNC_KEYS, owner=f"{owner}.bookSync", label=label)
        _ensure_str(book_sync_obj.get("text"), field=f"{owner}.bookSync.text", label=label)
        _validate_nullable_string(book_sync_obj.get("detail"), owner=f"{owner}.bookSync.detail", label=label)
        tone = _ensure_str(book_sync_obj.get("tone"), field=f"{owner}.bookSync.tone", label=label)
        if tone not in VALID_SETTINGS_BOOK_SYNC_TONES:
            raise UIWorldManifestError(f"{label} {owner}.bookSync.tone is invalid")
    _validate_nullable_string(seed.get("manualLoginUserId"), owner=f"{owner}.manualLoginUserId", label=label)
    _validate_optional_url(seed.get("debugLocalServerURL"), owner=f"{owner}.debugLocalServerURL", label=label)


def _validate_settings(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("settings"), field="settings", label=label).items():
        seed_obj = _require_mapping(seed, field=f"settings.{fixture_id}", label=label)
        _validate_settings_seed(seed_obj, owner=f"settings.{fixture_id}", label=label)


def _validate_today_review_link(seed: Mapping[str, Any], *, owner: str, bucket_kind: str, label: str) -> None:
    _validate_exact_keys(seed, expected=TODAY_REVIEW_LINK_KEYS, owner=owner, label=label)
    for field in ("id", "cardId", "word", "kind", "label", "reason"):
        _ensure_str(seed.get(field), field=f"{owner}.{field}", label=label)
    if seed.get("kind") != bucket_kind:
        raise UIWorldManifestError(f"{label} {owner}.kind must match graphLinksByKind bucket {bucket_kind}")
    confidence = _ensure_number(seed.get("confidence"), field=f"{owner}.confidence", label=label)
    if confidence < 0 or confidence > 1:
        raise UIWorldManifestError(f"{label} {owner}.confidence must be between 0 and 1")
    _ensure_bool(seed.get("hidden"), field=f"{owner}.hidden", label=label)


def _validate_today_review_card(seed: Mapping[str, Any], *, owner: str, label: str) -> str:
    _validate_exact_keys(seed, expected=TODAY_REVIEW_CARD_KEYS, owner=owner, label=label)
    word = _ensure_str(seed.get("word"), field=f"{owner}.word", label=label).strip()
    _ensure_str(seed.get("translation"), field=f"{owner}.translation", label=label)
    _ensure_str(seed.get("context"), field=f"{owner}.context", label=label)
    _ensure_str(seed.get("bookTitle"), field=f"{owner}.bookTitle", label=label)
    for field in ("explanation", "partOfSpeech", "chapterTitle", "difficultyTier", "rootForm"):
        _validate_nullable_string(seed.get(field), owner=f"{owner}.{field}", label=label)
    # Swift TodayReviewCardSeed.dateAdded 是非 optional Date（TodayReviewFixtures.swift）
    _validate_required_fixture_date(seed.get("dateAdded"), owner=f"{owner}.dateAdded", label=label)
    review_mode = _ensure_str(seed.get("reviewMode"), field=f"{owner}.reviewMode", label=label)
    if review_mode not in VALID_REVIEW_MODES:
        raise UIWorldManifestError(f"{label} {owner}.reviewMode is invalid")
    review_examples = _require_list(seed.get("reviewExamples"), field=f"{owner}.reviewExamples", label=label)
    for index, value in enumerate(review_examples):
        _ensure_str(value, field=f"{owner}.reviewExamples[{index}]", label=label)
    inflections = _require_list(seed.get("inflections"), field=f"{owner}.inflections", label=label)
    for index, value in enumerate(inflections):
        _ensure_str(value, field=f"{owner}.inflections[{index}]", label=label)
    links_by_kind = _require_mapping(seed.get("graphLinksByKind"), field=f"{owner}.graphLinksByKind", label=label)
    for kind, links in links_by_kind.items():
        kind_value = _ensure_str(kind, field=f"{owner}.graphLinksByKind key", label=label)
        link_list = _require_list(links, field=f"{owner}.graphLinksByKind.{kind_value}", label=label)
        for index, link in enumerate(link_list):
            link_obj = _require_mapping(link, field=f"{owner}.graphLinksByKind.{kind_value}[{index}]", label=label)
            _validate_today_review_link(
                link_obj,
                owner=f"{owner}.graphLinksByKind.{kind_value}[{index}]",
                bucket_kind=kind_value,
                label=label,
            )
    return word


def _validate_today_review(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("todayReview"), field="todayReview", label=label).items():
        seed_obj = _require_mapping(seed, field=f"todayReview.{fixture_id}", label=label)
        owner = f"todayReview.{fixture_id}"
        _validate_exact_keys(seed_obj, expected=TODAY_REVIEW_SESSION_KEYS, owner=owner, label=label)
        _ensure_string(seed_obj.get("progressText"), field=f"{owner}.progressText", label=label)
        reveal_stage = _ensure_str(seed_obj.get("revealStage"), field=f"{owner}.revealStage", label=label)
        if reveal_stage not in VALID_TODAY_REVIEW_REVEAL_STAGES:
            raise UIWorldManifestError(f"{label} {owner}.revealStage is invalid")
        for field in ("canShuffle", "canGoPrevious", "canGoNext", "isAutoPlaying", "isAutoPlayPaused", "autoplaySoundEnabled", "showFirstRunHint"):
            _ensure_bool(seed_obj.get(field), field=f"{owner}.{field}", label=label)
        for field in ("remainingCount", "forgotCount", "rememberedCount", "rememberedFeedbackTrigger", "forgotFeedbackTrigger"):
            value = _ensure_int(seed_obj.get(field), field=f"{owner}.{field}", label=label)
            if value < 0:
                raise UIWorldManifestError(f"{label} {owner}.{field} must be non-negative")
        autoplay_progress = _ensure_number(seed_obj.get("autoplayProgress"), field=f"{owner}.autoplayProgress", label=label)
        if autoplay_progress < 0 or autoplay_progress > 1:
            raise UIWorldManifestError(f"{label} {owner}.autoplayProgress must be between 0 and 1")
        autoplay_speed = _ensure_str(seed_obj.get("autoplaySpeed"), field=f"{owner}.autoplaySpeed", label=label)
        if autoplay_speed not in VALID_SETTINGS_AUTOPLAY_SPEEDS:
            raise UIWorldManifestError(f"{label} {owner}.autoplaySpeed is invalid")
        if seed_obj.get("isAutoPlayPaused") and not seed_obj.get("isAutoPlaying"):
            raise UIWorldManifestError(f"{label} {owner}.isAutoPlayPaused requires isAutoPlaying=true")
        card_words: list[str] = []
        for card_key in ("currentCard", "nextCard"):
            card = seed_obj.get(card_key)
            if card is not None:
                card_words.append(
                    _validate_today_review_card(
                        _require_mapping(card, field=f"{owner}.{card_key}", label=label),
                        owner=f"{owner}.{card_key}",
                        label=label,
                    )
                )
        if seed_obj.get("remainingCount") == 0 and seed_obj.get("currentCard") is not None:
            raise UIWorldManifestError(f"{label} {owner} completed session must not declare currentCard")
        _validate_unique(card_words, owner=f"{owner}.card.word", label=label)


def _validate_color_hex(raw: Any, *, owner: str, label: str) -> None:
    if raw is None:
        return
    value = _ensure_str(raw, field=owner, label=label)
    if len(value) != 7 or not value.startswith("#") or any(ch not in "0123456789abcdefABCDEF" for ch in value[1:]):
        raise UIWorldManifestError(f"{label} {owner} must be #RRGGBB")


def _validate_podcast(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("podcast"), field="podcast", label=label).items():
        seed_obj = _require_mapping(seed, field=f"podcast.{fixture_id}", label=label)
        owner = f"podcast.{fixture_id}"
        _validate_exact_keys(seed_obj, expected=PODCAST_SEED_KEYS, owner=owner, label=label)
        series = _require_mapping(seed_obj.get("series"), field=f"{owner}.series", label=label)
        _validate_exact_keys(series, expected=PODCAST_SERIES_KEYS, owner=f"{owner}.series", label=label)
        _ensure_str(series.get("remoteId"), field=f"{owner}.series.remoteId", label=label)
        _ensure_str(series.get("title"), field=f"{owner}.series.title", label=label)
        hosts = _require_list(series.get("hostNames"), field=f"{owner}.series.hostNames", label=label)
        if not hosts:
            raise UIWorldManifestError(f"{label} {owner}.series.hostNames must not be empty")
        for index, host in enumerate(hosts):
            _ensure_str(host, field=f"{owner}.series.hostNames[{index}]", label=label)
        _validate_color_hex(series.get("colorHex"), owner=f"{owner}.series.colorHex", label=label)
        _validate_nullable_string(series.get("coverPattern"), owner=f"{owner}.series.coverPattern", label=label)
        episode_numbers: list[str] = []
        episodes = _require_list(seed_obj.get("episodes"), field=f"{owner}.episodes", label=label)
        if not episodes:
            raise UIWorldManifestError(f"{label} {owner}.episodes must not be empty")
        for index, episode in enumerate(episodes):
            episode_obj = _require_mapping(episode, field=f"{owner}.episodes[{index}]", label=label)
            episode_owner = f"{owner}.episodes[{index}]"
            _validate_exact_keys(episode_obj, expected=PODCAST_EPISODE_KEYS, owner=episode_owner, label=label)
            episode_number = _ensure_int(episode_obj.get("episodeNumber"), field=f"{episode_owner}.episodeNumber", label=label)
            if episode_number <= 0:
                raise UIWorldManifestError(f"{label} {episode_owner}.episodeNumber must be positive")
            episode_numbers.append(str(episode_number))
            _ensure_str(episode_obj.get("title"), field=f"{episode_owner}.title", label=label)
            duration = _ensure_number(episode_obj.get("durationSec"), field=f"{episode_owner}.durationSec", label=label)
            if duration <= 0:
                raise UIWorldManifestError(f"{label} {episode_owner}.durationSec must be positive")
            last_played = episode_obj.get("lastPlayedTime")
            if last_played is not None:
                last_played_value = _ensure_number(last_played, field=f"{episode_owner}.lastPlayedTime", label=label)
                if last_played_value < 0:
                    raise UIWorldManifestError(f"{label} {episode_owner}.lastPlayedTime must be non-negative")
                if last_played_value > duration:
                    raise UIWorldManifestError(f"{label} {episode_owner}.lastPlayedTime must not exceed durationSec")
        _validate_unique(episode_numbers, owner=f"{owner}.episodes.episodeNumber", label=label)


def _validate_sync_presenter(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("syncPresenter"), field="syncPresenter", label=label).items():
        seed_obj = _require_mapping(seed, field=f"syncPresenter.{fixture_id}", label=label)
        owner = f"syncPresenter.{fixture_id}"
        _validate_exact_keys(seed_obj, expected=SYNC_PRESENTER_SEED_KEYS, owner=owner, label=label)
        _ensure_bool(seed_obj.get("isLoggedIn"), field=f"{owner}.isLoggedIn", label=label)
        _ensure_bool(seed_obj.get("isConnected"), field=f"{owner}.isConnected", label=label)
        phase = _ensure_str(seed_obj.get("phase"), field=f"{owner}.phase", label=label)
        if phase not in VALID_SYNC_PHASES:
            raise UIWorldManifestError(f"{label} {owner}.phase is invalid")
        failure_kind = seed_obj.get("failureKind")
        if failure_kind is None:
            if phase == "failed":
                raise UIWorldManifestError(f"{label} {owner}.failureKind must be explicit when phase is failed")
        else:
            failure_kind = _ensure_str(failure_kind, field=f"{owner}.failureKind", label=label)
            if failure_kind not in VALID_SYNC_FAILURE_KINDS:
                raise UIWorldManifestError(f"{label} {owner}.failureKind is invalid")
            if phase != "failed":
                raise UIWorldManifestError(f"{label} {owner} non-null failureKind requires failed phase")

        pending_count = _ensure_non_negative_int(seed_obj.get("pendingCount"), field=f"{owner}.pendingCount", label=label)
        add_count = _ensure_non_negative_int(seed_obj.get("addCount"), field=f"{owner}.addCount", label=label)
        delete_count = _ensure_non_negative_int(seed_obj.get("deleteCount"), field=f"{owner}.deleteCount", label=label)
        if pending_count != add_count + delete_count:
            raise UIWorldManifestError(f"{label} {owner}.pendingCount must equal addCount + deleteCount")
        _ensure_string(seed_obj.get("summaryText"), field=f"{owner}.summaryText", label=label)

        steps = _require_list(seed_obj.get("steps"), field=f"{owner}.steps", label=label)
        for index, step in enumerate(steps):
            step_obj = _require_mapping(step, field=f"{owner}.steps[{index}]", label=label)
            step_owner = f"{owner}.steps[{index}]"
            _validate_exact_keys(step_obj, expected=SYNC_PRESENTER_STEP_KEYS, owner=step_owner, label=label)
            step_id = _ensure_str(step_obj.get("id"), field=f"{step_owner}.id", label=label)
            _ensure_str(step_obj.get("label"), field=f"{step_owner}.label", label=label)
            status = _ensure_str(step_obj.get("status"), field=f"{step_owner}.status", label=label)
            if status not in VALID_SYNC_STEP_STATUSES:
                raise UIWorldManifestError(f"{label} {step_owner}.{step_id}.status is invalid")
            current = _ensure_non_negative_int(step_obj.get("current"), field=f"{step_owner}.current", label=label)
            total = _ensure_non_negative_int(step_obj.get("total"), field=f"{step_owner}.total", label=label)
            if current > total:
                raise UIWorldManifestError(f"{label} {step_owner}.current must not exceed total")
            _ensure_string(step_obj.get("detail"), field=f"{step_owner}.detail", label=label)

        pending_rows = _require_list(seed_obj.get("pendingRows"), field=f"{owner}.pendingRows", label=label)
        if phase == "ready" and len(pending_rows) != pending_count:
            raise UIWorldManifestError(f"{label} {owner}.pendingRows count must equal pendingCount in ready phase")
        for index, row in enumerate(pending_rows):
            row_obj = _require_mapping(row, field=f"{owner}.pendingRows[{index}]", label=label)
            row_owner = f"{owner}.pendingRows[{index}]"
            _validate_exact_keys(row_obj, expected=SYNC_PRESENTER_PENDING_ROW_KEYS, owner=row_owner, label=label)
            _validate_uuid(row_obj.get("id"), owner=f"{row_owner}.id", label=label)
            _ensure_str(row_obj.get("word"), field=f"{row_owner}.word", label=label)
            part_of_speech = row_obj.get("partOfSpeech")
            if part_of_speech is not None:
                _ensure_str(part_of_speech, field=f"{row_owner}.partOfSpeech", label=label)
            _ensure_str(row_obj.get("translation"), field=f"{row_owner}.translation", label=label)
            for field in ("wordTone", "actionTone"):
                tone = _ensure_str(row_obj.get(field), field=f"{row_owner}.{field}", label=label)
                if tone not in VALID_WORD_ROW_TONES:
                    raise UIWorldManifestError(f"{label} {row_owner}.{field} is invalid")
            _ensure_bool(row_obj.get("isStrikethrough"), field=f"{row_owner}.isStrikethrough", label=label)
            _ensure_str(row_obj.get("actionSystemImage"), field=f"{row_owner}.actionSystemImage", label=label)
            _ensure_str(
                row_obj.get("actionAccessibilityLabel"),
                field=f"{row_owner}.actionAccessibilityLabel",
                label=label,
            )


def _validate_auth_state(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("auth"), field="auth", label=label).items():
        seed_obj = _require_mapping(seed, field=f"auth.{fixture_id}", label=label)
        owner = f"auth.{fixture_id}"
        keys = set(seed_obj)
        missing = sorted(AUTH_REQUIRED_KEYS - keys)
        extra = sorted(keys - AUTH_REQUIRED_KEYS)
        if missing or extra:
            raise UIWorldManifestError(
                f"{label} {owner} keys 不符合 UI World v2: extra={extra} missing={missing}"
            )
        is_logged_in = seed_obj.get("isLoggedIn")
        if not isinstance(is_logged_in, bool):
            raise UIWorldManifestError(f"{label} {owner}.isLoggedIn 必須是 bool")
        token_state = _ensure_str(seed_obj.get("keychainTokenState"), field=f"{owner}.keychainTokenState", label=label)
        token = seed_obj.get("token")
        user_id = seed_obj.get("userId")

        if is_logged_in:
            _ensure_str(user_id, field=f"{owner}.userId", label=label)
            if seed_obj.get("isAuthenticating") is True:
                raise UIWorldManifestError(f"{label} {owner} logged-in seed must not also be authenticating")
            if seed_obj.get("authError") is not None:
                raise UIWorldManifestError(f"{label} {owner} logged-in seed must not carry authError")

        if token_state == "available":
            if is_logged_in is not True:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=available requires isLoggedIn=true")
            _ensure_str(token, field=f"{owner}.token", label=label)
        elif token_state == "readFailed":
            if is_logged_in is not True:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=readFailed requires isLoggedIn=true")
            _ensure_str(user_id, field=f"{owner}.userId", label=label)
            if token is not None:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=readFailed must not expose a readable token")
        elif token_state == "absent":
            if is_logged_in:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=absent requires isLoggedIn=false")
            if token is not None:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=absent must not include token")
        else:
            raise UIWorldManifestError(f"{label} {owner}.keychainTokenState 不支援: {token_state}")


def _validate_preferences(data: dict[str, Any], *, label: str) -> None:
    preferences = _require_mapping(data.get("preferences"), field="preferences", label=label)
    keys = set(preferences)
    missing = sorted(PREFERENCES_KEYS - keys)
    extra = sorted(keys - PREFERENCES_KEYS)
    if missing or extra:
        raise UIWorldManifestError(
            f"{label} preferences keys 不符合 UI World v2: extra={extra} missing={missing}"
        )

    for domain in sorted(PREFERENCES_KEYS):
        entries = _require_mapping(preferences.get(domain), field=f"preferences.{domain}", label=label)
        unknown = sorted(set(entries) - PREFERENCE_DOMAIN_KEYS[domain])
        if unknown:
            raise UIWorldManifestError(f"{label} preferences.{domain} contains unknown app preference keys {unknown}")
        for key, value in sorted(entries.items()):
            if not isinstance(key, str) or not key.strip():
                raise UIWorldManifestError(f"{label} preferences.{domain} contains an empty key")
            if not isinstance(value, (str, int, float, bool)) or value is None:
                raise UIWorldManifestError(
                    f"{label} preferences.{domain}.{key} value 必須是 string、number 或 bool"
                )


def _all_notebook_ids(data: dict[str, Any], *, label: str) -> set[str]:
    notebook_ids: set[str] = set()
    for fixture_id, seed in _require_mapping(
        data.get("notebook"),
        field="notebook",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"notebook.{fixture_id}", label=label)
        for index, notebook in enumerate(
            _require_list(
                seed_obj.get("notebooks"),
                field=f"notebook.{fixture_id}.notebooks",
                label=label,
            )
        ):
            notebook_obj = _require_mapping(
                notebook,
                field=f"notebook.{fixture_id}.notebooks[{index}]",
                label=label,
            )
            remote_id = _ensure_str(
                notebook_obj.get("remoteId"),
                field=f"notebook.{fixture_id}.notebooks[{index}].remoteId",
                label=label,
            ).strip()
            notebook_ids.add(remote_id)
    return notebook_ids


def _require_notebook_ref(ref: Any, *, notebook_ids: set[str], owner: str, label: str) -> str:
    value = _ensure_str(ref, field=owner, label=label).strip()
    if value not in notebook_ids:
        raise UIWorldManifestError(f"{label} {owner} references missing notebook {value}")
    return value


def _validate_book_asset_alignment(
    *,
    ref: str,
    asset: dict[str, Any],
    file_name: Any,
    book_format: Any,
    owner: str,
    label: str,
) -> None:
    file_name_value = _ensure_str(file_name, field=f"{owner}.fileName", label=label).strip()
    format_value = _ensure_str(book_format, field=f"{owner}.format", label=label).strip()
    expected_install = f"Books/{file_name_value}"
    if asset.get("installAs") != expected_install:
        raise UIWorldManifestError(
            f"{label} {owner} {ref} installAs must be {expected_install}, got {asset.get('installAs')}"
        )
    expected_content_type = BOOK_FORMAT_CONTENT_TYPES.get(format_value)
    if expected_content_type is None:
        raise UIWorldManifestError(f"{label} {owner}.format 不支援: {format_value}")
    content_type = _ensure_str(asset.get("contentType"), field=f"{owner}.contentType", label=label)
    if not content_type.startswith(expected_content_type):
        raise UIWorldManifestError(
            f"{label} {owner} {ref} contentType must start with {expected_content_type}, got {content_type}"
        )


def _validate_cross_references(data: dict[str, Any], *, label: str) -> None:
    assets = _require_mapping(data.get("assets"), field="assets", label=label)
    asset_refs = {
        f"{bucket}.{asset_id}"
        for bucket, entries in assets.items()
        if isinstance(entries, dict)
        for asset_id in entries
    }
    auth_refs = {
        f"auth.{key}"
        for key in _require_mapping(data.get("auth"), field="auth", label=label)
    }
    entitlements_refs = {
        f"entitlements.{key}"
        for key in _require_mapping(data.get("entitlements"), field="entitlements", label=label)
    }
    notebook_ids = _all_notebook_ids(data, label=label)

    for fixture_id, seed in _require_mapping(
        data.get("settings"),
        field="settings",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"settings.{fixture_id}", label=label)
        auth_ref = _require_ref(
            seed_obj.get("authFixtureRef"),
            prefix="auth.",
            refs=auth_refs,
            owner=f"settings.{fixture_id}.authFixtureRef",
            label=label,
        )
        auth_key = auth_ref.removeprefix("auth.")
        auth_seed = _require_mapping(data["auth"][auth_key], field=auth_ref, label=label)
        auth_state = _require_mapping(
            seed_obj.get("auth"),
            field=f"settings.{fixture_id}.auth",
            label=label,
        )
        if auth_state.get("isLoggedIn") != auth_seed.get("isLoggedIn"):
            raise UIWorldManifestError(
                f"{label} settings.{fixture_id}.auth.isLoggedIn must match {auth_ref}.isLoggedIn"
            )
        if auth_state.get("authError") != auth_seed.get("authError"):
            raise UIWorldManifestError(
                f"{label} settings.{fixture_id}.auth.authError must match {auth_ref}.authError"
            )
        if auth_state.get("isLoggedIn"):
            for field in ("email", "displayName"):
                if auth_state.get(field) != auth_seed.get(field):
                    raise UIWorldManifestError(
                        f"{label} settings.{fixture_id}.auth.{field} must match {auth_ref}.{field}"
                    )

        entitlements_ref = seed_obj.get("entitlementsFixtureRef")
        if entitlements_ref is None:
            if seed_obj.get("subscription") is not None:
                raise UIWorldManifestError(
                    f"{label} settings.{fixture_id} without entitlementsFixtureRef must not declare subscription UI state"
                )
        else:
            ent_ref = _require_ref(
                entitlements_ref,
                prefix="entitlements.",
                refs=entitlements_refs,
                owner=f"settings.{fixture_id}.entitlementsFixtureRef",
                label=label,
            )
            subscription = seed_obj.get("subscription")
            if isinstance(subscription, dict) and not subscription.get("isRefreshing", False):
                ent_key = ent_ref.removeprefix("entitlements.")
                ent_seed = _require_mapping(
                    data["entitlements"][ent_key],
                    field=ent_ref,
                    label=label,
                )
                pro = _require_mapping(ent_seed.get("pro"), field=f"{ent_ref}.pro", label=label)
                if subscription.get("isActive") != pro.get("is_active"):
                    raise UIWorldManifestError(
                        f"{label} settings.{fixture_id}.subscription.isActive must match {ent_ref}.pro.is_active"
                    )

    for fixture_id, seed in _require_mapping(
        data.get("runtimePodcast"),
        field="runtimePodcast",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"runtimePodcast.{fixture_id}", label=label)
        _require_ref(
            seed_obj.get("audioAssetRef"),
            prefix="audio.",
            refs=asset_refs,
            owner=f"runtimePodcast.{fixture_id}.audioAssetRef",
            label=label,
        )
        _require_ref(
            seed_obj.get("subtitleAssetRef"),
            prefix="subtitles.",
            refs=asset_refs,
            owner=f"runtimePodcast.{fixture_id}.subtitleAssetRef",
            label=label,
        )
        preferred_notebook = seed_obj.get("preferredNotebookId")
        if preferred_notebook is not None and str(preferred_notebook).strip():
            _require_notebook_ref(
                preferred_notebook,
                notebook_ids=notebook_ids,
                owner=f"runtimePodcast.{fixture_id}.preferredNotebookId",
                label=label,
            )
        for index, episode in enumerate(
            _require_list(
                seed_obj.get("episodes"),
                field=f"runtimePodcast.{fixture_id}.episodes",
                label=label,
            )
        ):
            episode_obj = _require_mapping(
                episode,
                field=f"runtimePodcast.{fixture_id}.episodes[{index}]",
                label=label,
            )
            download = episode_obj.get("download")
            if download is None:
                continue
            download_obj = _require_mapping(
                download,
                field=f"runtimePodcast.{fixture_id}.episodes[{index}].download",
                label=label,
            )
            download_owner = f"runtimePodcast.{fixture_id}.episodes[{index}].download"
            _validate_exact_keys(
                download_obj,
                expected=RUNTIME_PODCAST_DOWNLOAD_KEYS,
                owner=download_owner,
                label=label,
            )
            audio_ref = _require_ref(
                download_obj.get("audioAssetRef"),
                prefix="audio.",
                refs=asset_refs,
                owner=f"{download_owner}.audioAssetRef",
                label=label,
            )
            audio_asset = _require_mapping(
                assets["audio"][audio_ref.removeprefix("audio.")],
                field=audio_ref,
                label=label,
            )
            _validate_download_local_path(
                download_obj.get("localAudioPath"),
                expected_install_as=_ensure_str(
                    audio_asset.get("installAs"),
                    field=f"{audio_ref}.installAs",
                    label=label,
                ),
                owner=f"{download_owner}.localAudioPath",
                label=label,
            )
            subtitle_ref = download_obj.get("subtitleAssetRef")
            if subtitle_ref is not None:
                subtitle_ref = _require_ref(
                    subtitle_ref,
                    prefix="subtitles.",
                    refs=asset_refs,
                    owner=f"{download_owner}.subtitleAssetRef",
                    label=label,
                )
                subtitle_asset = _require_mapping(
                    assets["subtitles"][subtitle_ref.removeprefix("subtitles.")],
                    field=subtitle_ref,
                    label=label,
                )
                expected_subtitle_path: str | None = _ensure_str(
                    subtitle_asset.get("installAs"),
                    field=f"{subtitle_ref}.installAs",
                    label=label,
                )
            else:
                expected_subtitle_path = None
            _validate_download_local_path(
                download_obj.get("localSubtitlePath"),
                expected_install_as=expected_subtitle_path,
                owner=f"{download_owner}.localSubtitlePath",
                label=label,
            )

    for fixture_id, seed in _require_mapping(data.get("reader"), field="reader", label=label).items():
        seed_obj = _require_mapping(seed, field=f"reader.{fixture_id}", label=label)
        _validate_notebook_sync_status(
            seed_obj.get("notebookSyncStatus"),
            owner=f"reader.{fixture_id}.notebookSyncStatus",
            label=label,
        )
        entry_obj = _require_mapping(seed_obj.get("entry"), field=f"reader.{fixture_id}.entry", label=label)
        _validate_ui_world_entry(entry_obj, owner=f"reader.{fixture_id}.entry", label=label)
        _require_ref(
            seed_obj.get("textAssetRef"),
            prefix="text.",
            refs=asset_refs,
            owner=f"reader.{fixture_id}.textAssetRef",
            label=label,
        )
        ref = _require_ref(
            seed_obj.get("bookAssetRef"),
            prefix="books.",
            refs=asset_refs,
            owner=f"reader.{fixture_id}.bookAssetRef",
            label=label,
        )
        _validate_book_asset_alignment(
            ref=ref,
            asset=assets["books"][ref.removeprefix("books.")],
            file_name=seed_obj.get("bookFileName"),
            book_format="epub",
            owner=f"reader.{fixture_id}",
            label=label,
        )

    for fixture_id, seed in _require_mapping(
        data.get("bookshelf"),
        field="bookshelf",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"bookshelf.{fixture_id}", label=label)
        _validate_exact_keys(
            seed_obj,
            expected=BOOKSHELF_SEED_KEYS,
            owner=f"bookshelf.{fixture_id}",
            label=label,
        )
        _parse_iso8601(
            seed_obj.get("referenceDate"),
            owner=f"bookshelf.{fixture_id}.referenceDate",
            label=label,
        )
        for index, book in enumerate(
            _require_list(
                seed_obj.get("books"),
                field=f"bookshelf.{fixture_id}.books",
                label=label,
            )
        ):
            book_obj = _require_mapping(
                book,
                field=f"bookshelf.{fixture_id}.books[{index}]",
                label=label,
            )
            owner = f"bookshelf.{fixture_id}.books[{index}]"
            _validate_exact_keys(book_obj, expected=BOOKSHELF_BOOK_KEYS, owner=owner, label=label)
            _ensure_str(book_obj.get("title"), field=f"{owner}.title", label=label)
            if not isinstance(book_obj.get("author"), str):
                raise UIWorldManifestError(f"{label} {owner}.author 必須是 string")
            _validate_optional_progression(book_obj.get("progression"), owner=f"{owner}.progression", label=label)
            date_added = _parse_iso8601(book_obj.get("dateAdded"), owner=f"{owner}.dateAdded", label=label)
            date_last_read = _validate_optional_iso8601(
                book_obj.get("dateLastRead"),
                owner=f"{owner}.dateLastRead",
                label=label,
            )
            if date_last_read is not None and date_last_read < date_added:
                raise UIWorldManifestError(f"{label} {owner}.dateLastRead must not be earlier than dateAdded")
            ref = _require_ref(
                book_obj.get("bookAssetRef"),
                prefix="books.",
                refs=asset_refs,
                owner=f"{owner}.bookAssetRef",
                label=label,
            )
            _validate_book_asset_alignment(
                ref=ref,
                asset=assets["books"][ref.removeprefix("books.")],
                file_name=book_obj.get("fileName"),
                book_format=book_obj.get("format"),
                owner=owner,
                label=label,
            )
            preferred_notebook = book_obj.get("preferredNotebookId")
            if preferred_notebook is not None and str(preferred_notebook).strip():
                _require_notebook_ref(
                    preferred_notebook,
                    notebook_ids=notebook_ids,
                    owner=f"{owner}.preferredNotebookId",
                    label=label,
                )

    for fixture_id, seed in _require_mapping(
        data.get("notebook"),
        field="notebook",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"notebook.{fixture_id}", label=label)
        _validate_exact_keys(seed_obj, expected=NOTEBOOK_SEED_KEYS, owner=f"notebook.{fixture_id}", label=label)
        notebooks = _require_list(seed_obj.get("notebooks"), field=f"notebook.{fixture_id}.notebooks", label=label)
        notebook_remote_ids: list[str] = []
        for index, item in enumerate(notebooks):
            item_obj = _require_mapping(
                item,
                field=f"notebook.{fixture_id}.notebooks[{index}]",
                label=label,
            )
            owner = f"notebook.{fixture_id}.notebooks[{index}]"
            _validate_exact_keys(item_obj, expected=NOTEBOOK_ROW_KEYS, owner=owner, label=label)
            remote_id = _ensure_str(item_obj.get("remoteId"), field=f"{owner}.remoteId", label=label).strip()
            notebook_remote_ids.append(remote_id)
            _ensure_str(item_obj.get("name"), field=f"{owner}.name", label=label)
            for field in ("color", "coverPattern", "coverImageAssetRef"):
                value = item_obj.get(field)
                if value is not None:
                    _ensure_str(value, field=f"{owner}.{field}", label=label)
            if item_obj.get("coverImageAssetRef") is not None:
                _require_ref(
                    item_obj.get("coverImageAssetRef"),
                    prefix="images.",
                    refs=asset_refs,
                    owner=f"{owner}.coverImageAssetRef",
                    label=label,
                )
            card_state = item_obj.get("cardState")
            if card_state is not None:
                _validate_notebook_card_state(
                    _require_mapping(card_state, field=f"{owner}.cardState", label=label),
                    owner=f"{owner}.cardState",
                    label=label,
                )
            _validate_notebook_sync_status(item_obj.get("syncStatus"), owner=f"{owner}.syncStatus", label=label)
            _ensure_bool(item_obj.get("isDefault"), field=f"{owner}.isDefault", label=label)
            _ensure_int(item_obj.get("sortOrder"), field=f"{owner}.sortOrder", label=label)
            entry_words: list[str] = []
            for entry_index, entry in enumerate(
                _require_list(item_obj.get("entries"), field=f"{owner}.entries", label=label)
            ):
                entry_obj = _require_mapping(entry, field=f"{owner}.entries[{entry_index}]", label=label)
                entry_words.append(
                    _validate_notebook_entry(entry_obj, owner=f"{owner}.entries[{entry_index}]", label=label)
                )
            _validate_unique(entry_words, owner=f"{owner}.entries.word", label=label)
        _validate_unique(notebook_remote_ids, owner=f"notebook.{fixture_id}.notebooks.remoteId", label=label)

        for index, item in enumerate(
            _require_list(seed_obj.get("editStates"), field=f"notebook.{fixture_id}.editStates", label=label)
        ):
            item_obj = _require_mapping(
                item,
                field=f"notebook.{fixture_id}.editStates[{index}]",
                label=label,
            )
            owner = f"notebook.{fixture_id}.editStates[{index}]"
            _validate_notebook_edit_state(item_obj, owner=owner, label=label)
            if item_obj.get("coverImageAssetRef") is not None:
                _require_ref(
                    item_obj.get("coverImageAssetRef"),
                    prefix="images.",
                    refs=asset_refs,
                    owner=f"{owner}.coverImageAssetRef",
                    label=label,
                )

    for fixture_id, seed in _require_mapping(data.get("vocabulary"), field="vocabulary", label=label).items():
        seed_obj = _require_mapping(seed, field=f"vocabulary.{fixture_id}", label=label)
        _validate_exact_keys(seed_obj, expected=VOCABULARY_SEED_KEYS, owner=f"vocabulary.{fixture_id}", label=label)
        _ensure_str(seed_obj.get("notebookRemoteId"), field=f"vocabulary.{fixture_id}.notebookRemoteId", label=label)
        _ensure_str(seed_obj.get("notebookName"), field=f"vocabulary.{fixture_id}.notebookName", label=label)
        _ensure_str(seed_obj.get("bookTitle"), field=f"vocabulary.{fixture_id}.bookTitle", label=label)
        _validate_notebook_sync_status(
            seed_obj.get("notebookSyncStatus"),
            owner=f"vocabulary.{fixture_id}.notebookSyncStatus",
            label=label,
        )
        entry_words = []
        entry_objs = []
        for index, entry in enumerate(_require_list(seed_obj.get("entries"), field=f"vocabulary.{fixture_id}.entries", label=label)):
            entry_obj = _require_mapping(entry, field=f"vocabulary.{fixture_id}.entries[{index}]", label=label)
            entry_words.append(_validate_ui_world_entry(entry_obj, owner=f"vocabulary.{fixture_id}.entries[{index}]", label=label))
            entry_objs.append(entry_obj)
        _validate_unique(entry_words, owner=f"vocabulary.{fixture_id}.entries.word", label=label)
        entry_word_set = set(entry_words)
        _validate_seed_graph_links(entry_objs, entry_word_set, owner_prefix=f"vocabulary.{fixture_id}", label=label)
        for index, record in enumerate(
            _require_list(seed_obj.get("reviewHistory"), field=f"vocabulary.{fixture_id}.reviewHistory", label=label)
        ):
            record_obj = _require_mapping(record, field=f"vocabulary.{fixture_id}.reviewHistory[{index}]", label=label)
            owner = f"vocabulary.{fixture_id}.reviewHistory[{index}]"
            _validate_exact_keys(record_obj, expected=REVIEW_HISTORY_KEYS, owner=owner, label=label)
            word = _ensure_str(record_obj.get("word"), field=f"{owner}.word", label=label)
            if word not in entry_word_set:
                raise UIWorldManifestError(f"{label} {owner}.{word} must reference an entry in the same seed")
            _ensure_int(record_obj.get("feedback"), field=f"{owner}.feedback", label=label)
            _parse_iso8601(record_obj.get("reviewedAt"), owner=f"{owner}.reviewedAt", label=label)

    for fixture_id, seed in _require_mapping(data.get("reviewDeck"), field="reviewDeck", label=label).items():
        seed_obj = _require_mapping(seed, field=f"reviewDeck.{fixture_id}", label=label)
        _validate_exact_keys(seed_obj, expected=REVIEW_DECK_SEED_KEYS, owner=f"reviewDeck.{fixture_id}", label=label)
        _ensure_str(seed_obj.get("notebookRemoteId"), field=f"reviewDeck.{fixture_id}.notebookRemoteId", label=label)
        _ensure_str(seed_obj.get("notebookName"), field=f"reviewDeck.{fixture_id}.notebookName", label=label)
        _validate_notebook_sync_status(
            seed_obj.get("notebookSyncStatus"),
            owner=f"reviewDeck.{fixture_id}.notebookSyncStatus",
            label=label,
        )
        entry_words = []
        entry_objs = []
        for index, entry in enumerate(_require_list(seed_obj.get("entries"), field=f"reviewDeck.{fixture_id}.entries", label=label)):
            entry_obj = _require_mapping(entry, field=f"reviewDeck.{fixture_id}.entries[{index}]", label=label)
            entry_words.append(_validate_ui_world_entry(entry_obj, owner=f"reviewDeck.{fixture_id}.entries[{index}]", label=label))
            entry_objs.append(entry_obj)
        _validate_unique(entry_words, owner=f"reviewDeck.{fixture_id}.entries.word", label=label)
        _validate_seed_graph_links(entry_objs, set(entry_words), owner_prefix=f"reviewDeck.{fixture_id}", label=label)


def validate_fixture_dataset_file(path: Path, *, label: str = "UI World dataset") -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UIWorldManifestError(f"{label} 不是可讀 JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UIWorldManifestError(f"{label} top-level 必須是 object: {path}")
    if data.get("schema") != FIXTURE_SCHEMA:
        raise UIWorldManifestError(f"{label} schema 必須是 {FIXTURE_SCHEMA}: {path}")
    keys = set(data)
    extra = sorted(keys - FIXTURE_TOP_LEVEL_KEYS)
    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - keys)
    if extra or missing:
        raise UIWorldManifestError(
            f"{label} top-level keys 不符合 UI World v2: extra={extra} missing={missing}"
        )
    dataset_id = data.get("datasetID")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise UIWorldManifestError(f"{label} datasetID 必須是非空字串: {path}")
    _validate_fixture_domain_ids(data, label=label)

    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise UIWorldManifestError(f"{label} assets 必須是 object: {path}")
    asset_keys = set(assets)
    if asset_keys != ASSET_BUCKETS:
        extra = sorted(asset_keys - ASSET_BUCKETS)
        missing = sorted(ASSET_BUCKETS - asset_keys)
        raise UIWorldManifestError(
            f"{label} assets buckets 不符合 UI World v2: extra={extra} missing={missing}"
        )
    install_paths: dict[str, str] = {}
    for bucket in sorted(ASSET_BUCKETS):
        entries = assets[bucket]
        if not isinstance(entries, dict):
            raise UIWorldManifestError(f"{label} assets.{bucket} 必須是 object: {path}")
        for asset_id, asset in sorted(entries.items()):
            asset_label = f"assets.{bucket}.{asset_id}"
            if not isinstance(asset_id, str) or not asset_id:
                raise UIWorldManifestError(f"{label} {asset_label} key 必須是非空字串")
            if not isinstance(asset, dict):
                raise UIWorldManifestError(f"{label} {asset_label} 必須是 object")
            keys = set(asset)
            missing = sorted(ASSET_REQUIRED_KEYS - keys)
            extra = sorted(keys - ASSET_REQUIRED_KEYS)
            if missing or extra:
                raise UIWorldManifestError(
                    f"{label} {asset_label} keys 不符合 UI World v2: extra={extra} missing={missing}"
                )
            source_path = _resolve_path(_ensure_str(asset.get("sourcePath"), field=f"{asset_label}.sourcePath", label=label))
            install_as = _ensure_str(asset.get("installAs"), field=f"{asset_label}.installAs", label=label)
            content_type = _ensure_str(asset.get("contentType"), field=f"{asset_label}.contentType", label=label)
            expected_hash = _ensure_str(asset.get("sha256"), field=f"{asset_label}.sha256", label=label)
            expected_size = asset.get("byteSize")
            _validate_install_as(install_as, field=asset_label, label=label)
            previous_asset = install_paths.get(install_as)
            if previous_asset is not None:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.installAs duplicates {previous_asset}.installAs: {install_as}"
                )
            install_paths[install_as] = asset_label
            if "/" not in content_type:
                raise UIWorldManifestError(f"{label} {asset_label}.contentType 必須是 MIME type")
            if content_type not in ASSET_CONTENT_TYPES_BY_BUCKET[bucket]:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.contentType {content_type} is invalid for assets.{bucket}"
                )
            ext = Path(install_as).suffix.lower().removeprefix(".") or source_path.suffix.lower().removeprefix(".")
            expected_content_type = ASSET_CONTENT_TYPES_BY_EXTENSION.get(ext)
            if expected_content_type is not None and content_type != expected_content_type:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.contentType must match .{ext} as {expected_content_type}, got {content_type}"
                )
            if len(expected_hash) != 64 or any(ch not in "0123456789abcdef" for ch in expected_hash):
                raise UIWorldManifestError(f"{label} {asset_label}.sha256 必須是 64 字元小寫 hex")
            if not isinstance(expected_size, int) or expected_size <= 0:
                raise UIWorldManifestError(f"{label} {asset_label}.byteSize 必須是正整數")
            if not source_path.is_file():
                raise UIWorldManifestError(f"{label} {asset_label}.sourcePath 不存在: {source_path}")
            actual_size = source_path.stat().st_size
            if actual_size != expected_size:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.byteSize mismatch: expected {expected_size}, got {actual_size}"
                )
            actual_hash = _sha256_hex(source_path)
            if actual_hash != expected_hash:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.sha256 mismatch: expected {expected_hash}, got {actual_hash}"
                )
    _validate_preferences(data, label=label)
    _validate_auth_state(data, label=label)
    _validate_entitlements(data, label=label)
    _validate_settings(data, label=label)
    _validate_podcast(data, label=label)
    _validate_today_review(data, label=label)
    _validate_sync_presenter(data, label=label)
    _validate_scenario_context(data, label=label)
    _validate_cross_references(data, label=label)
    return dataset_id


def _validate_scenario_context(data: dict[str, Any], *, label: str) -> None:
    """Validate optional cross-domain state used only by scenarios that request it."""
    if "scenarioContext" not in data:
        return
    mc = _require_mapping(data.get("scenarioContext"), field="scenarioContext", label=label)
    keys = set(mc)
    if keys != SCENARIO_CONTEXT_KEYS:
        extra = sorted(keys - SCENARIO_CONTEXT_KEYS)
        missing = sorted(SCENARIO_CONTEXT_KEYS - keys)
        raise UIWorldManifestError(
            f"{label} scenarioContext keys 不符: extra={extra} missing={missing}")

    clock = mc["reviewClock"]
    if clock is not None:
        clock_map = _require_mapping(clock, field="scenarioContext.reviewClock", label=label)
        ck = set(clock_map)
        if ck != REVIEW_CLOCK_FIELD_KEYS:
            extra = sorted(ck - REVIEW_CLOCK_FIELD_KEYS)
            missing = sorted(REVIEW_CLOCK_FIELD_KEYS - ck)
            raise UIWorldManifestError(
                f"{label} scenarioContext.reviewClock keys 不符: extra={extra} missing={missing}")
        frozen_now = _ensure_str(clock_map.get("frozenNow"),
                                 field="scenarioContext.reviewClock.frozenNow", label=label)
        try:
            datetime.strptime(frozen_now, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise UIWorldManifestError(
                f"{label} scenarioContext.reviewClock.frozenNow 必須是 "
                f"YYYY-MM-DDTHH:MM:SSZ: {frozen_now!r}") from exc
        if not isinstance(clock_map.get("frozenEpoch"), int) or isinstance(clock_map.get("frozenEpoch"), bool):
            raise UIWorldManifestError(
                f"{label} scenarioContext.reviewClock.frozenEpoch 必須是整數")
        anchor_day = _ensure_str(clock_map.get("anchorDay"),
                                 field="scenarioContext.reviewClock.anchorDay", label=label)
        try:
            datetime.strptime(anchor_day, "%Y-%m-%d")
        except ValueError as exc:
            raise UIWorldManifestError(
                f"{label} scenarioContext.reviewClock.anchorDay 必須是 YYYY-MM-DD: {anchor_day!r}") from exc
        _ensure_str(clock_map.get("source"),
                    field="scenarioContext.reviewClock.source", label=label)

    passage = _require_mapping(mc["readerPassage"], field="scenarioContext.readerPassage", label=label)
    pk = set(passage)
    if pk != READER_PASSAGE_KEYS:
        extra = sorted(pk - READER_PASSAGE_KEYS)
        missing = sorted(READER_PASSAGE_KEYS - pk)
        raise UIWorldManifestError(
            f"{label} scenarioContext.readerPassage keys 不符: extra={extra} missing={missing}")
    for str_field in ("bookTitle", "activeWord", "activeTranslation", "activeContext"):
        _ensure_str(passage.get(str_field),
                    field=f"scenarioContext.readerPassage.{str_field}", label=label)
    paragraphs = _require_list(passage.get("paragraphs"),
                               field="scenarioContext.readerPassage.paragraphs", label=label)
    if not paragraphs or any(not isinstance(p, str) or not p.strip() for p in paragraphs):
        raise UIWorldManifestError(
            f"{label} scenarioContext.readerPassage.paragraphs 必須是非空 string list")
    joined_tokens = {
        token.strip().strip(",.;:!?“”‘’\"'")
        for para in paragraphs for token in para.split()
    }
    active_words = _require_list(passage.get("activeWords"),
                                 field="scenarioContext.readerPassage.activeWords", label=label)
    vocab_words = _require_list(passage.get("vocabWords"),
                                field="scenarioContext.readerPassage.vocabWords", label=label)
    if active_words != [passage.get("activeWord")]:
        raise UIWorldManifestError(
            f"{label} scenarioContext.readerPassage.activeWords 必須是 [activeWord]")
    for hl in (*active_words, *vocab_words):
        if not isinstance(hl, str) or hl not in joined_tokens:
            raise UIWorldManifestError(
                f"{label} scenarioContext.readerPassage highlight {hl!r} 未出現在 paragraphs token")

    # wordDetail = vocab-seed 形狀（entries[0]=聚焦字 + 關聯卡），graph link 自足解析。
    wd = _require_mapping(mc["wordDetail"], field="scenarioContext.wordDetail", label=label)
    entry_words: list[str] = []
    entry_objs: list[dict[str, Any]] = []
    for i, entry in enumerate(_require_list(
            wd.get("entries"), field="scenarioContext.wordDetail.entries", label=label)):
        entry_obj = _require_mapping(entry, field=f"scenarioContext.wordDetail.entries[{i}]", label=label)
        entry_words.append(_validate_ui_world_entry(
            entry_obj, owner=f"scenarioContext.wordDetail.entries[{i}]", label=label))
        entry_objs.append(entry_obj)
    if not entry_words:
        raise UIWorldManifestError(f"{label} scenarioContext.wordDetail.entries 不可為空")
    _validate_unique(entry_words, owner="scenarioContext.wordDetail.entries.word", label=label)
    _validate_seed_graph_links(
        entry_objs, set(entry_words), owner_prefix="scenarioContext.wordDetail", label=label)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    validate = sub.add_parser("validate", help="validate one UI World v2 dataset")
    validate.add_argument("path", type=Path)
    validate.add_argument("--label", default="UI World dataset")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        try:
            dataset_id = validate_fixture_dataset_file(args.path, label=args.label)
        except UIWorldManifestError as exc:
            print(str(exc), file=sys.stderr)
            return 64
        print(dataset_id)
        return 0
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
