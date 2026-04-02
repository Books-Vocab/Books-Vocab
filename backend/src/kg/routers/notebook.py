from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..api_models import NotebookCreateRequest, NotebookResponse, NotebookUpdateRequest
from ..deps import _notebook_store, _card_store, _graph_store, _embedding_store, _gemini_client, get_current_user
from ..tracked_llm import TrackedLLM
from ..exceptions import BadRequestError, NotFoundError
from ..vocab_shared import _dt_to_iso

router = APIRouter()


def _notebook_response(nb, card_count: int = 0) -> NotebookResponse:
    return NotebookResponse(
        id=nb.id,
        name=nb.name,
        color=nb.color,
        sortOrder=nb.sort_order,
        isDefault=nb.is_default,
        isDeleted=nb.is_deleted,
        cardCount=card_count,
        updatedAt=_dt_to_iso(nb.updated_at),
    )


@router.get("/api/notebooks", response_model=list[NotebookResponse])
def list_notebooks(since: str | None = None, user: dict = Depends(get_current_user)):
    store = _notebook_store(user["dir"])
    store.ensure_default()
    cards = _card_store(user["dir"])

    if since:
        from ..user_store import parse_datetime
        parsed = parse_datetime(since)
        if parsed is None:
            raise BadRequestError("Invalid since timestamp")
        notebooks = store.get_modified_since(parsed)
    else:
        notebooks = store.all(include_deleted=True)

    counts = cards.count_by_notebook()
    return [
        _notebook_response(nb, card_count=counts.get(nb.id, 0))
        for nb in notebooks
    ]


@router.post("/api/notebooks", response_model=NotebookResponse, status_code=201)
def create_notebook(req: NotebookCreateRequest, user: dict = Depends(get_current_user)):
    store = _notebook_store(user["dir"])
    nb = store.create(name=req.name, color=req.color)
    return _notebook_response(nb)


@router.patch("/api/notebooks/{nb_id}", response_model=NotebookResponse)
def update_notebook(nb_id: str, req: NotebookUpdateRequest, user: dict = Depends(get_current_user)):
    store = _notebook_store(user["dir"])
    kwargs = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.color is not None:
        kwargs["color"] = req.color
    if req.sort_order is not None:
        kwargs["sort_order"] = req.sort_order
    if not kwargs:
        raise BadRequestError("No fields to update")
    nb = store.update(nb_id, **kwargs)
    if nb is None:
        raise NotFoundError("Notebook", nb_id)
    cards = _card_store(user["dir"])
    return _notebook_response(nb, card_count=cards.count(notebook_id=nb.id))


@router.delete("/api/notebooks/{nb_id}")
def delete_notebook(nb_id: str, user: dict = Depends(get_current_user)):
    store = _notebook_store(user["dir"])
    cards = _card_store(user["dir"])
    result = store.delete(nb_id)
    if result is False:
        raise BadRequestError("Cannot delete: notebook not found or is default")
    # 只在首次刪除時搬移卡片並合併 graph/embedding；冪等重試時已無資料需搬
    reassigned = 0
    if result is True:
        reassigned = cards.reassign_notebook(nb_id, "default")
        # Merge graph links/candidates and embeddings into default notebook
        # Failures are non-fatal: cards are already reassigned, graph/embedding
        # data can be reconciled later.
        try:
            src_graph = _graph_store(user["dir"], notebook_id=nb_id)
            tgt_graph = _graph_store(user["dir"], notebook_id="default")
            tgt_graph.merge_from(src_graph)
        except Exception:
            logging.warning("Failed to merge graph data from notebook %s", nb_id, exc_info=True)
        try:
            llm = TrackedLLM(_gemini_client(), user["id"])
            src_emb = _embedding_store(user["dir"], llm=llm, notebook_id=nb_id)
            tgt_emb = _embedding_store(user["dir"], llm=llm, notebook_id="default")
            tgt_emb.merge_from(src_emb)
        except Exception:
            logging.warning("Failed to merge embedding data from notebook %s", nb_id, exc_info=True)
    return {"deleted": nb_id, "cardsReassigned": reassigned}
