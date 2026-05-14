"""Contract tests for kg.sentry_init — focus on the credential scrubber.

We do not test that sentry_sdk.init() actually fires; that requires a live DSN
and would couple tests to network state. We test the pure-function scrubber
that protects against the most likely PII leak path (admin token in querystring,
auth header values in event payload).
"""
from __future__ import annotations

from kg.sentry_init import (
    _resolve_release,
    _scrub_event,
    _scrub_querystring,
    _traces_sampler,
    init_sentry,
)


def test_init_sentry_no_dsn_is_noop(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False


def test_scrub_querystring_redacts_token():
    qs = "token=secret123&foo=bar"
    assert _scrub_querystring(qs) == "token=[scrubbed]&foo=bar"


def test_scrub_querystring_redacts_multiple_keys():
    qs = "id_token=abc&code=xyz&page=2&access_token=def"
    out = _scrub_querystring(qs)
    assert "id_token=[scrubbed]" in out
    assert "code=[scrubbed]" in out
    assert "access_token=[scrubbed]" in out
    assert "page=2" in out


def test_scrub_querystring_handles_empty_and_no_value():
    assert _scrub_querystring("") == ""
    assert _scrub_querystring("flag") == "flag"


def test_scrub_event_redacts_authorization_header():
    event = {
        "request": {
            "query_string": "token=topsecret",
            "headers": {
                "Authorization": "Bearer eyJ...",
                "X-Admin-Token": "admintoken",
                "User-Agent": "pytest",
            },
            "cookies": {
                "admin_session": "abc",
                "preferences": "dark",
            },
        }
    }
    scrubbed = _scrub_event(event, {})
    req = scrubbed["request"]
    assert req["query_string"] == "token=[scrubbed]"
    assert req["headers"]["Authorization"] == "[scrubbed]"
    assert req["headers"]["X-Admin-Token"] == "[scrubbed]"
    assert req["headers"]["User-Agent"] == "pytest"
    assert req["cookies"]["admin_session"] == "[scrubbed]"
    assert req["cookies"]["preferences"] == "dark"


def test_scrub_event_tolerates_missing_request():
    assert _scrub_event({}, {}) == {}
    assert _scrub_event({"request": None}, {}) == {"request": None}


def test_scrub_event_tolerates_non_dict_subfields():
    event = {"request": {"headers": "garbled", "cookies": []}}
    assert _scrub_event(event, {}) == event


# ---------------------------------------------------------------------------
# Release resolution: env override → KG_VERSION → /app/VERSION file
# ---------------------------------------------------------------------------

def test_resolve_release_prefers_sentry_release_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_RELEASE", "abc1234")
    monkeypatch.setenv("KG_VERSION", "should-be-ignored")
    version_file = tmp_path / "VERSION"
    version_file.write_text("file-shadowed")
    assert _resolve_release(version_file=version_file) == "abc1234"


def test_resolve_release_falls_back_to_kg_version(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("KG_VERSION", "deadbeef")
    version_file = tmp_path / "VERSION"
    version_file.write_text("file-shadowed")
    assert _resolve_release(version_file=version_file) == "deadbeef"


def test_resolve_release_falls_back_to_version_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("KG_VERSION", raising=False)
    version_file = tmp_path / "VERSION"
    version_file.write_text("  cafef00d\n")
    assert _resolve_release(version_file=version_file) == "cafef00d"


def test_resolve_release_returns_none_when_nothing_available(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("KG_VERSION", raising=False)
    version_file = tmp_path / "VERSION"  # does not exist
    assert _resolve_release(version_file=version_file) is None


# ---------------------------------------------------------------------------
# Traces sampler: per-path rates so APM bill stays bounded while we keep
# observability on the LLM-call hot paths.
# ---------------------------------------------------------------------------

def _ctx(path: str) -> dict:
    """Minimal traces_sampler context resembling what sentry hands us."""
    return {
        "asgi_scope": {"type": "http", "path": path},
        "transaction_context": {"name": path, "op": "http.server"},
    }


def test_traces_sampler_hot_llm_paths_get_5pct():
    for path in ("/api/pipeline", "/api/translate", "/api/explain"):
        assert _traces_sampler(_ctx(path)) == 0.05, path


def test_traces_sampler_hot_llm_paths_match_subroutes():
    # /api/pipeline/run, /api/translate/batch etc. share the same prefix rate.
    assert _traces_sampler(_ctx("/api/pipeline/run")) == 0.05
    assert _traces_sampler(_ctx("/api/translate/batch")) == 0.05


def test_traces_sampler_health_paths_dropped():
    for path in ("/api/system/info", "/api/health", "/health"):
        assert _traces_sampler(_ctx(path)) == 0.0, path


def test_traces_sampler_default_baseline_1pct():
    assert _traces_sampler(_ctx("/api/vocabulary/list")) == 0.01
    assert _traces_sampler(_ctx("/api/notebooks")) == 0.01


def test_traces_sampler_handles_missing_path():
    # Defensive: sentry sometimes hands a context without asgi_scope (websockets,
    # background workers). Must not crash; default to baseline.
    assert _traces_sampler({}) == 0.01
    assert _traces_sampler({"asgi_scope": {}}) == 0.01


def test_resolve_release_treats_empty_strings_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_RELEASE", "   ")
    monkeypatch.setenv("KG_VERSION", "")
    version_file = tmp_path / "VERSION"
    version_file.write_text("")
    assert _resolve_release(version_file=version_file) is None
