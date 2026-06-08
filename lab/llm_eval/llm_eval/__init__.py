"""KG LLM Eval / Prompt Engineering Workbench.

Core API for agents:

    from llm_eval import run_eval, make_render_fn, compare_prompts
    from llm_eval.registry import PromptRegistry
    from llm_eval.datasets import load_dataset

    registry = PromptRegistry()
    dataset = load_dataset("translate_quick")
    render_fn = make_render_fn(registry, "translate_quick")
    results = await run_eval(
        prompt=render_fn(dataset[0]),  # fallback prompt (render_fn overrides per sample)
        samples=dataset,
        models=["gemma3:4b", "gemini-2.5-flash-lite"],
        render_fn=render_fn,
    )
"""

from __future__ import annotations

from collections.abc import Callable

from .config import EvalConfig
from .corpus import build_private_corpus, sanitize_context
from .datasets import load_dataset
from .gold_queue import build_gold_review_queue
from .reporting import compare_to_baseline, write_report
from .registry import PromptRegistry, RenderedPrompt
from .runner import EvalResult, EvalSummary, run_eval

__all__ = [
    "EvalConfig",
    "EvalResult",
    "EvalSummary",
    "PromptRegistry",
    "RenderedPrompt",
    "build_gold_review_queue",
    "build_private_corpus",
    "compare_to_baseline",
    "load_dataset",
    "make_render_fn",
    "run_eval",
    "sanitize_context",
    "write_report",
    "compare_prompts",
]

_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "zh-Hant": "Traditional Chinese",
    "zh-Hans": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
}


def make_render_fn(
    registry: PromptRegistry,
    name: str,
    version: str | None = None,
    **extra_vars,
) -> Callable[[dict], RenderedPrompt]:
    """Build a per-sample render_fn for use with run_eval(render_fn=...).

    Maps dataset sample fields to prompt template vars. Handles language
    name expansion (source_lang/target_lang → *_lang_name).
    """
    def _render(sample: dict) -> RenderedPrompt:
        vars: dict = {**sample, **extra_vars}
        vars.setdefault(
            "source_lang_name",
            _LANG_NAMES.get(sample.get("source_lang", "en"), sample.get("source_lang", "English")),
        )
        vars.setdefault(
            "target_lang_name",
            _LANG_NAMES.get(sample.get("target_lang", "zh-Hant"), sample.get("target_lang", "Traditional Chinese")),
        )
        candidates = sample.get("candidates")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], list):
            lines = [f"- {c[1]} ({c[2]})" for c in candidates if len(c) >= 3]
            vars.setdefault("candidate_list", "\n".join(lines))
            vars.setdefault("n", str(len(candidates)))
            vars.setdefault("max_links", str(max(1, len(candidates) // 2)))
        return registry.render(name, version, **vars)

    return _render


def compare_prompts(
    prompt_base: RenderedPrompt,
    prompt_variants: list[RenderedPrompt],
    samples: list[dict],
    model: str,
    config: EvalConfig | None = None,
) -> dict[str, EvalSummary]:
    """Compare multiple prompt variants on the same model and dataset.

    Returns dict[prompt_name, EvalSummary].
    """
    import asyncio

    async def _run():
        from .runner import run_eval as _run_eval
        results = {}
        for prompt in [prompt_base] + prompt_variants:
            summaries = await _run_eval(prompt, samples, [model], config)
            key = f"{prompt.name}_v{prompt.version}"
            results[key] = summaries.get(model)
        return results

    return asyncio.run(_run())
