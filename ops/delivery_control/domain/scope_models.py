"""Structured file-Scope value objects and canonical wire representation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from .errors import InvalidScope

SCOPE_SCHEMA = "kg.worktree.scope.v1"


class ScopeOperation(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


def _has_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _safe_relative_path(value: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\\" in value
        or _has_control(value)
    ):
        raise InvalidScope(f"unsafe Scope path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidScope(f"unsafe Scope path: {value!r}")
    if str(path) != value:
        raise InvalidScope(f"Scope path is not canonical: {value!r}")
    return value


@dataclass(frozen=True, order=True)
class ScopeFile:
    operation: ScopeOperation
    path: str

    def __post_init__(self) -> None:
        try:
            operation = ScopeOperation(self.operation)
        except (TypeError, ValueError) as error:
            raise InvalidScope(
                f"unsupported Scope operation: {self.operation!r}"
            ) from error
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "path", _safe_relative_path(self.path))

    def to_payload(self) -> dict[str, str]:
        return {"operation": self.operation.value, "path": self.path}


@dataclass(frozen=True)
class Scope:
    files: tuple[ScopeFile, ...]
    schema: str = field(default=SCOPE_SCHEMA, init=False)

    def __post_init__(self) -> None:
        if type(self.files) is not tuple or not self.files:
            raise InvalidScope("Scope must contain a non-empty tuple of files")
        if any(not isinstance(item, ScopeFile) for item in self.files):
            raise InvalidScope("Scope files must be ScopeFile values")
        canonical = tuple(
            sorted(self.files, key=lambda item: (item.path, item.operation.value))
        )
        paths = [item.path for item in canonical]
        if len(paths) != len(set(paths)):
            raise InvalidScope("Scope contains a duplicate path")
        object.__setattr__(self, "files", canonical)

    @classmethod
    def from_paths(
        cls,
        *,
        add: Sequence[str] = (),
        modify: Sequence[str] = (),
        delete: Sequence[str] = (),
    ) -> Scope:
        return cls(
            tuple(ScopeFile(ScopeOperation.ADD, path) for path in add)
            + tuple(ScopeFile(ScopeOperation.MODIFY, path) for path in modify)
            + tuple(ScopeFile(ScopeOperation.DELETE, path) for path in delete)
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Scope:
        if not isinstance(payload, Mapping):
            raise InvalidScope("Scope payload must be an object")
        if payload.get("schema") != SCOPE_SCHEMA:
            raise InvalidScope(f"Scope schema must be {SCOPE_SCHEMA}")
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise InvalidScope("Scope files must be a list")
        files: list[ScopeFile] = []
        for item in raw_files:
            if not isinstance(item, Mapping):
                raise InvalidScope("Scope files contain malformed entries")
            operation = item.get("operation")
            path = item.get("path")
            if type(operation) is not str or type(path) is not str:
                raise InvalidScope("Scope files contain malformed entries")
            files.append(ScopeFile(operation=ScopeOperation(operation), path=path))
        return cls(files=tuple(files))

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "files": [item.to_payload() for item in self.files],
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)

    def allows_changed_paths(self, changed_paths: Sequence[str]) -> bool:
        """Return whether a non-empty observed change set fits this Scope.

        Scope declares the files a lane is allowed to modify; a valid commit
        may therefore touch a strict subset of that declaration. Empty or
        duplicate observations remain invalid so missing or ambiguous GitHub
        path evidence cannot satisfy a lifecycle check.
        """

        observed = tuple(changed_paths)
        return (
            bool(observed)
            and len(observed) == len(set(observed))
            and set(observed).issubset(self.paths)
        )
