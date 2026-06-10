#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""review_flip_probe_report.py — review-flip probe JSONL 解析 + 預登門檻 verdict。

輸入：app 端 ReviewProbeMetrics 落的 JSONL（header + flip… + summary）。
輸出：verdict JSON（stdout）。exit code：0=pass、1=fail、2=invalid（run 殘缺，
不可拿來下任何效能結論 — invalid ≠ fail，兩者語意嚴格區分）。

預登門檻（法證審計 2026-06 的成功判準，不可事後鬆動）：
  max_gap_p95_ms < 33（@60fps 掉 2 幀）且 stalls_total == 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_THRESHOLDS = {
    "max_gap_p95_ms": 33.0,
    "stalls_total": 0,
}


@dataclass
class ParsedRun:
    header: dict | None = None
    flips: list[dict] = field(default_factory=list)
    summary: dict | None = None
    errors: list[str] = field(default_factory=list)


def parse_jsonl(lines: list[str]) -> ParsedRun:
    parsed = ParsedRun()
    for lineno, raw in enumerate(lines, start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            parsed.errors.append(f"line {lineno}: malformed JSON ({exc.msg})")
            continue
        kind = record.get("type")
        if kind == "header":
            parsed.header = record
        elif kind == "flip":
            parsed.flips.append(record)
        elif kind == "summary":
            parsed.summary = record
        else:
            parsed.errors.append(f"line {lineno}: unknown record type {kind!r}")
    return parsed


def evaluate(parsed: ParsedRun, thresholds: dict, min_flips: int) -> dict:
    verdict: dict = {
        "result": "invalid",
        "reasons": [],
        "thresholds": dict(thresholds),
        "min_flips": min_flips,
        "header": parsed.header or {},
        "summary": parsed.summary or {},
        "parse_errors": parsed.errors,
    }
    reasons: list[str] = verdict["reasons"]

    # ---- validity gates（殘缺 run 不下效能結論）----
    if parsed.header is None:
        # 不知 build config / thermal 的 pass 是弱證據 — 證據紀律上視為殘缺。
        reasons.append("invalid: no header record (build/thermal provenance unknown)")
        return verdict
    if parsed.summary is None:
        reasons.append("invalid: no summary record (run did not finish writing)")
        return verdict
    if parsed.summary.get("aborted"):
        reasons.append("invalid: run aborted (see console markers for reason)")
        return verdict
    # 欄位型別錯誤 = app 落了殘缺資料 → invalid，絕不可流為 fail（假效能結論）。
    try:
        n = int(parsed.summary.get("n", 0))
        p95 = float(parsed.summary.get("max_gap_p95_ms", 0.0))
        stalls = int(parsed.summary.get("stalls_total", 0))
    except (TypeError, ValueError) as exc:
        reasons.append(f"invalid: malformed summary field ({exc})")
        return verdict
    if n < min_flips:
        reasons.append(f"invalid: n={n} < min_flips={min_flips}")
        return verdict
    if len(parsed.flips) != n:
        reasons.append(f"invalid: flip records ({len(parsed.flips)}) != summary n ({n})")
        return verdict

    # ---- pre-registered performance gates ----
    if p95 >= thresholds["max_gap_p95_ms"]:
        reasons.append(
            f"fail: max_gap_p95_ms={p95:.1f} >= {thresholds['max_gap_p95_ms']:.1f}"
        )
    if stalls > thresholds["stalls_total"]:
        reasons.append(f"fail: stalls_total={stalls} > {thresholds['stalls_total']}")

    verdict["result"] = "fail" if reasons else "pass"
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", required=True, type=Path, help="probe JSONL 路徑")
    parser.add_argument(
        "--min-flips",
        type=int,
        default=30,
        help="低於此 flip 數 = invalid（統計上不可下結論；預設 30）",
    )
    parser.add_argument(
        "--max-gap-p95",
        type=float,
        default=DEFAULT_THRESHOLDS["max_gap_p95_ms"],
        help="p95 maxGap 門檻 ms（預登 33；改動須在 PR 說明理由）",
    )
    parser.add_argument(
        "--max-stalls",
        type=int,
        default=DEFAULT_THRESHOLDS["stalls_total"],
        help="允許的 stalls 總數（預登 0）",
    )
    args = parser.parse_args()

    if not args.jsonl.exists():
        print(
            json.dumps(
                {"result": "invalid", "reasons": [f"invalid: {args.jsonl} not found"]}
            )
        )
        return 2

    thresholds = {"max_gap_p95_ms": args.max_gap_p95, "stalls_total": args.max_stalls}
    parsed = parse_jsonl(args.jsonl.read_text(encoding="utf-8").splitlines())
    verdict = evaluate(parsed, thresholds, min_flips=args.min_flips)
    print(json.dumps(verdict, ensure_ascii=False, sort_keys=True))
    return {"pass": 0, "fail": 1}.get(verdict["result"], 2)


if __name__ == "__main__":
    sys.exit(main())
