#!/usr/bin/env -S uv run --no-project --python 3.13 python
"""Plan narrowly targeted ops validation without executing any test.

The command emits the deterministic ``kg.ops.test-plan.v1`` JSON contract.  It
accepts repository-relative changed paths as positional arguments and, when
stdin is piped or ``--paths-stdin`` is supplied, as one newline-delimited path
per stdin line.
Both sources are combined, normalized, sorted, and deduplicated.

This is deliberately a planner only.  It does not import or invoke a test
runner, mutate a worktree, or wire itself into an existing central router.
Unknown ops runtime surfaces and central routing surfaces select the complete
``./ops/test_ops.sh`` fallback so a new path cannot produce a false targeted
green result.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Iterable, Sequence
from typing import TextIO


SCHEMA = "kg.ops.test-plan.v1"
PYTEST_PREFIX = (
    "uv",
    "run",
    "--no-project",
    "--python",
    "3.13",
    "--with",
    "pytest",
    "pytest",
    "-q",
)
UI_WORLD_VALIDATION_SCRIPT = "ops/ui_world_manifest.py"
DEFAULT_UI_WORLD_MANIFEST = "ops/fixtures/ui_worlds/marketing_demo.json"
OPS_FALLBACK_COMMAND = ("./ops/test_ops.sh",)

CENTRAL_ROUTING_PATHS = frozenset(
    {
        "ops/test_ops.sh",
        "ops/ci_scope_router.sh",
    }
)


class InputFormatError(ValueError):
    """Stable, machine-readable planner input failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _ArgumentParser(argparse.ArgumentParser):
    """Turn argparse failures into the planner's JSON error contract."""

    def error(self, message: str) -> None:
        raise InputFormatError("argument-error", f"invalid arguments: {message}")


def _normalize_path(raw_path: object) -> str:
    if not isinstance(raw_path, str):
        raise InputFormatError("invalid-path", "changed path must be a string")
    if "\x00" in raw_path:
        raise InputFormatError("invalid-path", "changed path must not contain NUL")

    path = raw_path
    while path.startswith("./"):
        path = path[2:]
    if not path or path == ".":
        raise InputFormatError("invalid-path", "changed path must not be empty")
    if path.startswith("/") or path == ".." or path.startswith("../") or "/../" in path:
        raise InputFormatError(
            "invalid-path",
            f"changed path must be repository-relative: {raw_path!r}",
        )
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise InputFormatError(
            "invalid-path",
            f"changed path must use normalized repository separators: {raw_path!r}",
        )
    return path


def normalize_paths(raw_paths: Iterable[object]) -> list[str]:
    """Validate and return stable repository-relative changed paths."""

    paths = [_normalize_path(raw_path) for raw_path in raw_paths]
    if not paths:
        raise InputFormatError("missing-input", "at least one changed path is required")
    return sorted(set(paths))


def _read_stdin_paths(stream: TextIO) -> list[str]:
    try:
        text = stream.read()
    except (OSError, UnicodeError) as exc:
        raise InputFormatError("invalid-stdin", "changed paths stdin could not be read") from exc
    if "\x00" in text:
        raise InputFormatError("invalid-stdin", "changed paths stdin must not contain NUL")
    return [line[:-1] if line.endswith("\r") else line for line in text.splitlines() if line.strip()]


def _is_python_test(path: str) -> bool:
    return path.startswith("ops/tests/test_") and path.endswith(".py") and "/" not in path[len("ops/tests/") :]


def _is_shell_test(path: str) -> bool:
    return path.startswith("ops/tests/test_") and path.endswith(".sh") and "/" not in path[len("ops/tests/") :]


def _is_ui_world_path(path: str) -> bool:
    return (
        path == "ops/ui_world_manifest.py"
        or path.startswith("ops/fixtures/ui_worlds/")
        or path.startswith("ops/fixtures/assets/")
    )


def _is_workflow_path(path: str) -> bool:
    return path == ".github/workflows" or path.startswith(".github/workflows/")


