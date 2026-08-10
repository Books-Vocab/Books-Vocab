from __future__ import annotations

import gzip
import inspect
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from types import MethodType

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ops.kg_board import server


def _ticket(ticket_id: str, *, status: str = "open", groomed: bool = True) -> dict:
    row = {
        "id": ticket_id,
        "status": status,
        "severity": "med",
        "stream": "IMP",
        "category": "tool",
        "date": "2026-08-10",
        "brief": ticket_id,
    }
    if groomed:
        row.update(plan="plan", acceptance="acceptance", groomed_by="test")
    return row


def _handler(path: str, headers: dict[str, str] | None = None):
    handler = object.__new__(server.Handler)
    handler.path = path
    handler.headers = headers or {}
    return handler


def _capturing_handler(path: str, headers: dict[str, str] | None = None):
    handler = _handler(path, headers)
    handler.wfile = BytesIO()
    handler.response_code = None
    handler.response_headers = []
    handler.send_response = MethodType(
        lambda self, code: setattr(self, "response_code", code), handler
    )
    handler.send_header = MethodType(
        lambda self, name, value: self.response_headers.append((name, value)), handler
    )
    handler.end_headers = MethodType(lambda _self: None, handler)
    return handler


def _response_headers(handler) -> dict[str, str]:
    return dict(handler.response_headers)


def test_board_json_gzip_negotiation_round_trips_and_significantly_shrinks(monkeypatch):
    payload = {
        "entries": [
            {"id": f"IMP-{index:04d}", "detail": "canonical board decision " * 40}
            for index in range(500)
        ]
    }
    original = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    monkeypatch.setattr(server, "board_payload", lambda: payload)
    handler = _capturing_handler("/api/board", {"Accept-Encoding": "br, gzip; q=0.8"})

    handler.do_GET()

    encoded = handler.wfile.getvalue()
    headers = _response_headers(handler)
    assert handler.response_code == 200
    assert headers["Content-Encoding"] == "gzip"
    assert headers["Vary"] == "Accept-Encoding"
    assert int(headers["Content-Length"]) == len(encoded)
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert gzip.decompress(encoded) == original
    assert len(encoded) < len(original) * 0.2


@pytest.mark.parametrize(
    "accept_encoding",
    (
        None,
        "br",
        "brgzip",
        "x-gzip",
        "*",
        "gzip;q=0",
        "br, gzip; q=0.000",
        "gzip;q=.5",
        "gzip;q=1e-1",
        "gzip;q=0.0001",
        "gzip;q=1.001",
        "gzip;level=1",
        "gzip;q=0.5;level=1",
    ),
)
def test_gzip_requires_an_explicit_positive_quality_token(accept_encoding):
    body = b"canonical-board-payload" * 200
    headers = {} if accept_encoding is None else {"Accept-Encoding": accept_encoding}
    handler = _capturing_handler("/api/board", headers)

    handler._send(200, body, "application/json; charset=utf-8")

    response_headers = _response_headers(handler)
    assert handler.wfile.getvalue() == body
    assert "Content-Encoding" not in response_headers
    assert int(response_headers["Content-Length"]) == len(body)


@pytest.mark.parametrize("accept_encoding", ("gzip", "GZip; Q=0.5", "br, gzip;q=1"))
def test_gzip_accepts_case_insensitive_positive_quality_token(accept_encoding):
    body = b"canonical-board-payload" * 200
    handler = _capturing_handler("/api/board", {"Accept-Encoding": accept_encoding})

    handler._send(200, body, "application/json; charset=utf-8")

    assert gzip.decompress(handler.wfile.getvalue()) == body
    assert _response_headers(handler)["Content-Encoding"] == "gzip"


