"""Unified LLM wrapper with automatic token usage tracking + quota reservation."""
from __future__ import annotations

import logging

from .llm.providers import LLMProvider
from .quota_service import estimate_call_cost, reserve
from .token_tracker import record

logger = logging.getLogger(__name__)


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

    __slots__ = ("_client", "user_id", "_provider", "_enforce_quota", "_is_pro", "_reserve_quota")

    def __init__(
        self,
        client,
        user_id: str,
        provider: LLMProvider | None = None,
        *,
        enforce_quota: bool = False,
        is_pro: bool = False,
        reserve_quota: bool = True,
    ) -> None:
        self._client = client
        self.user_id = user_id
        self._provider = provider
        self._enforce_quota = enforce_quota
        self._is_pro = is_pro
        self._reserve_quota = reserve_quota

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
        reservation = estimate_call_cost(call_type) if self._reserve_quota else 0.0
        with reserve(self.user_id, reservation, enforce=self._enforce_quota, is_pro=self._is_pro):
            try:
                resp = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                self._record_failure(call_type, exc, kwargs.get("model"))
                raise
            self._record_chat(call_type, resp, kwargs.get("model"))
        return resp

    async def chat_async(self, call_type: str, **kwargs):
        kwargs = self._chat_kwargs(kwargs)
        reservation = estimate_call_cost(call_type) if self._reserve_quota else 0.0
        with reserve(self.user_id, reservation, enforce=self._enforce_quota, is_pro=self._is_pro):
            try:
                resp = await self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                self._record_failure(call_type, exc, kwargs.get("model"))
                raise
            self._record_chat(call_type, resp, kwargs.get("model"))
        return resp

    def embed(self, call_type: str = "embed", **kwargs):
        reservation = estimate_call_cost(call_type) if self._reserve_quota else 0.0
        with reserve(self.user_id, reservation, enforce=self._enforce_quota, is_pro=self._is_pro):
            try:
                resp = self._client.embeddings.create(**kwargs)
            except Exception as exc:
                self._record_failure(call_type, exc, kwargs.get("model"))
                raise
            self._record_embed(call_type, resp, kwargs.get("model"))
        return resp

    def _provider_name(self) -> str | None:
        return self._provider.name if self._provider is not None else None

    @staticmethod
    def _extract_status_code(exc: Exception) -> int | None:
        """Return the HTTP status code from an OpenAI SDK error, or None."""
        code = getattr(exc, "status_code", None)
        return code if isinstance(code, int) else None

    def _record_failure(self, call_type: str, exc: Exception, model: str | None = None) -> None:
        """Best-effort record of a terminal LLM failure. Never raises."""
        try:
            from .llm_error_log import record as record_error
            from .llm_error_log import redact_message
            if model is None and self._provider is not None:
                model = self._provider.chat_model
            record_error(
                user_id=self.user_id,
                call_type=call_type,
                provider=self._provider_name(),
                model=model,
                error_class=type(exc).__name__,
                status_code=self._extract_status_code(exc),
                message=redact_message(str(exc))[:500],
            )
        except Exception:  # noqa: BLE001 — logging must never mask the real failure.
            logger.warning(
                "Failed to record LLM error (provider=%s model=%s user_id=%s call_type=%s)",
                self._provider_name(),
                model if model is not None else (
                    self._provider.chat_model if self._provider is not None else None
                ),
                self.user_id,
                call_type,
                exc_info=True,
            )

    def _warn_usage_missing(self, call_type: str, model: str | None) -> None:
        """A successful LLM call returned no usage → the tokens it burned are
        never recorded against the user's quota and never priced. Billing /
        quota would silently under-count with zero trace. Emit a warning so the
        leak is at least visible (we deliberately do NOT fabricate a token
        count — estimating would corrupt billing with guesswork)."""
        logger.warning(
            "LLM response missing usage; token not recorded "
            "(provider=%s model=%s user_id=%s call_type=%s)",
            self._provider_name(),
            model if model is not None else (
                self._provider.chat_model if self._provider is not None else None
            ),
            self.user_id,
            call_type,
        )

    def _usage_or_warn(self, call_type: str, resp, model: str | None):
        """Return ``resp.usage``, or None (after warning) when it is missing/empty.

        Centralises the leak-observability guard shared by chat/embed recording.
        """
        usage = getattr(resp, "usage", None)
        if not usage:
            self._warn_usage_missing(call_type, model)
            return None
        return usage

    def _record_chat(self, call_type: str, resp, model: str | None = None) -> None:
        usage = self._usage_or_warn(call_type, resp, model)
        if usage is None:
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
        usage = self._usage_or_warn(call_type, resp, model)
        if usage is None:
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
