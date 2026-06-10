from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "review_flip_probe_report", ROOT / "ops" / "review_flip_probe_report.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

parse_jsonl = MODULE.parse_jsonl
evaluate = MODULE.evaluate
DEFAULT_THRESHOLDS = MODULE.DEFAULT_THRESHOLDS


def _header(**overrides):
    record = {
        "type": "header",
        "schema": 1,
        "build_config": "debug",
        "os_version": "26.0",
        "low_power_mode": False,
        "thermal_start": "nominal",
        "plan_flips": 3,
        "plan_reveal_hold_ms": 1000,
        "plan_inter_flip_ms": 1300,
        "started_at": "2026-06-10T12:00:00Z",
    }
    record.update(overrides)
    return record


def _flip(i, max_gap, stalls=0, hitch=0.0):
    return {
        "type": "flip",
        "i": i,
        "fb": "R" if i % 2 == 0 else "F",
        "frames": 51,
        "dur_ms": 850.0,
        "fps": 60.0,
        "max_gap_ms": max_gap,
        "max_gap_at_ms": 263.0,
        "stalls": stalls,
        "hitch_ms": hitch,
        "top_gaps_ms": [max_gap],
    }


def _summary(n, p95, stalls_total, aborted=False, **overrides):
    record = {
        "type": "summary",
        "n": n,
        "stalls_total": stalls_total,
        "flips_with_stall": 1 if stalls_total else 0,
        "max_gap_p50_ms": 17.0,
        "max_gap_p95_ms": p95,
        "max_gap_max_ms": p95,
        "hitch_ms_per_s": 0.0,
        "aborted": aborted,
        "thermal_end": "nominal",
    }
    record.update(overrides)
    return record


def _lines(*records):
    return [json.dumps(r) for r in records]


class TestParseJsonl:
    def test_parses_header_flips_summary(self):
        parsed = parse_jsonl(
            _lines(_header(), _flip(0, 17.0), _flip(1, 58.2, stalls=1), _summary(2, 58.2, 1))
        )
        assert parsed.header["build_config"] == "debug"
        assert len(parsed.flips) == 2
        assert parsed.summary["n"] == 2
        assert parsed.errors == []

    def test_missing_summary_is_recorded(self):
        parsed = parse_jsonl(_lines(_header(), _flip(0, 17.0)))
        assert parsed.summary is None

    def test_malformed_line_is_an_error_not_a_crash(self):
        parsed = parse_jsonl(["not json", json.dumps(_header())])
        assert parsed.header is not None
        assert len(parsed.errors) == 1


class TestEvaluate:
    def test_clean_run_passes(self):
        parsed = parse_jsonl(
            _lines(_header(), _flip(0, 17.0), _flip(1, 20.0), _flip(2, 16.0), _summary(3, 20.0, 0))
        )
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=3)
        assert verdict["result"] == "pass"
        assert verdict["reasons"] == []

    def test_residual_hitch_magnitude_fails_both_gates(self):
        # 歷史殘餘 hitch 量級（58-72ms / stalls=1）必須 fail —— rig 的存在理由。
        parsed = parse_jsonl(
            _lines(_header(), _flip(0, 58.2, stalls=1), _flip(1, 71.8, stalls=1), _summary(2, 71.8, 2))
        )
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=2)
        assert verdict["result"] == "fail"
        joined = " ".join(verdict["reasons"])
        assert "max_gap_p95_ms" in joined
        assert "stalls_total" in joined

    def test_aborted_run_is_invalid_not_fail(self):
        parsed = parse_jsonl(_lines(_header(), _flip(0, 17.0), _summary(1, 17.0, 0, aborted=True)))
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=1)
        assert verdict["result"] == "invalid"

    def test_too_few_flips_is_invalid(self):
        parsed = parse_jsonl(_lines(_header(), _flip(0, 17.0), _summary(1, 17.0, 0)))
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=30)
        assert verdict["result"] == "invalid"

    def test_missing_summary_is_invalid(self):
        parsed = parse_jsonl(_lines(_header(), _flip(0, 17.0)))
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=1)
        assert verdict["result"] == "invalid"

    def test_missing_header_is_invalid(self):
        # 不知 build config 的 pass 是弱證據 — header 缺失視為殘缺 run。
        parsed = parse_jsonl(_lines(_flip(0, 17.0), _summary(1, 17.0, 0)))
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=1)
        assert verdict["result"] == "invalid"

    def test_malformed_summary_field_is_invalid_never_fail(self):
        # app 落殘缺欄位（type 錯）絕不可流為 fail（假效能結論）。
        parsed = parse_jsonl(
            _lines(_header(), _flip(0, 17.0), _summary(1, 17.0, 0, max_gap_p95_ms=None))
        )
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=1)
        assert verdict["result"] == "invalid"
        assert any("malformed summary field" in r for r in verdict["reasons"])

    def test_verdict_carries_observed_numbers(self):
        parsed = parse_jsonl(
            _lines(_header(), _flip(0, 58.2, stalls=1), _summary(1, 58.2, 1))
        )
        verdict = evaluate(parsed, DEFAULT_THRESHOLDS, min_flips=1)
        assert verdict["summary"]["max_gap_p95_ms"] == 58.2
        assert verdict["thresholds"]["max_gap_p95_ms"] == 33.0
        assert verdict["header"]["build_config"] == "debug"


class TestCli:
    def test_cli_pass_and_fail_exit_codes(self, tmp_path):
        script = ROOT / "ops" / "review_flip_probe_report.py"

        ok = tmp_path / "ok.jsonl"
        ok.write_text(
            "\n".join(_lines(_header(), _flip(0, 17.0), _summary(1, 17.0, 0))) + "\n"
        )
        result = subprocess.run(
            [sys.executable, str(script), "--jsonl", str(ok), "--min-flips", "1"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        verdict = json.loads(result.stdout)
        assert verdict["result"] == "pass"

        bad = tmp_path / "bad.jsonl"
        bad.write_text(
            "\n".join(_lines(_header(), _flip(0, 58.2, stalls=1), _summary(1, 58.2, 1))) + "\n"
        )
        result = subprocess.run(
            [sys.executable, str(script), "--jsonl", str(bad), "--min-flips", "1"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert json.loads(result.stdout)["result"] == "fail"

        missing = tmp_path / "missing.jsonl"
        missing.write_text(json.dumps(_header()) + "\n")
        result = subprocess.run(
            [sys.executable, str(script), "--jsonl", str(missing), "--min-flips", "1"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert json.loads(result.stdout)["result"] == "invalid"
