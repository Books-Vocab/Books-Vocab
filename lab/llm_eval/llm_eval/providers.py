"""Provider resolution for eval: cloud registry + Ollama local."""

from __future__ import annotations

import dataclasses
import os

from kg.llm.providers import LLMProvider, REGISTRY as CLOUD_REGISTRY

OLLAMA_PROVIDER = LLMProvider(
    name="ollama",
    base_url="",
    api_key_env="OLLAMA_DUMMY_KEY",
    chat_model="gemma3:4b",
    input_price_per_m=0.0,
    output_price_per_m=0.0,
    cache_price_per_m=0.0,
    embed_price_per_m=0.0,
    max_tokens_default=None,
    extra_body={},
    supports_embeddings=False,
)


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_HOST", "http://localhost:11434/v1")


def resolve_provider(name: str) -> LLMProvider:
    """Resolve a provider by name. Supports cloud registry + ollama."""
    name = name.strip().lower()
    if name == "ollama":
        model = os.getenv("OLLAMA_MODEL", OLLAMA_PROVIDER.chat_model)
        return dataclasses.replace(
            OLLAMA_PROVIDER,
            base_url=_ollama_base_url(),
            chat_model=model,
        )
    provider = CLOUD_REGISTRY.get(name)
    if provider is None:
        raise ValueError(
            f"Unknown provider {name!r}. "
            f"Available: {sorted(CLOUD_REGISTRY)} + ['ollama']"
        )
    return provider


def list_available_providers() -> list[LLMProvider]:
    """List all providers whose API keys are configured (plus ollama if reachable)."""
    result: list[LLMProvider] = []
    for p in CLOUD_REGISTRY.values():
        if os.getenv(p.api_key_env):
            result.append(p)
    # Always include ollama — runner will mark unreachable if host down
    result.append(resolve_provider("ollama"))
    return result


def create_eval_client(provider: LLMProvider):
    """Create an OpenAI-compatible client for eval. Bypasses TrackedLLM and service_factories."""
    from openai import OpenAI

    api_key = "ollama" if provider.name == "ollama" else (os.getenv(provider.api_key_env) or "no-key")
    return OpenAI(api_key=api_key, base_url=provider.base_url or None)


def create_eval_async_client(provider: LLMProvider):
    """Create an async OpenAI-compatible client for eval. Bypasses TrackedLLM."""
    from openai import AsyncOpenAI

    api_key = "ollama" if provider.name == "ollama" else (os.getenv(provider.api_key_env) or "no-key")
    return AsyncOpenAI(api_key=api_key, base_url=provider.base_url or None)
