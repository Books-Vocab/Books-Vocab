"""Handled-failure reporting: ``sentry_init.capture_handled`` and its call sites.

``LoggingIntegration(event_level=None)`` turns ``logger.error`` into a
breadcrumb only, so a failure that is caught and logged never becomes a Sentry
event. ``capture_handled`` is the single seam that reports those failures with
a stable ``context`` tag. These tests stub the SDK module (no DSN, no network)
and drive the real helper through each wired path.
"""

from __future__ import annotations

import asyncio
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import kg.sentry_init as si
from kg.exceptions import ExternalServiceError, NotFoundError, QuotaExceededError
from test_external_api import _create_key, external_api  # noqa: F401 — fixture reuse


class _FakeScope:
    def __init__(self) -> None:
        self.tags: dict[str, str] = {}

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value


class _FakeSentry:
    def __init__(self) -> None:
        self.captured: list[tuple[BaseException, dict]] = []
        self.global_scope = _FakeScope()

    def capture_exception(self, exc: BaseException, **kwargs) -> str:
        self.captured.append((exc, kwargs))
        return "event-id"

    def get_global_scope(self) -> _FakeScope:
        return self.global_scope

    # Request-path hooks (bind_user / tag_request_id) also hit the module.
    def set_user(self, _payload) -> None:
        pass

    def set_tag(self, _key: str, _value: str) -> None:
        pass


@pytest.fixture()
def fake_sentry(monkeypatch) -> _FakeSentry:
    fake = _FakeSentry()
    monkeypatch.setattr(si, "_initialized", True)
    monkeypatch.setattr(si, "_sentry_module", fake)
    return fake


def _contexts(fake: _FakeSentry) -> list[str]:
    return [kwargs["tags"]["context"] for _exc, kwargs in fake.captured]


# ---------------------------------------------------------------------------
# Test isolation: conftest must neutralize any dev .env DSN before kg.api's
# load_dotenv() runs, otherwise test events ship tagged "production".
# ---------------------------------------------------------------------------


def test_conftest_clears_sentry_dsn():
    assert os.environ.get("SENTRY_DSN") == ""


# ---------------------------------------------------------------------------
# Helper contract
# ---------------------------------------------------------------------------


def test_capture_handled_is_noop_when_sentry_inactive(monkeypatch):
    monkeypatch.setattr(si, "_initialized", False)
    monkeypatch.setattr(si, "_sentry_module", None)
    assert si.capture_handled(RuntimeError("boom"), context="unit.test") is False


def test_capture_handled_reports_with_stable_context_tag(fake_sentry):
    exc = RuntimeError("boom")
    assert si.capture_handled(exc, context="unit.test", tags={"step": "enrich"}) is True
    assert len(fake_sentry.captured) == 1
    captured_exc, kwargs = fake_sentry.captured[0]
    assert captured_exc is exc
    assert kwargs["tags"] == {"context": "unit.test", "step": "enrich"}


def test_capture_handled_context_tag_cannot_be_overridden_by_extra_tags(fake_sentry):
    si.capture_handled(RuntimeError("boom"), context="stable", tags={"context": "spoof"})
    assert _contexts(fake_sentry) == ["stable"]


@pytest.mark.parametrize(
    "exc",
    [NotFoundError("card", "c1"), QuotaExceededError(reset_seconds=60)],
    ids=["404", "429"],
)
def test_capture_handled_skips_client_kgerrors(fake_sentry, exc):
    assert si.capture_handled(exc, context="unit.test") is False
    assert fake_sentry.captured == []


def test_capture_handled_reports_server_kgerrors(fake_sentry):
    assert si.capture_handled(ExternalServiceError("llm"), context="unit.test") is True
    assert _contexts(fake_sentry) == ["unit.test"]


@pytest.mark.parametrize(
    "exc",
    [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(1)],
    ids=["cancelled", "keyboard", "systemexit"],
)
def test_capture_handled_skips_cancellation_and_exit(fake_sentry, exc):
    assert si.capture_handled(exc, context="unit.test") is False
    assert fake_sentry.captured == []


