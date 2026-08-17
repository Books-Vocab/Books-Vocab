#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Run an explicit orchestrator test route with a collection preflight."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from lib import worktree_test_routes as routes


_COLLECTED_RE = re.compile(r"\b(\d+)\s+tests?\s+collected\b")


def _repo_root(value: str | None) -> Path:
    return Path(value).resolve() if value else Path.cwd().resolve()


def _has_collected_tests(output: str) -> bool:
    match = _COLLECTED_RE.search(output)
    return bool(match and int(match.group(1)) > 0)


def _run(command: list[str], root: Path) -> int:
    completed = subprocess.run(command, cwd=root, check=False)
    return completed.returncode


def cmd_run(args: argparse.Namespace) -> int:
    root = _repo_root(args.repo)
    selected = routes.routes_for_ids(args.route_id)
    command = routes.pytest_command(selected, focused=args.mode == "focused")
    collect = routes.pytest_command(
        selected, focused=args.mode == "focused", collect_only=True
    )
    print(
        f"[test-route] phase=collect mode={args.mode} routes="
        f"{','.join(route['route_id'] for route in selected)}",
        file=sys.stderr,
        flush=True,
    )
    probe = subprocess.run(
        collect,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or not _has_collected_tests(probe.stdout + probe.stderr):
        fallback = routes.routes_for_ids(["orchestrator.fallback"])
        fallback_collect = routes.pytest_command(
            fallback, focused=False, collect_only=True
        )
        print(
            "[test-route] collection failed or was empty; falling back to "
            "orchestrator.fallback",
            file=sys.stderr,
            flush=True,
        )
        fallback_probe = subprocess.run(
            fallback_collect,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if fallback_probe.returncode != 0 or not _has_collected_tests(
            fallback_probe.stdout + fallback_probe.stderr
        ):
            sys.stderr.write(fallback_probe.stdout)
            sys.stderr.write(fallback_probe.stderr)
            return fallback_probe.returncode or 5
        command = routes.pytest_command(fallback, focused=False)
    return _run(command, root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    run = sub.add_parser("run")
    run.add_argument("--mode", choices=("focused", "group"), required=True)
    run.add_argument("--route-id", nargs="+", required=True)
    run.add_argument("--repo")
    run.set_defaults(func=cmd_run)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    raise SystemExit(parsed.func(parsed))
