"""LLM-powered card enrichment (POS + teacher note).

Supports concurrent batch processing via ThreadPoolExecutor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .cards import Card
from .exceptions import QuotaExceededError
from .retry import llm_retryable_exceptions, sync_retry
from .sentry_init import capture_handled

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """針對每個英文詞彙，回傳 JSON array，每個元素含：
- word: 原詞
- pos: 詞性 (n. / v. / adj. / adv. / phr. / conj.)
- note: 繁體中文教學筆記（50 字內），只寫一個最有價值的洞察。禁止重複翻譯。選擇以下其中一種：
  · 易混詞辨析（何時用 A 不用 B）
  · 語域/語感提示（正式/口語/文學）
  · 構詞記憶線索（詞根、意象）
  · 用法陷阱（常見錯誤搭配）
- collocations: 2-3 個常見搭配詞組（字串陣列）
- meaning_fix: 修正後的繁體中文翻譯，須滿足：
  · adj. 結尾加「的」、adv. 結尾加「地」
  · 必須是繁體中文（不可簡體、不可英文）
  · 翻譯要能看出詞性
  · 如原翻譯已正確，回傳 null"""


USER_TEMPLATE = """分析以下單字（含現有翻譯和例句上下文）：
{words_json}

回傳 JSON array。"""

PRIVATE_CONTEXT_TEMPLATE = """分析以下單字。每個單字的 disambiguation_context 只供本次
翻譯與教學判斷使用，不要把它當成該單字的例句，也不要在 note 或 collocations 中
重述來源句子或來源單字：
{words_json}

