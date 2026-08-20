from __future__ import annotations

import io
import json
import sys
import urllib.error
from typing import Any, Self

import pytest

sys.path.insert(0, "ops")

import sentry_tool
from sentry_api import SentryAPIClient, SentryAPIError, SentryConfig


class FakeHeaders(dict[str, str]):
    def get(self, key: str, default: str | None = None) -> str | None:
        return super().get(key, default)


class FakeResponse:
    def __init__(self, payload: Any, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = FakeHeaders(headers or {})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def _config(**overrides: Any) -> SentryConfig:
    values: dict[str, Any] = {
        "api_url": "https://sentry.example.test/api/0",
        "auth_token": "secret-token",
        "organization": "kg-org",
        "project_ios": "ios",
        "retries": 0,
    }
    values.update(overrides)
    return SentryConfig(**values)


def test_config_strips_query_from_api_url_and_hides_token() -> None:
    config = SentryConfig.from_env(
        {
            "SENTRY_API_URL": "https://sentry.example.test/api/0?token=secret-token#fragment",
            "SENTRY_AUTH_TOKEN": "secret-token",
            "SENTRY_ORG": "kg-org",
            "SENTRY_PROJECT_IOS": "ios",
        }
    )
    assert config.api_url == "https://sentry.example.test/api/0"
    assert "secret-token" not in repr(config)


def test_list_issues_all_sends_explicit_empty_query_and_follows_pagination() -> None:
    calls: list[str] = []
    base = "https://sentry.example.test/api/0"

    def opener(request: Any, timeout: float) -> FakeResponse:
        assert timeout == 10.0
        calls.append(request.full_url)
        assert request.method == "GET"
        assert request.get_header("Authorization") == "Bearer secret-token"
        if len(calls) == 1:
            return FakeResponse(
                {"results": [{"id": "one"}], "links": {"next": {"url": f"{base}/next", "results": True}}}
            )
        return FakeResponse({"results": [{"id": "two"}], "links": {"next": {"results": False}}})

    rows = SentryAPIClient(_config(), opener=opener).list_issues("ios", status="all")
    assert [row["id"] for row in rows] == ["one", "two"]
    assert "query=" in calls[0]
    assert len(calls) == 2


def test_retry_after_is_bounded_and_retries_429() -> None:
    calls = 0
    sleeps: list[float] = []

    def opener(request: Any, timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                FakeHeaders({"Retry-After": "99"}),
                io.BytesIO(b"private body secret-token"),
            )
        return FakeResponse({"id": "project"})

    result = SentryAPIClient(_config(retries=1), opener=opener, sleeper=sleeps.append).project("ios")
    assert result["id"] == "project"
    assert calls == 2
    assert sleeps == [2.0]


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_http_errors_are_public_safe(status: int) -> None:
    def opener(request: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "private body secret-token",
            FakeHeaders(),
            io.BytesIO(b"email=person@example.com Authorization=Bearer secret-token"),
        )

    with pytest.raises(SentryAPIError) as caught:
        SentryAPIClient(_config(), opener=opener).project("ios")
    assert caught.value.status == status
    assert "secret-token" not in str(caught.value)
    assert "person@example.com" not in str(caught.value)


def test_timeout_is_retryable_network_error_without_body() -> None:
    def opener(_request: Any, timeout: float) -> Any:
        raise urllib.error.URLError(TimeoutError("secret-token"))

    with pytest.raises(SentryAPIError) as caught:
        SentryAPIClient(_config(), opener=opener).project("ios")
    assert caught.value.kind == "network"
    assert caught.value.retryable is True
    assert "secret-token" not in str(caught.value)


def test_cli_health_is_structured_and_warns_when_api_is_unconfigured(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SENTRY_ORG", raising=False)
    monkeypatch.delenv("SENTRY_PROJECT_IOS", raising=False)
    monkeypatch.setattr(
        sentry_tool,
        "load_local_ios_summary",
        lambda _root=None: {
            "verdict": "partial",
            "readiness": {"source_present": True, "package_present": True, "target_linked": True},
            "issues": [],
        },
    )

    code = sentry_tool.main(["health", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == sentry_tool.EXIT_WARN
    assert payload["schema"] == "kg.sentry.health.v1"
    assert payload["verdict"] == "partial"
    assert payload["checks"]["api_configured"] is False
    assert payload["checks"]["api_authenticated"] == "unchecked"


def test_cli_normalizes_issue_and_never_emits_forbidden_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeClient:
        def __init__(self, _config: SentryConfig) -> None:
            pass

        def list_issues(self, _project: str, **_kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "id": "123",
                    "shortId": "IOS-1",
                    "title": "book title from user",
                    "status": "unresolved",
                    "project": {"slug": "ios"},
                    "release": "com.example.app@2.0.1+10",
                }
            ]

    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("SENTRY_ORG", "kg-org")
    monkeypatch.setenv("SENTRY_PROJECT_IOS", "ios")
    monkeypatch.setattr(sentry_tool, "SentryAPIClient", FakeClient)

    code = sentry_tool.main(["issues", "--project", "ios", "--environment", "production", "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 0
    assert payload["issues"][0]["issue"]["title"] == "redacted"
    assert "book title from user" not in output
    assert "secret-token" not in output


def test_cli_missing_auth_returns_safe_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_ORG", "kg-org")
    monkeypatch.setenv("SENTRY_PROJECT_IOS", "ios")
    code = sentry_tool.main(["events", "--issue", "123", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == sentry_tool.EXIT_WARN
    assert payload["schema"] == "kg.sentry.error.v1"
    assert payload["error"]["kind"] == "missing_auth"
