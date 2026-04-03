"""Unit tests for _parse_batch_response — pure function, no mocks needed."""

import json

import pytest

from kg.judge import Judgement, _parse_batch_response

CANDIDATES = [
    ("c1", "word1", "meaning1"),
    ("c2", "word2", "meaning2"),
    ("c3", "word3", "meaning3"),
]


# ── 1. Empty / None content ──────────────────────────────────

class TestEmptyContent:
    def test_none_content_returns_all_none(self):
        result = _parse_batch_response(None, CANDIDATES)
        assert result == {"c1": None, "c2": None, "c3": None}

    def test_empty_string_returns_all_none(self):
        result = _parse_batch_response("", CANDIDATES)
        assert result == {"c1": None, "c2": None, "c3": None}

    def test_none_content_raw_decisions_get_parse_error(self):
        raw: list[dict] = []
        _parse_batch_response(None, CANDIDATES, raw_decisions=raw)
        assert len(raw) == 3
        for d in raw:
            assert d["verdict"] == "parse_error"
            assert d["accepted"] == 0
            assert d["reject_reason"] == "parse_error"


# ── 2. JSON decode error ─────────────────────────────────────

class TestJsonDecodeError:
    def test_invalid_json_returns_all_none(self):
        result = _parse_batch_response("not json {{{", CANDIDATES)
        assert result == {"c1": None, "c2": None, "c3": None}

    def test_invalid_json_raw_decisions_parse_error(self):
        raw: list[dict] = []
        _parse_batch_response("not json", CANDIDATES, raw_decisions=raw)
        assert len(raw) == 3
        assert all(d["verdict"] == "parse_error" for d in raw)


# ── 3. Dict wrapper unwrap ────────────────────────────────────

class TestDictWrapperUnwrap:
    @pytest.mark.parametrize("wrapper_key", ["results", "judgements", "items", "candidates"])
    def test_unwrap_known_keys(self, wrapper_key):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r1"},
            {"word": "word2", "link": "shares_usage", "confidence": 0.8, "reason": "r2"},
            {"word": "word3", "link": "not_applicable", "confidence": 0.0, "reason": ""},
        ]
        content = json.dumps({wrapper_key: items})
        result = _parse_batch_response(content, CANDIDATES)
        assert isinstance(result["c1"], Judgement)
        assert result["c1"].link == "contrasts_with"
        assert result["c3"] is None  # not_applicable


# ── 4. Single object dict ────────────────────────────────────

class TestSingleObjectDict:
    def test_single_object_with_link_key_wrapped_in_list(self):
        content = json.dumps({"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r"})
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(content, cands)
        assert isinstance(result["c1"], Judgement)
        assert result["c1"].link == "contrasts_with"

    def test_dict_without_link_key_becomes_empty(self):
        content = json.dumps({"foo": "bar"})
        result = _parse_batch_response(content, CANDIDATES)
        assert all(v is None for v in result.values())


# ── 5. Non-list / non-dict ───────────────────────────────────

class TestNonListNonDict:
    def test_string_json_becomes_empty(self):
        content = json.dumps("hello")
        result = _parse_batch_response(content, CANDIDATES)
        assert all(v is None for v in result.values())

    def test_number_json_becomes_empty(self):
        content = json.dumps(123)
        result = _parse_batch_response(content, CANDIDATES)
        assert all(v is None for v in result.values())

    def test_bool_json_becomes_empty(self):
        content = json.dumps(True)
        result = _parse_batch_response(content, CANDIDATES)
        assert all(v is None for v in result.values())


# ── 6. Positional match ──────────────────────────────────────

