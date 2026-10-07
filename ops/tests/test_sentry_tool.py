from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Self

import pytest

sys.path.insert(0, "ops")

import sentry_api
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
    assert config.api_url_valid is True
    assert "secret-token" not in repr(config)


def test_config_rejects_non_loopback_http_and_non_finite_timeout() -> None:
    config = SentryConfig.from_env(
        {
            "SENTRY_API_URL": "http://sentry.example.test/api/0",
            "SENTRY_API_TIMEOUT_SECONDS": "nan",
            "SENTRY_AUTH_TOKEN": "secret-token",
            "SENTRY_ORG": "kg-org",
            "SENTRY_PROJECT_IOS": "ios",
        }
    )
    assert config.api_url_valid is False
    assert config.api_configured is False
    assert config.timeout_seconds == 10.0


def test_loopback_http_is_allowed_for_fake_server() -> None:
    config = SentryConfig.from_env({"SENTRY_API_URL": "http://127.0.0.1:8123/api/0"})
    assert config.api_url == "http://127.0.0.1:8123/api/0"
    assert config.api_url_valid is True


def test_cross_origin_redirect_is_rejected_before_bearer_forwarding() -> None:
    handler = sentry_api._SameHostRedirectHandler()
    request = urllib.request.Request("https://sentry.example.test/api/0/issues/")
    with pytest.raises(SentryAPIError) as caught:
        handler.redirect_request(
            request,
            None,
            302,
            "redirect",
            FakeHeaders(),
            "https://evil.example.test/collect",
        )
    assert caught.value.kind == "redirect_origin_mismatch"


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
                {
                    "results": [{"id": "one"}],
                    "links": {"next": {"url": f"{base}/next", "results": True}},
                }
            )
        return FakeResponse(
            {"results": [{"id": "two"}], "links": {"next": {"results": False}}}
        )

    rows = SentryAPIClient(_config(), opener=opener).list_issues("ios", status="all")
    assert [row["id"] for row in rows] == ["one", "two"]
    assert "query=" in calls[0]
    assert "project=ios" in calls[0]
    assert len(calls) == 2


def test_collection_pagination_fails_closed_on_truncation_duplicate_or_malformed_payload() -> (
    None
):
    base = "https://sentry.example.test/api/0"

    def truncated(request: Any, timeout: float) -> FakeResponse:
        return FakeResponse(
            {
                "results": [{"id": "one"}],
                "links": {"next": {"url": f"{base}/next", "results": True}},
            }
        )

    with pytest.raises(SentryAPIError) as caught:
        SentryAPIClient(_config(), opener=truncated).list_issues("ios", max_pages=1)
    assert caught.value.kind == "pagination_incomplete"

    def duplicate(request: Any, timeout: float) -> FakeResponse:
        if request.full_url.endswith("/next"):
            return FakeResponse(
                {"results": [{"id": "one"}], "links": {"next": {"results": False}}}
            )
        return FakeResponse(
            {
                "results": [{"id": "one"}],
                "links": {"next": {"url": f"{base}/next", "results": True}},
            }
        )

    with pytest.raises(SentryAPIError) as caught:
        SentryAPIClient(_config(), opener=duplicate).list_issues("ios")
    assert caught.value.kind == "duplicate_page_item"

    with pytest.raises(SentryAPIError) as caught:
        SentryAPIClient(
            _config(), opener=lambda _request, timeout: FakeResponse({"unexpected": []})
        ).list_issues("ios")
    assert caught.value.kind == "invalid_collection"


def test_issue_environment_is_sent_as_a_server_side_filter() -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: float) -> FakeResponse:
        calls.append(request.full_url)
        return FakeResponse({"id": "123", "project": {"slug": "ios"}})

    SentryAPIClient(_config(), opener=opener).issue("123", environment="production")
    assert "environment=production" in calls[0]


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

    result = SentryAPIClient(
        _config(retries=1), opener=opener, sleeper=sleeps.append
    ).project("ios")
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


