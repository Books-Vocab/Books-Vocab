from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ..api_models import PipelineQueueResponse
from ..deps import (
    _card_store,
    _embedding_store,
    _gemini_client,
    _graph_store,
    _require_pro_access,
    get_user_lock,
    get_current_user,
    logger,
)
from ..graph import LinkKind
from ..pipeline_handlers import queue_pipeline_response
from ..pipeline_service import run_pipeline_background as _run_pipeline_bg
from ..settings import KGSettings

router = APIRouter()


async def _run_pipeline_background(user: dict, *, settings: KGSettings, force_enrich: bool = False):
    await _run_pipeline_bg(
        user,
        get_user_lock_fn=get_user_lock,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        embedding_store_factory=_embedding_store, gemini_client_factory=_gemini_client,
        logger=logger, link_kind_enum=LinkKind, jwt_secret=settings.jwt_secret,
        force_enrich=force_enrich,
    )


@router.post("/api/pipeline", response_model=PipelineQueueResponse)
async def run_pipeline(
    background_tasks: BackgroundTasks,
    request: Request,
    user: dict = Depends(get_current_user),
    force_enrich: bool = False,
):
    settings = request.app.state.kg_settings

    async def _bg(u: dict) -> None:
        await _run_pipeline_background(u, settings=settings, force_enrich=force_enrich)

    return queue_pipeline_response(
        background_tasks, user,
        require_pro_access=_require_pro_access, run_pipeline_background_fn=_bg,
    )
