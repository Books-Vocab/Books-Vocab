"""Shared file-level Scope contract for the delivery progress board.

The backlog keeps legacy prose values readable, but a matrix cell is only
created from this structured shape.  The board therefore never guesses a file
from ``fix_site`` or from technical prose.
"""

from __future__ import annotations

import json
import posixpath
from pathlib import PurePosixPath

SCOPE_SCHEMA = "kg.backlog.scope.v1"
SCOPE_OPERATIONS = ("add", "modify")


def _normalise_path(value) -> tuple[str | None, str | None]:
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


def scope_problems(value) -> list[dict]:
    """Return named validation findings; legacy prose is intentionally allowed."""
    if value in (None, ""):
        return []
    if not isinstance(value, dict):
        # Existing entries use prose.  They remain readable and are projected as
        # unknown until a groom/update supplies the structured file claim.
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
            problems.append({"kind": "scope-file-bad-path", "index": index,
                             "path": item.get("path"), "reason": path_error})
        elif path in seen:
            problems.append({"kind": "scope-file-duplicate", "index": index,
                             "path": path})
        elif path is not None:
            seen.add(path)
        operation = item.get("operation")
        if operation not in SCOPE_OPERATIONS:
            problems.append({"kind": "scope-file-bad-operation", "index": index,
                             "operation": operation,
                             "allowed": list(SCOPE_OPERATIONS)})
    return problems


def normalise_scope(value) -> dict:
    """Canonicalise a structured Scope or raise a named ``ValueError``."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid scope JSON: {exc.msg}") from exc
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


def coerce_scope(value):
    """Parse JSON-looking CLI values while preserving legacy prose values."""
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


def scope_status(value) -> str:
    return "known" if isinstance(value, dict) and not scope_problems(value) else "unknown"


def scope_files(value) -> list[dict]:
    if scope_status(value) != "known":
        return []
    return [dict(item) for item in value["files"]]
