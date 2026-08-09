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

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from ui_world_manifest import UIWorldManifestError, validate_fixture_dataset_file
from ui_quality_plane import RESOURCES as PLANE_RESOURCES

FAST_LAYERS = {"static-code", "static-value"}
SLOW_LAYERS = {
    "structure",
    "state-snapshot",
    "behavior",
    "perf",
    "visual-regression",
    "cross-platform",
}

# What to run a mechanism with lives on the mechanism, in
# ops/ui_quality_plane.yml. This file used to keep its own tables of the same
# fact, so a mechanism added to the plane and forgotten here resolved to no
# command and was quietly recorded as unrun — which is not a failure, so the
# gate stayed green (IMP-0041).
#
# What stays here is the *behaviour* per required resource, which is genuinely
# runner-side. The set of resource names is imported rather than restated, and
# the check below refuses to start if the plane grows a resource this runner
# does not handle — an enumerated hole instead of a silent one.
UNRUNNABLE = object()

# Stated here rather than branched on, because ops/injection_lint.py's
# _BASELINE_RAW states exactly the same thing — `os.environ.get(
# "KG_INJECTION_BASELINE", "ops/injection_baseline.txt")`, resolved against the
# repo root the same way. Reading the variable with `if override:`
# instead made the two disagree on one input: for KG_INJECTION_BASELINE= (empty)
# the parent fell back to the tracked file and planned --baseline-check while the
# child resolved Path("") to the repo root and died with IsADirectoryError. The
# only way two processes cannot disagree about a path is to resolve it the same
# way, default included.
DEFAULT_INJECTION_BASELINE = "ops/injection_baseline.txt"

HANDLED_RESOURCES = {"ui-world", "injection-baseline"}
if HANDLED_RESOURCES != PLANE_RESOURCES:
    raise SystemExit(
        "ui_quality_gate: resource vocabulary drift — plane declares "
        f"{sorted(PLANE_RESOURCES)}, runner handles {sorted(HANDLED_RESOURCES)}"
    )


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


