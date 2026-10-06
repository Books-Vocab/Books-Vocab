"""LLM-powered card enrichment (POS + teacher note).

Supports concurrent batch processing via ThreadPoolExecutor.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from concurrent.futures import ThreadPoolExecutor

from .cards import Card
from .exceptions import QuotaExceededError
from .retry import llm_retryable_exceptions, sync_retry

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
    template = (
        PRIVATE_CONTEXT_TEMPLATE
        if disambiguation_context_by_card_id
        else USER_TEMPLATE
    )
    return template.format(
        words_json=json.dumps(items, ensure_ascii=False, indent=2),
    )


def _parse_enrich_response(raw_content: str) -> list[dict]:
    """Parse LLM response into enrichment results list."""
    data = json.loads(raw_content or "{}")
    if isinstance(data, list):
        return data
    # First-line defense: a top-level scalar/null (e.g. `"x"`, `5`, `null`)
    # is not a container — `.values()` on it would raise AttributeError.
    # Treat any non-dict shape as "no enrichments".
    if not isinstance(data, dict):
        return []
    if "results" in data:
        return data["results"]
    for v in data.values():
        if isinstance(v, list):
            return v
    return []


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

    def _process_batch_with_retry(batch: list[Card], loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        """Worker function that handles retries and pushes progress to the async queue.

        Contract: this worker MUST enqueue exactly one terminal message
        ("success" or "error") for its batch, no matter what happens. The
        consumer decrements tasks_remaining on each terminal message and only
        unblocks once all batches are accounted for. A single escaped
        exception (or a dropped terminal message) leaves tasks_remaining > 0
        forever → the consumer's `await queue.get()` blocks and the
        ThreadPoolExecutor never releases. So the whole body is wrapped, and
        terminal delivery is guaranteed (see _put_terminal).
        """
        def _put_terminal(msg: dict) -> None:
            """Deliver a terminal message, guaranteeing it is never dropped.

            Plain put_nowait (used for non-terminal 'retry' hints) raises
            QueueFull when the bounded queue is full; inside a
            call_soon_threadsafe callback that exception is swallowed by
            asyncio's default handler, silently losing the message and
            deadlocking the consumer. Terminal messages are delivery-critical,
            so we schedule a loop callback that retries put_nowait via
            call_later until it lands. This stays on the loop thread (no
            cross-thread coroutine-future wait, which would itself deadlock the
            worker against the loop), and a transiently full queue only delays
            the terminal rather than losing it."""
            def _try_put() -> None:
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    # Consumer is draining concurrently; re-attempt shortly.
                    loop.call_later(0.01, _try_put)

            loop.call_soon_threadsafe(_try_put)

        def _delay_fn(attempt: int, exc: BaseException) -> float | None:
            wait_time = 2 ** (attempt + 1)
            # Non-terminal progress hint: safe to drop if the queue is full.
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "retry",
                "detail": _retry_detail(wait_time),
            })
            return float(wait_time)

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
            _put_terminal({
                "type": "quota_exhausted",
                "reset_seconds": e.reset_seconds,
                "headers": e.headers,
            })
        except BaseException as e:  # noqa: BLE001 — terminal guarantee trumps catch-specificity
            # Any escaped exception (known or future) becomes an error terminal
            # so tasks_remaining is always decremented. Without this, a new
            # uncaught exception type would silently re-introduce the deadlock.
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

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all batches
        [
            loop.run_in_executor(executor, _process_batch_with_retry, batch, loop, queue)
            for batch in batches
        ]

        # Await results as they come in
        tasks_remaining = len(batches)

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
                    "results": msg["results"]
                }
            elif msg["type"] == "retry":
                yield {
                    "status": "retry",
                    "current": completed_cards,
                    "total": total_cards,
                    "detail": msg["detail"],
                    "results": []
                }
            elif msg["type"] == "error":
                tasks_remaining -= 1
                yield {
                    "status": "error",
                    "current": completed_cards,
                    "total": total_cards,
                    "detail": f"Batch failed: {msg['error']}",
                    "results": []
                }
                # Optional: We could break here, but allowing other batches to finish is more robust
            elif msg["type"] == "quota_exhausted":
                raise QuotaExceededError(msg["reset_seconds"], headers=msg.get("headers"))
