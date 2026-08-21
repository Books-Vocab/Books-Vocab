"""Immutable value objects shared by the delivery control plane."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import InvalidReceipt, InvalidScope

SCOPE_SCHEMA = "kg.worktree.scope.v1"
# Internal normalized envelope. The existing kg.worktree.handback.v1 wire
# schema remains owned by worktree_registry.py and is translated by adapters.
HANDBACK_SCHEMA = "kg.delivery.handback.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ScopeOperation(StrEnum):
    ADD = "add"
    MODIFY = "modify"


class CheckStatus(StrEnum):
    ABSENT = "absent"
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


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


def _require_sha(name: str, value: object) -> str:
    if type(value) is not str or not _SHA_RE.fullmatch(value):
        raise InvalidReceipt(f"{name} must be a lowercase 40-character Git SHA")
    return value


def _require_text(name: str, value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or _has_control(value)
    ):
        raise InvalidReceipt(f"{name} must be non-empty canonical text")
    return value


def _require_generation(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise InvalidReceipt(f"{name} must be a non-negative integer")
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
    ) -> Scope:
        return cls(
            tuple(ScopeFile(ScopeOperation.ADD, path) for path in add)
            + tuple(ScopeFile(ScopeOperation.MODIFY, path) for path in modify)
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Scope:
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


@dataclass(frozen=True)
class ValidationEvidence:
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    observed_at: datetime
    log_path: str | None = None

    def __post_init__(self) -> None:
        if type(self.command) is not tuple or not self.command:
            raise InvalidReceipt("validation command must be a non-empty tuple")
        for item in self.command:
            _require_text("validation command item", item)
        if type(self.exit_code) is not int:
            raise InvalidReceipt("validation exit_code must be an integer")
        if type(self.duration_seconds) is not float or not math.isfinite(
            self.duration_seconds
        ):
            raise InvalidReceipt("validation duration must be a finite float")
        if self.duration_seconds < 0:
            raise InvalidReceipt("validation duration cannot be negative")
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.utcoffset() is None
        ):
            raise InvalidReceipt("validation timestamp must be offset-aware")
        if self.log_path is not None:
            _require_text("validation log_path", self.log_path)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "observed_at": self.observed_at.isoformat(),
        }
        if self.log_path is not None:
            payload["log_path"] = self.log_path
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ValidationEvidence:
        try:
            command = payload["command"]
            exit_code = payload["exit_code"]
            duration = payload["duration_seconds"]
            observed_at = payload["observed_at"]
            log_path = payload.get("log_path")
            if not isinstance(command, list) or any(
                type(item) is not str for item in command
            ):
                raise TypeError("command must be a list of strings")
            if type(exit_code) is not int:
                raise TypeError("exit_code must be an integer")
            if type(duration) is not float:
                raise TypeError("duration_seconds must be a float")
            if type(observed_at) is not str:
                raise TypeError("observed_at must be a string")
            if log_path is not None and type(log_path) is not str:
                raise TypeError("log_path must be a string")
            return cls(
                command=tuple(command),
                exit_code=exit_code,
                duration_seconds=duration,
                observed_at=datetime.fromisoformat(observed_at),
                log_path=log_path,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("validation evidence is malformed") from error


@dataclass(frozen=True)
class HandbackReceipt:
    lane_id: str
    owner_thread_id: str
    claim_generation: int
    branch: str
    worktree_path: str
    base_sha: str
    parent_sha: str
    head_sha: str
    origin_main_sha: str
    content_digest: str
    scope: Scope
    validation: tuple[ValidationEvidence, ...] = ()
    schema: str = field(default=HANDBACK_SCHEMA, init=False)

    def __post_init__(self) -> None:
        for name in ("lane_id", "owner_thread_id", "branch"):
            _require_text(name, getattr(self, name))
        _require_generation("claim_generation", self.claim_generation)
        _require_text("worktree_path", self.worktree_path)
        worktree_path = Path(self.worktree_path)
        if not worktree_path.is_absolute():
            raise InvalidReceipt("worktree_path must be absolute")
        object.__setattr__(self, "worktree_path", str(worktree_path.resolve()))
        for name in ("base_sha", "parent_sha", "head_sha", "origin_main_sha"):
            _require_sha(name, getattr(self, name))
        if type(self.content_digest) is not str or not _DIGEST_RE.fullmatch(
            self.content_digest
        ):
            raise InvalidReceipt("content_digest must be a lowercase SHA-256 digest")
        if type(self.validation) is not tuple or any(
            not isinstance(item, ValidationEvidence) for item in self.validation
        ):
            raise InvalidReceipt("validation must be a tuple of evidence")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "lane_id": self.lane_id,
            "owner_thread_id": self.owner_thread_id,
            "claim_generation": self.claim_generation,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "base_sha": self.base_sha,
            "parent_sha": self.parent_sha,
            "head_sha": self.head_sha,
            "origin_main_sha": self.origin_main_sha,
            "content_digest": self.content_digest,
            "scope": self.scope.to_payload(),
            "scope_digest": self.scope.digest,
            "validation": [item.to_payload() for item in self.validation],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> HandbackReceipt:
        if payload.get("schema") != HANDBACK_SCHEMA:
            raise InvalidReceipt(f"handback schema must be {HANDBACK_SCHEMA}")
        try:
            raw_scope = payload["scope"]
            if not isinstance(raw_scope, Mapping):
                raise TypeError("scope must be an object")
            scope = Scope.from_payload(raw_scope)
            if payload.get("scope_digest") != scope.digest:
                raise InvalidReceipt("scope digest does not match Scope")
            raw_validation = payload.get("validation", [])
            if not isinstance(raw_validation, list) or any(
                not isinstance(item, Mapping) for item in raw_validation
            ):
                raise TypeError("validation entries must be objects")
            string_fields = (
                "lane_id",
                "owner_thread_id",
                "branch",
                "worktree_path",
                "base_sha",
                "parent_sha",
                "head_sha",
                "origin_main_sha",
                "content_digest",
            )
            if any(type(payload.get(name)) is not str for name in string_fields):
                raise TypeError("handback string field has the wrong type")
            generation = payload["claim_generation"]
            if type(generation) is not int:
                raise TypeError("claim_generation must be an integer")
            return cls(
                lane_id=payload["lane_id"],
                owner_thread_id=payload["owner_thread_id"],
                claim_generation=generation,
                branch=payload["branch"],
                worktree_path=payload["worktree_path"],
                base_sha=payload["base_sha"],
                parent_sha=payload["parent_sha"],
                head_sha=payload["head_sha"],
                origin_main_sha=payload["origin_main_sha"],
                content_digest=payload["content_digest"],
                scope=scope,
                validation=tuple(
                    ValidationEvidence.from_payload(item) for item in raw_validation
                ),
            )
        except InvalidReceipt:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("handback receipt is malformed") from error


@dataclass(frozen=True)
class MergedPullRequestProof:
    """Exact GitHub observation authorizing a terminal merged disposition."""

    lane_id: str
    pr_number: int
    branch: str
    head_sha: str
    base_branch: str = "main"
    pr_state: str = "MERGED"

    def __post_init__(self) -> None:
        _require_text("lane_id", self.lane_id)
        _require_text("branch", self.branch)
        _require_sha("head_sha", self.head_sha)
        if type(self.pr_number) is not int or self.pr_number <= 0:
            raise InvalidReceipt("pr_number must be a positive integer")
        if self.base_branch != "main" or self.pr_state != "MERGED":
            raise InvalidReceipt("merged PR proof must target main and be MERGED")
