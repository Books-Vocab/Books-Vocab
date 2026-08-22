"""Argument surface for the worktree registry compatibility entry point."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence


def build_parser(
    handlers: dict[str, Callable[[argparse.Namespace], int]],
    *,
    resolve_statuses: Sequence[str],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local worktree ownership and hand-back evidence"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--state", default=None)
        command.add_argument("--json", action="store_true")
        command.add_argument("--at", default=None, help=argparse.SUPPRESS)

    register = sub.add_parser("register", help="record one local worktree owner")
    common(register)
    register.add_argument("--branch", required=True)
    register.add_argument("--path", default=None)
    register.add_argument("--intent", required=True)
    register.add_argument("--base", default="main")
    register.add_argument("--external-id", action="append", default=[])
    register.add_argument("--scope", default=None)
    register.add_argument("--scope-file", default=None)
    register.add_argument("--codex-thread-id", default=None)
    register.add_argument(
        "--delegated", action=argparse.BooleanOptionalAction, default=None
    )
    register.set_defaults(func=handlers["register"])

    scope = sub.add_parser(
        "scope-set", help="replace a worktree's structured file Scope"
    )
    common(scope)
    scope.add_argument("--branch")
    scope.add_argument("--path")
    scope.add_argument("--scope", default=None)
    scope.add_argument("--scope-file", default=None)
    scope.set_defaults(func=handlers["scope-set"])

    owner = sub.add_parser("owner-bind", help="bind the stable local owner identity")
    common(owner)
    owner.add_argument("--branch")
    owner.add_argument("--path")
    owner.add_argument("--codex-thread-id", required=True)
    owner.add_argument(
        "--delegated", action=argparse.BooleanOptionalAction, default=None
    )
    owner.set_defaults(func=handlers["owner-bind"])

    listed = sub.add_parser("list", help="list local worktree records")
    common(listed)
    listed.add_argument("--active-only", action="store_true")
    listed.add_argument("--branch")
    listed.add_argument("--path")
    listed.add_argument("--external-id")
    listed.add_argument("--conflicts", action="store_true")
    listed.set_defaults(func=handlers["list"])

    handback = sub.add_parser(
        "hand-back", help="record exact HEAD and optional green evidence"
    )
    common(handback)
    handback.add_argument("--branch")
    handback.add_argument("--path")
    handback.add_argument("--outcomes", default=None)
    handback.add_argument(
        "--hold", action="append", choices=("p0", "p1", "security")
    )
    handback.set_defaults(func=handlers["hand-back"])

    resolve = sub.add_parser(
        "resolve", help="transition one exact local ownership record"
    )
    common(resolve)
    resolve.add_argument("--branch")
    resolve.add_argument("--path")
    resolve.add_argument("--status", choices=resolve_statuses, required=True)
    resolve.add_argument("--expected-generation", type=int)
    resolve.add_argument("--expected-head-sha")
    resolve.add_argument("--terminal-proof")
    resolve.set_defaults(func=handlers["resolve"])

    sweep = sub.add_parser("sweep", help="report missing registered worktrees")
    common(sweep)
    sweep.add_argument("--commit", action="store_true")
    sweep.set_defaults(func=handlers["sweep"])

    compact = sub.add_parser(
        "compact", help="retain in-flight claims and remove terminal local history"
    )
    common(compact)
    compact.add_argument("--commit", action="store_true")
    compact.set_defaults(func=handlers["compact"])
    return parser
