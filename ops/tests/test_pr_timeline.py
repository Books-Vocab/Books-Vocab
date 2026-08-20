from __future__ import annotations

import json
import plistlib
import sys
import threading
from pathlib import Path
from typing import Self
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "pr_timeline"))

from server import (
    CacheStore,
    GitHubClient,
    TimelineHTTPServer,
    TimelineState,
    merge_pull_requests,
    normalize_pull_request,
)


def _api_pr(number: int, merged_at: str | None, *, title: str = "PR") -> dict:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/Books-Vocab/Books-Vocab/pull/{number}",
        "state": "closed",
        "merged_at": merged_at,
        "created_at": "2026-08-01T10:00:00Z",
        "updated_at": merged_at or "2026-08-01T10:00:00Z",
        "user": {"login": "MaxChen228"},
        "base": {"ref": "main"},
        "head": {"ref": f"feat/pr-{number}"},
        "draft": False,
        "merge_commit_sha": f"sha-{number}",
    }


def test_normalize_pull_request_uses_merge_time_and_identity() -> None:
    record = normalize_pull_request(_api_pr(12, "2026-08-20T03:04:05Z", title="Ship it"))

    assert record == {
        "number": 12,
        "title": "Ship it",
        "url": "https://github.com/Books-Vocab/Books-Vocab/pull/12",
        "state": "merged",
        "merged_at": "2026-08-20T03:04:05Z",
        "created_at": "2026-08-01T10:00:00Z",
        "updated_at": "2026-08-20T03:04:05Z",
        "author": "MaxChen228",
        "base_ref": "main",
        "head_ref": "feat/pr-12",
        "draft": False,
        "merge_commit_sha": "sha-12",
    }


def test_normalize_pull_request_ignores_unmerged_pull_requests() -> None:
    assert normalize_pull_request(_api_pr(13, None)) is None


def test_merge_pull_requests_deduplicates_and_orders_by_merge_time() -> None:
    old = normalize_pull_request(_api_pr(1, "2026-08-19T03:00:00Z", title="old"))
    newer = normalize_pull_request(_api_pr(2, "2026-08-20T03:00:00Z"))
    replacement = normalize_pull_request(_api_pr(1, "2026-08-19T03:00:00Z", title="edited"))

    assert old is not None and newer is not None and replacement is not None
    merged = merge_pull_requests([old, newer], [replacement])

    assert [item["number"] for item in merged] == [1, 2]
    assert merged[0]["title"] == "edited"


def test_cache_store_round_trips_json(tmp_path: Path) -> None:
    path = tmp_path / "state" / "prs.json"
    store = CacheStore(path)
    records = [normalize_pull_request(_api_pr(21, "2026-08-20T04:00:00Z"))]
    assert records[0] is not None

    store.save(records, repo="Books-Vocab/Books-Vocab")

    payload = json.loads(path.read_text())
    assert payload["schema"] == "kg.pr-timeline.cache.v1"
    assert store.load(repo="Books-Vocab/Books-Vocab") == records


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_github_client_sends_bearer_token_and_normalizes_page() -> None:
    captured: dict[str, object] = {}

    def opener(request, timeout: float):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _FakeResponse([_api_pr(31, "2026-08-20T05:00:00Z")])

    client = GitHubClient(
        repo="Books-Vocab/Books-Vocab",
        token="secret-token",
        opener=opener,
    )

    result = client.fetch_page(1)

    assert captured == {
        "url": "https://api.github.com/repos/Books-Vocab/Books-Vocab/pulls?state=closed&sort=updated&direction=desc&per_page=100&page=1",
        "authorization": "Bearer secret-token",
        "timeout": 15.0,
    }
    assert result[0]["number"] == 31


def test_timeline_state_keeps_cached_records_when_refresh_fails(tmp_path: Path) -> None:
    cached = normalize_pull_request(_api_pr(41, "2026-08-20T06:00:00Z"))
    fresh = normalize_pull_request(_api_pr(42, "2026-08-20T07:00:00Z"))
    assert cached is not None and fresh is not None

    class _Client:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_pages(self, *, start_page: int, page_count: int) -> list[dict]:
            self.calls += 1
            if self.calls == 1:
                return [fresh]
            raise RuntimeError("GitHub unavailable")

    state = TimelineState(
        client=_Client(),
        cache=CacheStore(tmp_path / "prs.json"),
        repo="Books-Vocab/Books-Vocab",
        initial_records=[cached],
    )

    state.refresh(page_count=2)
    assert [item["number"] for item in state.snapshot()["prs"]] == [41, 42]

    state.refresh(page_count=2)
    snapshot = state.snapshot()
    assert [item["number"] for item in snapshot["prs"]] == [41, 42]
    assert snapshot["stale"] is True
    assert snapshot["error"] == "GitHub unavailable"


