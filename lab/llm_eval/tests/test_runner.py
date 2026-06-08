"""Tests for async eval runner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_eval.config import EvalConfig
from llm_eval.providers import MissingProviderApiKeyError
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

        result = await _call_one("gemini", "gemini-2.5-flash-lite", mock_prompt, sample, EvalConfig(prompt_name="test"))

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
        mock_client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_client_factory.return_value = mock_client

        result = await _call_one("gemini", "gemini-2.5-flash-lite", mock_prompt, sample, EvalConfig(prompt_name="test", cloud_timeout_s=0.01))

    assert result.error == "timeout"
    assert result.parsed_output is None


@pytest.mark.asyncio
async def test_call_one_missing_provider_key_raises_before_remote(mock_prompt, sample, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingProviderApiKeyError, match="GEMINI_API_KEY"):
        await _call_one(
            "gemini",
            "gemini-2.5-flash-lite",
            mock_prompt,
            sample,
            EvalConfig(prompt_name="test"),
        )


@pytest.mark.asyncio
async def test_call_one_ollama_unreachable(mock_prompt, sample):
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        result = await _call_one("ollama", "gemma3:4b", mock_prompt, sample, EvalConfig(prompt_name="test"))

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
async def test_run_eval_scores_each_result_for_prompt_name():
    prompt = RenderedPrompt(
        name="translate_quick",
        version="v1",
        system=None,
        user="Translate: hello",
        schema={},
    )
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"輝煌的","p":"adj.","r":"resplendent"}'))]
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
            choices=[MagicMock(message=MagicMock(content='{"t":"輝煌的","p":"adj.","r":"resplendent"}'))],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5),
        ),
        MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"t":"輝煌","p":"adj.","r":"resplendent"}'))],
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
    mock_resp.choices = [MagicMock(message=MagicMock(content='[{"t":"喚起","p":"v.","r":"evoke"}]'))]
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
        mock_client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError)
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
    mock_resp.choices = [MagicMock(message=MagicMock(content='[{"t":"喚起","p":"v.","r":"evoke"}]'))]
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
        results = await run_eval(mock_prompt, samples, ["gemini-2.5-flash-lite"], config)

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
        static_prompt = RenderedPrompt(name="test", version="v1", system=None, user="STATIC", schema={})
        await run_eval(static_prompt, samples, ["gemini-2.5-flash-lite"], render_fn=_render_fn)

    assert rendered_words == ["evoke", "meticulous", "resilient"]


@pytest.mark.asyncio
async def test_call_one_render_fn_overrides_prompt(sample):
    """_call_one must use render_fn output, not the static prompt arg."""
    override_prompt = RenderedPrompt(name="override", version="v1", system=None, user="override user", schema={})

    def _render_fn(_sample: dict) -> RenderedPrompt:
        return override_prompt

    captured_messages: list = []

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{}'))]
    mock_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

    async def _capture(**kwargs):
        captured_messages.extend(kwargs["messages"])
        return mock_resp

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = _capture
        mock_client_factory.return_value = mock_client

        static_prompt = RenderedPrompt(name="static", version="v1", system=None, user="STATIC", schema={})
        await _call_one("gemini", "gemini-2.5-flash-lite", static_prompt, sample, EvalConfig(prompt_name="test"), render_fn=_render_fn)

    assert any(m["content"] == "override user" for m in captured_messages)
    assert not any(m["content"] == "STATIC" for m in captured_messages)
