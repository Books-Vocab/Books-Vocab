"""Contract tests for kg.sentry_init — focus on the credential scrubber.

We do not test that sentry_sdk.init() actually fires; that requires a live DSN
and would couple tests to network state. We test the pure-function scrubber
that protects against the most likely PII leak path (admin token in querystring,
auth header values in event payload).
"""
from __future__ import annotations

from kg.sentry_init import _scrub_event, _scrub_querystring, init_sentry


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
