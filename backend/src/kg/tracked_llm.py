"""Unified LLM wrapper with automatic token usage tracking + quota reservation."""
from __future__ import annotations

from .llm.providers import LLMProvider
from .quota_service import estimate_call_cost, reserve
from .token_tracker import record


class TrackedLLM:
    """Per-request LLM wrapper. Binds user_id at construction, auto-records on every call.

    Sync callers (judge/enrich/embed): pass OpenAI client, use .chat() / .embed()
    Async callers (translate): pass AsyncOpenAI client, use .chat_async()

    Every call holds an in-flight quota reservation for its duration. This
    closes the pre-flight gap: the route-level `check_quota` gate runs before
    a call, but `record()` only lands after it. Concurrent same-user calls
    (multi-tab translate, pipeline enrich fanning out 5-way) would otherwise
    all clear the gate seeing `used=0`. The reservation makes those in-flight
    calls visible to the gate; it is released the instant the real cost is
    recorded.

    When a `provider` is bound, every chat call has the provider's
    `extra_body` and `max_tokens_default` merged in — this is where DeepSeek's
    `thinking: disabled` gets enforced without touching call sites. Caller-
    supplied values always win on conflict. `provider=None` (legacy
    construction) injects nothing and preserves exact prior behavior.
    """

    __slots__ = ("_client", "user_id", "_provider")

    def __init__(self, client, user_id: str, provider: LLMProvider | None = None) -> None:
        self._client = client
        self.user_id = user_id
        self._provider = provider

    def _chat_kwargs(self, kwargs: dict) -> dict:
        """Merge provider-level chat defaults into kwargs and return it (caller
        wins on conflict). Mutates `kwargs` in place — safe because chat() /
        chat_async() always hand in a fresh **kwargs dict."""
        p = self._provider
        if p is None:
            return kwargs
        if p.extra_body:
            # Copy so the registry's dict is never mutated; caller keys win.
            merged = dict(p.extra_body)
            merged.update(kwargs.get("extra_body") or {})
            kwargs["extra_body"] = merged
        if p.max_tokens_default is not None and kwargs.get("max_tokens") is None:
            kwargs["max_tokens"] = p.max_tokens_default
        return kwargs

    def chat(self, call_type: str, **kwargs):
        kwargs = self._chat_kwargs(kwargs)
        with reserve(self.user_id, estimate_call_cost(call_type)):
            resp = self._client.chat.completions.create(**kwargs)
            self._record_chat(call_type, resp, kwargs.get("model"))
        return resp

    async def chat_async(self, call_type: str, **kwargs):
        kwargs = self._chat_kwargs(kwargs)
        with reserve(self.user_id, estimate_call_cost(call_type)):
            resp = await self._client.chat.completions.create(**kwargs)
            self._record_chat(call_type, resp, kwargs.get("model"))
        return resp

    def embed(self, call_type: str = "embed", **kwargs):
        with reserve(self.user_id, estimate_call_cost(call_type)):
            resp = self._client.embeddings.create(**kwargs)
            self._record_embed(call_type, resp, kwargs.get("model"))
        return resp

    def _provider_name(self) -> str | None:
        return self._provider.name if self._provider is not None else None

    def _record_chat(self, call_type: str, resp, model: str | None = None) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        # Prefer the model actually sent; fall back to the bound provider's
        # default chat model so the row is never NULL when a provider is bound.
        if model is None and self._provider is not None:
            model = self._provider.chat_model
        record(
            self.user_id,
            call_type,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            provider=self._provider_name(),
            model=model,
        )

    def _record_embed(self, call_type: str, resp, model: str | None = None) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        record(
            self.user_id,
            call_type,
            prompt or getattr(usage, "total_tokens", 0) or 0,
            0,
            provider=self._provider_name(),
            model=model,
        )