回傳 JSON array。"""


def _build_prompt(
    cards: list[Card],
    *,
    disambiguation_context_by_card_id: Mapping[str, str] | None = None,
) -> str:
    """Build the user prompt from a batch of cards."""
    items = []
    for c in cards:
        item = {"word": c.content, "meaning": c.meaning}
        private_context = (disambiguation_context_by_card_id or {}).get(c.id, "")
        if private_context.strip():
            item["disambiguation_context"] = private_context[:1000]
        elif c.examples:
            item["context"] = c.examples[0][:200]
        items.append(item)
    template = PRIVATE_CONTEXT_TEMPLATE if disambiguation_context_by_card_id else USER_TEMPLATE
    return template.format(
        words_json=json.dumps(items, ensure_ascii=False, indent=2),
    )


def sanitize_enrich_item(item: Any) -> dict | None:
    """Return a type-safe copy of one LLM enrichment item, or None to skip it.

    LLM JSON is untrusted: the item must be a dict with a non-empty str
    ``word``. Optional fields with the wrong type are dropped (not raised on):
    ``pos`` / ``note`` / ``meaning_fix`` must be str, ``collocations`` a list
    (non-str entries are filtered out).
    """
    if not isinstance(item, dict):
        return None
    word = item.get("word")
    if not isinstance(word, str) or not word.strip():
        return None
    clean = dict(item)
    for key in ("pos", "note", "meaning_fix"):
        if key in clean and not isinstance(clean[key], str):
            del clean[key]
    if "collocations" in clean:
        colls = clean["collocations"]
        if isinstance(colls, list):
            clean["collocations"] = [c for c in colls if isinstance(c, str)]
        else:
            del clean["collocations"]
    return clean


def _parse_enrich_response(raw_content: str) -> list[dict]:
    """Parse LLM response into a list of valid enrichment items.

    Malformed items are skipped with a warning instead of raising, so one bad
    element cannot discard an already-billed batch.
    """
    data = json.loads(raw_content or "{}")
    items: Any = []
    if isinstance(data, list):
        items = data
    # First-line defense: a top-level scalar/null (e.g. `"x"`, `5`, `null`)
    # is not a container — `.values()` on it would raise AttributeError.
    # Treat any non-dict shape as "no enrichments".
    elif isinstance(data, dict):
        if "results" in data:
            items = data["results"]
        else:
            items = next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(items, list):
        return []
    cleaned = [c for c in (sanitize_enrich_item(i) for i in items) if c is not None]
    if len(cleaned) != len(items):
        logger.warning("Skipped %d malformed enrichment items", len(items) - len(cleaned))
    return cleaned


def _call_enrich_llm(
    llm,
    batch: list[Card],
    model: str | None = None,
    disambiguation_context_by_card_id: Mapping[str, str] | None = None,
):
    """Single LLM call for enrichment. Returns the raw response object."""
    return llm.chat(
        "enrich",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_prompt(
                    batch,
                    disambiguation_context_by_card_id=disambiguation_context_by_card_id,
                ),
            },
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )


def _retry_detail(wait_time: float) -> str:
    """Progress message for an enrich retry. Provider-neutral — enrich
    routes via provider_for('enrich'), which is not necessarily Gemini.
    Says "error" not "rate limit": the retryable set also covers 5xx /
    APIError, so a 'rate limit' wording would be inaccurate for those."""
    return f"LLM API error, retrying in {wait_time}s..."


async def enrich_cards_stream(
    llm,
    cards: list[Card],
    batch_size: int = 20,
    max_workers: int = 5,
    model: str | None = None,
    disambiguation_context_by_card_id: Mapping[str, str] | None = None,
) -> AsyncIterator[dict]:
    """Enrich cards concurrently and yield real-time progress updates.

    Yields dictionaries like:
    {"status": "running"|"retry"|"error", "current": int, "total": int, "detail": str, "results": list[dict]}
    """
    if not cards:
        yield {"status": "done", "current": 0, "total": 0, "detail": "No cards to enrich", "results": []}
        return

    batches = [cards[i : i + batch_size] for i in range(0, len(cards), batch_size)]
    total_cards = len(cards)
    completed_cards = 0
    # Set when the generator exits for any reason (exhausted, raised, aclose()d,
    # cancelled, GC'd). From then on nothing drains the queue and the loop may
    # be closed, so workers and loop callbacks must stop touching either.
    closed = threading.Event()
    exhausted = threading.Event()

    def _process_batch_with_retry(batch: list[Card], loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        """Worker function that handles retries and pushes progress to the async queue.

        Contract: while the stream is open, this worker MUST enqueue exactly
        one terminal message ("success" or "error") for its batch, no matter
        what happens. The consumer decrements tasks_remaining on each terminal
        message and only unblocks once all batches are accounted for. A single
        escaped exception (or a dropped terminal message) leaves
        tasks_remaining > 0 forever → the consumer's `await queue.get()`
        blocks. So the whole body is wrapped, and terminal delivery is
        guaranteed (see _put_terminal). After the stream closes there is no
        consumer to deliver to, so delivery is intentionally skipped: a batch
        that has not started returns at once, and an in-flight batch finishes
        its LLM call and discards the result.
        """
        if closed.is_set():
            # Dequeued by a pool thread just before shutdown(cancel_futures=True).
            return

        def _call_on_loop(callback, *args) -> None:
            """Schedule ``callback`` on the loop thread while the stream is open.

            Once the stream has closed, the loop may be closed too, and then
            call_soon_threadsafe raises RuntimeError; delivery is moot then.
            """
            if closed.is_set():
                return
            try:
                loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                if closed.is_set():
                    return
                raise

        def _put_terminal(msg: dict) -> None:
            """Deliver a terminal message, never dropping it while the stream is open.

            Plain put_nowait raises QueueFull when the bounded queue is full;
            inside a call_soon_threadsafe callback that exception is swallowed by
            asyncio's default handler, silently losing the message and
            deadlocking the consumer. Terminal messages are delivery-critical,
            so we schedule a loop callback that retries put_nowait via
            call_later until it lands or the stream closes. This stays on the
            loop thread (no cross-thread coroutine-future wait, which would
            itself deadlock the worker against the loop), and a transiently
            full queue only delays the terminal rather than losing it."""

            def _try_put() -> None:
                if closed.is_set():
                    # No consumer left: stop re-arming instead of polling forever.
                    return
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    # Consumer is draining concurrently; re-attempt shortly.
                    loop.call_later(0.01, _try_put)

            _call_on_loop(_try_put)

        def _put_hint(msg: dict) -> None:
            """Enqueue a non-terminal progress hint on the loop thread.

            Hints are droppable: a full queue or a closed stream discards them."""
            if closed.is_set():
                return
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

        def _delay_fn(attempt: int, exc: BaseException) -> float | None:
            wait_time = 2 ** (attempt + 1)
            _call_on_loop(_put_hint, {"type": "retry", "detail": _retry_detail(wait_time)})
            return float(wait_time)

        if exhausted.is_set():
            # Another batch hit real quota exhaustion: don't start (and bill)
            # more LLM calls, but still deliver a terminal so the consumer's
            # accounting reaches zero and in-flight batches get drained.
            _put_terminal({"type": "skipped"})
            return

        try:
            # Retry only explicit transient provider failures; non-retryable
            # 4xx errors fail this batch on the first call.
            response = sync_retry(
                _call_enrich_llm,
                llm,
                batch,
                model,
                disambiguation_context_by_card_id,
                max_attempts=4,
                base_delay=2.0,
                retryable_exceptions=llm_retryable_exceptions(),
                delay_fn=_delay_fn,
                step_name="Enrich stream",
            )
            results = _parse_enrich_response(response.choices[0].message.content)
            _put_terminal({"type": "success", "results": results, "count": len(batch)})
        except QuotaExceededError as e:
            exhausted.set()
            _put_terminal(
                {
                    "type": "quota_exhausted",
                    "reset_seconds": e.reset_seconds,
                    "headers": e.headers,
                }
            )
        except BaseException as e:  # noqa: BLE001 — terminal guarantee trumps catch-specificity
            # Any escaped exception (known or future) becomes an error terminal
            # so tasks_remaining is always decremented. Without this, a new
            # uncaught exception type would silently re-introduce the deadlock.
            capture_handled(e, context="enrich.batch")
            try:
                _put_terminal({"type": "error", "error": str(e)})
            except BaseException:  # noqa: BLE001
                # Terminal delivery itself failed (e.g. loop torn down). Nothing
                # more we can safely do from a worker thread; re-raise the
                # original so it surfaces on the future rather than vanishing.
                raise e from None

    # Bounded queue: with max_workers=5 the natural in-flight count is small,
    # but cap at 100 so a stalled consumer can't let workers buffer unlimited
    # progress messages and OOM the process.
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    loop = asyncio.get_running_loop()

    # Explicit shutdown instead of `with`: ThreadPoolExecutor.__exit__ is
    # shutdown(wait=True), which on an early exit (consumer raised, aclose(),
    # cancellation, the quota abort below) would block the event loop until
    # every queued batch had run and been billed, with its result discarded.
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="kg-enrich")
    try:
        # Submit all batches
        [loop.run_in_executor(executor, _process_batch_with_retry, batch, loop, queue) for batch in batches]

        # Await results as they come in
        tasks_remaining = len(batches)
        quota_error: QuotaExceededError | None = None

        while tasks_remaining > 0:
            msg = await queue.get()

            if msg["type"] == "success":
                completed_cards += msg["count"]
                tasks_remaining -= 1
                yield {
                    "status": "running",
                    "current": completed_cards,
                    "total": total_cards,
                    "detail": f"Enriched {completed_cards}/{total_cards} cards...",
                    "results": msg["results"],
                }
            elif msg["type"] == "retry":
                yield {
                    "status": "retry",
                    "current": completed_cards,
                    "total": total_cards,
                    "detail": msg["detail"],
                    "results": [],
                }
            elif msg["type"] == "error":
                tasks_remaining -= 1
                yield {
                    "status": "error",
                    "current": completed_cards,
                    "total": total_cards,
                    "detail": f"Batch failed: {msg['error']}",
                    "results": [],
                }
                # Optional: We could break here, but allowing other batches to finish is more robust
            elif msg["type"] == "skipped":
                tasks_remaining -= 1
            elif msg["type"] == "quota_exhausted":
                # Keep draining: batches admitted (and billed) before the
                # exhaustion still deliver results that must be persisted.
                tasks_remaining -= 1
                if quota_error is None:
                    quota_error = QuotaExceededError(msg["reset_seconds"], headers=msg.get("headers"))
        if quota_error is not None:
            raise quota_error
    finally:
        closed.set()
        # Never blocks the loop: batches not yet started are cancelled, and
        # in-flight ones finish on their own threads without delivering.
        executor.shutdown(wait=False, cancel_futures=True)
