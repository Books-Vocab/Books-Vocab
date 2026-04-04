"""Tests for MochiParser — parsing Mochi markdown back to Card fields."""

from __future__ import annotations

import pytest

from kg.parser import MochiParser
from kg.renderer import FIELDS


@pytest.fixture
def parser():
    return MochiParser()


# ── Recognition mode (Front: Word, Back: Meaning) ──────────────────


class TestParseRecognition:
    def test_basic_word_and_meaning(self, parser):
        content = "**hello**\n---\nworld"
        result = parser.parse(content, "recognition")
        assert result["content"] == "hello"
        assert result["meaning"] == "world"

    def test_word_with_pos(self, parser):
        content = "**hello** [noun]\n---\nworld"
        result = parser.parse(content, "recognition")
        assert result["content"] == "hello"
        assert result["pos"] == "noun"
        assert result["meaning"] == "world"

    def test_word_with_example(self, parser):
        content = "**hello**\n> Say hello to the world\n---\nworld"
        result = parser.parse(content, "recognition")
        assert result["content"] == "hello"
        assert result["examples"] == ["Say hello to the world"]

    def test_collocations_in_back(self, parser):
        content = "**run**\n---\nmeaning\n`run away` `run out`"
        result = parser.parse(content, "recognition")
        assert result["collocations"] == ["run away", "run out"]

    def test_no_separator_returns_empty(self, parser):
        result = parser.parse("no separator here", "recognition")
        assert result == {}

    def test_empty_front_still_parses_back(self, parser):
        result = parser.parse("\n---\nback content", "recognition")
        assert result["meaning"] == "back content"
        assert "content" not in result

    def test_backtick_lines_with_links_ignored(self, parser):
        content = "**word**\n---\nmeaning\n[[linked]] `coll`"
        result = parser.parse(content, "recognition")
        assert "collocations" not in result


# ── Production mode (Front: Meaning, Back: Word) ───────────────────


class TestParseProduction:
    def test_basic(self, parser):
        content = "*the meaning*\n---\n**word**"
        result = parser.parse(content, "production")
        assert result["meaning"] == "the meaning"
        assert result["content"] == "word"

    def test_with_pos(self, parser):
        content = "*the meaning*\n---\n**word** [verb]"
        result = parser.parse(content, "production")
        assert result["content"] == "word"
        assert result["pos"] == "verb"

    def test_fallback_meaning_without_italics(self, parser):
        content = "plain meaning\n---\n**word**"
        result = parser.parse(content, "production")
        assert result["meaning"] == "plain meaning"

    def test_collocations(self, parser):
        content = "*meaning*\n---\n**word**\n`col1` `col2`"
        result = parser.parse(content, "production")
        assert result["collocations"] == ["col1", "col2"]

    def test_no_separator_returns_empty(self, parser):
        result = parser.parse("no separator", "production")
        assert result == {}


# ── parse_fields (Mochi fields dict) ───────────────────────────────


class TestParseFields:
    def _make_fields(self, **kwargs):
        """Build a Mochi-style fields dict from keyword args."""
        result = {}
        for alias, value in kwargs.items():
            field_id = FIELDS.get(alias)
            if field_id:
                result[field_id] = {"id": field_id, "value": value}
        return result

    def test_all_fields(self, parser):
        fields = self._make_fields(
            word="hello", meaning="world", pos="noun",
            note="a note", example="This is a ==test==",
        )
        result = parser.parse_fields(fields)
        assert result["content"] == "hello"
        assert result["meaning"] == "world"
        assert result["pos"] == "noun"
        assert result["note"] == "a note"
        assert result["examples"] == ["This is a **test**"]

    def test_highlight_to_bold_conversion(self, parser):
        fields = self._make_fields(example="==word== is ==good==")
        result = parser.parse_fields(fields)
        assert result["examples"] == ["**word** is **good**"]

    def test_strip_legacy_italic_wrapper(self, parser):
        fields = self._make_fields(example="_the example_")
        result = parser.parse_fields(fields)
        assert result["examples"] == ["the example"]

    def test_empty_fields(self, parser):
        result = parser.parse_fields({})
        assert result == {}

    def test_missing_field_id_skipped(self, parser):
        fields = {"nonexistent_id": {"id": "nonexistent_id", "value": "x"}}
        result = parser.parse_fields(fields)
        assert result == {}

    def test_none_value_skipped(self, parser):
        field_id = FIELDS["word"]
        fields = {field_id: {"id": field_id, "value": None}}
        result = parser.parse_fields(fields)
        assert "content" not in result
