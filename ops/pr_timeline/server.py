#!/usr/bin/env -S uv run --no-project --python 3.13 python
"""Small, private PR merge timeline service for the Felix tailnet host."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("kg.pr_timeline")
ASSET_ROOT = Path(__file__).resolve().parent
API_ROOT = "https://api.github.com"
API_PAGE_SIZE = 100
CACHE_SCHEMA = "kg.pr-timeline.cache.v1"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_timestamp(value: str | None) -> str | None:
    parsed = timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def normalize_pull_request(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one GitHub REST pull request into the page's small data shape."""

    merged_at = canonical_timestamp(payload.get("merged_at"))
    if merged_at is None:
        return None

    number = payload.get("number")
    if isinstance(number, bool):
        return None
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None

    user = payload.get("user")
    base = payload.get("base")
    head = payload.get("head")
    return {
        "number": number,
        "title": _text(payload.get("title"), "Untitled PR"),
        "url": _text(payload.get("html_url")),
        "state": "merged",
        "merged_at": merged_at,
        "created_at": canonical_timestamp(payload.get("created_at")),
        "updated_at": canonical_timestamp(payload.get("updated_at")),
        "author": _text(user.get("login") if isinstance(user, dict) else None, "unknown"),
        "base_ref": _text(base.get("ref") if isinstance(base, dict) else None),
        "head_ref": _text(head.get("ref") if isinstance(head, dict) else None),
        "draft": bool(payload.get("draft", False)),
        "merge_commit_sha": _text(payload.get("merge_commit_sha")) or None,
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[datetime, int]:
    merged_at = timestamp(record.get("merged_at")) or datetime.min.replace(tzinfo=timezone.utc)
    number = record.get("number")
    try:
        number = int(number)
    except (TypeError, ValueError):
        number = 0
    return merged_at, number


def merge_pull_requests(
    existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge by PR number, letting the newest API observation win."""

    records: dict[int, dict[str, Any]] = {}
    for record in (*list(existing), *list(incoming)):
        try:
            number = int(record.get("number"))
        except (AttributeError, TypeError, ValueError):
            continue
        if number <= 0 or timestamp(record.get("merged_at")) is None:
            continue
        records[number] = dict(record)
    return sorted(records.values(), key=_record_sort_key)


class CacheStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, *, repo: str) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != CACHE_SCHEMA or payload.get("repo") != repo:
                return []
            records = payload.get("prs")
            if not isinstance(records, list):
                return []
            return merge_pull_requests(records, [])
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("cannot read PR cache %s: %s", self.path, exc)
            return []

    def save(self, records: Iterable[dict[str, Any]], *, repo: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": CACHE_SCHEMA,
            "repo": repo,
            "updated_at": utc_now().isoformat(timespec="seconds").replace("+00:00", "Z"),
            "prs": merge_pull_requests(records, []),
        }
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


Opener = Callable[..., Any]


class GitHubClient:
    def __init__(
        self,
        *,
        repo: str,
        token: str | None = None,
        opener: Opener = urlopen,
        timeout: float = 15.0,
        api_root: str = API_ROOT,
    ) -> None:
        self.repo = repo
        self.token = token
        self.opener = opener
        self.timeout = timeout
        self.api_root = api_root.rstrip("/")

    def _fetch_page_payload(self, page: int) -> tuple[list[dict[str, Any]], int]:
        query = urlencode(
            {
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": API_PAGE_SIZE,
                "page": page,
            }
        )
        url = f"{self.api_root}/repos/{self.repo}/pulls?{query}"
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "kg-pr-timeline",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("message", "")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"GitHub API HTTP {exc.code}{suffix}") from exc
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GitHub request failed: {exc}") from exc
        if not isinstance(raw, list):
            raise TypeError("GitHub API returned a non-list PR payload")
        return [item for item in raw if isinstance(item, dict)], len(raw)

    def fetch_page(self, page: int) -> list[dict[str, Any]]:
        payload, _raw_count = self._fetch_page_payload(page)
        return [record for item in payload if (record := normalize_pull_request(item)) is not None]

    def fetch_pages(self, *, start_page: int, page_count: int) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for page in range(start_page, start_page + max(1, page_count)):
            payload, raw_count = self._fetch_page_payload(page)
            records.extend(
                record for item in payload if (record := normalize_pull_request(item)) is not None
            )
            if raw_count < API_PAGE_SIZE:
                break
        return records


def resolve_github_token() -> str | None:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(name, "").strip()
        if token:
            return token

    gh_bin = os.environ.get("GH_BIN") or shutil.which("gh")
    if not gh_bin:
        for candidate in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh"):
            if Path(candidate).is_file():
                gh_bin = candidate
                break
    if not gh_bin:
        return None
    try:
        result = subprocess.run(
            [gh_bin, "auth", "token", "--hostname", "github.com"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.warning("cannot read gh auth token: %s", exc)
        return None
    token = result.stdout.strip()
    return token or None


class TimelineState:
    def __init__(
        self,
        *,
        client: GitHubClient,
        cache: CacheStore,
        repo: str,
        initial_records: Iterable[dict[str, Any]] | None = None,
        refresh_seconds: int = 60,
        source_sha: str | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.repo = repo
        self.refresh_seconds = max(10, refresh_seconds)
        self.source_sha = source_sha or "unknown"
        self._lock = threading.RLock()
        cached = cache.load(repo=repo)
        self._records = merge_pull_requests(cached, initial_records or [])
        self._last_sync_at: str | None = None
        self._last_success_at: str | None = None
        self._error: str | None = None
        self._source = "cache" if cached else "none"
        self._stale = bool(cached)

    def refresh(self, *, page_count: int, start_page: int = 1) -> None:
        try:
            fetched = self.client.fetch_pages(start_page=start_page, page_count=page_count)
            synced_at = utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")
            with self._lock:
                self._records = merge_pull_requests(self._records, fetched)
                self._last_sync_at = synced_at
                self._last_success_at = synced_at
                self._error = None
                self._source = "github"
                self._stale = False
                records = list(self._records)
            self.cache.save(records, repo=self.repo)
        except Exception as exc:  # noqa: BLE001 - keep the stale page available on network errors.
            with self._lock:
                self._error = str(exc)
                self._stale = True
            LOGGER.warning("PR refresh failed: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)
            return {
                "schema": "kg.pr-timeline.snapshot.v1",
                "repo": self.repo,
                "prs": records,
                "count": len(records),
                "last_sync_at": self._last_sync_at,
                "last_success_at": self._last_success_at,
                "source": self._source,
                "stale": self._stale,
                "error": self._error,
                "refresh_seconds": self.refresh_seconds,
                "source_sha": self.source_sha,
                "timezone": "browser-local",
            }

    def run_forever(self, *, initial_pages: int, refresh_pages: int, stop: threading.Event) -> None:
        self.refresh(page_count=initial_pages)
        while not stop.wait(self.refresh_seconds):
            self.refresh(page_count=refresh_pages)


class TimelineRequestHandler(BaseHTTPRequestHandler):
    server: TimelineHTTPServer

    def _send(self, status: int, body: bytes, content_type: str, *, cache_control: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _asset(self, name: str, content_type: str) -> None:
        path = ASSET_ROOT / name
        try:
            body = path.read_bytes()
        except OSError:
            self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")
            return
        self._send(HTTPStatus.OK, body, content_type, cache_control="no-cache")

    def _handle(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._asset("index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._asset("app.js", "text/javascript; charset=utf-8")
        elif path == "/styles.css":
            self._asset("styles.css", "text/css; charset=utf-8")
        elif path == "/api/prs":
            self._json(HTTPStatus.OK, self.server.timeline_state.snapshot())
        elif path == "/healthz":
            snapshot = self.server.timeline_state.snapshot()
            healthy = snapshot["last_success_at"] is not None or snapshot["source"] == "cache"
            self._json(HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE, {"ok": healthy, **snapshot})
        else:
            self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)


class TimelineHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], timeline_state: TimelineState) -> None:
        self.timeline_state = timeline_state
        super().__init__(address, TimelineRequestHandler)


def _default_cache_path() -> Path:
    configured = os.environ.get("PR_TIMELINE_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "kg-pr-timeline" / "prs.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a private GitHub PR merge timeline.")
    parser.add_argument("--host", default=os.environ.get("PR_TIMELINE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PR_TIMELINE_PORT", "8008")))
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", "Books-Vocab/Books-Vocab"),
        help="GitHub repository in OWNER/REPO form",
    )
    parser.add_argument("--cache", type=Path, default=_default_cache_path())
    parser.add_argument(
        "--refresh",
        type=int,
        default=int(os.environ.get("PR_TIMELINE_REFRESH_SECONDS", "60")),
    )
    parser.add_argument(
        "--initial-pages",
        type=int,
        default=int(os.environ.get("PR_TIMELINE_INITIAL_PAGES", "50")),
    )
    parser.add_argument(
        "--refresh-pages",
        type=int,
        default=int(os.environ.get("PR_TIMELINE_REFRESH_PAGES", "2")),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=os.environ.get("PR_TIMELINE_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    client = GitHubClient(repo=args.repo, token=resolve_github_token())
    state = TimelineState(
        client=client,
        cache=CacheStore(args.cache.expanduser()),
        repo=args.repo,
        refresh_seconds=args.refresh,
        source_sha=os.environ.get("PR_TIMELINE_SOURCE_SHA"),
    )
    stop = threading.Event()
    refresh_thread = threading.Thread(
        target=state.run_forever,
        kwargs={"initial_pages": args.initial_pages, "refresh_pages": args.refresh_pages, "stop": stop},
        name="pr-timeline-refresh",
        daemon=True,
    )
    refresh_thread.start()

    server = TimelineHTTPServer((args.host, args.port), state)
    LOGGER.info("serving PR timeline for %s on http://%s:%d", args.repo, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("stopping")
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
