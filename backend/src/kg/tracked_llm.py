"""Unified LLM wrapper with automatic token usage tracking + quota reservation."""
from __future__ import annotations

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
    """

    __slots__ = ("_client", "user_id")

    def __init__(self, client, user_id: str) -> None:
        self._client = client
        self.user_id = user_id

    def chat(self, call_type: str, **kwargs):
        with reserve(self.user_id, estimate_call_cost(call_type)):
            resp = self._client.chat.completions.create(**kwargs)
            self._record_chat(call_type, resp)
        return resp

    async def chat_async(self, call_type: str, **kwargs):
        with reserve(self.user_id, estimate_call_cost(call_type)):
            resp = await self._client.chat.completions.create(**kwargs)
            self._record_chat(call_type, resp)
        return resp

    def embed(self, call_type: str = "embed", **kwargs):
        with reserve(self.user_id, estimate_call_cost(call_type)):
            resp = self._client.embeddings.create(**kwargs)
            self._record_embed(call_type, resp)
        return resp

    def _record_chat(self, call_type: str, resp) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        record(
            self.user_id,
            call_type,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    def _record_embed(self, call_type: str, resp) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        record(
            self.user_id,
            call_type,
            prompt or getattr(usage, "total_tokens", 0) or 0,
            0,
        )
