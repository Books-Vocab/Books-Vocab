from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from pydantic import BeforeValidator

from .. import podcast_progress as progress_store
from ..api_models.podcast import (
    PodcastProgressListResponse,
    PodcastProgressRequest,
    PodcastProgressResponse,
)
from ..deps import CurrentUser

_MAX_EPISODE_NUM = 999


def _reject_boolean_progress_seconds(value: Any) -> Any:
    if isinstance(value, Mapping):
        for field_name in ("position_sec", "duration_sec"):
            if isinstance(value.get(field_name), bool):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} must be a number",
                )
    return value


_PodcastProgressPayload = Annotated[
    PodcastProgressRequest,
    BeforeValidator(_reject_boolean_progress_seconds),
]


def _canonical_updated_at(raw: str) -> str:
    """Validate + canonicalise ``updated_at`` to UTC ISO8601.

    Done as a helper rather than a Pydantic ``field_validator`` because
    Pydantic v2 stuffs the originating exception object into the error
    ``ctx``, which the project's existing validation_error_handler then
    cannot JSON-serialise (it returns ``exc.errors()`` verbatim). Raising
    ``HTTPException(422)`` from the route body sidesteps that path entirely.

    Parsing/normalisation is delegated to
    :func:`podcast_progress.parse_instant` — the same canonicaliser the LWW
    store uses — so the HTTP-layer and store-layer agree bit-for-bit; this
    helper only maps its ``None`` sentinel to a 422 and serialises to ISO8601.
    """
    dt = progress_store.parse_instant(raw)
    if dt is None:
        raise HTTPException(status_code=422, detail="updated_at must be ISO8601")
    return dt.isoformat()


def build_podcast_progress_router(
    *,
    validate_series_id: Callable[[str], None],
) -> APIRouter:
    router = APIRouter(tags=["podcast"])

    @router.get("/api/podcasts/progress", response_model=PodcastProgressListResponse)
    def list_user_progress(user: CurrentUser):
        """Return every progress row for the calling user."""
        items = progress_store.list_for_user(user_id=user["id"])
        return {"items": items}

    @router.post("/api/podcasts/{series_id}/{ep_num}/progress", response_model=PodcastProgressResponse)
    def upsert_user_progress(
        series_id: str,
        ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
        payload: _PodcastProgressPayload,
        user: CurrentUser,
    ):
        """Last-write-wins upsert keyed by ``(user, series, ep)``.

        A stale write (older ``updated_at`` than the stored row) is accepted at
        the HTTP layer (200) but discarded at the store layer — the response
        body reflects the current authoritative row so the client can converge
        its local copy without a second GET.
        """
        validate_series_id(series_id)
        return progress_store.upsert(
            user_id=user["id"],
            series_id=series_id,
            ep_num=ep_num,
            position_sec=payload.position_sec,
            duration_sec=payload.duration_sec,
            updated_at=_canonical_updated_at(payload.updated_at),
        )

    # The parent podcast router supplies the globals used by backend-quality's
    # endpoint reflection. Keep the evaluated alias on the endpoint so that
    # reflection does not need to resolve this child-module private name.
    upsert_user_progress.__annotations__["payload"] = _PodcastProgressPayload

    @router.get("/api/podcasts/{series_id}/{ep_num}/progress", response_model=PodcastProgressResponse)
    def get_user_progress(
        series_id: str,
        ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
        user: CurrentUser,
    ):
        validate_series_id(series_id)
        row = progress_store.get_single(
            user_id=user["id"],
            series_id=series_id,
            ep_num=ep_num,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="No playback progress found")
        return row

    return router