def test_gzip_keeps_small_or_inapplicable_bodies_unencoded():
    cases = (
        (200, b"small", "application/json; charset=utf-8"),
        (204, b"x" * 5000, "application/json; charset=utf-8"),
        (200, b"x" * 5000, "image/png"),
    )
    for code, body, content_type in cases:
        handler = _capturing_handler("/", {"Accept-Encoding": "gzip"})

        handler._send(code, body, content_type)

        headers = _response_headers(handler)
        assert handler.wfile.getvalue() == body
        assert "Content-Encoding" not in headers
        assert int(headers["Content-Length"]) == len(body)


def test_active_page_is_external_assets_with_mobile_decision_ia():
    assert not hasattr(server, "PAGE")
    assert not hasattr(server, "LEGACY_PAGE")

    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert index.index('id="trust-strip"') < index.index("<nav")
    sticky = index[index.index('id="sticky-shell"'):index.index("</div>") + len("</div>")]
    assert 'id="trust-strip"' in sticky and "<nav" in sticky
    assert [f'data-tab="{tab}"' in index for tab in ("now", "blocked", "inflight", "all")] == [True] * 4
    assert all(label in js for label in ("可開始", "進行中", "被阻擋", "待梳理"))
    assert all(label in js for label in ("total", "fixed", "wont-fix"))
    assert "by_area" not in js
    assert "areaCard" not in js

    compact_css = "".join(css.split())
    assert "html,body{margin:0;max-width:100%;overflow-x:clip" in compact_css
    assert "overflow-x:hidden" not in compact_css
    assert "min-height:44px" in compact_css
    assert "@media(max-width:390px)" in compact_css
    assert ".sticky-shell{position:sticky;top:0" in compact_css
    assert "nav{position:sticky" not in compact_css
    assert "nav{top:" not in compact_css
    assert ".focus(" not in js

    assert all(f'data-action="{action}"' in js for action in ("pin", "rank", "snooze"))
    assert 'data-action="claim"' not in js
    assert 'data-action="resolve"' not in js
    assert 'data.dispatch.filter(row=>!row.snoozed)' in js
    assert "decision.deferred" in js
    assert "可在全部取消" in js


def test_index_injects_process_csrf_and_app_revision_without_bearer(monkeypatch):
    monkeypatch.setattr(server, "CSRF_TOKEN", "ephemeral-csrf")
    monkeypatch.setattr(server, "APP_REVISION", "app-revision")

    rendered = server.render_index().decode("utf-8")

    assert 'content="ephemeral-csrf"' in rendered
    assert 'content="app-revision"' in rendered
    assert "Bearer" not in rendered


