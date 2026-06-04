"""KG LLM Eval / Prompt Engineering Workbench.

Core API for agents:

    from llm_eval import run_eval, compare_prompts
    from llm_eval.registry import PromptRegistry
    from llm_eval.datasets import load_dataset

    registry = PromptRegistry()
    prompt = registry.render("translate_quick", word="evoke", context="...")
    dataset = load_dataset("translate_quick")
    results = run_eval(prompt, dataset, models=["gemma3:4b", "gemini-2.5-flash-lite"])
"""

from __future__ import annotations

from .config import EvalConfig
from .datasets import load_dataset
from .registry import PromptRegistry, RenderedPrompt
from .runner import EvalResult, EvalSummary, run_eval

__all__ = [
    "EvalConfig",
    "EvalResult",
    "EvalSummary",
    "PromptRegistry",
    "RenderedPrompt",
    "load_dataset",
    "run_eval",
    "compare_prompts",
]


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
