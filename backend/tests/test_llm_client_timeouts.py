"""#2059: LLM clients must fail a stalled provider within a bounded time.

The OpenAI SDK defaults are ``read=600s`` and ``max_retries=2``: a provider
that accepts the connection and never answers holds the request — and the
caller's in-flight quota reservation (``TrackedLLM`` wraps the whole SDK call,
retries included, in ``quota_service.reserve``) — for ~3 x 600s = 30 minutes.

The stall is simulated with ``httpx.MockTransport``: the handler reads the
read timeout the SDK put on each request and raises ``httpx.ReadTimeout``
when the simulated stall exceeds it, which is exactly what a real transport
does after that many seconds. The production clients are exercised through
``with_options(http_client=...)``, which keeps their timeout/retry policy.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx
import openai
import pytest

import kg.quota_service as qs
from kg.llm.providers import REGISTRY
from kg.service_factories import create_async_client, create_client, reset_async_clients, reset_clients
from kg.tracked_llm import TrackedLLM
from kg.vocab_graph import embed_and_link_new_cards

# Longest a single TrackedLLM call may hold its reservation against a provider
# that never answers: every attempt's read timeout, summed over the SDK's
# retries. Five minutes keeps a stuck call from pinning a user's quota for
# the better part of an hour while leaving room for a slow legit generation.
_MAX_STALLED_HOLD_S = 300.0
_STALL_S = 3600.0
_USER = "u-stall-2059"


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-2059")
    reset_clients()
    asyncio.run(reset_async_clients())
    qs.clear_reservations()
    yield
    reset_clients()
    asyncio.run(reset_async_clients())
    qs.clear_reservations()


@pytest.fixture
def failures(monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setattr("kg.llm_error_log.record", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr("kg.tracked_llm.record", lambda *a, **k: None)
    return recorded


@dataclass
class _StalledProvider:
    """Never answers: each attempt times out after the client's read timeout."""

    read_timeouts: list[float | None] = field(default_factory=list)
    reserved_during_attempt: list[float] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        read_timeout = request.extensions["timeout"]["read"]
        self.read_timeouts.append(read_timeout)
        self.reserved_during_attempt.append(qs._reserved_usd(_USER))
        if read_timeout is None or _STALL_S > read_timeout:
            raise httpx.ReadTimeout("provider stalled", request=request)
        raise AssertionError(f"read timeout {read_timeout}s is longer than the simulated stall")

    def simulated_hold_s(self) -> float:
        return sum(t if t is not None else float("inf") for t in self.read_timeouts)


def _messages() -> list[dict]:
    return [{"role": "user", "content": "hi"}]


@pytest.mark.parametrize("factory", [create_client, create_async_client], ids=["sync", "async"])
def test_clients_declare_bounded_timeout_and_retries(factory):
    client = factory(REGISTRY["gemini"])
    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.connect is not None and client.timeout.connect <= 10
    for phase in ("read", "write", "pool"):
        value = getattr(client.timeout, phase)
        assert value is not None and value <= 120, f"{phase} timeout {value!r}s is unbounded/too long"
    assert client.max_retries <= 1
    assert (client.max_retries + 1) * client.timeout.read <= _MAX_STALLED_HOLD_S


def test_sync_stalled_provider_fails_bounded_and_releases_reservation(failures):
    stalled = _StalledProvider()
    base = create_client(REGISTRY["gemini"])
    client = base.with_options(http_client=httpx.Client(transport=httpx.MockTransport(stalled)))
    llm = TrackedLLM(client, _USER, provider=REGISTRY["gemini"])
    try:
        with pytest.raises(openai.APITimeoutError):
            llm.chat("translate_quick", model=REGISTRY["gemini"].chat_model, messages=_messages())
    finally:
        client.close()

    assert len(stalled.read_timeouts) == base.max_retries + 1
    assert stalled.simulated_hold_s() <= _MAX_STALLED_HOLD_S
    assert all(held > 0 for held in stalled.reserved_during_attempt), "reservation must cover every attempt"
    assert qs._reserved_usd(_USER) == 0.0, "reservation leaked after the bounded failure"
    assert [f["error_class"] for f in failures] == ["APITimeoutError"]


def test_async_stalled_provider_fails_bounded_and_releases_reservation(failures):
    stalled = _StalledProvider()
    base = create_async_client(REGISTRY["gemini"])

    async def run() -> None:
        client = base.with_options(http_client=httpx.AsyncClient(transport=httpx.MockTransport(stalled)))
        llm = TrackedLLM(client, _USER, provider=REGISTRY["gemini"])
        try:
            with pytest.raises(openai.APITimeoutError):
                await llm.chat_async("translate_quick", model=REGISTRY["gemini"].chat_model, messages=_messages())
        finally:
            await client.close()

    asyncio.run(run())

    assert len(stalled.read_timeouts) == base.max_retries + 1
    assert stalled.simulated_hold_s() <= _MAX_STALLED_HOLD_S
    assert all(held > 0 for held in stalled.reserved_during_attempt), "reservation must cover every attempt"
    assert qs._reserved_usd(_USER) == 0.0, "reservation leaked after the bounded failure"
    assert [f["error_class"] for f in failures] == ["APITimeoutError"]


class _Card:
    def __init__(self, card_id: str) -> None:
        self.id = card_id

    def embed_text(self) -> str:
        return "cat"


class _Cards:
    def get(self, card_id: str) -> _Card:
        return _Card(card_id)


class _TimingOutEmbeddings:
    def has(self, card_id: str) -> bool:
        return False

    def add_batch(self, items):
        raise openai.APITimeoutError(request=httpx.Request("POST", "https://provider.test/embeddings"))


class _Graph:
    def __init__(self) -> None:
        self.pending: list[str] = []

    def add_pending_judge(self, ids) -> None:
        self.pending.extend(ids)


def test_intake_embed_timeout_does_not_fail_the_add():
    """Cards are already durable when intake embeds; a now-bounded provider
    timeout must degrade like the pipeline's embed step (warn, backfill next
    run), not turn the successful add into a 5xx the client retries."""

    @dataclass
    class _Entry:
        word: str

    graph = _Graph()
    embed_and_link_new_cards(
        cards=_Cards(),
        embeddings=_TimingOutEmbeddings(),
        graph=graph,
        card_ids={"cat": "c1"},
        entries=[_Entry(word="cat")],
        logger=logging.getLogger("test.2059"),
    )
    assert graph.pending == []
