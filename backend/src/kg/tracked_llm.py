"""Unified LLM wrapper with automatic token usage tracking."""
from __future__ import annotations

from .token_tracker import record


class TrackedLLM:
    """Per-request LLM wrapper. Binds user_id at construction, auto-records on every call.

    Sync callers (judge/enrich/embed): pass OpenAI client, use .chat() / .embed()
    Async callers (translate): pass AsyncOpenAI client, use .chat_async()
    """

    __slots__ = ("_client", "user_id")

    def __init__(self, client, user_id: str) -> None:
        self._client = client
        self.user_id = user_id

    def chat(self, call_type: str, **kwargs):
        resp = self._client.chat.completions.create(**kwargs)
        self._record_chat(call_type, resp)
        return resp

    async def chat_async(self, call_type: str, **kwargs):
        resp = await self._client.chat.completions.create(**kwargs)
        self._record_chat(call_type, resp)
        return resp

    def embed(self, call_type: str = "embed", **kwargs):
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
