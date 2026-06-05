"""Async execution engine for eval: parallel model calls, retry, result aggregation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import EvalConfig
from .providers import create_eval_async_client, resolve_provider
from .registry import RenderedPrompt

logger = logging.getLogger("llm_eval")


@dataclass(frozen=True)
class EvalResult:
    """Result for one (model, sample) pair."""

    sample_id: str
    model: str
    provider: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    raw_output: str
    parsed_output: dict[str, Any] | None
    error: str | None = None


@dataclass
class EvalSummary:
    """Aggregated results for one model across all samples."""

    model: str
    provider: str
    sample_count: int
    success_count: int
    error_count: int
    avg_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    samples: list[EvalResult] = field(default_factory=list)


def _model_to_provider_name(model: str) -> str:
    """Map a model name to its provider."""
    # Direct provider name
    try:
        resolve_provider(model)
        return model
    except ValueError:
        pass
    # Known model → provider mapping
    _MODEL_MAP: dict[str, str] = {
        "gemma3:4b": "ollama",
        "gemini-2.5-flash-lite": "gemini",
        "gemini-2.5-flash": "gemini",
        "deepseek-v4-flash": "deepseek",
    }
    provider = _MODEL_MAP.get(model)
    if provider:
        return provider
    # Fallback: try each provider's chat_model
    from kg.llm.providers import REGISTRY
    for name, p in REGISTRY.items():
        if p.chat_model == model:
            return name
    raise ValueError(f"Cannot resolve provider for model {model!r}")


async def _call_one(
    provider_name: str,
    model: str,
    prompt: RenderedPrompt,
    sample: dict[str, Any],
    config: EvalConfig,
    render_fn: Callable[[dict[str, Any]], RenderedPrompt] | None = None,
) -> EvalResult:
    """Call one LLM for one sample."""
    if render_fn is not None:
        prompt = render_fn(sample)
    provider = resolve_provider(provider_name)
    sample_id = sample.get("id", sample.get("word", "unknown"))

    # Check Ollama reachability
    if provider.name == "ollama":
        import urllib.request
        try:
            urllib.request.urlopen(provider.base_url.replace("/v1", ""), timeout=2)
        except Exception:
            return EvalResult(
                sample_id=sample_id,
                model=model,
                provider=provider.name,
                latency_ms=0,
                input_tokens=0,
                output_tokens=0,
                raw_output="",
                parsed_output=None,
                error="ollama_unavailable",
            )

    client = create_eval_async_client(provider)
    messages: list[dict[str, str]] = []
    if prompt.system:
        messages.append({"role": "system", "content": prompt.system})
    messages.append({"role": "user", "content": prompt.user})

    kwargs: dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=config.temperature,
    )
    if prompt.response_format:
        kwargs["response_format"] = prompt.response_format
    if provider.extra_body:
        kwargs["extra_body"] = dict(provider.extra_body)
    if provider.max_tokens_default is not None:
        kwargs["max_tokens"] = provider.max_tokens_default

    timeout = config.ollama_timeout_s if provider.name == "ollama" else config.cloud_timeout_s

    t0 = time.time()
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=timeout,
        )
        latency_ms = int((time.time() - t0) * 1000)
        content = resp.choices[0].message.content if resp.choices else ""
        usage = getattr(resp, "usage", None)

        # Try parse JSON
        parsed: dict[str, Any] | None = None
        if content:
            try:
                data = json.loads(content)
                if isinstance(data, list) and data:
                    data = data[0]
                if isinstance(data, dict):
                    parsed = data
            except json.JSONDecodeError:
                pass

        return EvalResult(
            sample_id=sample_id,
            model=model,
            provider=provider.name,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0 if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0 if usage else 0,
            raw_output=content or "",
            parsed_output=parsed,
            error=None,
        )
    except asyncio.TimeoutError:
        return EvalResult(
            sample_id=sample_id, model=model, provider=provider.name,
            latency_ms=int((time.time() - t0) * 1000),
            input_tokens=0, output_tokens=0, raw_output="", parsed_output=None,
            error="timeout",
        )
    except Exception as exc:
        return EvalResult(
            sample_id=sample_id, model=model, provider=provider.name,
            latency_ms=int((time.time() - t0) * 1000),
            input_tokens=0, output_tokens=0, raw_output="", parsed_output=None,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_eval(
    prompt: RenderedPrompt,
    samples: list[dict[str, Any]],
    models: list[str],
    config: EvalConfig | None = None,
    render_fn: Callable[[dict[str, Any]], RenderedPrompt] | None = None,
) -> dict[str, EvalSummary]:
    """Run eval: one prompt against multiple models on a dataset.

    Pass render_fn to re-render the prompt per sample (required when prompt
    contains per-sample variables like word/context). The static prompt arg
    is used as fallback when render_fn is None.

    Returns dict[model_name, EvalSummary].
    """
    config = config or EvalConfig(prompt_name=prompt.name)

    # Filter samples
    if config.sample_ids:
        samples = [s for s in samples if s.get("id") in config.sample_ids]
    if config.limit:
        samples = samples[:config.limit]

    # Resolve providers
    provider_map: dict[str, str] = {}
    for m in models:
        try:
            provider_map[m] = _model_to_provider_name(m)
        except ValueError as exc:
            logger.warning("Skipping model %s: %s", m, exc)

    # Run all (model, sample) pairs with per-provider concurrency limit
    semaphores: dict[str, asyncio.Semaphore] = {
        pname: asyncio.Semaphore(config.concurrency)
        for pname in set(provider_map.values())
    }

    async def _run_with_sem(model: str, sample: dict[str, Any]) -> EvalResult:
        pname = provider_map[model]
        async with semaphores[pname]:
            return await _call_one(pname, model, prompt, sample, config, render_fn)

    tasks = [
        _run_with_sem(m, s)
        for m in models if m in provider_map
        for s in samples
    ]
    results = await asyncio.gather(*tasks)

    # Aggregate by model
    summaries: dict[str, EvalSummary] = {}
    for m in models:
        if m not in provider_map:
            continue
        pname = provider_map[m]
        model_results = [r for r in results if r.model == m]

        success = sum(1 for r in model_results if r.error is None)
        errors = sum(1 for r in model_results if r.error is not None)
        latencies = [r.latency_ms for r in model_results if r.error is None]
        in_toks = sum(r.input_tokens for r in model_results)
        out_toks = sum(r.output_tokens for r in model_results)

        # Cost
        provider = resolve_provider(pname)
        cost = (
            in_toks * provider.input_price_per_m / 1_000_000
            + out_toks * provider.output_price_per_m / 1_000_000
        )

        summaries[m] = EvalSummary(
            model=m,
            provider=pname,
            sample_count=len(model_results),
            success_count=success,
            error_count=errors,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
            total_input_tokens=in_toks,
            total_output_tokens=out_toks,
            total_cost_usd=cost,
            samples=model_results,
        )

    return summaries