def _is_central_routing_path(path: str) -> bool:
    return path in CENTRAL_ROUTING_PATHS or _is_workflow_path(path)


def _command(
    kind: str,
    paths: Sequence[str],
    command: str,
    reason: str,
) -> dict[str, object]:
    return {
        "kind": kind,
        "paths": list(paths),
        "command": command,
        "reason": reason,
    }


def _ui_validation_targets(paths: Sequence[str]) -> list[str]:
    manifests = sorted(
        path
        for path in paths
        if path.startswith("ops/fixtures/ui_worlds/") and path.endswith(".json")
    )
    return manifests or [DEFAULT_UI_WORLD_MANIFEST]


def build_plan(changed_paths: Iterable[object]) -> dict[str, object]:
    """Build a side-effect-free targeted-test plan for changed paths."""

    paths = normalize_paths(changed_paths)
    python_tests: list[str] = []
    shell_tests: list[str] = []
    ui_world_paths: list[str] = []
    central_paths: list[str] = []
    unknown_ops_paths: list[str] = []
    non_ops_paths: list[str] = []

    for path in paths:
        if _is_central_routing_path(path):
            central_paths.append(path)
        elif _is_python_test(path):
            python_tests.append(path)
        elif _is_shell_test(path):
            shell_tests.append(path)
        elif _is_ui_world_path(path):
            ui_world_paths.append(path)
        elif path.startswith("ops/"):
            unknown_ops_paths.append(path)
        else:
            non_ops_paths.append(path)

    fallback_paths = sorted([*central_paths, *unknown_ops_paths])
    commands: list[dict[str, object]] = []
    if fallback_paths:
        if central_paths and unknown_ops_paths:
            fallback_reason = "complete ops fallback: central or unknown ops surface changed"
        elif central_paths:
            fallback_reason = "complete ops fallback: central ops routing surface changed"
        else:
            fallback_reason = "complete ops fallback: unknown ops runtime changed"
        commands.append(
            _command(
                "ops-fallback",
                fallback_paths,
                OPS_FALLBACK_COMMAND[0],
                fallback_reason,
            )
        )
    else:
        if python_tests:
            for path in python_tests:
                commands.append(
                    _command(
                        "pytest",
                        [path],
                        shlex.join((*PYTEST_PREFIX, path)),
                        "exact pytest file",
                    )
                )
        for path in shell_tests:
            commands.append(
                _command(
                    "shell",
                    [path],
                    shlex.join((f"./{path}",)),
                    "direct shell test file",
                )
            )
        if ui_world_paths:
            for manifest in _ui_validation_targets(ui_world_paths):
                commands.append(
                    _command(
                        "ui-fixture-validation",
                        ui_world_paths,
                        shlex.join(
                            (
                                "uv",
                                "run",
                                "--no-project",
                                "--python",
                                "3.13",
                                "python",
                                UI_WORLD_VALIDATION_SCRIPT,
                                "validate",
                                manifest,
                            )
                        ),
                        "UI World fixture validation route",
                    )
                )

    return {
        "schema": SCHEMA,
        "status": "planned",
        "executed": False,
        "changedPaths": paths,
        "ignoredPaths": non_ops_paths,
        "fallback": bool(fallback_paths),
        "commands": commands,
    }


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Plan targeted ops validation without executing tests.",
        epilog="Provide repository-relative paths as arguments or one path per line with --paths-stdin.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="repository-relative changed paths",
    )
    parser.add_argument(
        "--paths-stdin",
        action="store_true",
        help="also read newline-delimited changed paths from stdin",
    )
    return parser


def _error_payload(error: InputFormatError) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "status": "error",
        "error": {"code": "input-error", "message": error.message},
    }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        raw_paths: list[object] = list(args.paths)
        read_stdin = args.paths_stdin
        if not read_stdin:
            try:
                read_stdin = not sys.stdin.isatty()
            except OSError:
                read_stdin = False
        if read_stdin:
            raw_paths.extend(_read_stdin_paths(sys.stdin))
        _emit(build_plan(raw_paths))
        return 0
    except InputFormatError as exc:
        _emit(_error_payload(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
