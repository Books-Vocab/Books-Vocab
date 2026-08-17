from __future__ import annotations

import gzip
import inspect
import json
import re
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


def _near_real_board_payload(monkeypatch) -> dict:
    entries = []
    for index in range(99):
        row = _ticket(f"IMP-{index:04d}", groomed=index < 80)
        row.update(
            brief=f"Ticket {index} " + "brief " * 12,
            detail=f"Decision context {index} " + "detail " * 90,
            scope="scope " * 60,
            plan="plan " * 120,
            acceptance="acceptance " * 40,
            fix_site=f"ops/component_{index % 8}.py",
            surface="kg-board",
            source="deterministic-fixture",
        )
        entries.append(row)
    dispatch_ids = [row["id"] for row in entries[:60]]
    held = {
        row["id"]: {"branch": f"feat/held-{index}", "claimed_at": "now"}
        for index, row in enumerate(entries[:5])
    }
    blocked = [
        {"id": row["id"], "waiting_on": ["DEPENDENCY"]}
        for row in entries[60:80]
    ]
    monkeypatch.setattr(
        server,
        "read_entries",
        lambda: {
            "entries": entries,
            "dispatch_ids": dispatch_ids,
            "dispatch_meta": {
                "clauses": ["groomed", "unresolved", "unclaimed", "unblocked"],
                "withheld_blocked": blocked,
            },
            "local_held": held,
            "ungroomed_ids": [row["id"] for row in entries[80:]],
        },
    )
    monkeypatch.setattr(server, "mirror_held_claims", lambda: {})
    monkeypatch.setattr(server, "freshness", lambda: {"freshness_state": "current"})
    return server.board_payload()


def test_board_payload_v3_is_single_compact_row_set_with_id_partitions(monkeypatch):
    payload = _near_real_board_payload(monkeypatch)

    assert payload["schema"] == "kg.board.v3"
    assert all(name not in payload for name in ("dispatch", "blocked", "deferred"))
    assert len(payload["board"]) == 99
    assert all(
        set(row) == {
            "id", "brief", "detail", "severity", "stream", "held", "ready",
        }
        for row in payload["board"]
    )
    assert set(payload["dispatch_ids"]) == {f"IMP-{index:04d}" for index in range(5, 60)}
    assert set(payload["blocked_ids"]) == {f"IMP-{index:04d}" for index in range(60, 80)}
    assert set(payload["dispatch_ids"]).isdisjoint(payload["blocked_ids"])
    assert sum(payload["segments"].values()) == payload["counts"]["unresolved"] == 99


def test_board_payload_v3_stays_within_raw_and_gzip_budgets(monkeypatch):
    payload = _near_real_board_payload(monkeypatch)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)

    assert len(raw) < 120 * 1024
    assert len(compressed) < 60 * 1024


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


