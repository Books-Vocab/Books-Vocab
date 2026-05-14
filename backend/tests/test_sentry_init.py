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
    bind_user,
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


# ---------------------------------------------------------------------------
# bind_user: ties uid to the current Sentry scope so error groups are
# clusterable by user without sending email / IP / username.
# ---------------------------------------------------------------------------

def test_bind_user_no_op_when_sentry_inactive(monkeypatch):
    # SENTRY_DSN unset → init returns False → bind_user must silently do nothing
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # Must not raise even though sentry isn't initialized.
    bind_user("uid-123")
    bind_user(None)
    bind_user("")


def test_bind_user_only_sends_id(monkeypatch):
    """When Sentry is active, only {'id': uid} reaches set_user — no PII."""
    captured: list = []

    class FakeSentry:
        @staticmethod
        def set_user(payload):
            captured.append(payload)

    import kg.sentry_init as si

    # Force the "sentry active" branch without standing up a real DSN.
    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", FakeSentry, raising=False)

    si.bind_user("user-xyz")
    assert captured == [{"id": "user-xyz"}]
    # Defensive: must not leak email / username / ip_address keys even if
    # somebody adds them later by accident.
    for entry in captured:
        assert set(entry.keys()) == {"id"}


def test_bind_user_clears_scope_when_uid_none(monkeypatch):
    """Unauthenticated request path should clear any stale uid."""
    captured: list = []

    class FakeSentry:
        @staticmethod
        def set_user(payload):
            captured.append(payload)

    import kg.sentry_init as si
    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", FakeSentry, raising=False)

    si.bind_user(None)
    si.bind_user("")
    # Both call paths must clear the scope (sentry uses None payload for clear).
    assert captured == [None, None]


def test_traces_sampler_handles_missing_path():
    # Defensive: sentry sometimes hands a context without asgi_scope (websockets,
    # background workers). Must not crash; default to baseline.
    assert _traces_sampler({}) == 0.01
    assert _traces_sampler({"asgi_scope": {}}) == 0.01


# ---------------------------------------------------------------------------
# deps.get_current_user → sentry_init.bind_user wiring
# ---------------------------------------------------------------------------

def test_get_current_user_binds_uid_to_sentry(tmp_path, monkeypatch):
    """Authenticated request must surface uid to Sentry scope."""
    import json
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    import jwt as pyjwt
    from fastapi.security import HTTPAuthorizationCredentials

    from kg import deps
    from kg.settings import KGSettings

    captured: list = []
    monkeypatch.setattr(
        deps, "bind_user", lambda uid: captured.append(uid), raising=True
    )

    user_id = "uid-binds-to-sentry"
    secret = "test-secret-for-this-test-only-1234567"
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({user_id: {"config": {}}}))

    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret=secret,
        jwt_algorithm="HS256",
    )
    token = pyjwt.encode(
        {
            "sub": user_id,
            "iat": datetime.now(tz=UTC),
            "exp": datetime.now(tz=UTC) + timedelta(hours=1),
        },
        secret,
        algorithm="HS256",
    )

    fake_app = SimpleNamespace(
        state=SimpleNamespace(
            kg_settings=settings,
            load_users=lambda: json.loads(users_file.read_text()),
        )
    )
    fake_request = SimpleNamespace(app=fake_app)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    result = deps.get_current_user(fake_request, creds)  # type: ignore[arg-type]
    assert result["id"] == user_id
    assert captured == [user_id], "bind_user should be called with the uid on auth success"


def test_resolve_release_treats_empty_strings_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_RELEASE", "   ")
    monkeypatch.setenv("KG_VERSION", "")
    version_file = tmp_path / "VERSION"
    version_file.write_text("")
    assert _resolve_release(version_file=version_file) is None


# ---------------------------------------------------------------------------
# init_sentry kwargs: SENTRY_TRACES_SAMPLE_RATE must produce a flat
# traces_sample_rate (no traces_sampler), so operators can pin a fixed APM
# rate from env without re-deploying. Regression guard for review feedback
# pointing out the flat-override branch had no coverage.
# ---------------------------------------------------------------------------

def _reset_sentry_module_state(monkeypatch):
    """Reset module-level singleton so init_sentry() runs each test fresh."""
    import kg.sentry_init as si

    monkeypatch.setattr(si, "_initialized", False, raising=False)
    monkeypatch.setattr(si, "_sentry_module", None, raising=False)


def _patch_sentry_sdk(monkeypatch):
    """Stub sentry_sdk.init so we capture init_kwargs without contacting Sentry."""
    import sys
    import types

    captured: dict = {}

    fake_module = types.ModuleType("sentry_sdk")

    def fake_init(**kwargs):
        captured["init_kwargs"] = kwargs

    fake_module.init = fake_init  # type: ignore[attr-defined]
    fake_module.set_user = lambda payload: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_module)

    # Integrations are imported by name in init_sentry; stub them too so the
    # import inside init_sentry doesn't reach real sentry internals.
    for name in (
        "sentry_sdk.integrations.fastapi",
        "sentry_sdk.integrations.starlette",
        "sentry_sdk.integrations.logging",
    ):
        mod = types.ModuleType(name)
        # Each integration is constructed with kwargs; make it a no-op callable.
        cls_name = {
            "sentry_sdk.integrations.fastapi": "FastApiIntegration",
            "sentry_sdk.integrations.starlette": "StarletteIntegration",
            "sentry_sdk.integrations.logging": "LoggingIntegration",
        }[name]
        setattr(mod, cls_name, lambda *a, **kw: object())
        monkeypatch.setitem(sys.modules, name, mod)

    return captured


def test_init_sentry_flat_override_uses_traces_sample_rate(monkeypatch):
    """SENTRY_TRACES_SAMPLE_RATE=0.5 must short-circuit the per-path sampler."""
    _reset_sentry_module_state(monkeypatch)
    captured = _patch_sentry_sdk(monkeypatch)

    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")
    # Clear release sources so we don't accidentally read host /app/VERSION.
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("KG_VERSION", raising=False)

    assert init_sentry() is True
    kwargs = captured["init_kwargs"]
    assert kwargs.get("traces_sample_rate") == 0.5
    assert "traces_sampler" not in kwargs, (
        "flat env override must replace the per-path sampler, not run alongside it"
    )


def test_init_sentry_default_uses_traces_sampler(monkeypatch):
    """Without SENTRY_TRACES_SAMPLE_RATE, the per-path sampler stays wired."""
    _reset_sentry_module_state(monkeypatch)
    captured = _patch_sentry_sdk(monkeypatch)

    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example/1")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("KG_VERSION", raising=False)

    assert init_sentry() is True
    kwargs = captured["init_kwargs"]
    assert "traces_sample_rate" not in kwargs
    assert callable(kwargs.get("traces_sampler"))
