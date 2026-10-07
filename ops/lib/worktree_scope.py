"""Structured file ownership declarations for local worktrees.

GitHub owns product work items and delivery state.  A local worktree still needs
an explicit file scope so parallel agents can detect overlap without guessing from
prose or from a diff produced after the fact.
"""

from __future__ import annotations

import difflib
import json
import posixpath
from pathlib import PurePosixPath

SCOPE_SCHEMA = "kg.worktree.scope.v1"
SCOPE_OPERATIONS = ("add", "modify", "delete")
# Spellings agents reach for naturally; canonicalised on input, never stored.
SCOPE_OPERATION_ALIASES = {"create": "add", "new": "add"}


def _normalise_path(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, "path must be a non-empty string"
    path = value.strip()
    if "\x00" in path:
        return None, "path contains NUL"
    if "\\" in path:
        return None, "path must use / separators"
    if path.startswith("/") or PurePosixPath(path).is_absolute():
        return None, "path must be relative to the repository"
    if path.endswith("/"):
        return None, "path must identify a file, not a directory"
    parts = path.split("/")
    if any(part in ("", "..") for part in parts):
        return None, "path must not contain empty or parent components"
    normalised = posixpath.normpath(path)
    if normalised in ("", ".", "..") or normalised.startswith("../"):
        return None, "path must identify a repository file"
    return normalised, None


def scope_problems(value: object) -> list[dict]:
    """Return named validation findings for a structured Scope."""
    if value in (None, ""):
        return []
    if not isinstance(value, dict):
        # Old registry records may contain prose.  They remain readable but do
        # not participate in file-overlap claims until explicitly replaced.
        return []
    problems: list[dict] = []
    schema = value.get("schema")
    if schema not in (None, SCOPE_SCHEMA):
        problems.append({"kind": "scope-unknown-schema", "schema": schema})
    files = value.get("files")
    if not isinstance(files, list) or not files:
        problems.append({"kind": "scope-files-empty"})
        return problems
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            problems.append({"kind": "scope-file-not-object", "index": index})
            continue
        path, path_error = _normalise_path(item.get("path"))
        if path_error:
            problems.append(
                {
                    "kind": "scope-file-bad-path",
                    "index": index,
                    "path": item.get("path"),
                    "reason": path_error,
                }
            )
        elif path in seen:
            problems.append(
                {"kind": "scope-file-duplicate", "index": index, "path": path}
            )
        elif path is not None:
            seen.add(path)
        operation = item.get("operation")
        if operation not in SCOPE_OPERATIONS:
            problem = {
                "kind": "scope-file-bad-operation",
                "index": index,
                "operation": operation,
                "allowed": list(SCOPE_OPERATIONS),
            }
            close = difflib.get_close_matches(
                str(operation), SCOPE_OPERATIONS, n=1, cutoff=0.5
            )
            if close:
                problem["suggestion"] = close[0]
            problems.append(problem)
    return problems


def _canonical_operations(value: object) -> object:
    """Map accepted operation aliases (``create`` -> ``add``) on a copy."""
    if not isinstance(value, dict) or not isinstance(value.get("files"), list):
        return value
    files = [
        {
            **item,
            "operation": SCOPE_OPERATION_ALIASES.get(
                item["operation"], item["operation"]
            ),
        }
        if isinstance(item, dict) and isinstance(item.get("operation"), str)
        else item
        for item in value["files"]
    ]
    return {**value, "files": files}


def normalise_scope(value: object) -> dict:
    """Canonicalise a structured Scope or raise a named ``ValueError``."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid scope JSON: {exc.msg}") from exc
    value = _canonical_operations(value)
    problems = scope_problems(value)
    if problems:
        raise ValueError(f"invalid scope: {problems}")
    if not isinstance(value, dict):
        raise ValueError("invalid scope: expected an object with files[]")
    files = []
    for item in value["files"]:
        path, _ = _normalise_path(item["path"])
        files.append({"path": path, "operation": item["operation"]})
    return {"schema": SCOPE_SCHEMA, "files": files}


def coerce_scope(value: object) -> object:
    """Parse JSON-looking CLI values while preserving old prose records."""
    if isinstance(value, dict):
        return normalise_scope(value)
    if isinstance(value, list):
        raise ValueError("invalid scope: expected an object with files[]")
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        return normalise_scope(stripped)
    return value


def scope_status(value: object) -> str:
    return (
        "known" if isinstance(value, dict) and not scope_problems(value) else "unknown"
    )


def scope_files(value: object) -> list[dict]:
    if scope_status(value) != "known":
        return []
    return [dict(item) for item in value["files"]]


_STATUS_OPERATIONS = {"A": "add", "M": "modify", "D": "delete", "T": "modify"}


def scope_from_name_status(text: str) -> dict:
    """Name-status diff output -> a structured Scope.

    A rename is a delete of the old path plus an add of the new one, which is
    how Scope overlap has to see it.
    """
    files: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0][0]
        if code in "RC":
            if code == "R":
                files.append({"operation": "delete", "path": parts[1]})
            files.append({"operation": "add", "path": parts[2]})
        elif code in _STATUS_OPERATIONS:
            files.append({"operation": _STATUS_OPERATIONS[code], "path": parts[1]})
        else:
            raise ValueError(f"unrecognised git status {parts[0]!r} for {parts[-1]!r}")
    return {"schema": SCOPE_SCHEMA, "files": files}