def test_index_is_never_compressed(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    original = server.render_index()
    assert len(original) >= server.GZIP_MIN_BYTES
    handler = _capturing_handler("/", {"Accept-Encoding": "gzip"})

    handler.do_GET()

    headers = _response_headers(handler)
    assert handler.response_code == 200
    assert handler.wfile.getvalue() == original
    assert "Content-Encoding" not in headers
    assert "Vary" not in headers
    assert int(headers["Content-Length"]) == len(original)


def test_active_page_is_admin_readonly_tree_and_collapsed_card_ia():
    assert not hasattr(server, "PAGE")
    assert not hasattr(server, "LEGACY_PAGE")

    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'class="admin-nav"' in index
    assert 'id="scope-matrix-wrap"' in index
    assert '檔案佔用矩陣' in index
    assert 'id="git-tree"' in index and 'id="commit-inspector"' in index
    assert '<details>' not in index  # cards are data-driven and collapsed by default
    assert '<title>交付進度看板 · 唯讀觀測</title>' in index
    assert '<a class="brand" href="/">交付進度看板</a>' in index
    assert '票面、工作樹與資料新鮮度' in index
    assert [f'data-tab="{tab}"' in index for tab in ("now", "blocked", "inflight", "ungroomed", "all", "history")] == [True] * 6
    assert all(label in index for label in ("現在", "進行中", "阻塞", "未梳理"))
    assert "歷史完成" in index
    assert "<details data-ticket-details" in js and "loadHistory" in js
    assert "commitInspector" in js

    compact_css = "".join(css.split())
    assert "html,body{margin:0;max-width:100%;overflow-x:hidden" in compact_css
    assert ".admin-nav{position:sticky;top:0" in compact_css
    assert ".tickets{display:grid;grid-template-columns:repeat(2" in compact_css
    assert "@media(max-width:860px)" in compact_css
    assert "@media(max-width:520px)" in compact_css

    assert all(f'data-action="{action}"' not in js for action in ("pin", "rank", "snooze"))
    assert 'data-action="claim"' not in js
    assert 'data-action="resolve"' not in js
    assert all(name in js for name in ("board.dispatch_ids", "board.blocked_ids"))
    assert re.search(r"data\.(?:dispatch|blocked|deferred)(?!_)", js) is None
    assert "/api/git-tree" in js
    assert "/api/scope-matrix" in js
    assert "scope_status" in js and "scope-cell-collision" in js
    assert "/api/ticket/" in js


def test_board_trust_detail_does_not_append_seconds_to_unknown_age():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'const treeLabels={current:"已追平",stale:"有落差",error:"錯誤",unknown:"未知"};' in js
    assert "tree ${treeStateLabel}" in js
    assert 'const treeAgeLabel=freshness.git_tree_age==null?"未知":`${freshness.git_tree_age}s`;' in js
    assert "mirror ${treeAgeLabel}" in js


def test_index_injects_app_revision_without_browser_write_token(monkeypatch):
    monkeypatch.setattr(server, "APP_REVISION", "app-revision")

    rendered = server.render_index().decode("utf-8")

    assert 'content="app-revision"' in rendered
    assert "Bearer" not in rendered
    assert "kg-csrf" not in rendered


def test_git_tree_browser_uses_bounded_branch_viewport_without_recursive_stack():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "TREE_VIEW_RADIUS = 10" in js
    assert "firstBranchPoint" in js
    assert "treeViewport" in js
    assert "branchAnchors" in js
    assert "ticketRefs" in js
    assert "ticketRefs.forEach" in js
    assert "branchLanes" in js
    assert "branchLanes.set(ref.branch,index+1)" in js
    assert "mainlineWindow" in js
    assert "treeLayout" in js
    assert "compactLabel" in js
    assert 'ref.live_state!=="unknown"' in js
    assert "第一個分支附近" in js
    assert "Maximum call stack" not in js
    assert "treeZoom" in js
    assert "renderTreeZoom" in js
    assert "renderedWidth" in js
    assert 'data-zoom="${treeZoom}"' in js


def test_git_tree_browser_separates_branch_labels_and_uses_ranked_orthogonal_layout():
    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="tree-legend"' in index
    assert index.index('id="git-tree"') < index.index('id="tree-legend"')
    assert "圖面下方" in index
    assert "renderTreeLegend" in js
    assert "tree-index-label" in js
    assert "treeLayout" in js
    assert "edgePath" in js
    assert "reachableCommitSet" in js
    assert "mainReachableSet" in js
    assert "TREE_ROW_HEIGHT" in js
    assert "lane-header" in js
    assert "foreignObject" not in js
    assert "branchTruncations" in js
    assert "branchDetached" in js
    assert "edge-truncated" in js
    assert "lane-dot" in js
    assert "compactBranchLabel" in js
    assert ".tree-legend" in css
    assert ".git-tree:focus-visible" in css
    assert ".commitcircle{r:14px}" not in "".join(css.split())


def test_git_tree_browser_marks_parents_outside_the_bounded_viewport():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "parent-missing" in js
    assert "tree-parent-endpoint" in js
    assert "此 commit 的 parent 在目前圖面外" in js
    assert "parentSha" in js


def test_git_tree_hover_details_explain_boundaries_and_preserve_unknown_diff_stats():
    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="tree-hover-card"' in index
    assert "圖面邊界" in index
    assert "showTreeHover" in js
    assert "hideTreeHover" in js
    assert "data-boundary-detail" in js
    assert "data-branch" in js
    assert "tree-mobile-branch-name" in js
    assert "stateOverride" in js
    assert 'node.addEventListener("click",show)' in js
    assert "formatDiffStat" in js
    assert "Number.isInteger(row?.insertions)" in js
    assert "row.insertions??0" not in js
    assert "row.deletions??0" not in js
    assert ".tree-hover-card" in css
    assert ".tree-boundary-note" in css


def test_git_tree_browser_has_fit_and_reset_controls_without_overriding_manual_zoom():
    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="tree-fit"' in index
    assert 'id="tree-reset"' in index
    assert "fitTreeZoom" in js
    assert "treeFitInitialized" in js
    assert "cancelTreeAutoFit" in js
    assert ".tree-control-button" in css


def test_git_tree_browser_preserves_manual_zoom_through_empty_refreshes():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")
    empty_branch = js[js.index('if(!tree||!tree.commits?.length)'):js.index('const commits=new Map', js.index('if(!tree||!tree.commits?.length)'))]

    assert "treeFitInitialized=false" not in empty_branch
    assert "if(!treeFitInitialized&&treeBaseWidth)treeFitInitialized=fitTreeZoom()" in js


def test_git_tree_browser_keeps_lane_density_readable_at_fit_scale():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "const TREE_LANE_WIDTH = 124" in js
    assert "const TREE_ROW_HEIGHT = 44" in js
    assert "const TREE_PADDING_X = 30" in js


def test_git_tree_browser_routes_cross_lane_edges_without_shared_horizontal_buses():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "routeCrossLaneEdge" in js
    assert "routeIndex" in js
    assert "H ${x(to.lane)}" not in js
    assert "C ${" in js
    assert "const crossLaneEdges=graphEdges.filter" in js
    assert "const routeRailGroups=new Map" in js
    assert "const routeRailByEdge=new Map" in js
    assert "routeRailByEdge.get(edge)" in js
    assert "const railY=(startY+endY)/2" in js
    assert "const control1Y=railY" in js
    assert "const control2Y=railY" in js
    assert "routeGroups" not in js


def test_git_tree_browser_exposes_adjustable_worktree_lane_spacing():
    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")

    assert 'id="tree-lane-spacing"' in index
    assert 'id="tree-lane-spacing-value"' in index
    assert "TREE_LANE_WIDTH_MIN" in js
    assert "TREE_LANE_WIDTH_MAX" in js
    assert "let treeLaneWidth = TREE_LANE_WIDTH" in js
    assert "tree-lane-spacing" in js
    assert "const laneSpacingInput=document.getElementById(\"tree-lane-spacing\")" in js
    assert "if(laneSpacingInput)" in js
    assert '@media(max-width:1100px)and(min-width:861px)' in "".join(css.split())
    assert 'grid-template-areas:"zoom-label zoom-input zoom-output"' in css


def test_git_tree_browser_exposes_full_worktree_and_commit_hover_details():
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert '<title>${esc(ref.branch)} · ${esc(stateLabel)}</title>' in js
    assert '<title>${esc(shortSha(row.sha)+" · "+row.subject)}</title>' in js


def test_ticket_summary_keeps_id_and_brief_in_separate_flex_slots():
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")

    compact_css = "".join(css.split())
    assert ".ticket-title{display:flex" in compact_css
    assert "flex:1 1 auto" in css
    assert ".ticket-titlecode{flex:00auto" in compact_css
    assert ".ticket-title>span{min-width:0" in compact_css


def test_board_mobile_surface_has_a_compact_tree_and_touch_safe_ia():
    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "交付進度看板" in index
    assert "分支與工作樹" in index
    assert "主線與工作分支依 commit 關係排列" in index
    assert "樹圖縮放" in index
    assert 'id="tree-zoom"' in index
    assert 'id="tree-zoom-value"' in index
    assert "tree-mobile-list" in js
    assert "renderMobileTree" in js
    assert "tree-held-tickets" in index
    assert "renderHeldTickets" in js
    assert "heldTicketGroups" in js
    assert "目前認領中的票據" in js
    assert "看板資料讀取錯誤" in js
    assert "min-height:44px" in "".join(css.split())
    assert ".section-heading{flex-direction:column" in "".join(css.split())
    assert ".metric:last-child{grid-column:1/-1}" in "".join(css.split())
    assert "-webkit-line-clamp:2" in "".join(css.split())
    assert "--sub:#637181" in "".join(css.split())
    assert ".tree-controls{display:none}" in "".join(css.split())
    assert ".tree-legend.tree-ticket{min-height:44px;min-width:44px}" in "".join(css.split())
    assert ".tree-control-button{min-height:44px}" in "".join(css.split())
    assert re.search(r"@media\(max-width:860px\)\{[^}]*\.git-tree\{display:block", css)
    assert ".tree-mobile-list{display:block;border:1pxsolidvar(--border-light);background:var(--surface-alt);padding:10px}" in "".join(css.split())
    assert ".tree-mobile-list.tree-ticket,.tree-legend.tree-ticket{min-height:44px;min-width:44px}" in "".join(css.split())
    assert "viewport.branchPaths.values()" in js
    assert "refs.map(ref=>ref.head)" in js
    assert 'stateLabel=detached?"未連接":treeStateOf(ref)' in js
    assert ".searchinput{width:100%;min-height:44px" in "".join(css.split())


def test_git_tree_mobile_has_edge_to_edge_viewer_with_free_pan_and_zoom():
    index = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (server.WEB_DIR / "app.css").read_text(encoding="utf-8")
    js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")
    compact_css = "".join(css.split())

    assert 'id="tree-fullscreen"' in index
    assert 'id="tree-fullscreen-viewer"' in index
    assert 'id="tree-fullscreen-canvas"' in index
    assert 'id="tree-fullscreen-close"' in index
    assert 'id="tree-fullscreen-fit"' in index
    assert 'id="tree-fullscreen-reset"' in index
    assert "openTreeFullscreen" in js
    assert "closeTreeFullscreen" in js
    assert "requestFullscreen" in js
    assert "treeFullscreen" in js
    assert 'addEventListener("pointerdown"' in js
    assert 'addEventListener("pointermove"' in js
    assert 'addEventListener("wheel"' in js
    assert "tree-fullscreen-open" in compact_css
    assert "touch-action:none" in compact_css
    assert ".tree-fullscreen-viewer{position:fixed" in compact_css


def test_asset_routes_serve_index_css_and_javascript(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    monkeypatch.setattr(server, "APP_REVISION", "rev")

    for path, content_type, marker in (
        ("/", "text/html; charset=utf-8", b"admin-nav"),
        ("/assets/app.css", "text/css; charset=utf-8", b"min-height"),
        ("/assets/app.js", "text/javascript; charset=utf-8", b"/api/git-tree"),
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


def test_git_tree_read_route_returns_versioned_projection(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    monkeypatch.setattr(server, "git_tree_payload", lambda: {
        "schema": "kg.board.git-tree.v1", "refs": [], "commits": [],
    })
    handler = _capturing_handler("/api/git-tree")

    handler.do_GET()

    assert handler.response_code == 200
    assert json.loads(handler.wfile.getvalue())["schema"] == "kg.board.git-tree.v1"


def test_scope_matrix_read_route_returns_versioned_projection(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    monkeypatch.setattr(server, "scope_matrix_payload", lambda: {
        "schema": "kg.board.scope-matrix.v1", "tickets": [], "files": [],
    })
    handler = _capturing_handler("/api/scope-matrix")

    handler.do_GET()

    assert handler.response_code == 200
    assert json.loads(handler.wfile.getvalue())["schema"] == "kg.board.scope-matrix.v1"


def test_ticket_read_route_returns_full_detail_projection(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    row = _ticket("IMP-1")
    row.update(scope="small", plan="do it", fix_site="ops/x.py", acceptance="green")
    monkeypatch.setattr(server, "read_entries", lambda: {
        "entries": [row], "dispatch_ids": ["IMP-1"], "ungroomed_ids": [],
        "local_held": {}, "dispatch_meta": {},
    })
    monkeypatch.setattr(server, "mirror_held_claims", lambda: {})
    handler = _capturing_handler("/api/ticket/IMP-1")

    handler.do_GET()

    payload = json.loads(handler.wfile.getvalue())
    assert payload["schema"] == "kg.board.ticket.v1"
    assert payload["ticket"]["scope"] == "small"
    assert payload["ticket"]["acceptance"] == "green"


def test_history_read_route_returns_only_resolved_rows(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", False)
    monkeypatch.setattr(server, "read_entries", lambda: {
        "entries": [_ticket("OPEN"), _ticket("FIXED", status="fixed"), _ticket("WONT", status="wont-fix")],
    })
    monkeypatch.setattr(server, "freshness", lambda: {"freshness_state": "current"})
    handler = _capturing_handler("/api/history")

    handler.do_GET()

    payload = json.loads(handler.wfile.getvalue())
    assert payload["schema"] == "kg.board.history.v1"
    assert [row["id"] for row in payload["board"]] == ["WONT", "FIXED"]
    assert payload["count"] == 2


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


def test_browser_writes_are_removed_while_mirror_keeps_bearer(monkeypatch):
    monkeypatch.setattr(server, "TOKEN", "bearer-secret")
    assert not hasattr(server.Handler, "_priority_precondition")
    priority = _capturing_handler("/api/priority")
    priority.do_POST()
    assert priority.response_code == 404

    assert "bearer" in _handler(
        "/api/mirror/claims", {"Content-Type": "application/json"}
    )._mirror_precondition()
    assert _handler(
        "/api/mirror/claims",
        {"Content-Type": "application/json", "Authorization": "Bearer bearer-secret"},
    )._mirror_precondition() is None


def test_mirror_git_tree_accepts_large_snapshot_without_widening_browser_writes(monkeypatch):
    payload = {"commits": [{"id": "c" * 64, "message": "m" * 256} for _ in range(9000)]}
    raw = json.dumps(payload).encode("utf-8")
    assert 1_000_000 < len(raw) < 16 * 1024 * 1024

    monkeypatch.setattr(server, "TOKEN", "mirror-secret")
    monkeypatch.setattr(server, "_update_json", lambda *args: None)
    mirror = _capturing_handler(
        "/api/mirror/git-tree",
        {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
            "Authorization": "Bearer mirror-secret",
        },
    )
    mirror.rfile = BytesIO(raw)
    mirror.do_POST()
    assert mirror.response_code == 200
    assert json.loads(mirror.wfile.getvalue())["stored"] == "git_tree"

    browser_write = _handler(
        "/api/priority",
        {"Content-Length": str(len(raw))},
    )
    browser_write.rfile = BytesIO(raw)
    with pytest.raises(ValueError, match="oversized"):
        browser_write._body()


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
    path = tmp_path / "mirror.json"

    def write(index: int):
        def add_row(current):
            updated = dict(current)
            updated[f"T-{index}"] = {"at": index}
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
    assert "/api/priority" not in inspect.getsource(server.Handler.do_POST)


def test_web_assets_and_revision_are_bound_to_immutable_release_checkout(monkeypatch):
    release_dir = Path(server.__file__).resolve().parent
    assert server.WEB_DIR == release_dir / "web"
    assert server.RELEASE_DIR == release_dir
    assert "clone_head" not in inspect.getsource(server.main)

    monkeypatch.setattr(server, "read_token", lambda: "token")
    monkeypatch.setattr(server, "CLONE", server.RELEASE_ROOT)
    assert server.main() == 78
