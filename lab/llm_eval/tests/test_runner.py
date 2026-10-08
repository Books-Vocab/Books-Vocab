"""Tests for async eval runner."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from llm_eval import providers
from llm_eval.config import EvalConfig
from llm_eval.providers import EVAL_MAX_RETRIES, resolve_provider
from llm_eval.registry import RenderedPrompt
from llm_eval.runner import _call_one, run_eval


@pytest.fixture
def mock_prompt():
    return RenderedPrompt(
        name="test",
        version="v1",
        system=None,
        user="Translate: {{ word }}",
        schema={},
    )


@pytest.fixture
def sample():
    return {"id": "test_001", "word": "hello"}


@pytest.mark.asyncio
async def test_call_one_success(mock_prompt, sample):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        result = await _call_one(
            "gemini",
            "gemini-2.5-flash-lite",
            mock_prompt,
            sample,
            EvalConfig(prompt_name="test"),
        )

    assert result.sample_id == "test_001"
    assert result.model == "gemini-2.5-flash-lite"
    assert result.provider == "gemini"
    assert result.error is None
    assert result.parsed_output == {"t": "你好"}
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.scores == {}


@pytest.mark.asyncio
async def test_call_one_timeout(mock_prompt, sample):
    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError
        )
        mock_client_factory.return_value = mock_client

        result = await _call_one(
            "gemini",
            "gemini-2.5-flash-lite",
            mock_prompt,
            sample,
            EvalConfig(prompt_name="test", cloud_timeout_s=0.01),
        )

    assert result.error == "timeout"
    assert result.parsed_output is None


@pytest.mark.asyncio
async def test_call_one_missing_provider_key_marks_error_before_remote(
    mock_prompt, sample, monkeypatch
):
    """A missing key is a per-model failure: it is recorded on the result and
    no request is sent with a fake key."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    sent: list[object] = []

    def _handler(request):
        sent.append(request)
        return httpx.Response(500)

    _route_sdk_through(monkeypatch, _handler)

    result = await _call_one(
        "gemini",
        "gemini-2.5-flash-lite",
        mock_prompt,
        sample,
        EvalConfig(prompt_name="test"),
    )

    assert result.error == "missing_api_key: GEMINI_API_KEY"
    assert result.parsed_output is None
    assert sent == []


@pytest.mark.asyncio
async def test_run_eval_missing_key_is_isolated_to_that_model(mock_prompt, monkeypatch):
    """One provider without a key must not abort the run or drop other models."""
    monkeypatch.delenv(resolve_provider("gemini").api_key_env, raising=False)
    monkeypatch.setenv(resolve_provider("deepseek").api_key_env, "test-key")
    real_factory = providers.create_eval_async_client
    called_models: list[str] = []

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    async def _create(**kwargs):
        called_models.append(kwargs["model"])
        return mock_resp

    def _factory(provider):
        real_factory(provider)  # keeps the real missing-key guard in the path
        client = MagicMock()
        client.chat.completions.create = _create
        return client

    samples = [{"id": "s1", "word": "hello"}, {"id": "s2", "word": "world"}]
    with patch("llm_eval.runner.create_eval_async_client", side_effect=_factory):
        results = await run_eval(
            mock_prompt, samples, ["gemini-2.5-flash-lite", "deepseek-v4-flash"]
        )

    missing = results["gemini-2.5-flash-lite"]
    assert missing.error_count == 2
    assert {r.error for r in missing.samples} == {"missing_api_key: GEMINI_API_KEY"}
    healthy = results["deepseek-v4-flash"]
    assert healthy.success_count == 2
    assert healthy.error_count == 0
    assert called_models == ["deepseek-v4-flash", "deepseek-v4-flash"]


