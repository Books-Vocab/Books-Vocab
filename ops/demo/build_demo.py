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
        "--check", action="store_true",
        help="verify committed artifact == fresh emit; exit 1 on drift")
    globals_parent.add_argument(
        "--commit", action="store_true",
        help="write generated artifact(s) to disk (never seeds production)")
    globals_parent.add_argument(
        "--json", action="store_true", help="machine-readable output")

    parser = argparse.ArgumentParser(
        prog="build_demo.py",
        description="Generate per-platform demo artifacts from the single demo SoT.",
        parents=[globals_parent],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in _EMITTERS:
        sp = sub.add_parser(name, parents=[globals_parent], help=f"run the {name} emitter")
        sp.set_defaults(target=name)
    return parser


def _emit_output(payload: dict, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for k, v in payload.items():
            print(f"{k}: {v}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        sot = load_sot()
    except SoTError as exc:
        _emit_output({"mode": "error", "stage": "load-sot", "error": str(exc)},
                     json_mode=args.json)
        return 1

    emit_fn = _EMITTERS[args.target]
    try:
        result = emit_fn(sot, check=args.check, commit=args.commit)
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