def test_capture_handled_swallows_sdk_failure(monkeypatch):
    class Exploding:
        def capture_exception(self, *_a, **_kw):
            raise RuntimeError("sdk down")

    monkeypatch.setattr(si, "_initialized", True)
    monkeypatch.setattr(si, "_sentry_module", Exploding())
    assert si.capture_handled(RuntimeError("boom"), context="unit.test") is False


# ---------------------------------------------------------------------------
# init_sentry(job=...) for CLI / cron entrypoints
# ---------------------------------------------------------------------------


def test_init_sentry_job_tags_global_scope(monkeypatch, fake_sentry):
    assert si.init_sentry(job="log_retention") is True
    assert fake_sentry.global_scope.tags == {"job": "log_retention"}


def test_init_sentry_job_without_dsn_is_noop(monkeypatch):
    monkeypatch.setattr(si, "_initialized", False)
    monkeypatch.setattr(si, "_sentry_module", None)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert si.init_sentry(job="log_retention") is False


def _record_init(monkeypatch, module) -> list:
    calls: list = []
    monkeypatch.setattr(module, "init_sentry", lambda **kw: calls.append(kw) or False)
    return calls


def test_log_retention_main_initializes_sentry_with_job(monkeypatch):
    from kg import log_retention

    calls = _record_init(monkeypatch, log_retention)
    assert log_retention.main([]) == 2  # no target → help, but init already ran
    assert calls == [{"job": "log_retention"}]


def test_orphan_scan_main_initializes_sentry_with_job(monkeypatch):
    from kg import orphan_scan

    calls = _record_init(monkeypatch, orphan_scan)
    assert orphan_scan.main([]) == 2
    assert calls == [{"job": "orphan_scan"}]


def test_ops_cli_main_initializes_sentry_with_job(monkeypatch):
    from kg import ops_cli_app

    calls = _record_init(monkeypatch, ops_cli_app)
    ran: list = []
    monkeypatch.setattr(ops_cli_app, "_parser_main", lambda: ran.append(True))
    ops_cli_app.main()
    assert calls == [{"job": "ops_cli"}]
    assert ran == [True]


# ---------------------------------------------------------------------------
# Wired paths
# ---------------------------------------------------------------------------


def _run_step(coro_fn):
    from kg.pipeline_service.runner import _run_step as run_step

    return asyncio.run(run_step("u1", "enrich", coro_fn, logger=logging.getLogger("t")))


def test_pipeline_step_failure_reports_with_context(fake_sentry):
    async def boom():
        raise RuntimeError("step exploded")

    assert _run_step(boom) == "failed"
    assert _contexts(fake_sentry) == ["pipeline.step"]
    assert fake_sentry.captured[0][1]["tags"]["step"] == "enrich"


def test_pipeline_step_quota_exhaustion_is_not_reported(fake_sentry):
    async def quota():
        raise QuotaExceededError(reset_seconds=60)

    assert _run_step(quota) == "quota_exhausted"
    assert fake_sentry.captured == []


def test_pipeline_step_client_kgerror_is_not_reported(fake_sentry):
    async def missing():
        raise NotFoundError("notebook", "nb")

    assert _run_step(missing) == "failed"
    assert fake_sentry.captured == []


def test_enrich_batch_failure_reports_with_context(fake_sentry):
    from kg.cards import Card
    from kg.enrich import enrich_cards_stream

    async def drain():
        return [
            msg
            async for msg in enrich_cards_stream(
                MagicMock(), [Card(content="hello", meaning="你好", examples=[])], batch_size=1
            )
        ]

    with patch("kg.enrich.sync_retry", side_effect=RuntimeError("provider down")):
        results = asyncio.run(asyncio.wait_for(drain(), timeout=10))

    assert results[-1]["status"] == "error"
    assert _contexts(fake_sentry) == ["enrich.batch"]


def test_external_enrich_operation_failure_reports_with_context(fake_sentry, monkeypatch):
    import kg.routers.external_api as external_router

    monkeypatch.setattr(external_router, "_run_pipeline_bg", AsyncMock(side_effect=RuntimeError("bg")))
    with patch("kg.pipeline_log.end_run"):
        asyncio.run(
            external_router._run_external_pipeline(SimpleNamespace(), "op-1", force=False, notebook_id="default")
        )
    assert _contexts(fake_sentry) == ["external_api.enrich_operation"]


