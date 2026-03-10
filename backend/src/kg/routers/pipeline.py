from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter

from ..api_models import PipelineQueueResponse


def build_pipeline_router(
    *,
    run_pipeline: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.post("/api/pipeline", response_model=PipelineQueueResponse)(run_pipeline)
    return router