def _route_sdk_through(monkeypatch, handler):
    """Make the production client factory build a real ``AsyncOpenAI`` whose
    HTTP layer is ``handler`` — the SDK's own retry/backoff stays in the path."""
    real_client = openai.AsyncOpenAI

    def _client(**kwargs):
        return real_client(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(openai, "AsyncOpenAI", _client)


def _completion_payload(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gemini-2.5-flash-lite",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.mark.asyncio
async def test_call_one_retries_rate_limit_with_backoff_then_succeeds(
    mock_prompt, sample, monkeypatch
):
    """429 twice then 200 → success, with exponential backoff between attempts."""
    monkeypatch.setenv(resolve_provider("gemini").api_key_env, "test-key")
    statuses = iter([429, 429, 200])
    sent: list[float] = []

    def _handler(request):
        sent.append(time.monotonic())
        status = next(statuses)
        if status == 200:
            return httpx.Response(200, json=_completion_payload('{"t":"你好"}'))
        return httpx.Response(status, json={"error": {"message": "rate limited"}})

    _route_sdk_through(monkeypatch, _handler)

    result = await _call_one(
        "gemini",
        "gemini-2.5-flash-lite",
        mock_prompt,
        sample,
        EvalConfig(prompt_name="test"),
    )

    assert result.error is None
    assert result.parsed_output == {"t": "你好"}
    assert len(sent) == EVAL_MAX_RETRIES + 1
    # SDK backoff floor: 0.5s * 2**n * jitter(>=0.75) per retry.
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    assert gaps[0] >= 0.375
    assert gaps[1] >= 0.75


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_call_one_retry_is_bounded(mock_prompt, sample, monkeypatch, status):
    """A persistent 429/5xx stops after the bounded attempt budget and is
    recorded as an error instead of retrying forever."""
    monkeypatch.setenv(resolve_provider("gemini").api_key_env, "test-key")
    sent: list[object] = []

    def _handler(request):
        sent.append(request)
        return httpx.Response(
            status, headers={"retry-after-ms": "5"}, json={"error": {"message": "nope"}}
        )

    _route_sdk_through(monkeypatch, _handler)

    result = await _call_one(
        "gemini",
        "gemini-2.5-flash-lite",
        mock_prompt,
        sample,
        EvalConfig(prompt_name="test"),
    )

    assert len(sent) == EVAL_MAX_RETRIES + 1
    assert result.parsed_output is None
    assert result.error is not None
    assert result.error.startswith(("RateLimitError", "InternalServerError"))


def test_eval_clients_pin_the_retry_budget(monkeypatch):
    monkeypatch.setenv(resolve_provider("gemini").api_key_env, "test-key")
    provider = resolve_provider("gemini")

    assert EVAL_MAX_RETRIES >= 1
    assert providers.create_eval_async_client(provider).max_retries == EVAL_MAX_RETRIES
    assert providers.create_eval_client(provider).max_retries == EVAL_MAX_RETRIES


@pytest.mark.asyncio
async def test_ollama_probe_does_not_block_event_loop(mock_prompt, sample):
    """The reachability probe must run off the event-loop thread and close
    its response."""
    probes: list[dict[str, bool]] = []

    class _Response:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

        def close(self):
            self.closed = True

    responses: list[_Response] = []

    def _urlopen(url, timeout=None):
        try:
            asyncio.get_running_loop()
            on_loop_thread = True
        except RuntimeError:
            on_loop_thread = False
        probes.append({"on_loop_thread": on_loop_thread})
        responses.append(_Response())
        return responses[-1]

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

    with (
        patch("urllib.request.urlopen", side_effect=_urlopen),
        patch("llm_eval.runner.create_eval_async_client") as mock_client_factory,
    ):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        result = await _call_one(
            "ollama", "gemma3:4b", mock_prompt, sample, EvalConfig(prompt_name="test")
        )

    assert result.error is None
    assert probes == [{"on_loop_thread": False}]
    assert all(r.closed for r in responses)


@pytest.mark.asyncio
async def test_call_one_ollama_unreachable(mock_prompt, sample):
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        result = await _call_one(
            "ollama", "gemma3:4b", mock_prompt, sample, EvalConfig(prompt_name="test")
        )

    assert result.error == "ollama_unavailable"


@pytest.mark.asyncio
async def test_run_eval_basic(mock_prompt):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        samples = [
            {"id": "s1", "word": "hello"},
            {"id": "s2", "word": "world"},
        ]
        results = await run_eval(mock_prompt, samples, ["gemini-2.5-flash-lite"])

    assert "gemini-2.5-flash-lite" in results
    summary = results["gemini-2.5-flash-lite"]
    assert summary.sample_count == 2
    assert summary.success_count == 2
    assert summary.error_count == 0
    assert len(summary.samples) == 2


@pytest.mark.asyncio
async def test_run_eval_duplicate_models_are_called_once(mock_prompt):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"x"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as factory:
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=mock_resp)
        factory.return_value = client
        samples = [{"id": "s1", "word": "a"}, {"id": "s2", "word": "b"}]
        m = "gemini-2.5-flash-lite"
        results = await run_eval(mock_prompt, samples, [m, m])

    assert list(results) == [m]
    assert results[m].sample_count == 2
    assert results[m].total_input_tokens == 20
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_run_eval_scores_each_result_for_prompt_name():
    prompt = RenderedPrompt(
        name="translate_quick",
        version="v1",
        system=None,
        user="Translate: hello",
        schema={},
    )
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(content='{"t":"輝煌的","p":"adj.","r":"resplendent"}')
        )
    ]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            prompt,
            [{"id": "s1", "word": "resplendent", "gold_status": "unverified"}],
            ["gemini-2.5-flash-lite"],
        )

    summary = results["gemini-2.5-flash-lite"]
    assert summary.samples[0].scores["json_valid"] == 1.0
    assert summary.samples[0].scores["pos_correct"] == 1.0
    assert summary.format_score_avg == 1.0
    assert summary.quality_score_avg is None


