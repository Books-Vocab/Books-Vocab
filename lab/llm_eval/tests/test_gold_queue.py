"""Tests for human gold review queue generation."""

from __future__ import annotations

import json
import subprocess
import sys

from llm_eval.gold_queue import build_gold_review_queue
from llm_eval.gold_queue_cli import main


def test_build_translate_quick_gold_review_queue_excludes_high_risk(tmp_path):
    candidates = tmp_path / "translate_quick_candidates.jsonl"
    _write_jsonl(
        candidates,
        [
            {
                "id": "candidate_0001",
                "word": "resplendent",
                "context": "The robe was resplendent.",
                "source_lang": "en",
                "target_lang": "zh-Hant",
                "source": "historical_user_data",
                "gold_status": "unverified",
                "pii_risk": "low",
                "gold_queue_eligible": True,
                "weak_reference": {"translation": "輝煌的", "pos": "adj.", "root": "resplendent"},
                "source_trace": {"ordinal": 1},
            },
            {
                "id": "candidate_0002",
                "word": "[EMAIL]",
                "context": "Email [EMAIL].",
                "source_lang": "en",
                "target_lang": "zh-Hant",
                "source": "historical_user_data",
                "gold_status": "unverified",
                "pii_risk": "high",
                "gold_queue_eligible": False,
                "weak_reference": {"translation": "[EMAIL]", "pos": "n.", "root": "[EMAIL]"},
                "source_trace": {"ordinal": 2},
            },
        ],
    )
    output = tmp_path / "translate_quick_gold.review.jsonl"

    rows = build_gold_review_queue(
        candidates,
        output,
        prompt_name="translate_quick",
        limit=10,
        seed=7,
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "candidate_0001"
    assert rows[0]["gold_status"] == "unverified"
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["gold_translation"] == ""
    assert rows[0]["gold_pos"] == ""
    assert rows[0]["gold_root"] == ""
    assert rows[0]["reviewer_notes"] == ""
    assert "candidate_0002" not in output.read_text(encoding="utf-8")


def test_build_translate_explain_gold_review_queue_uses_keyword_template(tmp_path):
    candidates = tmp_path / "translate_explain_candidates.jsonl"
    _write_jsonl(
        candidates,
        [
            {
                "id": "candidate_0001",
                "word": "stamped out",
                "context": "The fire was stamped out.",
                "source_lang": "en",
                "target_lang": "zh-Hant",
                "source": "historical_user_data",
                "gold_status": "unverified",
                "pii_risk": "low",
                "gold_queue_eligible": True,
                "weak_reference": {"translation": "撲滅", "pos": "phr.", "root": ""},
                "source_trace": {"ordinal": 1},
            }
        ],
    )
    output = tmp_path / "translate_explain_gold.review.jsonl"

    rows = build_gold_review_queue(
        candidates,
        output,
        prompt_name="translate_explain",
        limit=5,
    )

    assert rows[0]["gold_keywords"] == []
    assert rows[0]["rubric_notes"] == ""
    assert rows[0]["reviewer_notes"] == ""
    assert "gold_translation" not in rows[0]


def test_gold_review_queue_requires_explicit_allowed_pii_risk(tmp_path):
    candidates = tmp_path / "translate_quick_candidates.jsonl"
    _write_jsonl(
        candidates,
        [
            {
                "id": "missing_pii",
                "word": "opaque",
                "context": "An opaque row.",
                "gold_status": "unverified",
                "gold_queue_eligible": True,
            },
            {
                "id": "unknown_pii",
                "word": "opaque",
                "context": "An opaque row.",
                "gold_status": "unverified",
                "gold_queue_eligible": True,
                "pii_risk": "unknown",
            },
            {
                "id": "medium_pii",
                "word": "opaque",
                "context": "An opaque row.",
                "gold_status": "unverified",
                "gold_queue_eligible": True,
                "pii_risk": "medium",
            },
        ],
    )
    output = tmp_path / "translate_quick_gold.review.jsonl"

    rows = build_gold_review_queue(
        candidates,
        output,
        prompt_name="translate_quick",
        limit=10,
    )

    assert [row["id"] for row in rows] == ["medium_pii"]
    assert rows[0]["pii_risk"] == "medium"


def test_sample_gold_queue_cli_prints_summary(tmp_path, capsys):
    candidates = tmp_path / "translate_quick_candidates.jsonl"
    _write_jsonl(
        candidates,
        [
            {
                "id": "candidate_0001",
                "word": "resplendent",
                "context": "The robe was resplendent.",
                "source_lang": "en",
                "target_lang": "zh-Hant",
                "source": "historical_user_data",
                "gold_status": "unverified",
                "pii_risk": "low",
                "gold_queue_eligible": True,
                "weak_reference": {"translation": "輝煌的"},
                "source_trace": {"ordinal": 1},
            }
        ],
    )
    output = tmp_path / "review.jsonl"

    exit_code = main(
        [
            "--prompt",
            "translate_quick",
            "--candidates",
            str(candidates),
            "--output",
            str(output),
            "--limit",
            "30",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["prompt_name"] == "translate_quick"
    assert summary["rows"] == 1
    assert summary["output"] == str(output)
    assert "candidates" not in summary


def test_sample_gold_queue_cli_rejects_non_positive_limit(tmp_path):
    candidates = tmp_path / "translate_quick_candidates.jsonl"
    candidates.write_text("", encoding="utf-8")

    exit_code = main(
        [
            "--prompt",
            "translate_quick",
            "--candidates",
            str(candidates),
            "--output",
            str(tmp_path / "review.jsonl"),
            "--limit",
            "0",
        ]
    )

    assert exit_code == 2


def test_sample_gold_queue_script_wrapper_can_show_help():
    script = _lab_root() / "scripts" / "sample_gold_queue.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=_lab_root(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Sample private candidates" in result.stdout


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _lab_root():
    return __import__("pathlib").Path(__file__).resolve().parents[1]
