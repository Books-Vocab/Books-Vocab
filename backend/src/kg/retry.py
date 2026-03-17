import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def sync_retry(
    fn: Callable[..., T],
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
            if delay_fn is not None:
                custom_delay = delay_fn(attempt, exc)
                delay = custom_delay if custom_delay is not None else min(base_delay * (2 ** attempt), max_delay)
            else:
                delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning("[%s] %s attempt %d failed: %s, retrying in %.1fs", uid, step_name, attempt + 1, exc, delay)
            time.sleep(delay)
    return fn(*args, **kwargs)  # unreachable, satisfies type checker


async def async_retry(
    fn,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
    step_name: str = "",
    uid: str = "",
    **kwargs,
):
    """執行 fn(*args, **kwargs)，瞬時錯誤時 exponential backoff 重試。"""
    for attempt in range(max_attempts):
        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as exc:
            if attempt == max_attempts - 1:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning("[%s] %s attempt %d failed: %s, retrying in %.1fs", uid, step_name, attempt + 1, exc, delay)
            await asyncio.sleep(delay)