class TestPositionalMatch:
    def test_positional_match_word_matches(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r1"},
            {"word": "word2", "link": "shares_usage", "confidence": 0.8, "reason": "r2"},
            {"word": "word3", "link": "contrasts_with", "confidence": 0.95, "reason": "r3"},
        ]
        result = _parse_batch_response(json.dumps(items), CANDIDATES)
        assert result["c1"] == Judgement(link="contrasts_with", confidence=0.9, reason="r1")
        assert result["c2"] == Judgement(link="shares_usage", confidence=0.8, reason="r2")
        assert result["c3"] == Judgement(link="contrasts_with", confidence=0.95, reason="r3")

    def test_positional_match_empty_word_field(self):
        """Empty word in response still matches positionally."""
        items = [
            {"word": "", "link": "contrasts_with", "confidence": 0.9, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert isinstance(result["c1"], Judgement)


# ── 7. LLM reorder ───────────────────────────────────────────

class TestLLMReorder:
    def test_reorder_falls_back_to_word_lookup(self):
        # LLM returns word2 first, word1 second
        items = [
            {"word": "word2", "link": "shares_usage", "confidence": 0.8, "reason": "r2"},
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r1"},
            {"word": "word3", "link": "contrasts_with", "confidence": 0.85, "reason": "r3"},
        ]
        result = _parse_batch_response(json.dumps(items), CANDIDATES)
        # c1 should get word1's item via word-keyed fallback
        assert result["c1"] == Judgement(link="contrasts_with", confidence=0.9, reason="r1")
        # c2 should get word2's item via word-keyed fallback
        assert result["c2"] == Judgement(link="shares_usage", confidence=0.8, reason="r2")


# ── 8. not_applicable rejection ──────────────────────────────

class TestNotApplicable:
    def test_not_applicable_returns_none(self):
        items = [
            {"word": "word1", "link": "not_applicable", "confidence": 0.9, "reason": "no relation"},
        ]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert result["c1"] is None

    def test_not_applicable_raw_decision_reject_reason(self):
        items = [
            {"word": "word1", "link": "not_applicable", "confidence": 0.5, "reason": "no relation"},
        ]
        cands = [("c1", "word1", "m1")]
        raw: list[dict] = []
        _parse_batch_response(json.dumps(items), cands, raw_decisions=raw)
        assert raw[0]["reject_reason"] == "not_applicable"
        assert raw[0]["accepted"] == 0
        assert raw[0]["verdict"] == "not_applicable"


# ── 9. Low confidence rejection ──────────────────────────────

class TestLowConfidence:
    def test_confidence_below_0_7_returns_none(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.69, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert result["c1"] is None

    def test_confidence_exactly_0_7_accepted(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.7, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert isinstance(result["c1"], Judgement)

    def test_low_confidence_raw_decision_reject_reason(self):
        items = [
            {"word": "word1", "link": "shares_usage", "confidence": 0.5, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        raw: list[dict] = []
        _parse_batch_response(json.dumps(items), cands, raw_decisions=raw)
        assert raw[0]["reject_reason"] == "low_confidence"
        assert raw[0]["accepted"] == 0


# ── 10. Invalid LinkKind ─────────────────────────────────────

class TestInvalidLinkKind:
    def test_confusable_returns_none(self):
        items = [
            {"word": "word1", "link": "confusable", "confidence": 0.9, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert result["c1"] is None

    def test_related_returns_none(self):
        items = [
            {"word": "word1", "link": "related", "confidence": 0.9, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert result["c1"] is None

    def test_invalid_kind_raw_decision_reject_reason(self):
        items = [
            {"word": "word1", "link": "synonym", "confidence": 0.85, "reason": "r"},
        ]
        cands = [("c1", "word1", "m1")]
        raw: list[dict] = []
        _parse_batch_response(json.dumps(items), cands, raw_decisions=raw)
        assert raw[0]["reject_reason"] == "invalid_kind"
        assert raw[0]["accepted"] == 0
        assert raw[0]["confidence"] == 0.85


# ── 11. Beyond response length ───────────────────────────────

class TestBeyondResponseLength:
    def test_fewer_items_than_candidates(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r1"},
        ]
        result = _parse_batch_response(json.dumps(items), CANDIDATES)
        assert isinstance(result["c1"], Judgement)
        assert result["c2"] is None
        assert result["c3"] is None

    def test_beyond_length_raw_decisions_no_response(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r1"},
        ]
        raw: list[dict] = []
        _parse_batch_response(json.dumps(items), CANDIDATES, raw_decisions=raw)
        no_resp = [d for d in raw if d["reject_reason"] == "no_response"]
        assert len(no_resp) == 2
        assert {d["to_id"] for d in no_resp} == {"c2", "c3"}


# ── 12. Happy path ───────────────────────────────────────────

class TestHappyPath:
    def test_full_valid_batch(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "對比"},
            {"word": "word2", "link": "shares_usage", "confidence": 0.85, "reason": "相關用法"},
            {"word": "word3", "link": "contrasts_with", "confidence": 0.75, "reason": "反義"},
        ]
        result = _parse_batch_response(json.dumps(items), CANDIDATES)
        assert result["c1"] == Judgement(link="contrasts_with", confidence=0.9, reason="對比")
        assert result["c2"] == Judgement(link="shares_usage", confidence=0.85, reason="相關用法")
        assert result["c3"] == Judgement(link="contrasts_with", confidence=0.75, reason="反義")

    def test_happy_path_raw_decisions_all_accepted(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r1"},
            {"word": "word2", "link": "shares_usage", "confidence": 0.8, "reason": "r2"},
        ]
        cands = [("c1", "word1", "m1"), ("c2", "word2", "m2")]
        raw: list[dict] = []
        _parse_batch_response(json.dumps(items), cands, raw_decisions=raw)
        assert len(raw) == 2
        assert all(d["accepted"] == 1 for d in raw)
        assert all(d["reject_reason"] is None for d in raw)
        assert raw[0]["to_id"] == "c1"
        assert raw[1]["to_id"] == "c2"

    def test_mixed_accept_reject(self):
        items = [
            {"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "good"},
            {"word": "word2", "link": "not_applicable", "confidence": 0.0, "reason": ""},
            {"word": "word3", "link": "shares_usage", "confidence": 0.5, "reason": "weak"},
        ]
        raw: list[dict] = []
        result = _parse_batch_response(json.dumps(items), CANDIDATES, raw_decisions=raw)
        assert isinstance(result["c1"], Judgement)
        assert result["c2"] is None
        assert result["c3"] is None  # low confidence
        assert raw[0]["accepted"] == 1
        assert raw[1]["reject_reason"] == "not_applicable"
        assert raw[2]["reject_reason"] == "low_confidence"


# ── Edge: raw_decisions=None (default) doesn't crash ─────────

class TestRawDecisionsNone:
    def test_no_raw_decisions_param(self):
        items = [{"word": "word1", "link": "contrasts_with", "confidence": 0.9, "reason": "r"}]
        cands = [("c1", "word1", "m1")]
        result = _parse_batch_response(json.dumps(items), cands)
        assert isinstance(result["c1"], Judgement)

    def test_none_content_no_raw_decisions_no_crash(self):
        result = _parse_batch_response(None, CANDIDATES)
        assert len(result) == 3
