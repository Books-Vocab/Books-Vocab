"""Tests for private corpus builder."""

from __future__ import annotations

import json

from llm_eval.corpus import build_private_corpus, sanitize_context


def test_sanitize_context_redacts_ids_and_truncates():
    raw = "user 000287.04e254024c2f4341849278a933743257.0228 card abc123def456 " + ("x" * 400)
    clean = sanitize_context(raw, max_chars=120)
    assert "000287" not in clean
    assert "abc123def456" not in clean
    assert len(clean) <= 120


def test_build_private_corpus_from_fake_dump(tmp_path):
    dump = {
        "user_id": "000287.04e254024c2f4341849278a933743257.0228",
        "cards": [
            {
                "id": "card123",
                "content": "resplendent",
                "meaning": "輝煌的",
                "pos": "adj.",
                "root_form": "resplendent",
                "examples": ["The queen wore a **resplendent** robe."],
                "note": "正式語感。",
                "review_count": 3,
                "last_review_feedback": 1,
            },
            {
                "id": "card456",
                "content": "stamped out",
                "meaning": "被徹底消滅",
                "pos": "phr.",
                "root_form": None,
                "examples": ["The rebellion was **stamped out**."],
                "note": "片語。",
                "review_count": 8,
                "last_review_feedback": 0,
            },
        ],
    }
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")

    outputs = build_private_corpus(dump_path, tmp_path / "private_corpus", limit=10)

    quick_rows = [
        json.loads(line)
        for line in outputs["translate_quick"].read_text(encoding="utf-8").splitlines()
    ]
    phrase_rows = [
        json.loads(line)
        for line in outputs["translate_phrase"].read_text(encoding="utf-8").splitlines()
    ]
    explain_rows = [
        json.loads(line)
        for line in outputs["translate_explain"].read_text(encoding="utf-8").splitlines()
    ]

    assert quick_rows[0]["source"] == "historical_user_data"
    assert quick_rows[0]["gold_status"] == "unverified"
    assert "weak_reference" in quick_rows[0]
    assert "user_id" not in quick_rows[0]
    assert "card123" not in json.dumps(quick_rows, ensure_ascii=False)
    assert phrase_rows[0]["word"] == "stamped out"
    assert explain_rows[0]["review"]["last_review_feedback"] == 0


def test_build_private_corpus_sanitizes_weak_reference_and_excludes_high_risk_from_gold_queue(tmp_path):
    dump = {
        "user_id": "000287.04e254024c2f4341849278a933743257.0228",
        "cards": [
            {
                "id": "abc123def456",
                "content": "max@example.com",
                "meaning": "max@example.com 的秘密",
                "pos": "n.",
                "root_form": "000287.04e254024c2f4341849278a933743257.0228",
                "examples": ["Email max@example.com about 000287.04e254024c2f4341849278a933743257.0228."],
                "note": "card abc123def456 belongs to max@example.com",
                "review_count": 4,
                "last_review_feedback": 0,
            }
        ],
    }
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")

    outputs = build_private_corpus(dump_path, tmp_path / "private_corpus")
    quick_rows = [
        json.loads(line)
        for line in outputs["translate_quick"].read_text(encoding="utf-8").splitlines()
    ]
    explain_rows = outputs["translate_explain"].read_text(encoding="utf-8").splitlines()
    serialized = json.dumps(quick_rows, ensure_ascii=False)

    assert quick_rows[0]["pii_risk"] == "high"
    assert quick_rows[0]["gold_queue_eligible"] is False
    assert quick_rows[0]["word"] == "[EMAIL]"
    assert "max@example.com" not in serialized
    assert "000287" not in serialized
    assert "abc123def456" not in serialized
    assert explain_rows == []


def test_root_form_pii_marks_row_ineligible_for_gold_queue(tmp_path):
    dump = {
        "cards": [
            {
                "content": "ordinary",
                "meaning": "普通的",
                "pos": "adj.",
                "root_form": "max@example.com",
                "examples": ["An **ordinary** sentence."],
                "review_count": 1,
                "last_review_feedback": 1,
            }
        ]
    }
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")

    outputs = build_private_corpus(dump_path, tmp_path / "private_corpus")
    quick_rows = [
        json.loads(line)
        for line in outputs["translate_quick"].read_text(encoding="utf-8").splitlines()
    ]
    explain_rows = outputs["translate_explain"].read_text(encoding="utf-8").splitlines()

    assert quick_rows[0]["pii_risk"] == "high"
    assert quick_rows[0]["gold_queue_eligible"] is False
    assert quick_rows[0]["weak_reference"]["root"] == "[EMAIL]"
    assert explain_rows == []
