"""Tests for sentry_init.tag_request_id + middleware wiring.

The middleware (`request_id_middleware` in `kg.api`) tags every Sentry scope
with the same `request_id` we already log + echo back in the
`X-Request-ID` response header. These tests verify:

  1. `tag_request_id` is a no-op when Sentry is inactive (dev/test, DSN unset).
  2. When Sentry is active, exactly `set_tag("request_id", <id>)` is invoked.
  3. Falsy ids are dropped (no spurious tags with empty strings).
  4. The middleware actually calls `tag_request_id` per request.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Unit-level: tag_request_id
# ---------------------------------------------------------------------------

def test_tag_request_id_no_op_when_sentry_inactive(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    import kg.sentry_init as si

    # Must not raise even though sentry isn't initialized.
    si.tag_request_id("req-abc")
    si.tag_request_id(None)
    si.tag_request_id("")


def test_tag_request_id_sets_tag_when_active(monkeypatch):
    captured: list[tuple[str, str]] = []

    class FakeSentry:
        @staticmethod
        def set_tag(key, value):
            captured.append((key, value))

    import kg.sentry_init as si
    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", FakeSentry, raising=False)

    si.tag_request_id("req-xyz")
    assert captured == [("request_id", "req-xyz")]


def test_tag_request_id_skips_falsy(monkeypatch):
    """Empty / None ids must not produce stray empty tags on the scope."""
    captured: list = []

    class FakeSentry:
        @staticmethod
        def set_tag(key, value):
            captured.append((key, value))

    import kg.sentry_init as si
    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", FakeSentry, raising=False)

    si.tag_request_id(None)
    si.tag_request_id("")
    assert captured == []


def test_tag_request_id_suppresses_sentry_errors(monkeypatch):
    """A sentry-side exception must never propagate into the request flow."""

    class BoomSentry:
        @staticmethod
        def set_tag(key, value):
            raise RuntimeError("sentry transport down")

    import kg.sentry_init as si
    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", BoomSentry, raising=False)

    # Must swallow.
    si.tag_request_id("req-boom")


# ---------------------------------------------------------------------------
# Middleware wiring: request_id_middleware → tag_request_id
# ---------------------------------------------------------------------------

def test_middleware_calls_tag_request_id_with_header_value(monkeypatch):
    """Inbound X-Request-ID is propagated to the Sentry scope."""
    captured: list[str] = []

    import kg.sentry_init as si
    monkeypatch.setattr(
        si, "tag_request_id",
        lambda rid: captured.append(rid),
        raising=True,
    )

    from kg.api import create_app
    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/system/info", headers={"X-Request-ID": "test-correlation-id"})
    assert resp.status_code == 200
    assert "test-correlation-id" in captured


def test_middleware_calls_tag_request_id_with_generated_id(monkeypatch):
    """No inbound header → middleware generates an id and still tags it."""
    captured: list[str] = []

    import kg.sentry_init as si
    monkeypatch.setattr(
        si, "tag_request_id",
        lambda rid: captured.append(rid),
        raising=True,
    )

    from kg.api import create_app
    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/system/info")
    assert resp.status_code == 200
    # One id was generated and tagged (matches what the client sees back).
    assert len(captured) == 1
    assert captured[0] == resp.headers.get("X-Request-ID")
    assert captured[0]  # non-empty
