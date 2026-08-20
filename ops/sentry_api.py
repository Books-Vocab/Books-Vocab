#!/usr/bin/env -S uv run --python 3.13
"""Read-only Sentry Web API client used by the KG agent tooling.

The client intentionally exposes only GET endpoints.  Authentication tokens
never appear in exception text, reprs, logs, or returned payloads.  Network
behavior is injectable so all contract tests can use a fake transport without
depending on a Sentry account or the public service.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_API_URL = "https://sentry.io/api/0"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRIES = 2
MAX_RETRIES = 3
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._:@+-]{1,256}$")


class SentryAPIError(RuntimeError):
    """Public-safe API failure; response bodies are deliberately discarded."""

    def __init__(
        self,
        operation: str,
        *,
        status: int | None = None,
        kind: str = "request",
        retryable: bool = False,
    ) -> None:
        self.operation = operation
        self.status = status
        self.kind = kind
        self.retryable = retryable
        detail = f"{kind}{f' HTTP {status}' if status is not None else ''}"
        super().__init__(f"Sentry {operation}: {detail}")

    def public(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "kind": self.kind,
            "status": self.status,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class SentryConfig:
    api_url: str = DEFAULT_API_URL
    auth_token: str | None = field(default=None, repr=False)
    organization: str | None = None
    project_ios: str | None = None
    project_backend: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retries: int = DEFAULT_RETRIES

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> SentryConfig:
        env = os.environ if environ is None else environ
        raw_timeout = env.get("SENTRY_API_TIMEOUT_SECONDS", "")
        try:
            timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        timeout = min(max(timeout, 0.1), 60.0)

        raw_retries = env.get("SENTRY_API_RETRIES", "")
        try:
            retries = int(raw_retries) if raw_retries else DEFAULT_RETRIES
        except ValueError:
            retries = DEFAULT_RETRIES
        retries = min(max(retries, 0), MAX_RETRIES)

        api_url = _normalise_api_url(env.get("SENTRY_API_URL", DEFAULT_API_URL))
        return cls(
            api_url=api_url,
            auth_token=_non_empty(env.get("SENTRY_AUTH_TOKEN")),
            organization=_non_empty(env.get("SENTRY_ORG")),
            project_ios=_non_empty(env.get("SENTRY_PROJECT_IOS")),
            project_backend=_non_empty(env.get("SENTRY_PROJECT_BACKEND")),
            timeout_seconds=timeout,
            retries=retries,
        )

    def project_for(self, project: str) -> str | None:
        if project == "ios":
            return self.project_ios
        if project == "backend":
            return self.project_backend
        return None

    @property
    def api_configured(self) -> bool:
        return bool(self.auth_token and self.organization and self.project_ios)


@dataclass(frozen=True)
class _HTTPResult:
    payload: Any
    headers: Any
    url: str


class SentryAPIClient:
    """Small GET-only client for the documented Sentry API v0 resources."""

    def __init__(
        self,
        config: SentryConfig,
        *,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.auth_token:
            raise SentryAPIError("configure", kind="missing_auth", retryable=False)
        if not config.organization:
            raise SentryAPIError("configure", kind="missing_org", retryable=False)
        self.config = config
        self._opener = opener or urllib.request.urlopen
        self._sleeper = sleeper

    def project(self, project: str) -> dict[str, Any]:
        return self._get_json(
            f"/projects/{_segment(self.config.organization)}/{_segment(project)}/",
            operation="project",
        )

    def list_issues(
        self,
        project: str,
        *,
        environment: str | None = None,
        status: str = "unresolved",
        query: str | None = None,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        if status not in {"unresolved", "resolved", "all"}:
            raise SentryAPIError("issues", kind="invalid_status")
        search = query
        if search is None:
            # The project issues endpoint defaults to unresolved.  An explicit
            # empty query is required to make status=all really mean all.
            search = "" if status == "all" else f"is:{status}"
        params: list[tuple[str, str]] = [("limit", "100"), ("statsPeriod", "")]
        if search is not None:
            params.append(("query", search))
        if environment:
            params.append(("environment", environment))
        path = f"/projects/{_segment(self.config.organization)}/{_segment(project)}/issues/"
        return self._paginate(path, params=params, operation="issues", max_pages=max_pages)

    def issue(self, issue_id: str) -> dict[str, Any]:
        path = f"/organizations/{_segment(self.config.organization)}/issues/{_segment(issue_id)}/"
        return self._get_json(path, operation="issue")

    def list_issue_events(
        self,
        issue_id: str,
        *,
        environment: str | None = None,
        full: bool = True,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = [("full", "1" if full else "0"), ("per_page", "100")]
        if environment:
            params.append(("environment", environment))
        path = f"/organizations/{_segment(self.config.organization)}/issues/{_segment(issue_id)}/events/"
        return self._paginate(path, params=params, operation="events", max_pages=max_pages)

    def issue_event(
        self,
        issue_id: str,
        event_id: str = "latest",
        *,
        environment: str | None = None,
    ) -> dict[str, Any]:
        params: list[tuple[str, str]] = []
        if environment:
            params.append(("environment", environment))
        path = (
            f"/organizations/{_segment(self.config.organization)}/issues/"
            f"{_segment(issue_id)}/events/{_segment(event_id)}/"
        )
        return self._get_json(path, params=params, operation="event")

    def releases(
        self,
        project: str | None = None,
        *,
        environment: str | None = None,
        query: str | None = None,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = [("per_page", "100")]
        if project:
            params.append(("project", project))
        if environment:
            params.append(("environment", environment))
        if query:
            params.append(("query", query))
        path = f"/organizations/{_segment(self.config.organization)}/releases/"
        return self._paginate(path, params=params, operation="releases", max_pages=max_pages)

    def regressions(self, project: str, release: str) -> list[dict[str, Any]]:
        if not _SAFE_PATH_SEGMENT.fullmatch(release):
            raise SentryAPIError("regressions", kind="invalid_release")
        search = f'release:"{release}" is:unresolved'
        return self.list_issues(project, status="all", query=search)

    def _paginate(
        self,
        path: str,
        *,
        params: Iterable[tuple[str, str]],
        operation: str,
        max_pages: int,
    ) -> list[dict[str, Any]]:
        if max_pages < 1:
            raise SentryAPIError(operation, kind="invalid_pagination")
        next_url = self._build_url(path, params)
        rows: list[dict[str, Any]] = []
        for _ in range(max_pages):
            response = self._request_url(next_url, operation=operation)
            payload = response.payload
            page = _page_items(payload)
            rows.extend(item for item in page if isinstance(item, dict))
            next_url = _next_url(payload, response.headers, base_url=self.config.api_url)
            if not next_url:
                break
        return rows

    def _get_json(
        self,
        path: str,
        *,
        params: Iterable[tuple[str, str]] = (),
        operation: str,
    ) -> dict[str, Any]:
        response = self._request_url(self._build_url(path, params), operation=operation)
        if not isinstance(response.payload, dict):
            raise SentryAPIError(operation, kind="invalid_json")
        return response.payload

    def _build_url(self, path: str, params: Iterable[tuple[str, str]]) -> str:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise SentryAPIError("request", kind="invalid_path")
        query = urllib.parse.urlencode(list(params), doseq=True)
        return f"{self.config.api_url}{path}{f'?{query}' if query else ''}"

    def _request_url(self, url: str, *, operation: str) -> _HTTPResult:
        parsed = urllib.parse.urlparse(url)
        configured = urllib.parse.urlparse(self.config.api_url)
        if parsed.scheme != configured.scheme or parsed.netloc != configured.netloc:
            raise SentryAPIError(operation, kind="pagination_host_mismatch")

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.auth_token}",
                "User-Agent": "kg-sentry-tool/1",
            },
        )
        attempts = 0
        while True:
            try:
                with self._opener(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise SentryAPIError(operation, kind="response_too_large")
                    try:
                        payload = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
                    except json.JSONDecodeError as exc:
                        raise SentryAPIError(operation, kind="invalid_json") from exc
                    return _HTTPResult(payload=payload, headers=response.headers, url=url)
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if retryable and attempts < self.config.retries:
                    self._retry_delay(attempts, exc.headers)
                    attempts += 1
                    continue
                raise SentryAPIError(
                    operation,
                    status=exc.code,
                    kind="http",
                    retryable=retryable,
                ) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempts < self.config.retries:
                    self._retry_delay(attempts, None)
                    attempts += 1
                    continue
                raise SentryAPIError(operation, kind="network", retryable=True) from exc

    def _retry_delay(self, attempt: int, headers: Any) -> None:
        retry_after = None
        if headers is not None:
            raw = headers.get("Retry-After")
            try:
                retry_after = float(raw) if raw else None
            except (TypeError, ValueError):
                retry_after = None
        delay = min(max(retry_after if retry_after is not None else 0.25 * (2**attempt), 0.0), 2.0)
        self._sleeper(delay)


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalise_api_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return DEFAULT_API_URL
    parsed = urllib.parse.urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return DEFAULT_API_URL
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/0"):
        path = f"{path}/0" if path.endswith("/api") else f"{path}/api/0"
    # Deliberately discard query/fragment so a mistaken token-bearing API URL
    # can never become an Authorization-equivalent leak in requests.
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _segment(value: str | None) -> str:
    if not value or not _SAFE_PATH_SEGMENT.fullmatch(value):
        raise SentryAPIError("request", kind="invalid_path_segment")
    return urllib.parse.quote(value, safe="")


def _page_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    return []


def _next_url(payload: Any, headers: Any, *, base_url: str) -> str | None:
    candidate: Any = None
    if isinstance(payload, dict):
        links = payload.get("links")
        if isinstance(links, dict):
            candidate = links.get("next")
        elif isinstance(payload.get("next"), (str, dict)):
            candidate = payload.get("next")
    if candidate is not None:
        if isinstance(candidate, dict):
            if candidate.get("results") is False:
                return None
            candidate = candidate.get("url") or candidate.get("href")
        if isinstance(candidate, str) and candidate:
            return _same_host_url(candidate, base_url)

    raw_link = headers.get("Link", "") if headers is not None else ""
    for part in raw_link.split(","):
        match = re.search(r"<([^>]+)>;\s*rel=\"next\"([^>]*)", part)
        if not match:
            continue
        if re.search(r'results=\"false\"', match.group(2)):
            return None
        return _same_host_url(match.group(1), base_url)
    return None


def _same_host_url(value: str, base_url: str) -> str | None:
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(f"{base_url}/", value))
    base = urllib.parse.urlparse(base_url)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        raise SentryAPIError("pagination", kind="pagination_host_mismatch")
    return parsed.geturl()


__all__ = ["SentryAPIClient", "SentryAPIError", "SentryConfig"]