@pytest.mark.asyncio
async def test_run_eval_quality_score_is_never_auto_scored():
    """Quality is agent-reviewed, not auto-scored — quality_score_avg stays None
    even for human_gold samples; only format scoring runs automatically."""
    prompt = RenderedPrompt(
        name="translate_quick",
        version="v1",
        system=None,
        user="Translate: hello",
        schema={},
    )
    responses = [
        MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content='{"t":"輝煌的","p":"adj.","r":"resplendent"}'
                    )
                )
            ],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5),
        ),
        MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content='{"t":"輝煌","p":"adj.","r":"resplendent"}'
                    )
                )
            ],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5),
        ),
    ]

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=responses)
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            prompt,
            [
                {
                    "id": "gold",
                    "word": "resplendent",
                    "gold_status": "human_gold",
                    "gold_translation": "輝煌的",
                    "gold_pos": "adj.",
                    "gold_root": "resplendent",
                },
                {
                    "id": "candidate",
                    "word": "resplendent",
                    "gold_status": "unverified",
                },
            ],
            ["gemini-2.5-flash-lite"],
        )

    summary = results["gemini-2.5-flash-lite"]
    assert summary.sample_count == 2
    assert summary.quality_score_avg is None
    assert summary.format_score_avg == 1.0


@pytest.mark.asyncio
async def test_call_one_preserves_json_list_for_judge_and_enrich(mock_prompt, sample):
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content='[{"word":"sloppy","link":"contrasts_with","confidence":0.9,"reason":"相反的意思"}]'
            )
        )
    ]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        result = await _call_one(
            "gemini",
            "gemini-2.5-flash-lite",
            mock_prompt,
            sample,
            EvalConfig(prompt_name="judge_batch"),
        )

    assert isinstance(result.parsed_output, list)
    assert result.parsed_output[0]["word"] == "sloppy"
    assert result.scores["schema_conform"] == 1.0
    assert result.scores["link_valid"] == 1.0


@pytest.mark.asyncio
async def test_translate_prompt_rejects_json_list_schema(sample):
    prompt = RenderedPrompt(
        name="translate_quick",
        version="v1",
        system=None,
        user="Translate",
        schema={},
    )
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content='[{"t":"喚起","p":"v.","r":"evoke"}]'))
    ]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        result = await _call_one(
            "gemini",
            "gemini-2.5-flash-lite",
            prompt,
            sample,
            EvalConfig(prompt_name="translate_quick"),
        )

    assert isinstance(result.parsed_output, list)
    assert result.scores["json_valid"] == 1.0
    assert result.scores["schema_conform"] == 0.0


@pytest.mark.asyncio
async def test_errored_result_excluded_from_format_score():
    prompt = RenderedPrompt(
        name="translate_quick",
        version="v1",
        system=None,
        user="Translate",
        schema={},
    )

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError
        )
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            prompt,
            [
                {
                    "id": "gold",
                    "word": "evoke",
                    "gold_status": "human_gold",
                    "gold_translation": "喚起",
                    "gold_pos": "v.",
                    "gold_root": "evoke",
                }
            ],
            ["gemini-2.5-flash-lite"],
            EvalConfig(prompt_name="translate_quick", cloud_timeout_s=0.01),
        )

    summary = results["gemini-2.5-flash-lite"]
    assert summary.error_count == 1
    assert summary.format_score_avg is None
    assert summary.quality_score_avg is None


@pytest.mark.asyncio
async def test_human_gold_schema_failure_lowers_format_score(sample):
    prompt = RenderedPrompt(
        name="translate_quick",
        version="v1",
        system=None,
        user="Translate",
        schema={},
    )
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content='[{"t":"喚起","p":"v.","r":"evoke"}]'))
    ]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            prompt,
            [
                {
                    "id": "test_001",
                    "word": "evoke",
                    "gold_status": "human_gold",
                    "gold_translation": "喚起",
                    "gold_pos": "v.",
                    "gold_root": "evoke",
                }
            ],
            ["gemini-2.5-flash-lite"],
            EvalConfig(prompt_name="translate_quick"),
        )

    summary = results["gemini-2.5-flash-lite"]
    # list-shaped output fails dict schema → schema_conform 0 → format < 1
    assert summary.format_score_avg == 0.5
    assert summary.quality_score_avg is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("concurrency", 0), ("concurrency", -1), ("limit", 0), ("limit", -3)],
)
def test_eval_config_rejects_counts_below_one(field, value):
    """concurrency 0 → Semaphore(0) → every call waits forever; limit 0 is
    falsy → the whole dataset runs."""
    with pytest.raises(ValueError, match=field):
        EvalConfig(prompt_name="test", **{field: value})


