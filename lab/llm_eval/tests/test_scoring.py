"""Tests for rule-based scoring."""

from __future__ import annotations

from llm_eval.scoring import (
    EnrichScorer,
    JsonSchemaScorer,
    JudgeBatchScorer,
    TranslateQualityScorer,
    score_result,
)


class TestJsonSchemaScorer:
    def test_valid_json_all_keys(self):
        scorer = JsonSchemaScorer(["t", "p", "r"])
        result = scorer.score({"t": "喚起", "p": "v.", "r": "evoke"}, {})
        assert result["json_valid"] == 1.0
        assert result["schema_conform"] == 1.0

    def test_missing_key(self):
        scorer = JsonSchemaScorer(["t", "p", "r"])
        result = scorer.score({"t": "喚起", "p": "v."}, {})
        assert result["json_valid"] == 1.0
        assert result["schema_conform"] == 0.0

    def test_empty_parsed(self):
        scorer = JsonSchemaScorer(["t"])
        result = scorer.score({}, {})
        assert result["json_valid"] == 0.0
        assert result["schema_conform"] == 0.0


class TestTranslateQualityScorer:
    def test_trad_chinese_pass(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "輝煌的", "p": "adj.", "r": "resplendent"}, {"word": "resplendent"})
        assert result["trad_chinese"] == 1.0

    def test_trad_chinese_fail_simplified(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "辉煌的", "p": "adj.", "r": "resplendent"}, {"word": "resplendent"})
        assert result["trad_chinese"] == 0.0

    def test_pos_suffix_adj_correct(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "輝煌的", "p": "adj.", "r": "resplendent"}, {"word": "resplendent"})
        assert result["pos_correct"] == 1.0

    def test_pos_suffix_adj_wrong(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "輝煌", "p": "adj.", "r": "resplendent"}, {"word": "resplendent"})
        assert result["pos_correct"] == 0.0

    def test_pos_suffix_adv_correct(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "端莊地", "p": "adv.", "r": "dignifiedly"}, {"word": "dignifiedly"})
        assert result["pos_correct"] == 1.0

    def test_pos_no_suffix_rule_for_noun(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "記憶", "p": "n.", "r": "memory"}, {"word": "memory"})
        assert result["pos_correct"] == 1.0

    def test_lemma_empty(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "喚起", "p": "v.", "r": ""}, {"word": "evoke"})
        assert result["lemma_ok"] == 0.0

    def test_lemma_valid(self):
        scorer = TranslateQualityScorer()
        result = scorer.score({"t": "喚起", "p": "v.", "r": "evoke"}, {"word": "evoke"})
        assert result["lemma_ok"] == 1.0


class TestJudgeBatchScorer:
    def test_valid_batch(self):
        scorer = JudgeBatchScorer()
        parsed = [
            {"word": "sloppy", "link": "contrasts_with", "confidence": 0.9, "reason": "相反的意思"},
            {"word": "careless", "link": "shares_usage", "confidence": 0.8, "reason": "類似用法"},
        ]
        result = scorer.score(parsed, {})
        assert result["link_valid"] == 1.0
        assert result["confidence_range"] == 1.0
        assert result["reason_trad"] == 1.0

    def test_invalid_link(self):
        scorer = JudgeBatchScorer()
        parsed = [{"word": "x", "link": "invalid", "confidence": 0.5, "reason": "test"}]
        result = scorer.score(parsed, {})
        assert result["link_valid"] == 0.0

    def test_confidence_out_of_range(self):
        scorer = JudgeBatchScorer()
        parsed = [{"word": "x", "link": "contrasts_with", "confidence": 1.5, "reason": "test"}]
        result = scorer.score(parsed, {})
        assert result["confidence_range"] == 0.0

    def test_confidence_nan(self):
        scorer = JudgeBatchScorer()
        parsed = [{"word": "x", "link": "contrasts_with", "confidence": float("nan"), "reason": "test"}]
        result = scorer.score(parsed, {})
        assert result["confidence_range"] == 0.0

    def test_reason_simplified(self):
        scorer = JudgeBatchScorer()
        parsed = [{"word": "x", "link": "contrasts_with", "confidence": 0.9, "reason": "这完全没有关联"}]
        result = scorer.score(parsed, {})
        assert result["reason_trad"] == 0.0


class TestEnrichScorer:
    def test_valid_enrich(self):
        scorer = EnrichScorer()
        parsed = [
            {
                "word": "resilient",
                "pos": "adj.",
                "note": "強調從挫折中恢復的能力",
                "collocations": ["resilient community", "emotionally resilient"],
                "meaning_fix": "有韌性的",
            }
        ]
        result = scorer.score(parsed, {})
        assert result["pos_valid"] == 1.0
        assert result["note_trad"] == 1.0
        assert result["meaning_fix_trad"] == 1.0

    def test_invalid_pos(self):
        scorer = EnrichScorer()
        parsed = [{"word": "x", "pos": "adjective", "note": "test", "collocations": [], "meaning_fix": None}]
        result = scorer.score(parsed, {})
        assert result["pos_valid"] == 0.0

    def test_note_simplified(self):
        scorer = EnrichScorer()
        parsed = [{"word": "x", "pos": "n.", "note": "强调重点", "collocations": [], "meaning_fix": None}]
        result = scorer.score(parsed, {})
        assert result["note_trad"] == 0.0

    def test_meaning_fix_adj_suffix_wrong(self):
        scorer = EnrichScorer()
        parsed = [{"word": "x", "pos": "adj.", "note": "test", "collocations": [], "meaning_fix": "輝煌"}]
        result = scorer.score(parsed, {})
        assert result["meaning_fix_trad"] == 0.0


class TestScoreResultDispatcher:
    def test_translate_quick(self):
        scores = score_result(
            "translate_quick",
            {"t": "輝煌的", "p": "adj.", "r": "resplendent"},
            {"word": "resplendent"},
        )
        assert "json_valid" in scores
        assert "trad_chinese" in scores
        assert "pos_correct" in scores

    def test_unknown_prompt(self):
        scores = score_result("unknown_prompt", {"x": 1}, {})
        assert scores == {}