def all_mechanisms(root: Path) -> list[dict]:
    """Every declared mechanism, ignoring which files changed.

    The five static lints do not accept a file list — each one scans the whole
    tree and compares against its baseline — so diff-scoping buys no scan cost
    here, it only selects *which* lints run. For CI that trade is strictly bad:
    it adds a base-resolution step that can fail (and did, silently, for two
    months) in exchange for nothing. `.github/workflows/design-system.yml`
    already takes this shape: run unconditionally, let `on: paths:` decide when.
    """
    proc = subprocess.run(
        [sys.executable, "ops/ui_quality_plane.py", "list", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"[ui_quality_gate] plane list failed (rc={proc.returncode})", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        sys.exit(2)
    mechs = json.loads(proc.stdout)
    for mech in mechs:
        mech.setdefault("matched", [])
    return mechs


def decide_status(rc: int, warning: str | None) -> str:
    """A warning may soften a green, never launder a red.

    `status = "warn"` used to be applied unconditionally when a mechanism
    carried a warning, so a mechanism that genuinely failed (rc != 0) dropped
    out of summary["failed"] and the gate returned 0.
    """
    if rc != 0:
        return "failed"
    return "warn" if warning else "passed"


def tier_ok(layer: str, tier: str) -> bool:
    if tier == "all":
        return True
    if tier == "fast":
        return layer in FAST_LAYERS
    return layer in SLOW_LAYERS


def injection_args(root: Path) -> tuple[list[str] | object, str | None]:
    """Decide --baseline-check vs --report vs refuse, per KG_INJECTION_BASELINE.

    Three outcomes, and the asymmetry between the last two is the whole point:

      [--baseline-check]   the baseline is a readable file. Enforce.
      [--report] + warning KG_INJECTION_BASELINE is UNSET and the tracked
                           default is absent. Nobody has bootstrapped a baseline
                           yet, so a degraded report is the only thing left to
                           offer. Still exit 0 (the lint's own exit 2 for a
                           missing or empty Views tree is unaffected — a
                           degraded baseline verdict is not a licence to
                           certify a tree nobody read).
      UNRUNNABLE + warning the caller NAMED a path and it is not a readable
                           file. A typo, or a stale export from an earlier
                           session — not a bootstrap. Degrading here would be a
                           silent green: --report exits 0 for any tree it can
                           actually scan, and `warn` is
                           excluded from summary["failed"], so the gate returns
                           0 with this lint switched off. This command is a
                           block-level cutover gate (ops/worktree_orchestrate.py)
                           and a pre-commit hook, both of which inherit the
                           caller's environment, and cutover is offline so CI
                           cannot cover for it. decide_status forbids exactly
                           this shape one level down; a runner that launders it
                           one level up gains nothing.

    KG_INJECTION_BASELINE has always been read by ops/injection_lint.py, but
    this runner used to hardcode the path. The two then disagreed: the parent
    planned --baseline-check against the tracked file while the child resolved
    a different (or absent) baseline from the environment and read every
    finding as a regression — a split brain that surfaced only as a bare rc=1.
    Because the override could not reach this function, the only way to stage a
    missing baseline was to `mv` the *version-controlled* ops/injection_baseline.txt
    aside, and a concurrent `git add -A` once committed that absence (IMP-0048).

    run_mech below deliberately passes no env=, so the child inherits ours, and
    the child resolves a relative override against its own repo root (see
    ops/injection_lint.py's BASELINE_FILE) — both sides therefore land on the
    same file. That used to rest on injection_lint.sh happening to cd to the
    repo root first, which held only for callers who went through the wrapper;
    since IMP-20260807-1674d1 the module itself is anchored, so the agreement no
    longer depends on anyone's cwd. Do not convert that call to an explicit env
    dict: it would drop PATH/UV_BIN and injection_lint.sh would lose uv.
    """
    raw = os.environ.get("KG_INJECTION_BASELINE", DEFAULT_INJECTION_BASELINE)
    named_by_caller = "KG_INJECTION_BASELINE" in os.environ
    candidate = Path(raw)
    baseline = candidate if candidate.is_absolute() else root / candidate
    # is_file(), not exists(): a directory is not a baseline the child could
    # read, and `KG_INJECTION_BASELINE=` resolving to the repo root is precisely
    # how the child used to die (IsADirectoryError). Whatever this rejects, the
    # child would have rejected louder and later.
    if baseline.is_file():
        return ["--baseline-check"], None
    if named_by_caller:
        return UNRUNNABLE, (
            f"KG_INJECTION_BASELINE={raw!r} resolves to {baseline}, which is not a readable "
            f"file. Point it at an existing baseline, or unset it to use "
            f"{DEFAULT_INJECTION_BASELINE}. Refusing rather than degrading to --report: "
            "--report exits 0 for any tree it can scan, so a stale export would silently "
            "disable this lint "
            "on a gate that blocks cutover."
        )
    return ["--report"], (
        f"{baseline} missing; running --report only. "
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


def resolve_dataset_path(dataset: str | None, dataset_file: str | None, root: Path) -> Path | None:
    if dataset:
        return root / "ops" / "fixtures" / "ui_worlds" / f"{dataset}.json"
    if dataset_file:
        path = Path(dataset_file)
        return path if path.is_absolute() else root / path
    return None


def resolve_args(
    mech: dict,
    root: Path,
    world_args: list[str] | None,
) -> tuple[list[str] | None | object, str | None]:
    """Return (args, warning) for a mechanism, reading the plane's `run:`.

    Three outcomes, deliberately distinct:
      UNRUNNABLE — the plane declares no command. A defect, not a deferral.
      None       — a declared requirement is not satisfied right now.
      [args]     — runnable.
    """
    if "run" not in mech:
        return UNRUNNABLE, "plane declares no `run:` for this mechanism — nothing can execute it"
    resolved = list(mech.get("run") or [])
    warning: str | None = None
    for resource in mech.get("requires") or []:
        if resource == "ui-world":
            if world_args is None:
                return None, "requires --dataset <name> or --dataset-file <path> (UI World SoT)"
            resolved = [*resolved, *world_args]
        elif resource == "injection-baseline":
            fallback, warn = injection_args(root)
            if fallback is UNRUNNABLE:
                return UNRUNNABLE, warn
            if warn:
                resolved, warning = fallback, warn
        else:
            # Unreachable while the import-time check above holds; kept so a
            # drift that slips past it still fails loudly rather than running
            # the command with its requirement unmet.
            return UNRUNNABLE, f"unknown required resource {resource!r}"
    return resolved, warning


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
        # A failure that carries a warning is one the runner refused to start,
        # so rc alone names nothing the caller can act on — the reason lives in
        # the warning, and printing only the rc sends them to read the child's
        # (empty) output instead of their own environment.
        if r.get("warning"):
            return f"[FAIL] {r['command']} (rc={r['rc']}) — {r['warning']}"
        return f"[FAIL] {r['command']} (rc={r['rc']})"
    return f"[UNKNOWN] {r['status']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="origin/main", help="git ref for changed files")
    parser.add_argument("--files", nargs="+", help="explicit changed files")
    parser.add_argument("--tier", choices=["fast", "slow", "all"], default="fast")
    parser.add_argument("--dry-run", action="store_true", help="print plan without running")
    parser.add_argument("--execute", action="store_true", help="run gates (fast tier only by default)")
    parser.add_argument("--execute-slow", action="store_true", help="also run slow/expensive gates")
    parser.add_argument("--dataset", help="UI World name under ops/fixtures/ui_worlds/<name>.json for slow UI World gates")
    parser.add_argument("--dataset-file", help="UI World JSON path for slow UI World gates")
    parser.add_argument("--include-ci", action="store_true", help="include gates already wired to CI")
    parser.add_argument("--exclude", action="append", default=[], help="mechanism ids to skip")
    parser.add_argument("--all-mechanisms", action="store_true",
                        help="run every mechanism in the tier, ignoring which files changed (CI shape)")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    # `--dry-run` was declared with default=True and then never read: the real
    # switch was `--execute` being opt-in, so a caller that forgot it got a
    # green no-op that looked like a run. Make the mode a decision, not a
    # default.
    if args.execute and args.dry_run:
        parser.error("choose exactly one of --dry-run or --execute")
    if not args.execute and not args.dry_run:
        parser.error("choose exactly one of --dry-run or --execute")

    root = repo_root()
    if args.dataset and args.dataset_file:
        parser.error("choose either --dataset or --dataset-file")
    dataset_path = resolve_dataset_path(args.dataset, args.dataset_file, root)
    if dataset_path is not None:
        if not dataset_path.is_file():
            parser.error(f"dataset file not found: {dataset_path}")
        try:
            validate_fixture_dataset_file(dataset_path, label="UI quality UI World dataset")
        except UIWorldManifestError as exc:
            parser.error(str(exc))
    world_args = ui_world_args(args.dataset, args.dataset_file, root)
    if args.all_mechanisms:
        if args.files:
            parser.error("--all-mechanisms and --files are mutually exclusive")
        impacted = all_mechanisms(root)
    else:
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

        resolved_args, warning = resolve_args(mech, root, world_args)

        if resolved_args is UNRUNNABLE and gate != "manual" and "run" not in mech:
            # The plane only requires `run:` of the gates it owns (`gate:
            # manual`); `cmd_validate` exempts the rest, and some of them
            # cannot have one — snapshot.review_card_layout_golden's entrypoint is a
            # Swift test file enforced by `ios_ops.sh test`. Failing them here
            # would make the validator and the runner disagree about the same
            # file and turn `--include-ci` permanently red on a clean tree.
            #
            # Keyed on the *reason*, not just on the gate: a mechanism that has
            # a `run:` and is unrunnable for some other reason (an unresolvable
            # required resource, e.g. a caller-named baseline that is not there)
            # would otherwise be filed as planned under the warning "no `run:`;
            # gate=ci runs it elsewhere" — green, and untrue.
            results.append({
                **base_result,
                "status": "planned",
                "command": entrypoint,
                "args": [],
                "warning": f"no `run:`; gate={gate} runs it elsewhere",
            })
            continue

        if resolved_args is UNRUNNABLE:
            # Not `unrun`: unrun is a deferral and does not fail the gate, which
            # is precisely how an unregistered mechanism used to pass (IMP-0041).
            results.append({
                **base_result,
                "status": "failed",
                "command": entrypoint,
                "args": [],
                "rc": 2,
                "stdout": "",
                "stderr": warning or "",
                "warning": warning,
            })
            continue

        command = " ".join(shlex.quote(p) for p in [entrypoint, *(resolved_args or [])])

        if resolved_args is None or (layer not in FAST_LAYERS and not args.execute_slow):
            if args.execute and layer not in FAST_LAYERS and not args.execute_slow:
                print(
                    "[ui_quality_gate] hint: slow gates stay planned; add --execute-slow to run them",
                    file=sys.stderr,
                )
            if resolved_args is None and args.execute and args.execute_slow:
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
        status = decide_status(rc, warning)
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

    # `selected` is the plan size; `unrun` counts mechanisms that stayed
    # unexecuted. They used to be one key called `planned`, which read like a
    # plan size but was a status count — so a healthy run printed `planned=0`
    # and so did a run that matched nothing at all. That second reading is the
    # signature CI printed while it no-op'd for two months (IMP-0050), and no
    # field distinguished the two. `selected=0` now says it on its own.
    summary = {
        "selected": len(impacted),
        "unrun": sum(1 for r in results if r["status"] == "planned"),
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
        print(f"summary: selected={summary['selected']} unrun={summary['unrun']} passed={summary['passed']} failed={summary['failed']} warn={summary['warn']} skipped={summary['skipped']}")

    if summary["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
