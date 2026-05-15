from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    cards: int
    links: int
    pendingCandidates: int
    lastModified: str | None
    db_ok: bool = True
    disk_free_mb: int | None = None
    data_dir_exists: bool = True


class PipelineQueueResponse(BaseModel):
    status: str
    message: str


class AdminTestRunRequest(BaseModel):
    itemIds: list[str] = []
