from __future__ import annotations

from fastapi import APIRouter

from ..api_models import NotebookCreateRequest, NotebookResponse, NotebookUpdateRequest
from ..deps import CurrentUser, _card_store, _notebook_store
from ..exceptions import BadRequestError, NotFoundError
from ..vocab_shared import _dt_to_iso

router = APIRouter(tags=["notebook"])


def _notebook_response(nb, card_count: int = 0) -> NotebookResponse:
    return NotebookResponse(
        id=nb.id,
        name=nb.name,
        color=nb.color,
        coverPattern=nb.cover_pattern,
        sortOrder=nb.sort_order,
        isDefault=nb.is_default,
        isDeleted=nb.is_deleted,
        cardCount=card_count,
        updatedAt=_dt_to_iso(nb.updated_at),
        sourceSharedDeckId=nb.source_shared_deck_id,
        sourceVersion=nb.source_version,
    )


@router.get("/api/notebooks", response_model=list[NotebookResponse])
def list_notebooks(user: CurrentUser, since: str | None = None):
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
def create_notebook(req: NotebookCreateRequest, user: CurrentUser):
    store = _notebook_store(user["dir"])
    nb = store.create(name=req.name, color=req.color, cover_pattern=req.cover_pattern)
    return _notebook_response(nb)


@router.patch("/api/notebooks/{nb_id}", response_model=NotebookResponse)
def update_notebook(nb_id: str, req: NotebookUpdateRequest, user: CurrentUser):
    store = _notebook_store(user["dir"])
    kwargs = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.color is not None:
        kwargs["color"] = req.color
    if req.cover_pattern is not None:
        kwargs["cover_pattern"] = req.cover_pattern if req.cover_pattern != "" else None
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
def delete_notebook(nb_id: str, user: CurrentUser):
    store = _notebook_store(user["dir"])
    cards = _card_store(user["dir"])
    result = store.delete(nb_id)
    if result is False:
        raise BadRequestError("Cannot delete: notebook not found or is default")
    cards_deleted = 0
    if result is True:
        cards_deleted = cards.soft_delete_by_notebook(nb_id)
        # Remove every per-notebook artifact. Filenames come from the
        # ops_shared.NOTEBOOK_FILE_SPECS SoT (the same source service_factories
        # uses to create them), so a new artifact kind can't silently orphan a
        # file here as the two lists drift.
        from ..ops_shared import notebook_files
        for path in notebook_files(user["dir"], nb_id).values():
            for suffix in ("", ".bak", ".tmp"):
                path.with_name(path.name + suffix).unlink(missing_ok=True)
        # Evict cached stores
        from ..service_factories import evict_notebook_cache
        evict_notebook_cache(user["dir"], nb_id)
    return {"deleted": nb_id, "cardsDeleted": cards_deleted}