def test_external_enrich_telemetry_close_failure_reports_with_context(fake_sentry, monkeypatch):
    import kg.routers.external_api as external_router

    monkeypatch.setattr(external_router, "_run_pipeline_bg", AsyncMock(side_effect=RuntimeError("bg")))
    with patch("kg.pipeline_log.end_run", side_effect=OSError("db gone")):
        asyncio.run(
            external_router._run_external_pipeline(SimpleNamespace(), "op-2", force=False, notebook_id="default")
        )
    assert _contexts(fake_sentry) == [
        "external_api.enrich_operation",
        "external_api.operation_telemetry_close",
    ]


def test_external_card_delete_embedding_eviction_reports_with_context(
    external_api,  # noqa: F811
    fake_sentry,
    monkeypatch,
):
    import kg.routers.external_api as external_router

    headers = {"X-KG-API-Key": _create_key(external_api)}
    created = external_api.client.post(
        "/api/v1/cards", json={"content": "eviction", "meaning": "驅逐"}, headers=headers
    )
    assert created.status_code == 201, created.text
    card_id = created.json()["card"]["id"]

    def fail_embedding_eviction(*_args, **_kwargs):
        raise OSError("embedding store unavailable")

    monkeypatch.setattr(external_router, "_embedding_store", fail_embedding_eviction)
    deleted = external_api.client.delete(f"/api/v1/cards/{card_id}", headers=headers)

    assert deleted.status_code == 200, deleted.text
    assert _contexts(fake_sentry) == ["external_api.embedding_evict"]


def test_capture_handled_against_real_sdk_client_without_network(monkeypatch):
    """Pin the SDK call shape: a real Client with an in-memory transport must
    receive the event with the ``context`` tag (guards sentry-sdk API drift
    that the stub module above cannot see)."""
    import sentry_sdk
    from sentry_sdk.transport import Transport

    events: list[dict] = []

    class MemoryTransport(Transport):
        def capture_envelope(self, envelope):
            events.extend(ev for ev in (item.get_event() for item in envelope.items) if ev)

    client = sentry_sdk.Client(
        dsn="https://public@sentry.example/1", transport=MemoryTransport, default_integrations=False
    )
    monkeypatch.setattr(si, "_initialized", True)
    monkeypatch.setattr(si, "_sentry_module", sentry_sdk)
    with sentry_sdk.new_scope() as scope:
        scope.set_client(client)
        assert si.capture_handled(RuntimeError("real"), context="unit.real", tags={"step": "s"}) is True

    assert len(events) == 1
    assert events[0]["tags"] == {"context": "unit.real", "step": "s"}


def _run_background_with_step_error(monkeypatch, exc: BaseException):
    from kg.pipeline_service import runner

    async def raising_step(*_a, **_k):
        raise exc

    async def get_lock(_uid):
        return asyncio.Lock()

    monkeypatch.setattr(runner, "_run_step", raising_step)
    monkeypatch.setattr(runner, "_telemetry", lambda *_a, **_k: None)
    asyncio.run(
        runner.run_pipeline_background(
            {"id": "u-sentry", "dir": None, "config": {}},
            get_user_lock_fn=get_lock,
            card_store_factory=lambda _dir: None,
            graph_store_factory=lambda _dir, notebook_id="default": None,
            embedding_store_factory=lambda _dir, llm=None, notebook_id="default": None,
            client_factory=lambda _provider: None,
            logger=logging.getLogger("t.sentry.bg"),
            link_kind_enum=lambda value: value,
            run_id="r-sentry",
            telemetry_started=True,
        )
    )


def test_pipeline_unexpected_step_error_leak_reports_with_context(fake_sentry, monkeypatch):
    exc = RuntimeError("leaked from step")
    _run_background_with_step_error(monkeypatch, exc)
    assert [e for e, _ in fake_sentry.captured] == [exc]
    assert _contexts(fake_sentry) == ["pipeline.run"]


def test_pipeline_non_recoverable_error_reports_with_context(fake_sentry, monkeypatch):
    exc = KeyError("user deleted mid-queue")
    _run_background_with_step_error(monkeypatch, exc)
    assert [e for e, _ in fake_sentry.captured] == [exc]
    assert _contexts(fake_sentry) == ["pipeline.run_aborted"]
