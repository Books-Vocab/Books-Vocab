from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class PodcastSeriesSummary(RootModel[dict[str, Any]]):
    """Editorial catalog entry.

    The producer owns this JSON shape and older fixtures intentionally include
    partial objects. Keep FastAPI from advertising an anonymous ``{}`` schema
    without making the endpoint reject legacy metadata at response time.
    """


class PodcastSeriesDetail(RootModel[dict[str, Any]]):
    """Full editorial series metadata; see ``PodcastSeriesSummary``."""


class PodcastProgressRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    position_sec: float = Field(ge=0.0)
    duration_sec: float = Field(ge=0.0)
    updated_at: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def reject_non_finite_progress(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for field_name in ("position_sec", "duration_sec"):
                field_value = value.get(field_name)
                if isinstance(field_value, float) and not math.isfinite(field_value):
                    raise HTTPException(
                        status_code=422,
                        detail=f"{field_name} must be finite",
                    )
        return value


class PodcastProgressResponse(BaseModel):
    series_id: str = Field(min_length=1)
    ep_num: int = Field(ge=1)
    position_sec: float = Field(ge=0.0)
    duration_sec: float = Field(ge=0.0)
    updated_at: str = Field(min_length=1)


class PodcastProgressListResponse(BaseModel):
    items: list[PodcastProgressResponse] = Field(default_factory=list, max_length=500)
