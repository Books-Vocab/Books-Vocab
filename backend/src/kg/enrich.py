"""LLM-powered card enrichment (POS + teacher note).

Supports concurrent batch processing via ThreadPoolExecutor.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from .cards import Card
from .languages import LANGUAGE_NAMES
from .retry import sync_retry

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


def build_enrich_system_prompt(target_lang: str = "zh-Hant") -> str:
    return SYSTEM_PROMPT


USER_TEMPLATE = """分析以下單字（含現有翻譯和例句上下文）：
{words_json}

回傳 JSON array。"""


def _build_prompt(cards: list[Card]) -> str:
    """Build the user prompt from a batch of cards."""
    items = []
    for c in cards:
        item = {"word": c.content, "meaning": c.meaning}
        if c.examples:
            item["context"] = c.examples[0][:200]
        items.append(item)
    return USER_TEMPLATE.format(
        words_json=json.dumps(items, ensure_ascii=False, indent=2),
    )


def _parse_enrich_response(raw_content: str) -> list[dict]:
    """Parse LLM response into enrichment results list."""
    data = json.loads(raw_content or "{}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    for v in data.values():
        if isinstance(v, list):
            return v
    return []


def _call_enrich_llm(llm, batch: list[Card], model: str = "gemini-2.5-flash-lite"):
    """Single LLM call for enrichment. Returns the raw response object."""
    return llm.chat(
        "enrich",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(batch)},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )


_ENRICH_RETRYABLE: tuple[type[Exception], ...] = ()


def _get_enrich_retryable() -> tuple[type[Exception], ...]:
    global _ENRICH_RETRYABLE
    if not _ENRICH_RETRYABLE:
        from openai import APIError, InternalServerError, RateLimitError
        _ENRICH_RETRYABLE = (RateLimitError, APIError, InternalServerError)
    return _ENRICH_RETRYABLE


def enrich_cards(llm, cards: list[Card], model: str = "gemini-2.5-flash-lite") -> list[dict]:
    """Enrich a batch of cards via a single LLM call.

    Returns a list of dicts with keys: word, pos, note.
    Token usage is recorded automatically by TrackedLLM.
    """
    if not cards:
        return []

    response = sync_retry(
        _call_enrich_llm, llm, cards, model,
        max_attempts=4,
        base_delay=2.0,
        retryable_exceptions=_get_enrich_retryable(),
        step_name="Enrich LLM",
    )

    return _parse_enrich_response(response.choices[0].message.content)


async def enrich_cards_stream(
    llm,
    cards: list[Card],
    batch_size: int = 20,
    max_workers: int = 5,
    model: str = "gemini-2.5-flash-lite",
):
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

    from openai import OpenAIError

    def _process_batch_with_retry(batch: list[Card], loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        """Worker function that handles retries and pushes progress to the async queue."""
        def _delay_fn(attempt: int, exc: BaseException) -> float | None:
            wait_time = 2 ** (attempt + 1)
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "retry",
                "detail": f"Gemini API rate limit, retrying in {wait_time}s..."
            })
            return float(wait_time)

        try:
            response = sync_retry(
                _call_enrich_llm, llm, batch, model,
                max_attempts=4,
                base_delay=2.0,
                retryable_exceptions=_get_enrich_retryable(),
                delay_fn=_delay_fn,
                step_name="Enrich stream",
            )
            results = _parse_enrich_response(response.choices[0].message.content)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "success", "results": results, "count": len(batch)})
        except (OpenAIError, json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(e)})

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