def test_http_server_serves_timeline_assets_and_snapshot(tmp_path: Path) -> None:
    record = normalize_pull_request(_api_pr(51, "2026-08-20T08:00:00Z", title="Timeline"))
    assert record is not None
    cache = CacheStore(tmp_path / "prs.json")
    cache.save([record], repo="Books-Vocab/Books-Vocab")
    state = TimelineState(
        client=GitHubClient(repo="Books-Vocab/Books-Vocab"),
        cache=cache,
        repo="Books-Vocab/Books-Vocab",
    )
    httpd = TimelineHTTPServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with urlopen(f"{base_url}/", timeout=2) as response:
            index = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert "id=\"timeline\"" in index

        with urlopen(f"{base_url}/styles.css", timeout=2) as response:
            assert response.status == 200
            assert b"--timeline-height" in response.read()

        with urlopen(f"{base_url}/app.js", timeout=2) as response:
            assert response.status == 200
            assert b"/api/prs" in response.read()

        with urlopen(f"{base_url}/api/prs", timeout=2) as response:
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["prs"][0]["number"] == 51
            assert payload["stale"] is True

        with urlopen(f"{base_url}/healthz", timeout=2) as response:
            health = json.loads(response.read())
            assert response.status == 200
            assert health["ok"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_http_server_has_private_security_headers_and_not_found() -> None:
    state = TimelineState(
        client=GitHubClient(repo="Books-Vocab/Books-Vocab"),
        cache=CacheStore(Path("/tmp/kg-pr-timeline-test-do-not-use")),
        repo="Books-Vocab/Books-Vocab",
    )
    httpd = TimelineHTTPServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with urlopen(Request(f"{base_url}/", method="HEAD"), timeout=2) as response:
            assert response.status == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Content-Security-Policy"] == (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
            assert response.headers["Cache-Control"] == "no-cache"

        try:
            urlopen(f"{base_url}/not-found", timeout=2)
        except Exception as exc:  # noqa: BLE001 - urllib wraps HTTP 404.
            assert getattr(exc, "code", None) == 404
        else:
            raise AssertionError("unknown path unexpectedly returned 200")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_frontend_exposes_zoomable_timeline_and_refresh_controls() -> None:
    asset_root = Path(__file__).parents[1] / "pr_timeline"
    index = (asset_root / "index.html").read_text(encoding="utf-8")
    script = (asset_root / "app.js").read_text(encoding="utf-8")
    styles = (asset_root / "styles.css").read_text(encoding="utf-8")

    assert 'id="timeline"' in index
    assert 'id="zoom"' in index
    assert 'id="zoom-value"' in index
    assert 'id="refresh"' in index
    assert 'id="range"' in index
    assert 'id="timeline-rule"' in index
    assert 'id="timeline-tooltip"' in index
    assert 'min="0.25"' in index
    assert 'max="48"' in index
    assert 'value="4"' in index
    assert 'fetch("/api/prs"' in script
    assert "addEventListener(\"input\"" in script
    assert "typeof value === \"number\"" in script
    assert 'window.addEventListener("resize"' in script
    assert ".timeline-rule" in styles
    assert "top: var(--line-y)" in styles
    assert ".pr-marker" in styles
    assert "lane" not in script


def test_frontend_uses_one_physical_line_without_inline_marker_labels() -> None:
    asset_root = Path(__file__).parents[1] / "pr_timeline"
    index = (asset_root / "index.html").read_text(encoding="utf-8")
    script = (asset_root / "app.js").read_text(encoding="utf-8")

    assert "timeline-card" not in index
    assert "section-heading" not in index
    assert "marker.title" in script
    assert "marker.setAttribute(\"aria-label\"" in script
    assert "marker.textContent" not in script


def test_launchd_manifest_is_tailnet_bound_and_restartable() -> None:
    manifest = Path(__file__).parents[1] / "launchd" / "com.kg.pr-timeline.plist"
    payload = plistlib.loads(manifest.read_bytes())

    assert payload["Label"] == "com.kg.pr-timeline"
    assert "--host" in payload["ProgramArguments"]
    assert payload["ProgramArguments"][payload["ProgramArguments"].index("--host") + 1] == "100.118.39.104"
    assert payload["EnvironmentVariables"]["PR_TIMELINE_HOST"] == "100.118.39.104"
    assert payload["EnvironmentVariables"]["PR_TIMELINE_PORT"] == "8008"
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True
