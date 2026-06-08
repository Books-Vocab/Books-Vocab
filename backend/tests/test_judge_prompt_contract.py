"""Contract tests for judge prompt consistency.

Pins the cross-prompt invariants fixed when ``contrasts_with`` was given a
single canonical meaning: **strict antonym / opposite**, NOT near-synonym.
Before this, batch / selective / manual each defined the link type
differently (batch=opposite, selective=opposite-or-nuance,
manual=similar-but-nuanced), so the same pair was judged inconsistently
across the three call paths. These tests guard against re-drifting.

They also pin two cost invariants on the *output* token budget (deepseek
charges 2x for output vs input, and prefix-caches the system prompt):
- ``not_applicable`` carries an empty reason (the reason is log-only, never
  shown to users, so emitting a 繁體中文 sentence for it is pure waste).
- the manual prompt never asks for ``confidence`` (manual.py always
  overwrites it to 1.0, so generating it wastes output tokens).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from kg.judge import (
    BATCH_SYSTEM_PROMPT,
    MANUAL_LINK_SYSTEM_PROMPT,
    SELECTIVE_BATCH_SYSTEM_PROMPT,
)
from kg.judge.prompts import MANUAL_USER_TEMPLATE
from kg.tracked_llm import TrackedLLM

# Selective is a format template ({n} / {max_links}); content checks are
# substring-based so the unfilled braces do not interfere.
_SELECTIVE = SELECTIVE_BATCH_SYSTEM_PROMPT
_ALL_BATCH = (BATCH_SYSTEM_PROMPT, _SELECTIVE)
_ALL = (BATCH_SYSTEM_PROMPT, _SELECTIVE, MANUAL_LINK_SYSTEM_PROMPT)


class TestCanonicalContrastSemantics:
    def test_every_prompt_frames_contrast_as_opposite(self):
        for p in _ALL:
            assert "contrasts_with" in p
            assert "opposite" in p.lower(), "contrast must be framed as opposite/antonym"

    def test_selective_dropped_the_nuance_drift(self):
        # the historical bug: "opposite or clearly different nuances of a
        # similar concept" let near-synonyms be judged contrasts_with.
        assert "different nuances" not in _SELECTIVE.lower()

    def test_manual_dropped_the_similar_overlapping_drift(self):
        # manual previously defined contrasts_with as "similar or overlapping
        # meanings but differ in nuance" — the exact opposite of canonical.
        assert "similar or overlapping" not in MANUAL_LINK_SYSTEM_PROMPT.lower()


class TestNotApplicableEmptyReason:
    def test_batch_instructs_empty_reason_for_not_applicable(self):
        assert "not_applicable" in BATCH_SYSTEM_PROMPT
        assert "empty" in BATCH_SYSTEM_PROMPT.lower()

    def test_selective_instructs_empty_reason_for_rejects(self):
        assert "empty" in _SELECTIVE.lower()


class TestManualConfidenceRemoved:
    def test_manual_system_prompt_does_not_request_confidence(self):
        assert "confidence" not in MANUAL_LINK_SYSTEM_PROMPT.lower()

    def test_manual_user_template_does_not_mention_confidence(self):
        assert "confidence" not in MANUAL_USER_TEMPLATE.lower()


class TestManualUserTemplateCentralized:
    def test_template_renders_both_words_and_meanings(self):
        rendered = MANUAL_USER_TEMPLATE.format(
            word_a="alpha", meaning_a="m_a", word_b="beta", meaning_b="m_b"
        )
        for token in ("alpha", "m_a", "beta", "m_b"):
            assert token in rendered

    def test_manual_judge_sends_template_rendered_user_message(self):
        """ManualLinkJudge.evaluate must build its user message from the shared
        template (not an inline string), so the production prompt and the
        llm_eval SoT snapshot stay byte-aligned."""
        captured: list[dict] = []
        client = MagicMock()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '{"link": "shares_usage", "reason": "r"}'
        resp.usage = None

        def _capture(**kwargs):
            captured.append(kwargs)
            return resp

        client.chat.completions.create.side_effect = _capture

        from kg.judge import ManualLinkJudge

        judge = ManualLinkJudge(llm=TrackedLLM(client, "u"))
        judge.evaluate("alpha", "m_a", "beta", "m_b")

        assert len(captured) == 1
        messages = captured[0]["messages"]
        assert messages[0]["content"] == MANUAL_LINK_SYSTEM_PROMPT
        assert messages[1]["content"] == MANUAL_USER_TEMPLATE.format(
            word_a="alpha", meaning_a="m_a", word_b="beta", meaning_b="m_b"
        )
