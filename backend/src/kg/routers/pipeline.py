from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from ..api_models import PipelineQueueResponse


def build_pipeline_router(
    *,
    run_pipeline: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.post("/api/pipeline", response_model=PipelineQueueResponse)(run_pipeline)
    return router
