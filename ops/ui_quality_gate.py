#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""ui_quality_gate — orchestrate manual UI quality gates from ui_quality_plane.

Usage:
  ops/ui_quality_gate.py [--since REF] [--files FILE...]
                         [--tier fast|slow|all]
                         [--execute] [--execute-slow]
                         [--dataset NAME | --dataset-file PATH]
                         [--include-ci] [--exclude ID...]
                         [--json]

Default is dry-run so it is safe to run anywhere. `--execute` runs the fast
static-code gates only; slow/expensive gates remain planned unless
`--execute-slow` is also given.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

FAST_LAYERS = {"static-code", "static-value"}
SLOW_LAYERS = {
    "structure",
    "state-snapshot",
    "behavior",
    "perf",
    "visual-regression",
    "cross-platform",
}

FAST_COMMANDS: dict[str, list[str]] = {
    "static.ui_token": ["--baseline-check"],
    "static.plain_deadzone": ["--baseline-check"],
    "static.i18n": ["--baseline-check"],
    "static.catalyst": ["--strict"],
}

SLOW_COMMANDS: dict[str, list[str]] = {
    "structure.ui_deadcode": ["--strict"],
    "structure.ui_graph": ["--json"],
    "snapshot.catalog": ["catalog", "snapshots"],
    "behavior.uitest_flows": ["--ui", "--lease"],
    "perf.review_flip_probe": ["--flips", "30"],
    "visual.catalog_regression": ["--auto"],
}

UI_WORLD_REQUIRED = {
    "snapshot.catalog",
    "behavior.uitest_flows",
    "perf.review_flip_probe",
}


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    return Path(out)


def get_impacted(root: Path, files: list[str] | None, since: str) -> list[dict]:
    cmd = [sys.executable, "ops/ui_quality_plane.py", "impact", "--json"]
    if files is not None:
        cmd += ["--files", *files]
    else:
        cmd += ["--since", since]
    proc = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"[ui_quality_gate] impact failed (rc={proc.returncode})", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        sys.exit(2)
    return json.loads(proc.stdout)


def tier_ok(layer: str, tier: str) -> bool:
    if tier == "all":
        return True
    if tier == "fast":
        return layer in FAST_LAYERS
    return layer in SLOW_LAYERS


def injection_args(root: Path) -> tuple[list[str], str | None]:
    baseline = root / "ops" / "injection_baseline.txt"
    if baseline.exists():
        return ["--baseline-check"], None
    return ["--report"], (
        "ops/injection_baseline.txt missing; running --report only. "
        "Run `ops/injection_lint.sh --baseline` to establish a baseline."
    )


def ui_world_args(dataset: str | None, dataset_file: str | None, root: Path) -> list[str] | None:
    if dataset:
        return ["--dataset", dataset]
    if dataset_file:
        path = Path(dataset_file)
        resolved = path if path.is_absolute() else root / path
        return ["--dataset-file", str(resolved)]
    return None


def resolve_args(
    mech_id: str,
    layer: str,
    root: Path,
    world_args: list[str] | None,
) -> tuple[list[str] | None, str | None]:
    """Return ([args], warning) for a mechanism. None args means dry-run only."""
    if mech_id in FAST_COMMANDS:
        return FAST_COMMANDS[mech_id], None
    if mech_id == "static.injection":
        return injection_args(root)
    if mech_id in SLOW_COMMANDS:
        if mech_id in UI_WORLD_REQUIRED:
            if world_args is None:
                return None, "requires --dataset <name> or --dataset-file <path> (UI World SoT)"
            return [*SLOW_COMMANDS[mech_id], *world_args], None
        return SLOW_COMMANDS[mech_id], None
    return None, None


