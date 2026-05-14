"""Tests for kg.enrich — LLM-powered card enrichment."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.cards import Card
from kg.enrich import _build_prompt, _parse_enrich_response, enrich_cards
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
# enrich_cards
# ---------------------------------------------------------------------------

class TestEnrichCards:
    def test_empty_cards_returns_empty(self):
        llm = TrackedLLM(MagicMock(), "test_user")
        result = enrich_cards(llm, [])
        assert result == []

    @patch("kg.enrich.sync_retry")
    def test_normal_batch(self, mock_retry):
        enriched = [{"word": "hello", "pos": "interj.", "note": "打招呼用語"}]
        mock_retry.return_value = _mock_response(json.dumps(enriched))

        llm = TrackedLLM(MagicMock(), "test_user")
        cards = [_make_card("hello", "你好")]
        result = enrich_cards(llm, cards)

        assert result == enriched
        mock_retry.assert_called_once()

    @patch("kg.token_tracker.record")
    @patch("kg.enrich.sync_retry")
    def test_usage_recorded_by_tracked_llm(self, mock_retry, mock_record):
        """Token tracking is now handled by TrackedLLM.chat(), not enrich_cards."""
        mock_retry.return_value = _mock_response(
            json.dumps([{"word": "x"}]), prompt_tokens=100, completion_tokens=50
        )
        llm = TrackedLLM(MagicMock(), "u_test")
        enrich_cards(llm, [_make_card()])
        # enrich_cards no longer calls record directly — TrackedLLM handles it
        # so we only verify sync_retry was called with llm
        mock_retry.assert_called_once()


# ---------------------------------------------------------------------------
# Hardening: malformed JSON / atomicity / token audit on success+failure
# ---------------------------------------------------------------------------


def _client_returning(content: str, prompt_tokens: int = 30,
                     completion_tokens: int = 15) -> MagicMock:
    """Build a MagicMock OpenAI client whose chat.completions.create() returns
    a response shaped like a real OpenAI ChatCompletion."""
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response(
        content, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    return client


class TestEnrichHardening:
    """Failure-mode contracts: malformed JSON, atomicity, token audit."""

    # -- 1. malformed LLM JSON ------------------------------------------------
    def test_enrich_handles_malformed_llm_json_response(self):
        """LLM returns truncated / non-JSON garbage.

        Contract:
          - enrich_cards must surface a deterministic, catchable error
            (json.JSONDecodeError) rather than crashing with TypeError /
            AttributeError or silently returning bogus data.
          - The underlying LLM call must have been attempted (not short-
            circuited before reaching the client).
        """
        truncated = '[{"word": "hello", "pos": "n.", "note": "incomp'  # cut mid-string
        client = _client_returning(truncated)
        llm = TrackedLLM(client, "u_malformed")
        cards = [_make_card("hello", "你好")]

        with pytest.raises(json.JSONDecodeError):
            enrich_cards(llm, cards)

        # The LLM was actually invoked exactly once — failure is in parse, not setup
        assert client.chat.completions.create.call_count == 1

        # And a second variant: pure garbage (no json at all)
        client2 = _client_returning("<<<not json>>>")
        llm2 = TrackedLLM(client2, "u_malformed2")
        with pytest.raises(json.JSONDecodeError):
            enrich_cards(llm2, cards)

    # -- 2. atomicity: caller's Card untouched on failure --------------------
    def test_enrich_preserves_user_metadata_on_failure(self):
        """When enrich fails mid-flow, the caller's Card objects must not be
        mutated. enrich_cards returns enrichment dicts; merging is the
        caller's responsibility — but the input list must remain pristine
        even if the LLM call fails. This guards against accidental in-place
        edits inside _build_prompt or future helpers."""
        card = _make_card("abandon", "放棄", ["He abandoned the project."])
        card.pos = "v."
        card.note = "user-written note"
        card.collocations = ["abandon hope"]

        # snapshot (deep copy of mutable fields)
        before = {
            "id": card.id,
            "content": card.content,
            "meaning": card.meaning,
            "pos": card.pos,
            "note": card.note,
            "examples": list(card.examples),
            "collocations": list(card.collocations),
        }

        client = _client_returning('{"this":"is": "broken')  # malformed
        llm = TrackedLLM(client, "u_atomic")

        with pytest.raises(json.JSONDecodeError):
            enrich_cards(llm, [card])

        # card identity + every captured field unchanged
        assert card.id == before["id"]
        assert card.content == before["content"]
        assert card.meaning == before["meaning"]
        assert card.pos == before["pos"]
        assert card.note == before["note"]
        assert card.examples == before["examples"]
        assert card.collocations == before["collocations"]

    # -- 3. token audit on BOTH success and failure --------------------------
    @patch("kg.tracked_llm.record")
    def test_enrich_token_usage_recorded_on_both_success_and_failure(self, mock_record):
        """Audit invariant: every LLM round-trip that returns a usage block
        must be recorded — regardless of whether downstream parsing succeeds.

        This matters because token cost is incurred the moment the provider
        responds. If we only recorded on success, we'd undercount quota usage
        whenever the model emits malformed JSON (a common failure mode for
        cheaper models).
        """
        # --- success path ---
        good_client = _client_returning(
            json.dumps([{"word": "ok", "pos": "n.", "note": "fine"}]),
            prompt_tokens=42, completion_tokens=17,
        )
        good_llm = TrackedLLM(good_client, "u_success")
        result = enrich_cards(good_llm, [_make_card("ok", "好")])
        assert result == [{"word": "ok", "pos": "n.", "note": "fine"}]

        # one record call from success path
        assert mock_record.call_count == 1
        success_call = mock_record.call_args_list[0]
        # signature: record(user_id, call_type, prompt_tokens, completion_tokens)
        assert success_call.args[0] == "u_success"
        assert success_call.args[1] == "enrich"
        assert success_call.args[2] == 42
        assert success_call.args[3] == 17

        # --- failure path (malformed JSON, but LLM did return usage) ---
        bad_client = _client_returning(
            '[{"word": "x", "pos":',   # truncated mid-token
            prompt_tokens=99, completion_tokens=4,
        )
        bad_llm = TrackedLLM(bad_client, "u_failure")
        with pytest.raises(json.JSONDecodeError):
            enrich_cards(bad_llm, [_make_card("x", "X")])

        # second record call should still have fired — audit not skipped
        assert mock_record.call_count == 2, (
            "token usage was not recorded on parse-failure path — "
            "audit/quota will undercount whenever the model emits malformed JSON"
        )
        failure_call = mock_record.call_args_list[1]
        assert failure_call.args[0] == "u_failure"
        assert failure_call.args[1] == "enrich"
        assert failure_call.args[2] == 99
        assert failure_call.args[3] == 4


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
