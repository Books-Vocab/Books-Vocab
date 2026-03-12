import asyncio
import logging

logger = logging.getLogger(__name__)


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
