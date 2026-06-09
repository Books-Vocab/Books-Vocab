"""Tests for kg.enrich — LLM-powered card enrichment."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.cards import Card
from kg.enrich import _build_prompt, _parse_enrich_response
from kg.exceptions import QuotaExceededError
from kg.tracked_llm import TrackedLLM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_card(content: str = "hello", meaning: str = "你好",
               examples: list[str] | None = None) -> Card:
    return Card(content=content, meaning=meaning,
                examples=examples or [])


def _mock_response(content: str, prompt_tokens: int = 10,
                   completion_tokens: int = 20):
    usage = SimpleNamespace(prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens)
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_single_card_with_example(self):
        card = _make_card("abandon", "放棄", ["He abandoned the project."])
        prompt = _build_prompt([card])
        assert "abandon" in prompt
        assert "放棄" in prompt
        assert "He abandoned the project." in prompt
        assert "context" in prompt

    def test_card_without_examples(self):
        card = _make_card("hello", "你好")
        prompt = _build_prompt([card])
        parsed = json.loads(prompt.split("分析以下單字（含現有翻譯和例句上下文）：\n")[1].split("\n\n回傳")[0])
        assert len(parsed) == 1
        assert "context" not in parsed[0]

    def test_multiple_cards(self):
        cards = [_make_card("a", "一"), _make_card("b", "二")]
        prompt = _build_prompt(cards)
        assert "a" in prompt
        assert "b" in prompt


# ---------------------------------------------------------------------------
# _parse_enrich_response
# ---------------------------------------------------------------------------

class TestParseEnrichResponse:
    def test_json_array_direct(self):
        data = [{"word": "hello", "pos": "n."}]
        result = _parse_enrich_response(json.dumps(data))
        assert result == data

    def test_results_key(self):
        data = {"results": [{"word": "hello"}]}
        result = _parse_enrich_response(json.dumps(data))
        assert result == [{"word": "hello"}]

    def test_fallback_to_first_list_value(self):
        data = {"enrichments": [{"word": "hello"}]}
        result = _parse_enrich_response(json.dumps(data))
        assert result == [{"word": "hello"}]

    def test_empty_string(self):
        """Empty/null content → empty dict parse → empty list."""
        # json.loads("") raises; the function does `raw_content or "{}"`
        result = _parse_enrich_response("")
        assert result == []

    def test_none_content(self):
        result = _parse_enrich_response(None)
        assert result == []

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_enrich_response("not json at all {{{")

    def test_dict_no_list_values(self):
        result = _parse_enrich_response('{"status": "ok"}')
        assert result == []


# ---------------------------------------------------------------------------
# enrich_cards_stream
# ---------------------------------------------------------------------------

class TestEnrichCardsStream:
    @pytest.mark.asyncio
    async def test_empty_cards(self):
        from kg.enrich import enrich_cards_stream
        llm = TrackedLLM(MagicMock(), "test_user")
        results = []
        async for msg in enrich_cards_stream(llm, []):
            results.append(msg)
        assert len(results) == 1
        assert results[0]["status"] == "done"
        assert results[0]["total"] == 0

    @pytest.mark.asyncio
    async def test_multi_batch_yields_progress(self):
        from kg.enrich import enrich_cards_stream
        enriched = [{"word": "w", "pos": "n."}]
        resp = _mock_response(json.dumps(enriched))

        llm = TrackedLLM(MagicMock(), "test_user")

        with patch("kg.enrich.sync_retry", return_value=resp):
            cards = [_make_card(f"word{i}", f"意思{i}") for i in range(5)]
            results = []
            async for msg in enrich_cards_stream(llm, cards, batch_size=2):
                results.append(msg)

        # 5 cards / batch_size 2 = 3 batches → at least 3 progress messages
        running_msgs = [r for r in results if r["status"] == "running"]
        assert len(running_msgs) >= 3
        # Last running message should have current == total
        assert running_msgs[-1]["current"] == 5

    @pytest.mark.asyncio
    async def test_stream_queue_is_bounded(self):
        """The internal asyncio.Queue must have a bounded maxsize so a slow
        consumer can't let workers OOM the process with results."""
        from kg import enrich as enrich_mod
        from kg.enrich import enrich_cards_stream

        captured: dict[str, int] = {}
        original_queue = enrich_mod.asyncio.Queue

        def spy_queue(*args, **kwargs):
            captured["maxsize"] = kwargs.get("maxsize", 0 if not args else args[0])
            return original_queue(*args, **kwargs)

        resp = _mock_response(json.dumps([{"word": "x"}]))
        llm = TrackedLLM(MagicMock(), "u_test")

        with patch("kg.enrich.sync_retry", return_value=resp), \
             patch.object(enrich_mod.asyncio, "Queue", side_effect=spy_queue):
            cards = [_make_card()]
            async for _ in enrich_cards_stream(llm, cards):
                pass

        assert captured.get("maxsize", 0) > 0, (
            "enrich_cards_stream queue is unbounded — a stalled consumer "
            "would let workers buffer unlimited messages."
        )

    @staticmethod
    async def _drain_with_timeout(agen_factory, timeout: float = 5.0):
        """Drain an async generator, failing the test (rather than hanging the
        whole suite) if it doesn't complete within `timeout`. Used to detect
        the consumer/worker deadlock regression."""
        async def _drain():
            out = []
            async for msg in agen_factory():
                out.append(msg)
            return out

        try:
            return await asyncio.wait_for(_drain(), timeout=timeout)
        except TimeoutError:
            pytest.fail(
                "enrich_cards_stream deadlocked: a batch worker failed to emit "
                "its terminal message, tasks_remaining never reached 0, and the "
                "consumer's `await queue.get()` blocked forever."
            )

    @pytest.mark.asyncio
    async def test_stream_does_not_deadlock_on_scalar_json_response(self):
        """Regression (first-line defense): a malformed LLM response whose
        top-level JSON is a scalar/null (e.g. `"x"`, `5`, `null`) used to make
        _parse_enrich_response call `.values()` on a non-dict → AttributeError,
        which was NOT in the worker's catch tuple. It escaped the worker, no
        terminal message was enqueued, tasks_remaining never reached 0, and the
        consumer blocked forever. The stream MUST now complete with exactly one
        terminal message for the single batch (scalar JSON parses to an empty
        enrichment list — a clean success — instead of crashing)."""
        from kg.enrich import enrich_cards_stream

        resp = _mock_response('"unexpected-scalar"')
        llm = TrackedLLM(MagicMock(), "u_deadlock_scalar")

        with patch("kg.enrich.sync_retry", return_value=resp):
            results = await self._drain_with_timeout(
                lambda: enrich_cards_stream(
                    llm, [_make_card("hello", "你好")], batch_size=1
                )
            )

        # tasks_remaining reached 0: the final yielded message accounts for the
        # batch (current == total) and the stream ended without blocking.
        assert results, "stream produced no messages"
        assert results[-1]["status"] in ("running", "error")
        assert results[-1]["current"] == results[-1]["total"] == 1

    @pytest.mark.asyncio
    async def test_stream_does_not_deadlock_on_unexpected_worker_exception(self):
        """Regression (catch-all guarantee): even an exception that bypasses
        _parse_enrich_response's defensive shaping — i.e. a brand-new exception
        type the original narrow catch tuple never anticipated — must still
        produce an error terminal and let the stream complete, rather than
        escaping the worker and deadlocking. Here parsing itself raises an
        unexpected error type."""
        from kg.enrich import enrich_cards_stream

        class WeirdError(Exception):
            """Not in any historical catch tuple."""

        resp = _mock_response('[{"word": "x"}]')
        llm = TrackedLLM(MagicMock(), "u_deadlock_weird")

        with patch("kg.enrich.sync_retry", return_value=resp), \
             patch("kg.enrich._parse_enrich_response", side_effect=WeirdError("boom")):
            results = await self._drain_with_timeout(
                lambda: enrich_cards_stream(
                    llm, [_make_card("hello", "你好")], batch_size=1
                )
            )

        errors = [r for r in results if r["status"] == "error"]
        assert len(errors) == 1, f"expected one error terminal, got: {results}"
        assert "boom" in errors[0]["detail"]
        assert results[-1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_stream_propagates_quota_exceeded(self):
        from kg.enrich import enrich_cards_stream

        llm = TrackedLLM(MagicMock(), "u_quota")

        headers = {"X-Quota-Fraction": "0.0", "X-Quota-Reset": "3600"}
        with patch("kg.enrich.sync_retry", side_effect=QuotaExceededError(reset_seconds=3600, headers=headers)):
            with pytest.raises(QuotaExceededError) as exc_info:
                async for _ in enrich_cards_stream(llm, [_make_card("hello", "你好")], batch_size=1):
                    pass

        assert exc_info.value.reset_seconds == 3600
        assert exc_info.value.headers == headers

    @pytest.mark.asyncio
    async def test_stream_token_tracking_via_tracked_llm(self):
        """Token tracking now happens inside TrackedLLM.chat(), not in stream consumer."""
        from kg.enrich import enrich_cards_stream
        resp = _mock_response(json.dumps([{"word": "x"}]),
                              prompt_tokens=50, completion_tokens=25)
        llm = TrackedLLM(MagicMock(), "u_test")

        with patch("kg.enrich.sync_retry", return_value=resp):
            cards = [_make_card()]
            msgs = []
            async for msg in enrich_cards_stream(llm, cards):
                msgs.append(msg)
            # Stream should still yield running messages without usage key
            running = [m for m in msgs if m["status"] == "running"]
            assert len(running) >= 1
            assert "usage" not in running[0]
