"""LLM provider A/B harness. **DEPRECATED** — use `lab/llm_eval/` instead.

⚠️  This module is deprecated. The LLM eval workbench in `lab/llm_eval/`
provides superset functionality: prompt comparison, model comparison,
rule-based scoring, and structured output for agent consumption.

Compares every provider with an API key configured, on KG's real
English→Traditional-Chinese translate prompt — the surface most sensitive
to provider quality. Calls the client directly (NOT via TrackedLLM) so an
A/B run never reserves quota or writes token_usage rows.

Usage::

    python -m kg.llm.ab                     # A/B all keyed providers, built-in sample
    python -m kg.llm.ab serendipity ephemeral   # A/B specific words
    python -m kg.llm.ab --dry-run           # show the plan, no API calls

Requires GEMINI_API_KEY and/or DEEPSEEK_API_KEY in the environment.

Redirect::

    cd lab/llm_eval
    PYTHONPATH=../../backend/src uv run python3 -c "
    from llm_eval import run_eval
    from llm_eval.registry import PromptRegistry
    from llm_eval.datasets import load_dataset
    r = PromptRegistry()
    p = r.render('translate_quick')
    d = load_dataset('translate_quick')
    print(run_eval(p, d, models=['gemini-2.5-flash-lite', 'deepseek-v4-flash']))
    "
"""
from __future__ import annotations

import os
import sys
import time
import warnings

from .providers import REGISTRY, LLMProvider

# Realistic vocab-app inputs: word + a sentence-length context.
SAMPLE_INPUTS: list[tuple[str, str]] = [
    ("evoke", "The old photograph can evoke memories of childhood summers."),
    ("meticulous", "She kept meticulous records of every transaction."),
    ("resilient", "The community proved remarkably resilient after the flood."),
    ("haggle", "Tourists often haggle with vendors at the night market."),
    ("ominous", "An ominous silence fell over the courtroom."),
    ("nuance", "He missed the nuance in her carefully worded reply."),
]

def available_providers() -> list[LLMProvider]:
    """Providers whose API-key env var is set, in registry order."""
    return [p for p in REGISTRY.values() if os.getenv(p.api_key_env)]


def run_one(provider: LLMProvider, word: str, context: str) -> dict:
    """One translate call against `provider`. Returns latency + output + tokens.

    Applies the provider's extra_body / max_tokens just like TrackedLLM, but
    bypasses quota reservation and token recording — this is an offline tool.
    """
    from ..api_models import TranslateRequest
    from ..service_factories import create_client
    from ..translate_service import build_quick_translate_prompt

    # Use KG's real translate prompt so the A/B reflects production fidelity.
    # Langs are passed explicitly (production resolves them via
    # resolve_translation_langs) so the prompt does not depend on None fallbacks.
    req = TranslateRequest(word=word, context=context)
    prompt = build_quick_translate_prompt(req, "en", "zh-Hant")

    client = create_client(provider)
    kwargs: dict = dict(
        model=provider.chat_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    if provider.extra_body:
        kwargs["extra_body"] = dict(provider.extra_body)
    if provider.max_tokens_default is not None:
        kwargs["max_tokens"] = provider.max_tokens_default

    t0 = time.time()
    resp = client.chat.completions.create(**kwargs)
    latency_s = time.time() - t0

    usage = getattr(resp, "usage", None)
    content = resp.choices[0].message.content if resp.choices else ""
    return {
        "provider": provider.name,
        "model": provider.chat_model,
        "latency_s": round(latency_s, 2),
        "content": (content or "").replace("\n", " ").strip(),
        "in_tokens": getattr(usage, "prompt_tokens", 0) or 0 if usage else 0,
        "out_tokens": getattr(usage, "completion_tokens", 0) or 0 if usage else 0,
    }


def main(argv: list[str] | None = None) -> int:
    warnings.warn(
        "kg.llm.ab is deprecated — use lab/llm_eval/ instead. "
        "See docs/reference/llm_eval.md for migration.",
        DeprecationWarning,
        stacklevel=2,
    )
    print("⚠️  kg.llm.ab is deprecated. Use lab/llm_eval/ for model/prompt comparison.")
    print("   See docs/reference/llm_eval.md")
    print()
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    words = [a for a in argv if not a.startswith("--")]
    samples = (
        [(w, f"The word {w} is used naturally in this sentence.") for w in words]
        if words
        else SAMPLE_INPUTS
    )
    providers = available_providers()

    print(f"Providers: {[p.name for p in providers] or '(none — set GEMINI_API_KEY / DEEPSEEK_API_KEY)'}")
    print(f"Samples: {len(samples)}")

    if dry_run:
        print("[dry-run] no API calls made.")
        return 0
    if not providers:
        print("No providers available — set an API key and retry.")
        return 1

    for word, context in samples:
        print(f"\n=== {word} ===  {context}")
        for provider in providers:
            try:
                r = run_one(provider, word, context)
                print(
                    f"  {r['provider']:9} {r['latency_s']:6.2f}s  "
                    f"in/out={r['in_tokens']}/{r['out_tokens']}  {r['content'][:140]}"
                )
            except Exception as exc:  # noqa: BLE001 — offline tool, report and continue
                print(f"  {provider.name:9} ERROR: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
