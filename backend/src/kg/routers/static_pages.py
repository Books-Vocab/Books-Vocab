from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()
_STATIC_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@router.get("/privacy.html")
def get_privacy_policy():
    path = _STATIC_ROOT / "privacy.html"
    if not path.exists():
        return HTMLResponse("<h1>Privacy Policy Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.get("/support.html")
def get_support():
    path = _STATIC_ROOT / "support.html"
    if not path.exists():
        return HTMLResponse("<h1>Support Page Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.get("/terms.html")
def get_terms():
    path = _STATIC_ROOT / "terms.html"
    if not path.exists():
        return HTMLResponse("<h1>Terms of Service Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.get("/guide.html")
def get_guide():
    path = _STATIC_ROOT / "guide.html"
    if not path.exists():
        return HTMLResponse("<h1>Guide Not Found</h1>", status_code=404)
    return FileResponse(path)
