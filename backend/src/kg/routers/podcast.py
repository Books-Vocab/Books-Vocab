import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ..deps import get_current_user

router = APIRouter(tags=["podcast"])
_SERIES_ID_RE = re.compile(r"^[a-z0-9_]+$")


def _podcasts_dir(request: Request | None = None) -> Path:
    if request is not None:
        return request.app.state.kg_settings.podcasts_dir
    from ..settings import load_settings
    return load_settings().podcasts_dir


@router.get("/api/podcasts")
def list_podcasts(request: Request, user: dict = Depends(get_current_user)):
    index_file = _podcasts_dir(request) / "index.json"
    if not index_file.exists():
        return []
    return json.loads(index_file.read_text(encoding="utf-8"))


@router.get("/api/podcasts/{series_id}")
def get_podcast_series(series_id: str, request: Request, user: dict = Depends(get_current_user)):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    meta_file = _podcasts_dir(request) / series_id / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(404, detail="Series not found")
    return json.loads(meta_file.read_text(encoding="utf-8"))


@router.get("/api/podcasts/{series_id}/{ep_num}/subtitle")
def get_podcast_subtitle(
    series_id: str, ep_num: int, request: Request, user: dict = Depends(get_current_user),
):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    srt_file = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / "subtitle.srt"
    if not srt_file.exists():
        raise HTTPException(404, detail="Subtitle not found")
    return PlainTextResponse(srt_file.read_text(encoding="utf-8"))