def run_mech(entrypoint: str, args: list[str], root: Path) -> tuple[int, str, str]:
    cmd = [entrypoint, *args]
    proc = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def human_summary(r: dict) -> str:
    if r["status"] == "planned":
        if r.get("warning"):
            return f"[DRY-RUN] {r['command']} ({r['warning']})"
        return f"[DRY-RUN] {r['command']}"
    if r["status"] == "skipped":
        return f"[SKIPPED] {r['reason']}"
    if r["status"] == "warn":
        return f"[WARN] {r['command']} ({r['warning']})"
    if r["status"] == "passed":
        return f"[PASS] {r['command']}"
    if r["status"] == "failed":
        return f"[FAIL] {r['command']} (rc={r['rc']})"
    return f"[UNKNOWN] {r['status']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="origin/main", help="git ref for changed files")
    parser.add_argument("--files", nargs="+", help="explicit changed files")
    parser.add_argument("--tier", choices=["fast", "slow", "all"], default="fast")
    parser.add_argument("--dry-run", action="store_true", default=True, help="print plan without running (default)")
    parser.add_argument("--execute", action="store_true", help="run gates (fast tier only by default)")
    parser.add_argument("--execute-slow", action="store_true", help="also run slow/expensive gates")
    parser.add_argument("--dataset", help="UI World name under ops/fixtures/ui_worlds/<name>.json for slow UI World gates")
    parser.add_argument("--dataset-file", help="UI World JSON path for slow UI World gates")
    parser.add_argument("--include-ci", action="store_true", help="include gates already wired to CI")
    parser.add_argument("--exclude", action="append", default=[], help="mechanism ids to skip")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    root = repo_root()
    if args.dataset and args.dataset_file:
        parser.error("choose either --dataset or --dataset-file")
    if args.dataset:
        named_path = root / "ops" / "fixtures" / "ui_worlds" / f"{args.dataset}.json"
        if not named_path.is_file():
            parser.error(f"dataset file not found: {named_path}")
    if args.dataset_file:
        dataset_file_path = Path(args.dataset_file)
        resolved_dataset_file = dataset_file_path if dataset_file_path.is_absolute() else root / dataset_file_path
        if not resolved_dataset_file.is_file():
            parser.error(f"dataset file not found: {resolved_dataset_file}")
    world_args = ui_world_args(args.dataset, args.dataset_file, root)
    impacted = get_impacted(root, args.files, args.since)

    excluded = set(args.exclude)
    results: list[dict] = []
    skipped: list[dict] = []

    for mech in impacted:
        mech_id = mech["id"]
        layer = mech.get("layer", "")
        gate = mech.get("gate", "")
        entrypoint = mech.get("entrypoint", "")
        matched = mech.get("matched", [])

        base_result = {
            "id": mech_id,
            "layer": layer,
            "gate": gate,
            "entrypoint": entrypoint,
            "matched": matched,
        }

        if mech_id in excluded:
            results.append({**base_result, "status": "skipped", "reason": "excluded by --exclude"})
            continue

        if gate != "manual" and not args.include_ci:
            results.append({**base_result, "status": "skipped", "reason": f"gate={gate} (use --include-ci)"})
            continue

        if not tier_ok(layer, args.tier):
            results.append({**base_result, "status": "skipped", "reason": f"layer={layer} not in tier={args.tier}"})
            continue

        resolved_args, warning = resolve_args(mech_id, layer, root, world_args)
        command = " ".join(shlex.quote(p) for p in [entrypoint, *(resolved_args or [])])

        if resolved_args is None or (layer not in FAST_LAYERS and not args.execute_slow):
            if args.execute and layer not in FAST_LAYERS and not args.execute_slow:
                print(
                    "[ui_quality_gate] hint: slow gates stay planned; add --execute-slow to run them",
                    file=sys.stderr,
                )
            if resolved_args is None and mech_id in UI_WORLD_REQUIRED and args.execute and args.execute_slow:
                results.append({
                    **base_result,
                    "status": "failed",
                    "command": command,
                    "args": [],
                    "rc": 2,
                    "stdout": "",
                    "stderr": warning or "",
                    "warning": warning,
                })
                continue
            results.append({
                **base_result,
                "status": "planned",
                "command": command,
                "args": resolved_args or [],
                "warning": warning,
            })
            continue

        if not args.execute:
            results.append({
                **base_result,
                "status": "planned",
                "command": command,
                "args": resolved_args,
                "warning": warning,
            })
            continue

        rc, stdout, stderr = run_mech(entrypoint, resolved_args, root)
        status = "passed" if rc == 0 else "failed"
        if warning:
            status = "warn"
        results.append({
            **base_result,
            "status": status,
            "command": command,
            "args": resolved_args,
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
            "warning": warning,
        })

    summary = {
        "planned": sum(1 for r in results if r["status"] == "planned"),
        "passed": sum(1 for r in results if r["status"] == "passed"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "warn": sum(1 for r in results if r["status"] == "warn"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }

    if args.json:
        print(json.dumps({
            "tier": args.tier,
            "execute": args.execute,
            "execute_slow": args.execute_slow,
            "results": results,
            "summary": summary,
        }, ensure_ascii=False, indent=2))
    else:
        mode = "execute" if args.execute else "dry-run"
        print(f"UI quality gate — tier={args.tier} mode={mode}")
        if not impacted:
            print("no UI quality mechanisms triggered")
        for r in results:
            print(f"{r['id']:<40} {human_summary(r)}")
        print(f"summary: planned={summary['planned']} passed={summary['passed']} failed={summary['failed']} warn={summary['warn']} skipped={summary['skipped']}")

    if summary["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
