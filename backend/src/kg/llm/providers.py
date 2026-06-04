"""LLM provider registry + per-call-type routing.

Every provider KG uses (Gemini today, DeepSeek next, Qwen/GLM later) exposes an
OpenAI-compatible chat/embeddings surface. A provider is therefore pure
configuration — there is no per-provider adapter code. Adding a provider is one
`REGISTRY` entry.

Routing is env-driven and read fresh on every `provider_for` call, so a deploy
can flip providers (or run an A/B) without a code change or restart-coupled
config reload:

    LLM_PROVIDER_<CALL_TYPE>   e.g. LLM_PROVIDER_TRANSLATE_QUICK=deepseek
    LLM_PROVIDER_<GROUP>       e.g. LLM_PROVIDER_TRANSLATE=deepseek  (all translate_*)
    LLM_PROVIDER_DEFAULT       fallback for every chat call_type
    LLM_PROVIDER_EMBED         embeddings only — never inherits DEFAULT
    <NAME>_MODEL               override a provider's model, e.g. DEEPSEEK_MODEL

Precedence for a chat call_type: exact > group > DEFAULT > gemini.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMProvider:
    """An OpenAI-compatible LLM provider.

    Prices are USD per 1M tokens. `extra_body` is merged into every chat
    request (e.g. DeepSeek needs `{"thinking": {"type": "disabled"}}` — its
    v4 models default to a slow, verbose thinking mode). `max_tokens_default`
    is applied when a caller does not pass one; `None` keeps provider default.
    """

    name: str
    base_url: str
    api_key_env: str
    chat_model: str
    input_price_per_m: float
    output_price_per_m: float
    cache_price_per_m: float
    embed_price_per_m: float
    max_tokens_default: int | None
    extra_body: dict[str, Any]
    supports_embeddings: bool


REGISTRY: dict[str, LLMProvider] = {
    "gemini": LLMProvider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        chat_model="gemini-2.5-flash-lite",
        input_price_per_m=0.10,
        output_price_per_m=0.40,
        cache_price_per_m=0.01,
        embed_price_per_m=0.00025,
        max_tokens_default=None,
        extra_body={},
        supports_embeddings=True,
    ),
    "deepseek": LLMProvider(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        chat_model="deepseek-v4-flash",
        input_price_per_m=0.14,
        output_price_per_m=0.28,
        cache_price_per_m=0.0028,
        embed_price_per_m=0.0,  # no embeddings endpoint
        max_tokens_default=8192,
        extra_body={"thinking": {"type": "disabled"}},
        supports_embeddings=False,
    ),
}

# Provider used for embeddings absent an LLM_PROVIDER_EMBED override.
# Embeddings deliberately never inherit LLM_PROVIDER_DEFAULT: flipping the
# chat default to a provider with no embeddings endpoint (DeepSeek) must not
# break the graph-link pipeline.
_DEFAULT_EMBED_PROVIDER = "gemini"
_DEFAULT_CHAT_PROVIDER = "gemini"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _resolve_provider_name(call_type: str) -> str:
    """Resolve which provider name serves a call_type, from env routing."""
    ct = call_type.strip().lower()
    if ct == "embed":
        return _env("LLM_PROVIDER_EMBED") or _DEFAULT_EMBED_PROVIDER
    key = ct.upper()
    group = key.split("_", 1)[0]
    return (
        _env(f"LLM_PROVIDER_{key}")
        or _env(f"LLM_PROVIDER_{group}")
        or _env("LLM_PROVIDER_DEFAULT")
        or _DEFAULT_CHAT_PROVIDER
    )


def provider_for(call_type: str) -> LLMProvider:
    """Return the resolved provider for a call_type, applying env overrides.

    Raises ValueError on an unknown provider name, or when `embed` is routed
    to a provider with no embeddings endpoint — both are deploy
    misconfigurations that must fail loudly rather than silently degrade.
    """
    name = _resolve_provider_name(call_type)
    base = REGISTRY.get(name)
    if base is None:
        raise ValueError(
            f"Unknown LLM provider {name!r} routed for call_type "
            f"{call_type!r}. Valid providers: {sorted(REGISTRY)}"
        )
    if call_type.strip().lower() == "embed" and not base.supports_embeddings:
        capable = sorted(p for p, v in REGISTRY.items() if v.supports_embeddings)
        raise ValueError(
            f"LLM_PROVIDER_EMBED={name!r} has no embeddings endpoint. "
            f"Route embeddings to an embedding-capable provider: {capable}"
        )
    model_override = _env(f"{base.name.upper()}_MODEL")
    if model_override:
        return dataclasses.replace(base, chat_model=model_override)
    return base
