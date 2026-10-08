from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

router = APIRouter(tags=["static-pages"])
_STATIC_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@router.api_route("/", methods=["GET", "HEAD"])
def get_home() -> Response:
    path = _STATIC_ROOT / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>Home Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.api_route("/privacy.html", methods=["GET", "HEAD"])
def get_privacy_policy() -> Response:
    path = _STATIC_ROOT / "privacy.html"
    if not path.exists():
        return HTMLResponse("<h1>Privacy Policy Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.api_route("/support.html", methods=["GET", "HEAD"])
def get_support() -> Response:
    path = _STATIC_ROOT / "support.html"
    if not path.exists():
        return HTMLResponse("<h1>Support Page Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.api_route("/terms.html", methods=["GET", "HEAD"])
def get_terms() -> Response:
    path = _STATIC_ROOT / "terms.html"
    if not path.exists():
        return HTMLResponse("<h1>Terms of Service Not Found</h1>", status_code=404)
    return FileResponse(path)


@router.api_route("/guide.html", methods=["GET", "HEAD"])
def get_guide() -> Response:
    path = _STATIC_ROOT / "guide.html"
    if not path.exists():
        return HTMLResponse("<h1>Guide Not Found</h1>", status_code=404)
    return FileResponse(path)


_SITE_ORIGIN = "https://wordnexus.lol"
_SITEMAP_PAGES = ("/", "/guide.html", "/support.html", "/privacy.html", "/terms.html")


@router.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
def get_robots() -> Response:
    body = (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Disallow: /login\n"
        "Disallow: /auth\n"
        "Disallow: /api\n"
        f"Sitemap: {_SITE_ORIGIN}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
def get_sitemap() -> Response:
    urls = "".join(f"<url><loc>{_SITE_ORIGIN}{p}</loc></url>" for p in _SITEMAP_PAGES)
    body = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(body, media_type="application/xml")


@router.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def get_favicon() -> Response:
    path = _STATIC_ROOT / "static" / "img" / "favicon-32.png"
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path, media_type="image/png")
