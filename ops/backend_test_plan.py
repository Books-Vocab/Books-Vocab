#!/usr/bin/env -S uv run --python 3.13
"""Plan the smallest safe backend pytest command for changed repository paths.

This module only classifies paths and emits a plan.  It deliberately does not
inspect the worktree, invoke pytest, or perform any other side effect.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import TextIO

SCHEMA = "kg.backend.test-plan.v1"
BACKEND_CWD = "backend"
FULL_COMMAND = ["uv", "run", "--locked", "python", "-m", "pytest", "-q"]
_TARGETED_REASON = "backend-test-files-only"
_SOURCE_REASON = "backend-source-changed-no-source-to-test-map"
_CONFIG_REASON = "backend-runtime-or-test-config-changed"
_UNKNOWN_REASON = "unknown-backend-path-fail-closed"


class InputFormatError(ValueError):
    """Raised when changed-path input cannot be safely classified."""


def _normalize_path(raw_path: str) -> str:
    if not isinstance(raw_path, str):
        raise InputFormatError("changed path must be a string")
    path = raw_path.strip()
    if not path:
        raise InputFormatError("changed path must not be empty")
    if "\x00" in path:
        raise InputFormatError(f"changed path must not contain NUL: {path}")
    if "\\" in path:
        raise InputFormatError(f"changed path must use POSIX separators: {path}")

    while path.startswith("./"):
        path = path[2:]
    if not path:
        raise InputFormatError("changed path must not be empty")

    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise InputFormatError(f"path traversal is not allowed: {path}")
    return path


def _is_backend_test_file(path: str) -> bool:
    prefix = "backend/tests/test_"
    if not path.startswith(prefix) or not path.endswith(".py"):
        return False
    return "/" not in path[len(prefix) :]


def _is_backend_source(path: str) -> bool:
    return path == "backend/src" or path.startswith("backend/src/")


def _is_backend_config_or_workflow(path: str) -> bool:
    config_names = {
        "pyproject.toml",
        "pytest.ini",
        "pytest.cfg",
        "pytest.toml",
        ".pytest.ini",
        "uv.lock",
        ".python-version",
    }
    if path in {f"backend/{name}" for name in config_names}:
        return True
    if path in {
        ".github/workflows/backend-quality.yml",
        ".github/workflows/backend-quality.yaml",
        ".github/workflows/pr-gate.yml",
        ".github/workflows/pr-gate.yaml",
    }:
        return True
    return path.startswith("backend/config/")


def _backend_reason(paths: Iterable[str]) -> str:
    if any(_is_backend_source(path) for path in paths):
        return _SOURCE_REASON
    if any(_is_backend_config_or_workflow(path) for path in paths):
        return _CONFIG_REASON
    return _UNKNOWN_REASON


def plan_changed_paths(changed_paths: Iterable[str]) -> dict[str, object]:
    """Return a deterministic, non-executing backend test plan."""

    if isinstance(changed_paths, (str, bytes)):
        raise InputFormatError("changed paths must be an iterable of paths")
    normalized_paths = sorted({_normalize_path(path) for path in changed_paths})
    if not normalized_paths:
        raise InputFormatError("at least one changed path is required")

    backend_test_paths = [path for path in normalized_paths if _is_backend_test_file(path)]
    backend_paths = [
        path
        for path in normalized_paths
        if path.startswith("backend/")
        or _is_backend_config_or_workflow(path)
    ]

    if not backend_paths:
        return {
            "schema": SCHEMA,
            "status": "planned",
            "plan_kind": "none",
            "changed_paths": normalized_paths,
            "backend_paths": [],
            "ignored_paths": normalized_paths,
            "selectors": [],
            "command": None,
            "cwd": BACKEND_CWD,
            "reason": "no-backend-paths",
        }

    non_targeted_backend_paths = [
        path for path in backend_paths if not _is_backend_test_file(path)
    ]
    if non_targeted_backend_paths:
        return {
            "schema": SCHEMA,
            "status": "planned",
            "plan_kind": "full",
            "changed_paths": normalized_paths,
            "backend_paths": backend_paths,
            "ignored_paths": sorted(set(normalized_paths) - set(backend_paths)),
            "selectors": [],
            "command": list(FULL_COMMAND),
            "cwd": BACKEND_CWD,
            "reason": _backend_reason(non_targeted_backend_paths),
        }

    selectors = sorted(path[len("backend/") :] for path in backend_test_paths)
    return {
        "schema": SCHEMA,
        "status": "planned",
        "plan_kind": "targeted",
        "changed_paths": normalized_paths,
        "backend_paths": backend_paths,
        "ignored_paths": sorted(set(normalized_paths) - set(backend_paths)),
        "selectors": selectors,
        "command": [*FULL_COMMAND, *selectors],
        "cwd": BACKEND_CWD,
        "reason": _TARGETED_REASON,
    }


def _error_plan(error: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "status": "error",
        "plan_kind": "error",
        "command": None,
        "cwd": BACKEND_CWD,
        "reason": "invalid-input",
        "error": error,
    }


HELP_TEXT = """Usage: ops/backend_test_plan.py [PATH ...]

Emit one deterministic kg.backend.test-plan.v1 JSON plan without executing
tests. PATH values are repository-relative; use --paths-stdin for one path per
stdin line. With no PATH arguments, stdin is read by default.

Options:
  --paths-stdin, --stdin  read changed paths from stdin
  -h, --help              show this help
"""


def _read_paths(argv: list[str], stdin: TextIO) -> list[str]:
    stdin_flags = {"--paths-stdin", "--stdin"}
    if any(flag in argv for flag in stdin_flags):
        remaining = [arg for arg in argv if arg not in stdin_flags]
        if remaining:
            raise InputFormatError("--paths-stdin cannot be combined with path arguments")
        return stdin.read().splitlines()
    if not argv:
        return stdin.read().splitlines()
    if any(arg.startswith("-") for arg in argv):
        unknown = next(arg for arg in argv if arg.startswith("-"))
        raise InputFormatError(f"unknown argument: {unknown}")
    return argv


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Emit one deterministic JSON plan and return its process status."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    if any(argument in {"-h", "--help"} for argument in arguments):
        output_stream.write(HELP_TEXT)
        return 0
    try:
        plan = plan_changed_paths(_read_paths(arguments, input_stream))
    except InputFormatError as error:
        plan = _error_plan(str(error))
        return_code = 2
    else:
        return_code = 0
    output_stream.write(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    output_stream.write("\n")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