def _priced_response() -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    resp.usage = MagicMock(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    return resp


@pytest.mark.asyncio
async def test_run_eval_cost_uses_the_model_price_not_the_provider_default(
    mock_prompt,
):
    """gemini-2.5-flash routes to the gemini provider, whose registry price is
    for its chat_model (gemini-2.5-flash-lite)."""
    gemini = resolve_provider("gemini")
    assert gemini.chat_model == "gemini-2.5-flash-lite"
    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_priced_response())
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            mock_prompt,
            [{"id": "s1", "word": "hello"}],
            ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        )

    # 1M input + 1M output tokens at Gemini 2.5 Flash list price ($0.30/$2.50).
    assert results["gemini-2.5-flash"].total_cost_usd == pytest.approx(2.80)
    assert results["gemini-2.5-flash-lite"].total_cost_usd == pytest.approx(
        gemini.input_price_per_m + gemini.output_price_per_m
    )


@pytest.mark.asyncio
async def test_run_eval_cost_is_unknown_for_a_model_without_a_price(
    mock_prompt, monkeypatch
):
    """If the provider default moves on, the old model must not be billed at
    the new default's price."""
    import dataclasses

    from kg.llm.providers import REGISTRY

    monkeypatch.setitem(
        REGISTRY,
        "gemini",
        dataclasses.replace(REGISTRY["gemini"], chat_model="gemini-next-flash"),
    )
    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_priced_response())
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            mock_prompt, [{"id": "s1", "word": "hello"}], ["gemini-2.5-flash-lite"]
        )

    assert results["gemini-2.5-flash-lite"].total_cost_usd is None


@pytest.mark.asyncio
async def test_provider_alias_requests_and_prices_the_providers_chat_model(
    mock_prompt,
):
    """`--models gemini` means the gemini provider's model; sending the literal
    "gemini" as the model name is rejected by the API."""
    gemini = resolve_provider("gemini")
    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_priced_response())
        mock_client_factory.return_value = mock_client

        results = await run_eval(
            mock_prompt, [{"id": "s1", "word": "hello"}], ["gemini"]
        )

    sent = mock_client.chat.completions.create.await_args.kwargs["model"]
    assert sent == gemini.chat_model
    assert results["gemini"].total_cost_usd == pytest.approx(
        gemini.input_price_per_m + gemini.output_price_per_m
    )


@pytest.mark.asyncio
async def test_run_eval_with_limit(mock_prompt):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        samples = [
            {"id": "s1", "word": "hello"},
            {"id": "s2", "word": "world"},
            {"id": "s3", "word": "foo"},
        ]
        config = EvalConfig(prompt_name="test", limit=2)
        results = await run_eval(
            mock_prompt, samples, ["gemini-2.5-flash-lite"], config
        )

    assert results["gemini-2.5-flash-lite"].sample_count == 2


@pytest.mark.asyncio
async def test_run_eval_render_fn_per_sample():
    """render_fn must be called once per sample, not reuse the static prompt."""
    rendered_words: list[str] = []

    def _render_fn(sample: dict) -> RenderedPrompt:
        rendered_words.append(sample["word"])
        return RenderedPrompt(
            name="test",
            version="v1",
            system=None,
            user=f"Translate: {sample['word']}",
            schema={},
        )

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"譯"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=5, completion_tokens=2)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        samples = [
            {"id": "a", "word": "evoke"},
            {"id": "b", "word": "meticulous"},
            {"id": "c", "word": "resilient"},
        ]
        static_prompt = RenderedPrompt(
            name="test", version="v1", system=None, user="STATIC", schema={}
        )
        await run_eval(
            static_prompt, samples, ["gemini-2.5-flash-lite"], render_fn=_render_fn
        )

    assert rendered_words == ["evoke", "meticulous", "resilient"]


@pytest.mark.asyncio
async def test_call_one_render_fn_overrides_prompt(sample):
    """_call_one must use render_fn output, not the static prompt arg."""
    override_prompt = RenderedPrompt(
        name="override", version="v1", system=None, user="override user", schema={}
    )

    def _render_fn(_sample: dict) -> RenderedPrompt:
        return override_prompt

    captured_messages: list = []

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="{}"))]
    mock_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

    async def _capture(**kwargs):
        captured_messages.extend(kwargs["messages"])
        return mock_resp

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = _capture
        mock_client_factory.return_value = mock_client

        static_prompt = RenderedPrompt(
            name="static", version="v1", system=None, user="STATIC", schema={}
        )
        await _call_one(
            "gemini",
            "gemini-2.5-flash-lite",
            static_prompt,
            sample,
            EvalConfig(prompt_name="test"),
            render_fn=_render_fn,
        )

    assert any(m["content"] == "override user" for m in captured_messages)
    assert not any(m["content"] == "STATIC" for m in captured_messages)
