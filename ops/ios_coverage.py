#!/usr/bin/env -S uv run --python 3.13 python
"""Parse Xcode xccov output into a stable KG iOS coverage envelope."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "kg.ios.coverage.v1"
DEFAULT_TARGET = "BooksAndVocab"


@dataclass(frozen=True)
class CoverageFile:
    name: str
    path: str | None
    line_coverage: float | None
    covered_lines: int | None
    executable_lines: int | None

    @property
    def line_percent(self) -> float | None:
        if self.line_coverage is not None:
            value = self.line_coverage * 100 if self.line_coverage <= 1 else self.line_coverage
            return round(value, 2)
        if self.covered_lines is not None and self.executable_lines:
            return round((self.covered_lines / self.executable_lines) * 100, 2)
        return None


@dataclass(frozen=True)
class CoverageTarget:
    name: str
    line_coverage: float | None
    covered_lines: int | None
    executable_lines: int | None
    files: tuple[CoverageFile, ...] = ()

    @property
    def line_percent(self) -> float | None:
        if self.line_coverage is not None:
            value = self.line_coverage * 100 if self.line_coverage <= 1 else self.line_coverage
            return round(value, 2)
        if self.covered_lines is not None and self.executable_lines:
            return round((self.covered_lines / self.executable_lines) * 100, 2)
        return None


def read_xccov_payload(args: argparse.Namespace) -> tuple[dict[str, Any] | None, str | None]:
    if args.fixture_xccov_json:
        try:
            return json.loads(Path(args.fixture_xccov_json).read_text(encoding="utf-8")), None
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            return None, f"failed to read fixture xccov json: {exc}"

    xcresult = Path(args.xcresult)
    if not xcresult.exists():
        return None, f"xcresult not found: {xcresult}"

    proc = subprocess.run(
        ["xcrun", "xccov", "view", "--report", "--json", str(xcresult)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None, proc.stderr.strip() or "xccov failed"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"xccov emitted invalid json: {exc}"


def as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_files(raw_files: Any) -> tuple[CoverageFile, ...]:
    if not isinstance(raw_files, list):
        return ()
    files: list[CoverageFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        path = item.get("path")
        if not isinstance(name, str) or not name:
            if isinstance(path, str) and path:
                name = Path(path).name
            else:
                continue
        files.append(
            CoverageFile(
                name=name,
                path=path if isinstance(path, str) and path else None,
                line_coverage=as_float(item.get("lineCoverage")),
                covered_lines=as_int(item.get("coveredLines")),
                executable_lines=as_int(item.get("executableLines")),
            )
        )
    return tuple(files)


def parse_targets(payload: dict[str, Any]) -> list[CoverageTarget]:
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        raw_targets = []
    targets: list[CoverageTarget] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        targets.append(
            CoverageTarget(
                name=name,
                line_coverage=as_float(item.get("lineCoverage")),
                covered_lines=as_int(item.get("coveredLines")),
                executable_lines=as_int(item.get("executableLines")),
                files=parse_files(item.get("files")),
            )
        )
    return targets


def is_app_target(target: CoverageTarget) -> bool:
    lowered = target.name.lower()
    return not (
        lowered.endswith("tests")
        or lowered.endswith("uitests")
        or "tests-runner" in lowered
        or lowered.endswith("runner")
    )


def select_target(targets: list[CoverageTarget], name: str | None) -> CoverageTarget | None:
    if name:
        for target in targets:
            if target.name == name:
                return target
    for target in targets:
        if target.name == DEFAULT_TARGET:
            return target
    for target in targets:
        if is_app_target(target):
            return target
    return targets[0] if targets else None


def format_target(target: CoverageTarget) -> dict[str, Any]:
    return {
        "name": target.name,
        "lineCoverage": target.line_percent,
        "coveredLines": target.covered_lines,
        "executableLines": target.executable_lines,
        "fileCount": len(target.files),
    }


def format_file(file: CoverageFile) -> dict[str, Any]:
    return {
        "name": file.name,
        "path": file.path,
        "lineCoverage": file.line_percent,
        "coveredLines": file.covered_lines,
        "executableLines": file.executable_lines,
    }


def lowest_files(target: CoverageTarget, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    candidates = [
        file
        for file in target.files
        if file.line_percent is not None and file.executable_lines is not None and file.executable_lines > 0
    ]
    candidates.sort(key=lambda file: (file.line_percent or 0, -(file.executable_lines or 0), file.path or file.name))
    return [format_file(file) for file in candidates[:limit]]


def parse_threshold(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--fail-under-lines must be numeric") from exc
    if threshold < 0 or threshold > 100:
        raise argparse.ArgumentTypeError("--fail-under-lines must be between 0 and 100")
    return threshold


def parse_nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def make_error_payload(args: argparse.Namespace, message: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source": {
            "xcresult": args.xcresult,
            "fixture": bool(args.fixture_xccov_json),
            "tool": "xccov",
        },
        "verdict": "error",
        "summary": {
            "target": args.target,
            "lineCoverage": None,
            "coveredLines": None,
            "executableLines": None,
            "fileCount": 0,
            "lowestFiles": [],
        },
        "thresholds": {"lineCoverage": {"failUnder": parse_threshold(args.fail_under_lines)}},
        "targets": [],
        "errors": [{"key": "coverage-unavailable", "status": "error", "error": message}],
    }


def make_payload(args: argparse.Namespace, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    targets = parse_targets(payload)
    selected = select_target(targets, args.target)
    threshold = parse_threshold(args.fail_under_lines)
    if selected is None or selected.line_percent is None:
        out = make_error_payload(args, f"target coverage unavailable: {args.target or DEFAULT_TARGET}")
        return out, 2

    errors: list[dict[str, Any]] = []
    verdict = "pass"
    if threshold is not None and selected.line_percent < threshold:
        verdict = "fail"
        errors.append(
            {
                "key": "coverage-threshold",
                "status": "fail",
                "error": f"line coverage {selected.line_percent:.2f}% is below {threshold:.2f}%",
            }
        )

    out = {
        "schema": SCHEMA,
        "source": {
            "xcresult": args.xcresult,
            "fixture": bool(args.fixture_xccov_json),
            "tool": "xccov",
        },
        "verdict": verdict,
        "summary": {
            "target": selected.name,
            "lineCoverage": selected.line_percent,
            "coveredLines": selected.covered_lines,
            "executableLines": selected.executable_lines,
            "fileCount": len(selected.files),
            "lowestFiles": lowest_files(selected, args.max_low_files),
        },
        "thresholds": {"lineCoverage": {"failUnder": threshold}},
        "targets": [format_target(target) for target in targets],
        "errors": errors,
    }
    return out, 1 if verdict == "fail" else 0


def format_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    threshold = payload["thresholds"]["lineCoverage"]["failUnder"]
    threshold_text = "none" if threshold is None else f"{threshold:.2f}"
    return (
        "[ios][coverage] "
        f"verdict={payload['verdict']} "
        f"target={summary['target']} "
        f"lineCoverage={summary['lineCoverage']} "
        f"coveredLines={summary['coveredLines']} "
        f"executableLines={summary['executableLines']} "
        f"failUnder={threshold_text}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit stable iOS coverage JSON from an Xcode .xcresult")
    parser.add_argument("--xcresult", required=True, help="Path to Test.xcresult")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Target to report, default: BooksAndVocab")
    parser.add_argument("--fail-under-lines", help="Fail if selected target line coverage is below this percent")
    parser.add_argument(
        "--max-low-files",
        type=parse_nonnegative_int,
        default=10,
        help="Maximum lowest-coverage files to include in summary, default: 10",
    )
    parser.add_argument("--fixture-xccov-json", help="Test-only xccov JSON fixture path")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        raw_payload, error = read_xccov_payload(args)
        if error:
            payload = make_error_payload(args, error)
            rc = 2
        else:
            assert raw_payload is not None
            payload, rc = make_payload(args, raw_payload)
    except argparse.ArgumentTypeError as exc:
        payload = make_error_payload(args, str(exc))
        rc = 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_text(payload))
        for error_item in payload.get("errors", []):
            print(f"[ios][coverage][{error_item['status']}] {error_item['key']}: {error_item['error']}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
