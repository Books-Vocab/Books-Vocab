"""LLM-powered card enrichment (POS + teacher note).

Supports concurrent batch processing via ThreadPoolExecutor.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from .cards import Card

SYSTEM_PROMPT = """你是英語教學專家。針對每個英文詞彙，提供：
1. pos：英文詞性縮寫 (n. / v. / adj. / adv. / phr. / conj.)
2. note：一段精煉中文教學筆記（80 字內），包含：
   - 常見搭配 (用 `code` 格式)
   - 用法語境
   - 易混詞區辨（如有）

回傳嚴格 JSON array，每個元素含 word, pos, note。"""

USER_TEMPLATE = """請分析以下單字：
{words_json}

每個單字的例句上下文：
{contexts_json}

回傳 JSON array。"""


def _build_prompt(cards: list[Card]) -> str:
    """Build the user prompt from a batch of cards."""
    words = [c.content for c in cards]
    contexts = {c.content: c.examples[0] if c.examples else "" for c in cards}
    return USER_TEMPLATE.format(
        words_json=json.dumps(words, ensure_ascii=False),
        contexts_json=json.dumps(contexts, ensure_ascii=False, indent=2),
    )


def enrich_cards(client: OpenAI, cards: list[Card], user_id: str | None = None) -> list[dict]:
    """Enrich a batch of cards via a single LLM call.

    Returns a list of dicts with keys: word, pos, note.
    """
    if not cards:
        return []

    import time
    from openai import RateLimitError, APIError, InternalServerError

    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model="gemini-2.5-flash-lite",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_prompt(cards)},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            break
        except (RateLimitError, APIError, InternalServerError) as e:
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
            else:
                raise e

    if user_id and response.usage:
        from .token_tracker import record
        record(user_id, "enrich",
               getattr(response.usage, "prompt_tokens", 0) or 0,
               getattr(response.usage, "completion_tokens", 0) or 0)

    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)

    # Handle both {"results": [...]} and [...] formats
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    # Try to find any list value in the dict
    for v in data.values():
        if isinstance(v, list):
            return v
    return []


import asyncio

async def enrich_cards_stream(
    client: OpenAI,
    cards: list[Card],
    user_id: str | None = None,
    batch_size: int = 20,
    max_workers: int = 5,
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

    import time
    from openai import RateLimitError, APIError, InternalServerError

    def _process_batch_with_retry(batch: list[Card], loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        """Worker function that handles retries and pushes progress to the async queue."""
        for attempt in range(4):
            try:
                response = client.chat.completions.create(
                    model="gemini-2.5-flash-lite",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": _build_prompt(batch)},
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )
                
                raw = response.choices[0].message.content or "{}"
                data = json.loads(raw)

                results = []
                if isinstance(data, list):
                    results = data
                elif isinstance(data, dict) and "results" in data:
                    results = data["results"]
                else:
                    for v in data.values():
                        if isinstance(v, list):
                            results = v
                            break

                usage_data = None
                if response.usage:
                    usage_data = {
                        "input": getattr(response.usage, "prompt_tokens", 0) or 0,
                        "output": getattr(response.usage, "completion_tokens", 0) or 0,
                    }

                # Push success to queue
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "success", "results": results, "count": len(batch), "usage": usage_data})
                return
                
            except (RateLimitError, APIError, InternalServerError) as e:
                if attempt < 3:
                    wait_time = 2 ** (attempt + 1)
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "type": "retry", 
                        "detail": f"Gemini API rate limit, retrying in {wait_time}s..."
                    })
                    time.sleep(wait_time)
                else:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(e)})
                    return
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(e)})
                return

    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all batches
        futures = [
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
                if user_id and msg.get("usage"):
                    from .token_tracker import record
                    record(user_id, "enrich", msg["usage"]["input"], msg["usage"]["output"])
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

