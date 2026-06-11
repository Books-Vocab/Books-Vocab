from __future__ import annotations

from pydantic import BaseModel, Field


class GraphLinkResponse(BaseModel):
    id: str
    fromId: str
    toId: str
    kind: str
    confidence: float
    reason: str


class AutoLinkConfig(BaseModel):
    """Per-user 自動連結開關 group(走 user config /api/user/config,屬 translation /
    review_* / vocab_ui 的 LWW 家族,單一 updated_at(epoch 秒)驅動整組跨裝置 LWW)。

    `enabled` 控制 pipeline `_step_embed_and_judge` Phase 2(judge LLM 自動連結):
    關閉時新單字仍照常 enrich + embed 並進 pending_judge 待判集合,只是不消費;
    重新開啟後下一輪 pipeline 續判,不丟失。預設 True 向後相容:既有帳號 config
    無此 group 視同開啟。手動連結(ManualLinkRequest)不受此開關影響。
    """

    enabled: bool = True
    updated_at: float | None = None  # LWW timestamp, epoch 秒


class ManualLinkRequest(BaseModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
