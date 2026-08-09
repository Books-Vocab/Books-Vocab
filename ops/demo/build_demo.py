#!/usr/bin/env python3
"""CLI orchestrator for the KG demo codegen.

Loads the single demo SoT (ops/demo/demo_identity.json + demo_dataset.json via
sot.py) and dispatches to one of three emitters:

    emit-ios      ops/demo/emit_ios.py::emit       SoT -> iOS FixtureDataset JSON
    emit-backend  ops/demo/emit_backend.py::emit   SoT -> ops_edit seed plan + expectation

Each emitter implements the same interface:

    emit(sot, *, check: bool = False, commit: bool = False) -> dict

Global flags:
    --check   verify the committed artifact == a fresh emit; exit 1 on drift.
    --commit  write the generated artifact(s) to disk (NEVER seeds production).
    --json    machine-readable output.

Phase A: the emitter modules are STUBS raising NotImplementedError; this CLI is
fully wired so Phase B only fills the emit() bodies.

Canonical invocation is the script form, run via uv from the backend venv:
    (cd backend && uv run python ../ops/demo/build_demo.py emit-ios --json)
The sibling modules (sot/emit_*) are imported by absolute name after prepending
this directory to sys.path, so no package context (ops/__init__.py) is required.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Support invocation as a bare script (no package context): make sibling
# modules importable by absolute name. When run via `-m ops.demo.build_demo`
# the package import path already exists, so these are no-ops.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import emit_backend  # noqa: E402
import emit_ios  # noqa: E402
from sot import SoTError, load_sot  # noqa: E402

_EMITTERS = {
    "emit-ios": emit_ios.emit,
    "emit-backend": emit_backend.emit,
}


def _build_parser() -> argparse.ArgumentParser:
    # Global flags live on a shared parent so they are accepted on BOTH sides of
    # the subcommand (`build_demo.py --json emit-ios` and `build_demo.py emit-ios
    # --json` both work).
    globals_parent = argparse.ArgumentParser(add_help=False)
    globals_parent.add_argument(
        "--check", action="store_true", default=argparse.SUPPRESS,
        help="verify committed artifact == fresh emit; exit 1 on drift")
    globals_parent.add_argument(
        "--commit", action="store_true", default=argparse.SUPPRESS,
        help="write generated artifact(s) to disk (never seeds production)")
    globals_parent.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="machine-readable output")

    parser = argparse.ArgumentParser(
        prog="build_demo.py",
        description="Generate per-platform demo artifacts from the single demo SoT.",
        parents=[globals_parent],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in _EMITTERS:
        sp = sub.add_parser(name, parents=[globals_parent], help=f"run the {name} emitter")
        sp.set_defaults(target=name)
        if name == "emit-ios":
            # SPEC MODE (UI World seed projector): derive the
            # vocabulary/notebook/reviewDeck/todayReview domains from a Phase-1
            # `ops_cli world-export` seed spec; every other domain follows the
            # committed baseline. Writes ONLY to --out; the committed generated
            # artifact and its --check gate are untouched. --check compares
            # --out against a fresh emit of --spec.
            sp.add_argument(
                "--spec", metavar="PATH", default=None,
                help="kg.seed_spec.v1 input (ops_cli world-export output); requires --out")
            sp.add_argument(
                "--out", metavar="PATH", default=None,
                help="spec-mode output path for the generated UI World JSON")
            sp.add_argument(
                "--plan", metavar="PATH", default=None,
                help="kg.history_plan.v1 input; freeze the review clock at the plan "
                     "anchor (deterministic). Requires --spec.")
    return parser


def _freeze_from_plan(plan_path: str) -> "object":
    """Deterministic freeze instant = anchor 日在最大 render offset 下的末刻。

    freeze = datetime(anchor_day) + timedelta(hours=24 - max(render_utc_offset_hours))
             - timedelta(seconds=1)（UTC）。單一 source 自 plan，不 hardcode。
    """
    from datetime import date, datetime, timedelta, timezone

    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    anchor = date.fromisoformat(str(plan["anchor_day"]))
    max_offset = max(plan["render_utc_offset_hours"])
    base = datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc)
    return base + timedelta(hours=24 - max_offset) - timedelta(seconds=1)


def _emit_output(payload: dict, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for k, v in payload.items():
            print(f"{k}: {v}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    for flag in ("check", "commit", "json"):
        if not hasattr(args, flag):
            setattr(args, flag, False)
    try:
        sot = load_sot()
    except SoTError as exc:
        _emit_output({"mode": "error", "stage": "load-sot", "error": str(exc)},
                     json_mode=args.json)
        return 1

    plan_path = getattr(args, "plan", None)
    if plan_path is not None and getattr(args, "spec", None) is None:
        _emit_output({"mode": "error", "target": args.target,
                      "error": "--plan requires --spec (review-clock freeze is spec-mode only)"},
                     json_mode=args.json)
        return 1

    emit_fn = _EMITTERS[args.target]
    extra_kwargs: dict = {}
    if getattr(args, "spec", None) is not None or getattr(args, "out", None) is not None:
        # Only emit-ios declares --spec/--out; emit_ios.emit fail-louds when
        # only one of the pair is provided.
        extra_kwargs = {"spec_path": getattr(args, "spec", None),
                        "out_path": getattr(args, "out", None)}
        if plan_path is not None:
            extra_kwargs["review_clock_frozen_at"] = _freeze_from_plan(plan_path)
    try:
        result = emit_fn(sot, check=args.check, commit=args.commit, **extra_kwargs)
    except NotImplementedError as exc:
        # Phase A: stubs are not implemented yet. Surface clearly, exit non-zero
        # so a check gate never reports a false green against an unimplemented emitter.
        _emit_output(
            {"mode": "stub", "target": args.target, "error": str(exc),
             "phase": "A", "hint": "emitter body filled in Phase B"},
            json_mode=args.json,
        )
        return 2
    except Exception as exc:  # noqa: BLE001 — surface any emit failure as a clean non-zero
        _emit_output({"mode": "error", "target": args.target, "error": str(exc)},
                     json_mode=args.json)
        return 1

    drift = bool(result.get("drift")) if isinstance(result, dict) else False
    payload = {"mode": "ok", "target": args.target,
               "check": args.check, "commit": args.commit, "result": result}
    _emit_output(payload, json_mode=args.json)
    # --check contract: exit 1 when the emitter reports drift.
    return 1 if (args.check and drift) else 0


if __name__ == "__main__":
    sys.exit(main())
