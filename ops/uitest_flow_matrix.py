#!/usr/bin/env -S uv run --python 3.13 python
"""Run one UITest flow across state/data variants."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DataVariant:
    kind: str
    value: str | None

    @property
    def label(self) -> str:
        if self.kind == "none":
            return "default-data"
        if self.kind == "dataset":
            return f"dataset:{self.value}"
        return f"dataset-file:{Path(self.value or '').name}"

    def args(self) -> list[str]:
        if self.kind == "dataset":
            return ["--dataset", self.value or ""]
        if self.kind == "dataset-file":
            return ["--dataset-file", self.value or ""]
        return []


@dataclass(frozen=True)
class FlowVariant:
    profile: str | None
    data: DataVariant

    @property
    def label(self) -> str:
        parts: list[str] = []
        if self.data.kind != "none":
            parts.append(self.data.label)
        if self.profile:
            parts.append(f"profile:{self.profile}")
        return "+".join(parts) if parts else "default"

    def args(self) -> list[str]:
        args = self.data.args()
        if self.profile:
            args += ["--ui-launch-profile", self.profile]
        return args


def build_variants(
    *,
    profiles: list[str],
    datasets: list[str],
    dataset_files: list[str],
    include_default_data: bool,
) -> list[FlowVariant]:
    data_variants: list[DataVariant] = []
    if include_default_data or (not datasets and not dataset_files):
        data_variants.append(DataVariant("none", None))
    data_variants.extend(DataVariant("dataset", item) for item in datasets)
    data_variants.extend(DataVariant("dataset-file", item) for item in dataset_files)

    profile_values: list[str | None] = profiles or [None]
    variants = [FlowVariant(profile=profile, data=data) for data in data_variants for profile in profile_values]
    seen: set[str] = set()
    unique: list[FlowVariant] = []
    for variant in variants:
        if variant.label in seen:
            continue
        seen.add(variant.label)
        unique.append(variant)
    return unique


def command_for(args: argparse.Namespace, variant: FlowVariant) -> list[str]:
    cmd = [
        str(ROOT / "ops" / "ios_ops.sh"),
        "test",
        "--ui",
        "--file",
        args.file,
        *variant.args(),
    ]
    for pattern in args.grep:
        cmd += ["-g", pattern]
    if args.lease:
        cmd.append("--lease")
    if args.device:
        cmd += ["--device", args.device]
    if args.destination:
        cmd += ["--destination", args.destination]
    cmd.append("--json")
    return cmd


def run_variant(cmd: list[str]) -> tuple[int, dict | None, str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = None
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
    return proc.returncode, payload, proc.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one UITest file across state/data variants.")
    parser.add_argument("--file", required=True, help="UITest Swift file or type name passed to ios_ops.sh test --file")
    parser.add_argument("--profile", action="append", default=[], help="Repeatable --ui-launch-profile value")
    parser.add_argument("--dataset", action="append", default=[], help="Repeatable fixture dataset name")
    parser.add_argument("--dataset-file", action="append", default=[], help="Repeatable fixture dataset file")
    parser.add_argument("--include-default-data", action="store_true", help="Also run without a dataset axis")
    parser.add_argument("-g", "--grep", action="append", default=[], help="Repeatable test selector forwarded to ios_ops.sh")
    parser.add_argument("--lease", action="store_true", help="Forward --lease to ios_ops.sh")
    parser.add_argument("--device")
    parser.add_argument("--destination")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned matrix without running xcodebuild")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable summary")
    args = parser.parse_args(argv)

    variants = build_variants(
        profiles=args.profile,
        datasets=args.dataset,
        dataset_files=args.dataset_file,
        include_default_data=args.include_default_data,
    )
    runs = [
        {
            "variantId": variant.label,
            "command": command_for(args, variant),
        }
        for variant in variants
    ]
    payload: dict = {
        "schema": "kg.ios.uitest-flow-matrix.v1",
        "file": args.file,
        "dryRun": args.dry_run,
        "summary": {"total": len(runs), "ok": 0, "failed": 0},
        "runs": runs,
    }
    if args.dry_run:
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for run in runs:
                print(" ".join(run["command"]))
        return 0

    failed = 0
    ok = 0
    for run in runs:
        rc, result, stderr = run_variant(run["command"])
        run["returnCode"] = rc
        run["result"] = result.get("result") if result else None
        run["reviewHtml"] = ((result or {}).get("uiVisualReview") or {}).get("reviewHtml")
        run["stderrTail"] = "\n".join(stderr.splitlines()[-20:])
        if rc == 0:
            ok += 1
        else:
            failed += 1
    payload["summary"] = {"total": len(runs), "ok": ok, "failed": failed}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for run in runs:
            print(f"{run['variantId']}\t{run.get('returnCode')}\t{run.get('result')}\t{run.get('reviewHtml')}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
