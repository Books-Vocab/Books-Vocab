from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field, field_validator


class NotebookResponse(BaseModel):
    id: str
    name: str
    color: str | None = None
    coverPattern: str | None = None
    sortOrder: int = 0
    isDefault: bool = False
    isDeleted: bool = False
    cardCount: int = 0
    updatedAt: str | None = None
    # Provenance (v1 inert): where this notebook was copied from (Phase 2 copy).
    sourceSharedDeckId: str | None = None
    sourceVersion: int | None = None


VALID_COVER_PATTERNS: Final[frozenset[str]] = frozenset({"dots", "lines", "grid", "waves", "circles", "noise"})


def _validate_cover_pattern(v: str | None) -> str | None:
    if v is not None and v != "" and v not in VALID_COVER_PATTERNS:
        raise ValueError(f"cover_pattern must be one of {VALID_COVER_PATTERNS} or empty string to clear")
    return v


class NotebookCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20, pattern=r"^#[0-9a-fA-F]{6}$")
    cover_pattern: str | None = Field(default=None, max_length=30)

    _validate_cover_pattern = field_validator("cover_pattern")(staticmethod(_validate_cover_pattern))


class NotebookUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int | None = None
    cover_pattern: str | None = Field(default=None, max_length=30)

    _validate_cover_pattern = field_validator("cover_pattern")(staticmethod(_validate_cover_pattern))


class VocabUIConfig(BaseModel):
    """Per-user vocab UI 跨裝置偏好 group(走 user config /api/user/config,對齊
    architecture.md User config contract 的 `vocab_ui` domain;屬 ReviewClockConfig /
    ReviewModeConfig 的 LWW 家族,用 snake_case wire 而非本檔 notebook CRUD 的 camelCase)。

    目前僅 `active_notebook_id` = 決定新選詞預設歸進哪一本的全域游標;預留未來
    notebook filter / sort 等 vocab UI 偏好(architecture.md:60)。per-book
    `preferredNotebookId` 走 CloudKit,不在此。單一 `updated_at`(epoch 秒)驅動整組
    跨裝置 LWW。

    對 client 寬鬆:id 指向已刪 notebook 的 stale 清理由各 client 自理(iOS
    NotebookListCoordinator / chrome reconcile 皆已有),後端此階段 passthrough 不驗
    存在性,與現有 translation / review_* group 一致;architecture.md:89 規劃的
    「server 拒絕已刪 notebook」+ stale-write gate 歸入後續 server-LWW 真化階段統一
    處理(屆時涵蓋全部 group,不單獨特殊化 vocab_ui)。default "default" 對齊 iOS
    `Book.resolvedNotebookId` fallback 與 chrome 預設本。
    """

    active_notebook_id: str = "default"
    updated_at: float | None = None  # LWW timestamp, epoch 秒
