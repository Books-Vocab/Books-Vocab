"""Lint: request URLs written in backend tests must not contain dot-segments.

httpx (the TestClient transport) applies RFC 3986 ``remove_dot_segments``
before sending, so ``client.get("/api/podcasts/../etc")`` actually requests
``/api/etc``. A traversal test written that way never reaches the route it
names and passes on the router's 404 for a path that does not exist (#2113).
Percent-encode the segment instead (``%2e%2e``): httpx leaves it alone, and
starlette decodes it to ``..`` only after the router has matched it as a
single path parameter, so the handler really receives the hostile value.

The check is static, so it only sees string literals (including the literal
parts of f-strings); a ``..`` interpolated into a URL at runtime is not caught.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_METHOD_FIRST = frozenset({"request", "stream"})  # (method, url, ...)
_SCHEME_AUTHORITY = re.compile(r"\A[a-z][a-z0-9+.-]*://[^/]*", re.IGNORECASE)
_DOT_SEGMENT = re.compile(r"(?:\A|/)\.{1,2}(?:/|\Z)")
_PLACEHOLDER = "\x00"  # stands in for an f-string interpolation; never part of a dot-segment


def _literal_text(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else _PLACEHOLDER for part in node.values)
    return None


def _url_argument(call: ast.Call) -> ast.expr | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    for keyword in call.keywords:
        if keyword.arg == "url":
            return keyword.value
    method = call.func.attr
    index = 0 if method in _HTTP_METHODS else 1 if method in _METHOD_FIRST else None
    if index is None or len(call.args) <= index:
        return None
    return call.args[index]


def find_dot_segment_urls(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """Return ``(line, url)`` for each request call whose literal URL path has a dot-segment."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        url_node = _url_argument(node)
        text = None if url_node is None else _literal_text(url_node)
        if text is None:
            continue
        path = _SCHEME_AUTHORITY.sub("", text, count=1)
        if not path.startswith("/"):
            continue
        path = re.split(r"[?#]", path, maxsplit=1)[0]
        if _DOT_SEGMENT.search(path):
            hits.append((node.lineno, text.replace(_PLACEHOLDER, "{...}")))
    return hits


def _test_sources() -> list[Path]:
    return sorted(TESTS_DIR.rglob("*.py"))


def test_detector_flags_dot_segment_urls():
    source = "\n".join(
        [
            'client.get("/api/podcasts/../etc")',
            'api.client.post(f"/api/podcasts/{sid}/../subtitle", json={})',
            'client.request("GET", "/a/./b")',
            'client.get(url="/a/..")',
            'client.get("http://testserver/a/../b?x=1")',
        ]
    )
    assert [line for line, _ in find_dot_segment_urls(source)] == [1, 2, 3, 4, 5]


def test_detector_ignores_encoded_interpolated_and_non_url_literals():
    source = "\n".join(
        [
            'client.get("/api/podcasts/%2e%2e/cover")',
            'client.get(f"/api/podcasts/{bad_id}/1/audio")',
            'client.get("/api/podcasts/series.a")',
            'client.get("/api/x?next=/../y")',
            'Path("child") / ".." / "x"',
            'os.path.join("..", "x")',
        ]
    )
    assert find_dot_segment_urls(source) == []


def test_scan_covers_backend_tests():
    scanned = {path.relative_to(TESTS_DIR).as_posix() for path in _test_sources()}
    assert {"conftest.py", "test_podcast_api.py", "routers/test_library.py", Path(__file__).name} <= scanned


def test_request_urls_have_no_dot_segments():
    offenders = [
        f"{path.relative_to(TESTS_DIR).as_posix()}:{line}: {url}"
        for path in _test_sources()
        for line, url in find_dot_segment_urls(path.read_text(encoding="utf-8"), str(path))
    ]
    assert not offenders, (
        "httpx strips dot-segments before sending, so these requests never reach the route they "
        "name; percent-encode the segment (%2e%2e) instead:\n" + "\n".join(offenders)
    )
