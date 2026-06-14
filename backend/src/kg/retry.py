import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

_LLM_RETRYABLE: tuple[type[Exception], ...] = ()
T = TypeVar("T")


class SyncCallable(Protocol[T]):
    def __call__(self, *args: Any, **kwargs: Any) -> T:
        ...


class AsyncCallable(Protocol[T]):
    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[T]:
        ...


def llm_retryable_exceptions() -> tuple[type[Exception], ...]:
    """Transient OpenAI-SDK transport errors worth retrying before giving up.

    Lazily imported and cached so the ``openai`` dependency stays optional at
    module import time. Shared by enrich + judge so the retryable set can never
    drift between call sites.
    """
    global _LLM_RETRYABLE
    if not _LLM_RETRYABLE:
        from openai import APIError, InternalServerError, RateLimitError
        _LLM_RETRYABLE = (RateLimitError, APIError, InternalServerError)
    return _LLM_RETRYABLE


def sync_retry[T](
    fn: SyncCallable[T],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
    delay_fn: Callable[[int, BaseException], float | None] | None = None,
    step_name: str = "",
    uid: str = "",
    **kwargs: Any,
) -> T:
    """同步版 retry，支援自訂 delay_fn（例如讀取 Retry-After header）。

    delay_fn(attempt, exc) 回傳秒數或 None（使用預設 exponential backoff）。
    """
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except retryable_exceptions as exc:
            if attempt == max_attempts - 1:
                raise
            default_delay = min(base_delay * (2 ** attempt), max_delay)
            if delay_fn is not None:
                custom_delay = delay_fn(attempt, exc)
                # `is not None` (not `or`): a delay_fn returning 0.0 means
                # "retry now" and must not fall back to the default backoff.
                delay = custom_delay if custom_delay is not None else default_delay
            else:
                delay = default_delay
            delay *= 0.5 + random.random()  # jitter: ×0.5–1.5
            logger.warning("[%s] %s attempt %d failed: %s, retrying in %.1fs", uid, step_name, attempt + 1, exc, delay)
            time.sleep(delay)
    return fn(*args, **kwargs)  # unreachable, satisfies type checker


async def async_retry[T](
    fn: AsyncCallable[T],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
    step_name: str = "",
    uid: str = "",
    **kwargs: Any,
) -> T:
    """執行 fn(*args, **kwargs)，瞬時錯誤時 exponential backoff 重試。"""
    for attempt in range(max_attempts):
        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as exc:
            if attempt == max_attempts - 1:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay *= 0.5 + random.random()  # jitter: ×0.5–1.5
            logger.warning("[%s] %s attempt %d failed: %s, retrying in %.1fs", uid, step_name, attempt + 1, exc, delay)
            await asyncio.sleep(delay)
    return await fn(*args, **kwargs)  # unreachable, satisfies type checker
