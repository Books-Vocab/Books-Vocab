from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter


def build_pipeline_router(
    *,
    run_pipeline: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.post("/api/pipeline")(run_pipeline)
    return router
