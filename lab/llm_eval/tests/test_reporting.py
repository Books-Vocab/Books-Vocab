"""Tests for eval report and baseline helpers."""

from __future__ import annotations

import json

from llm_eval.reporting import compare_to_baseline, write_report
from llm_eval.runner import EvalResult, EvalSummary


def _summary(*, model: str = "deepseek-v4-flash", format_score: float = 1.0, quality_score: float | None = None):
    return EvalSummary(
        model=model,
        provider="deepseek",
        sample_count=1,
        success_count=1,
        error_count=0,
        avg_latency_ms=123,
        total_input_tokens=10,
        total_output_tokens=5,
        total_cost_usd=0.001,
        format_score_avg=format_score,
        quality_score_avg=quality_score,
        score_breakdown={"json_valid": format_score},
        samples=[
            EvalResult(
                sample_id="s1",
                model=model,
                provider="deepseek",
                latency_ms=123,
                input_tokens=10,
                output_tokens=5,
                raw_output='{"t":"喚起"}',
                parsed_output={"t": "喚起"},
                scores={"json_valid": format_score},
            )
        ],
    )


def test_write_report_outputs_json_and_markdown(tmp_path):
    out = write_report(
        summaries={"deepseek-v4-flash": _summary(quality_score=0.9)},
        output_dir=tmp_path,
        prompt_name="translate_quick",
        prompt_version="v1",
        dataset_name="translate_quick_gold",
        dataset_hash="abc123",
        config={"temperature": 0.3},
        git_sha="deadbeef",
        timestamp="20260606T120000Z",
    )

    assert out.json_path.exists()
    assert out.markdown_path.exists()
    payload = json.loads(out.json_path.read_text(encoding="utf-8"))
    assert payload["git_sha"] == "deadbeef"
    assert payload["dataset_hash"] == "abc123"
    assert payload["models"]["deepseek-v4-flash"]["quality_score_avg"] == 0.9
    assert "translate_quick" in out.markdown_path.read_text(encoding="utf-8")


def test_compare_to_baseline_separates_format_and_quality_regression():
    current = {"m": _summary(model="m", format_score=0.8, quality_score=0.7)}
    baseline = {
        "models": {
            "m": {
                "format_score_avg": 1.0,
                "quality_score_avg": 0.9,
            }
        }
    }

    result = compare_to_baseline(current, baseline)

    assert result["m"]["format_delta"] == -0.2
    assert result["m"]["quality_delta"] == -0.2
    assert result["m"]["format_regression"] is True
    assert result["m"]["quality_regression"] is True


def test_compare_to_baseline_does_not_invent_quality_without_human_gold():
    current = {"m": _summary(model="m", format_score=1.0, quality_score=None)}
    baseline = {"models": {"m": {"format_score_avg": 1.0, "quality_score_avg": 0.9}}}

    result = compare_to_baseline(current, baseline)

    assert result["m"]["quality_delta"] is None
    assert result["m"]["quality_regression"] is False
