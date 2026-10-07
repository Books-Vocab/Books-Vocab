"""Same-origin request guard for the dashboard (#2097).

Two browser-driven attacks reach a localhost-bound dashboard:
  * DNS rebinding — an attacker hostname re-resolves to 127.0.0.1, so the page
    is *same-origin* with the dashboard and every Origin==Host comparison
    passes. Only a Host allowlist stops it (→ 400 on every request).
  * CSRF — a cross-site form/fetch POST. The browser stamps the real page
    origin in the forbidden `Origin` header (Referer as fallback), so a
    non-GET/HEAD request whose origin differs from the dashboard is 403'd
    before any handler runs (no marker written, no subprocess spawned).

Run:
    uv run --no-project --python 3.13 --with fastapi --with 'uvicorn[standard]' \
        --with python-multipart --with httpx --with pytest \
        python -m pytest lab/podcast/monitor/test_request_guard.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

import server  # noqa: E402

# A browser on the page TestClient serves (http://testserver/) stamps this.
SAME_ORIGIN = "http://testserver"
EVIL = "https://evil.example"
WS = "guard_abcd1234"
SAFE_METHODS = {"GET", "HEAD"}


class _SpawnRecorder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))

        class _Job:
            id = "job-guard"
            status = "running"
            label = "guard"

        return _Job()


@pytest.fixture
def spawn(monkeypatch):
    rec = _SpawnRecorder()
    monkeypatch.setattr(server.jobs, "spawn", rec)
    return rec


@pytest.fixture
def awaiting_ws(tmp_path, monkeypatch, spawn):
    """A workspace parked at the plan gate (plan done, no scripts, no marker),
    so a same-origin approve really writes `.plan_approved` and spawns."""
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [])
    ws = tmp_path / WS
    (ws / "plan" / "episodes").mkdir(parents=True)
    (ws / "plan" / "overview.md").write_text("# overview")
    (ws / "plan" / "episodes" / "ep_01.md").write_text("x")
    return ws


@pytest.fixture
def client():
    return TestClient(server.app)


def _approve(client, **headers):
    return client.post(f"/api/workspace/{WS}/approve?gate=plan", headers=headers)


def _mutating_routes() -> list[tuple[str, str]]:
    """Every (method, concrete path) the app serves that is not GET/HEAD —
    derived from the live route table so a future endpoint is covered too."""
    out: list[tuple[str, str]] = []
    for route in server.app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in sorted(route.methods - SAFE_METHODS):
            out.append((method, path))
    return out


# ─── Host allowlist (DNS rebinding) ─────────────────────────────────────────


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765"])
def test_foreign_host_is_rejected_400(client, awaiting_ws, host):
    resp = client.get("/api/workspaces", headers={"Host": host})
    assert resp.status_code == 400, resp.text


def test_rebinding_shaped_approve_is_rejected_before_any_mutation(
    client, awaiting_ws, spawn
):
    """Rebinding makes Origin == Host (both the attacker name). The Host
    allowlist must reject it — an Origin-vs-Host comparison alone would pass."""
    resp = _approve(client, Host="evil.example:8765", Origin="http://evil.example:8765")
    assert resp.status_code == 400, resp.text
    assert not (awaiting_ws / ".plan_approved").exists()
    assert spawn.calls == []


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:8765",
        "localhost:8765",
        "LOCALHOST:8765",
        "[::1]:8765",
        "localhost:9000",
    ],
)
def test_loopback_hosts_are_accepted(client, awaiting_ws, host):
    resp = client.get("/api/workspaces", headers={"Host": host})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "host", ["127.0.0.1:notaport", "user@127.0.0.1:8765", "127.0.0.1:8765/x"]
)
def test_malformed_host_is_rejected_400(client, awaiting_ws, host):
    resp = client.get("/api/workspaces", headers={"Host": host})
    assert resp.status_code == 400, resp.text


# ─── Origin / Referer check (CSRF) ──────────────────────────────────────────


def test_cross_origin_approve_is_403_with_no_marker_and_no_spawn(
    client, awaiting_ws, spawn
):
    resp = _approve(client, Origin=EVIL)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]  # same {"detail": ...} shape app.js toasts
    assert not (awaiting_ws / ".plan_approved").exists()
    assert spawn.calls == []


def test_same_origin_approve_writes_marker_and_spawns(client, awaiting_ws, spawn):
    resp = _approve(client, Origin=SAME_ORIGIN)
    assert resp.status_code == 200, resp.text
    assert (awaiting_ws / ".plan_approved").exists()
    assert spawn.calls == [["uv", "run", "pipeline.py", str(awaiting_ws)]]


def test_default_loopback_origin_approve_passes(client, awaiting_ws, spawn):
    """The production shape: page served from http://127.0.0.1:8765/."""
    resp = _approve(client, Host="127.0.0.1:8765", Origin="http://127.0.0.1:8765")
    assert resp.status_code == 200, resp.text
    assert spawn.calls