def test_cli_health_is_structured_and_warns_when_api_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SENTRY_ORG", raising=False)
    monkeypatch.delenv("SENTRY_PROJECT_IOS", raising=False)
    monkeypatch.setattr(
        sentry_tool,
        "load_local_ios_summary",
        lambda _root=None: {
            "verdict": "partial",
            "readiness": {
                "source_present": True,
                "package_present": True,
                "target_linked": True,
            },
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

    code = sentry_tool.main(
        ["issues", "--project", "ios", "--environment", "production", "--json"]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 0
    assert payload["issues"][0]["issue"]["title"] == "redacted"
    assert "book title from user" not in output
    assert "secret-token" not in output


def test_cli_missing_auth_returns_safe_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_ORG", "kg-org")
    monkeypatch.setenv("SENTRY_PROJECT_IOS", "ios")
    code = sentry_tool.main(["events", "--issue", "123", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == sentry_tool.EXIT_WARN
    assert payload["schema"] == "kg.sentry.error.v1"
    assert payload["error"]["kind"] == "missing_auth"


def test_cli_invalid_usage_is_json_and_uses_usage_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = sentry_tool.main(["issue"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == sentry_tool.EXIT_USAGE
    assert payload["schema"] == "kg.sentry.error.v1"
    assert payload["error"]["kind"] == "invalid_usage"
    assert captured.err == ""


# --- secrets file fallback, missing-config hint, release health -------------


@pytest.fixture(autouse=True)
def _isolate_sentry_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Never let the developer's real ~/.secrets/sentry.env leak into tests."""
    monkeypatch.setenv("SENTRY_ENV_FILE", str(tmp_path / "absent-sentry.env"))


def _write_env_file(path: Any, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_settings_fall_back_to_env_file(tmp_path: Any) -> None:
    env_file = _write_env_file(
        tmp_path / "sentry.env",
        "# comment\n"
        "\n"
        "SENTRY_AUTH_TOKEN=file-token\n"
        "export SENTRY_ORG='kg-org'\n"
        'SENTRY_PROJECT_IOS="kg-ios"\n'
        "SENTRY_PROJECT_BACKEND=kg-backend\n"
        "SENTRY_API_URL=https://us.sentry.io\n"
        "NOT_SENTRY=ignored\n"
        "malformed line\n",
    )
    settings = sentry_api.load_sentry_settings({"SENTRY_ENV_FILE": env_file})
    assert settings["SENTRY_AUTH_TOKEN"] == "file-token"
    assert settings["SENTRY_ORG"] == "kg-org"
    assert settings["SENTRY_PROJECT_IOS"] == "kg-ios"
    assert settings["SENTRY_PROJECT_BACKEND"] == "kg-backend"
    assert "NOT_SENTRY" not in settings
    config = SentryConfig.load({"SENTRY_ENV_FILE": env_file})
    assert config.api_configured is True
    assert config.api_url == "https://us.sentry.io/api/0"
    assert "file-token" not in repr(config)


def test_process_env_wins_over_env_file(tmp_path: Any) -> None:
    env_file = _write_env_file(
        tmp_path / "sentry.env",
        "SENTRY_AUTH_TOKEN=file-token\nSENTRY_ORG=file-org\nSENTRY_PROJECT_IOS=file-ios\n",
    )
    settings = sentry_api.load_sentry_settings(
        {"SENTRY_ENV_FILE": env_file, "SENTRY_ORG": "env-org", "SENTRY_PROJECT_IOS": ""}
    )
    assert settings["SENTRY_ORG"] == "env-org"
    assert settings["SENTRY_AUTH_TOKEN"] == "file-token"
    # An empty process variable does not blank out the file value.
    assert settings["SENTRY_PROJECT_IOS"] == "file-ios"


def test_env_file_path_defaults_to_secrets_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert sentry_api.sentry_env_file({}) == tmp_path / ".secrets" / "sentry.env"
    assert (
        sentry_api.sentry_env_file({"SENTRY_ENV_FILE": str(tmp_path / "x.env")})
        == tmp_path / "x.env"
    )
    assert sentry_api.load_sentry_settings({}) == {}


def test_cli_health_names_missing_keys_and_one_line_fix_without_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    env_file = _write_env_file(tmp_path / "sentry.env", "SENTRY_PROJECT_IOS=kg-ios\n")
    monkeypatch.setenv("SENTRY_ENV_FILE", env_file)
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SENTRY_ORG", raising=False)
    monkeypatch.delenv("SENTRY_PROJECT_IOS", raising=False)
    monkeypatch.setattr(
        sentry_tool,
        "load_local_ios_summary",
        lambda _root=None: {"verdict": "partial", "readiness": {}, "issues": []},
    )

    code = sentry_tool.main(["health", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == sentry_tool.EXIT_WARN
    assert payload["config"]["missing"] == ["SENTRY_AUTH_TOKEN", "SENTRY_ORG"]
    assert payload["config"]["env_file"] == env_file
    assert payload["config"]["env_file_present"] is True
    fix = payload["config"]["fix"]
    assert "\n" not in fix
    assert env_file in fix
    assert "org:read project:read event:read" in fix
    assert "SENTRY_AUTH_TOKEN" in fix and "SENTRY_ORG" in fix


def test_cli_health_omits_fix_hint_when_configured_and_never_prints_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    env_file = _write_env_file(
        tmp_path / "sentry.env",
        "SENTRY_AUTH_TOKEN=file-secret-token\nSENTRY_ORG=kg-org\nSENTRY_PROJECT_IOS=kg-ios\n",
    )
    monkeypatch.setenv("SENTRY_ENV_FILE", env_file)
    for key in ("SENTRY_AUTH_TOKEN", "SENTRY_ORG", "SENTRY_PROJECT_IOS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        sentry_tool,
        "load_local_ios_summary",
        lambda _root=None: {"verdict": "partial", "readiness": {}, "issues": []},
    )

    class FakeClient:
        def __init__(self, config: SentryConfig) -> None:
            assert config.auth_token == "file-secret-token"

        def project(self, _slug: str) -> dict[str, Any]:
            return {"id": "1"}

        def list_issues(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(sentry_tool, "SentryAPIClient", FakeClient)
    sentry_tool.main(["health", "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["checks"]["api_configured"] is True
    assert payload["checks"]["api_authenticated"] is True
    assert payload["config"]["missing"] == []
    assert "fix" not in payload["config"]
    assert "file-secret-token" not in output


def test_cli_missing_auth_error_carries_the_same_fix_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_ORG", "kg-org")
    monkeypatch.setenv("SENTRY_PROJECT_IOS", "ios")
    code = sentry_tool.main(["release-health", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == sentry_tool.EXIT_WARN
    assert payload["error"]["kind"] == "missing_auth"
    assert payload["config"]["missing"] == ["SENTRY_AUTH_TOKEN"]
    assert "org:read project:read event:read" in payload["config"]["fix"]


def _sessions_payload() -> dict[str, Any]:
    return {
        "start": "2026-09-23T00:00:00Z",
        "end": "2026-10-07T00:00:00Z",
        "groups": [
            {
                "by": {
                    "release": "com.example.app@2.0.1+10",
                    "environment": "production",
                },
                "totals": {
                    "crash_free_rate(session)": 0.9875,
                    "crash_free_rate(user)": 0.95,
                    "sum(session)": 800,
                    "count_unique(user)": 40,
                },
            },
            {
                "by": {
                    "release": "com.example.app@2.0.0+9",
                    "environment": "production",
                },
                "totals": {
                    "crash_free_rate(session)": None,
                    "crash_free_rate(user)": None,
                    "sum(session)": 0,
                    "count_unique(user)": 0,
                },
            },
        ],
    }


def test_release_health_queries_org_sessions_with_project_id() -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: float) -> FakeResponse:
        calls.append(request.full_url)
        assert request.method == "GET"
        return FakeResponse(_sessions_payload())

    groups = SentryAPIClient(_config(), opener=opener).release_health(
        "4505",
        environment="production",
        release="com.example.app@2.0.1+10",
        stats_period="14d",
    )
    assert len(groups) == 2
    url = calls[0]
    assert url.startswith(
        "https://sentry.example.test/api/0/organizations/kg-org/sessions/?"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["project"] == ["4505"]
    assert set(query["field"]) == {
        "crash_free_rate(session)",
        "crash_free_rate(user)",
        "sum(session)",
        "count_unique(user)",
    }
    assert set(query["groupBy"]) == {"release", "environment"}
    assert query["environment"] == ["production"]
    assert query["statsPeriod"] == ["14d"]
    assert query["query"] == ['release:"com.example.app@2.0.1+10"']


def test_release_health_rejects_unsafe_inputs() -> None:
    client = SentryAPIClient(_config(), opener=lambda *_a, **_k: FakeResponse({}))
    with pytest.raises(SentryAPIError) as caught:
        client.release_health("4505", stats_period="1y; drop")
    assert caught.value.kind == "invalid_stats_period"
    with pytest.raises(SentryAPIError) as caught:
        client.release_health("4505", release='x" OR release:"y')
    assert caught.value.kind == "invalid_release"


def test_cli_release_health_resolves_project_and_normalizes_rates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, _config: SentryConfig) -> None:
            pass

        def project(self, slug: str) -> dict[str, Any]:
            seen["slug"] = slug
            return {"id": "4505", "slug": slug}

        def release_health(
            self, project_id: str, **kwargs: Any
        ) -> list[dict[str, Any]]:
            seen["project_id"] = project_id
            seen.update(kwargs)
            return _sessions_payload()["groups"]

    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("SENTRY_ORG", "kg-org")
    monkeypatch.setenv("SENTRY_PROJECT_IOS", "kg-ios")
    monkeypatch.setattr(sentry_tool, "SentryAPIClient", FakeClient)

    code = sentry_tool.main(
        ["release-health", "--project", "ios", "--environment", "production", "--json"]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 0
    assert seen["slug"] == "kg-ios"
    assert seen["project_id"] == "4505"
    assert seen["environment"] == "production"
    assert seen["stats_period"] == "14d"
    assert payload["schema"] == "kg.sentry.release_health.v1"
    assert payload["project"] == "kg-ios"
    assert payload["stats_period"] == "14d"
    first, second = payload["releases"]
    assert first == {
        "release": "com.example.app@2.0.1+10",
        "environment": "production",
        "crash_free_sessions": 0.9875,
        "crash_free_users": 0.95,
        "sessions": 800,
        "users": 40,
    }
    assert second["crash_free_sessions"] is None
    assert second["sessions"] == 0
    assert "secret-token" not in output
