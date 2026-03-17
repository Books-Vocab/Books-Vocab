from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..api_models import NotebookCreateRequest, NotebookResponse, NotebookUpdateRequest
from ..deps import _notebook_store, _card_store, _require_pro_access, get_current_user
from ..vocab_service import _dt_to_iso

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
    _require_pro_access(user, "knowledge_sync")
    store = _notebook_store(user["dir"])
    store.ensure_default()
    cards = _card_store(user["dir"])

    if since:
        from ..user_store import parse_datetime
        parsed = parse_datetime(since)
        if parsed is None:
            raise HTTPException(400, "Invalid since timestamp")
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
    _require_pro_access(user, "knowledge_sync")
    store = _notebook_store(user["dir"])
    nb = store.create(name=req.name, color=req.color)
    return _notebook_response(nb)


@router.patch("/api/notebooks/{nb_id}", response_model=NotebookResponse)
def update_notebook(nb_id: str, req: NotebookUpdateRequest, user: dict = Depends(get_current_user)):
    _require_pro_access(user, "knowledge_sync")
    store = _notebook_store(user["dir"])
    kwargs = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.color is not None:
        kwargs["color"] = req.color
    if req.sort_order is not None:
        kwargs["sort_order"] = req.sort_order
    if not kwargs:
        raise HTTPException(400, "No fields to update")
    nb = store.update(nb_id, **kwargs)
    if nb is None:
        raise HTTPException(404, "Notebook not found")
    cards = _card_store(user["dir"])
    return _notebook_response(nb, card_count=cards.count(notebook_id=nb.id))


@router.delete("/api/notebooks/{nb_id}")
def delete_notebook(nb_id: str, user: dict = Depends(get_current_user)):
    _require_pro_access(user, "knowledge_sync")
    store = _notebook_store(user["dir"])
    if not store.delete(nb_id):
        raise HTTPException(400, "Cannot delete: notebook not found, already deleted, or is default")
    return {"deleted": nb_id}