def test_asset_routes_serve_index_css_and_javascript(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    monkeypatch.setattr(server, "CSRF_TOKEN", "csrf")
    monkeypatch.setattr(server, "APP_REVISION", "rev")

    for path, content_type, marker in (
        ("/", "text/html; charset=utf-8", b"trust-strip"),
        ("/assets/app.css", "text/css; charset=utf-8", b"min-height"),
        ("/assets/app.js", "text/javascript; charset=utf-8", b"X-KG-CSRF"),
    ):
        handler = _handler(path)
        responses = []
        handler._send = MethodType(
            lambda _self, code, body, ctype: responses.append((code, body, ctype)), handler
        )
        handler.do_GET()
        assert responses[0][0] == 200
        assert responses[0][2] == content_type
        assert marker in responses[0][1]


def test_require_token_mode_is_explicitly_api_only_without_browser_session(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", True)
    monkeypatch.setattr(server, "TOKEN", "read-secret")

    for path in ("/", "/assets/app.css", "/assets/app.js", "/api/board"):
        handler = _handler(path)
        responses = []
        handler._send = MethodType(
            lambda _self, code, body, ctype: responses.append((code, body, ctype)), handler
        )
        handler.do_GET()
        assert responses[0][0] == 401
        assert b"KG_BOARD_REQUIRE_TOKEN=1" in responses[0][1]


def test_priority_uses_same_origin_csrf_while_mirror_keeps_bearer(monkeypatch):
    monkeypatch.setattr(server, "CSRF_TOKEN", "csrf-secret")
    monkeypatch.setattr(server, "TOKEN", "bearer-secret")
    monkeypatch.setattr(server, "ALLOWED_HOSTS", {"board.local"})
    same_origin = {
        "Content-Type": "application/json",
        "Host": "board.local",
        "Origin": "http://board.local",
        "X-KG-CSRF": "csrf-secret",
    }

    assert _handler("/api/priority", same_origin)._priority_precondition() is None
    assert "csrf" in _handler(
        "/api/priority",
        {**same_origin, "X-KG-CSRF": "", "Authorization": "Bearer bearer-secret"},
    )._priority_precondition()
    assert "same-origin" in _handler(
        "/api/priority", {**same_origin, "Origin": "http://evil.example"}
    )._priority_precondition()
    hostile = {**same_origin, "Host": "evil.example", "Origin": "http://evil.example"}
    assert "configured host" in _handler("/api/priority", hostile)._priority_precondition()

    assert "bearer" in _handler("/api/mirror/claims", same_origin)._mirror_precondition()
    assert _handler(
        "/api/mirror/claims",
        {"Content-Type": "application/json", "Authorization": "Bearer bearer-secret"},
    )._mirror_precondition() is None


def test_projection_exposes_decision_counts_and_blocked_rows():
    entries = [
        _ticket("NOW"),
        _ticket("HELD"),
        _ticket("BLOCKED"),
        _ticket("UNGROOMED", groomed=False),
        _ticket("FIXED", status="fixed"),
        _ticket("WONT", status="wont-fix"),
    ]
    payload = server.project(
        entries,
        {},
        {"HELD": {"branch": "feat/held"}},
        canonical_dispatch_ids={"NOW", "HELD"},
        dispatch_meta={"withheld_blocked": [{"id": "BLOCKED", "waiting_on": ["WAIT"]}]},
        canonical_ungroomed_ids={"UNGROOMED"},
    )

    assert [row["id"] for row in payload["dispatch"]] == ["NOW"]
    assert [row["id"] for row in payload["blocked"]] == ["BLOCKED"]
    assert payload["counts"]["decision"] == {
        "now": 1,
        "inflight": 1,
        "blocked": 1,
        "ungroomed": 1,
        "deferred": 0,
    }
    assert payload["counts"]["history"] == {"total": 6, "fixed": 1, "wont_fix": 1}


def test_app_revision_is_part_of_shared_freshness_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "APP_REVISION", "frozen-process-revision")
    monkeypatch.setattr(server, "MIRROR_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(server, "_git", lambda _args: type("P", (), {"returncode": 0, "stdout": "0\n", "stderr": ""})())

    assert server.freshness()["app_revision"] == "frozen-process-revision"


def test_server_source_has_no_embedded_html_application():
    source = inspect.getsource(server)
    assert "<!doctype html>" not in source.lower()


def test_state_updates_are_serialized_without_lost_rows_or_temp_collisions(tmp_path):
    path = tmp_path / "overlay.json"

    def write(index: int):
        def add_row(current):
            updated = dict(current)
            updated[f"T-{index}"] = {"rank": index}
            return updated
        server._update_json(path, {}, add_row)

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(write, index) for index in range(80)]
        for future in futures:
            future.result()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload) == 80
    assert set(payload) == {f"T-{index}" for index in range(80)}
    assert not list(tmp_path.glob(".*.tmp"))
    assert "_update_json(OVERLAY_PATH" in inspect.getsource(server.Handler.do_POST)


def test_web_assets_and_revision_are_bound_to_immutable_release_checkout(monkeypatch):
    release_dir = Path(server.__file__).resolve().parent
    assert server.WEB_DIR == release_dir / "web"
    assert server.RELEASE_DIR == release_dir
    assert "clone_head" not in inspect.getsource(server.main)

    monkeypatch.setattr(server, "read_token", lambda: "token")
    monkeypatch.setattr(server, "CLONE", server.RELEASE_ROOT)
    assert server.main() == 78