def test_ssh_tunnel_port_approve_passes(client, awaiting_ws, spawn):
    """`ssh -L 9000:127.0.0.1:8765` — browser origin carries the tunnel port."""
    resp = _approve(client, Host="localhost:9000", Origin="http://localhost:9000")
    assert resp.status_code == 200, resp.text


def test_same_origin_referer_fallback_passes(client, awaiting_ws, spawn):
    resp = _approve(client, Referer=f"{SAME_ORIGIN}/?ws={WS}")
    assert resp.status_code == 200, resp.text
    assert spawn.calls


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-origin-no-referer"),
        pytest.param({"Origin": "null"}, id="opaque-null-origin"),
        pytest.param({"Origin": "http://testserver:3000"}, id="cross-port"),
        pytest.param({"Origin": "https://testserver"}, id="cross-scheme"),
        pytest.param(
            {"Referer": "https://evil.example/page"}, id="cross-origin-referer"
        ),
        pytest.param(
            {"Origin": EVIL, "Referer": f"{SAME_ORIGIN}/"},
            id="origin-wins-over-referer",
        ),
        pytest.param(
            {"Host": "127.0.0.1:8765", "Origin": "http://localhost:8765"},
            id="other-loopback-alias",
        ),
        pytest.param(
            {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:3000"},
            id="other-localhost-app",
        ),
    ],
)
def test_non_same_origin_approve_is_403(client, awaiting_ws, spawn, headers):
    resp = _approve(client, **headers)
    assert resp.status_code == 403, resp.text
    assert not (awaiting_ws / ".plan_approved").exists()
    assert spawn.calls == []


def test_mutating_route_table_is_nonempty_and_includes_known_endpoints():
    routes = set(_mutating_routes())
    assert ("POST", "/api/workspace/x/approve") in routes
    assert ("DELETE", "/api/remote/series/x") in routes
    assert ("POST", "/api/pipeline/start") in routes


@pytest.mark.parametrize(("method", "path"), _mutating_routes())
def test_every_mutating_route_rejects_cross_origin(
    client, awaiting_ws, spawn, monkeypatch, method, path
):
    called: list[str] = []
    monkeypatch.setattr(
        server.remote_ops, "delete_remote_series", lambda sid: called.append(sid)
    )
    monkeypatch.setattr(server.jobs, "kill", lambda jid: called.append(jid) or True)
    resp = client.request(method, path, headers={"Origin": EVIL})
    assert resp.status_code == 403, (method, path, resp.text)
    assert called == [] and spawn.calls == []


@pytest.mark.parametrize(("method", "path"), _mutating_routes())
def test_every_mutating_route_admits_same_origin(
    client, awaiting_ws, spawn, monkeypatch, method, path
):
    """Same-origin requests reach the handler (which answers 404/409/422 for
    the dummy params) — the guard never blocks the dashboard's own calls."""
    monkeypatch.setattr(
        server.remote_ops, "delete_remote_series", lambda sid: {"deleted": sid}
    )
    monkeypatch.setattr(server.jobs, "kill", lambda jid: False)
    resp = client.request(method, path, headers={"Origin": SAME_ORIGIN})
    assert resp.status_code not in (400, 403), (method, path, resp.text)


# ─── app.js contract: the browser must keep sending a same-origin Origin ────

STATIC = Path(__file__).parent / "static"


def test_dashboard_js_fetches_stay_same_origin_cors():
    """fetch() in its default `cors` mode always sends the page's real origin on
    POST/DELETE (Fetch spec, "append a request Origin header"). A cross-origin
    absolute URL, a `mode` override (no-cors/same-origin + no-referrer → `Origin:
    null`) or a referrerPolicy change would make the guard 403 the dashboard's
    own buttons, so pin all three out of the static bundle."""
    for name in ("app.js", "player.js"):
        src = (STATIC / name).read_text(encoding="utf-8")
        assert "fetch(" in src
        assert not re.search(r"fetch\(\s*[`'\"](?:https?:)?//", src), name
        assert not re.search(r"\bmode\s*:", src), name
        assert "referrerPolicy" not in src, name
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'name="referrer"' not in html
