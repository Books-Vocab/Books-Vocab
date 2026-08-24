"""Raw GitHub Issue demand facts and deterministic disposition projection."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from .candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateIssue,
    CandidateSeverity,
    CandidateSpec,
)
from .models import Scope
from .observations import InventoryProblem

ISSUE_INTAKE_SCHEMA = "kg.delivery.issue-intake.v1"
_ISSUE_INTAKE_BEGIN = "<!-- kg.delivery.issue-intake.v1\n"
_ISSUE_INTAKE_END = "\n-->"
_ISSUE_INTAKE_FIELDS = frozenset(
    {
        "schema",
        "title",
        "body",
        "labels",
        "source",
        "provenance",
        "severity",
        "priority",
        "acceptance",
        "scope",
        "operator",
    }
)


def _intake_text(value: object, name: str, *, multiline: bool = False) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"issue intake {name} must be canonical text")
    if any(
        ord(character) < 32
        and (not multiline or character not in "\n\t")
        or ord(character) == 127
        for character in value
    ):
        raise ValueError(f"issue intake {name} contains control characters")
    return value


@dataclass(frozen=True)
class IssueIntakeRequest:
    """Explicit payload for creating one raw Issue, never a candidate."""

    title: str
    body: str
    labels: tuple[str, ...]
    source: str
    provenance: str
    severity: CandidateSeverity
    priority: int
    acceptance: tuple[str, ...]
    scope: Scope
    operator: str
    schema: str = ISSUE_INTAKE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ISSUE_INTAKE_SCHEMA:
            raise ValueError(f"issue intake schema must be {ISSUE_INTAKE_SCHEMA}")
        for name in ("title", "source", "provenance", "operator"):
            _intake_text(getattr(self, name), name)
        _intake_text(self.body, "body", multiline=True)
        if type(self.labels) is not tuple or not self.labels:
            raise ValueError("issue intake labels must be a non-empty list")
        for label in self.labels:
            _intake_text(label, "labels")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("issue intake labels must not contain duplicates")
        try:
            severity = CandidateSeverity(self.severity)
        except (TypeError, ValueError) as error:
            raise ValueError("issue intake severity is unsupported") from error
        object.__setattr__(self, "severity", severity)
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("issue intake priority must be a non-negative integer")
        if type(self.acceptance) is not tuple or not self.acceptance:
            raise ValueError("issue intake acceptance must be a non-empty list")
        for item in self.acceptance:
            _intake_text(item, "acceptance")
        if len(set(self.acceptance)) != len(self.acceptance):
            raise ValueError("issue intake acceptance must not contain duplicates")
        if not isinstance(self.scope, Scope):
            raise ValueError("issue intake Scope is invalid")
        if _ISSUE_INTAKE_BEGIN in self.body:
            raise ValueError("issue intake body must not contain a typed intake block")
        object.__setattr__(self, "labels", tuple(sorted(self.labels)))

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> IssueIntakeRequest:
        if not isinstance(payload, Mapping):
            raise ValueError("issue intake payload must be an object")
        if set(payload) != _ISSUE_INTAKE_FIELDS:
            raise ValueError("issue intake payload fields are not exact")
        if payload.get("schema") != ISSUE_INTAKE_SCHEMA:
            raise ValueError(f"issue intake schema must be {ISSUE_INTAKE_SCHEMA}")
        raw_labels = payload.get("labels")
        raw_acceptance = payload.get("acceptance")
        raw_scope = payload.get("scope")
        if not isinstance(raw_labels, list) or not isinstance(raw_acceptance, list):
            raise ValueError("issue intake labels and acceptance must be lists")
        if not isinstance(raw_scope, Mapping):
            raise ValueError("issue intake Scope must be an object")
        try:
            scope = Scope.from_payload(raw_scope)
            severity = CandidateSeverity(payload.get("severity"))
        except (TypeError, ValueError) as error:
            raise ValueError("issue intake severity or Scope is invalid") from error
        try:
            return cls(
                title=payload.get("title"),  # type: ignore[arg-type]
                body=payload.get("body"),  # type: ignore[arg-type]
                labels=tuple(raw_labels),
                source=payload.get("source"),  # type: ignore[arg-type]
                provenance=payload.get("provenance"),  # type: ignore[arg-type]
                severity=severity,
                priority=payload.get("priority"),  # type: ignore[arg-type]
                acceptance=tuple(raw_acceptance),
                scope=scope,
                operator=payload.get("operator"),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as error:
            raise ValueError(str(error)) from error

    def to_payload(self, *, include_operator: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": self.schema,
            "title": self.title,
            "body": self.body,
            "labels": list(self.labels),
            "source": self.source,
            "provenance": self.provenance,
            "severity": self.severity.value,
            "priority": self.priority,
            "acceptance": list(self.acceptance),
            "scope": self.scope.to_payload(),
        }
        if include_operator:
            payload["operator"] = self.operator
        return payload

    @property
    def source_fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_payload(include_operator=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    @property
    def client_mutation_id(self) -> str:
        return self.source_fingerprint

    @property
    def has_security_hold(self) -> bool:
        labels = {label.casefold() for label in self.labels}
        if labels.intersection({"security", "delivery-hold:security"}):
            return True
        for line in self.body.casefold().splitlines():
            if "publish only" in line:
                return True
            if "security hold" in line and not re.search(
                r"\b(?:no|without|not|none)\b.{0,40}\bsecurity hold\b", line
            ):
                return True
        return False

    def render_body(self) -> str:
        machine = self.to_payload()
        machine["source_fingerprint"] = self.source_fingerprint
        encoded = json.dumps(
            machine, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return f"{self.body}\n\n{_ISSUE_INTAKE_BEGIN}{encoded}{_ISSUE_INTAKE_END}\n"


def issue_intake_fingerprint(body: str) -> str | None:
    """Read one intake marker without treating arbitrary body text as evidence."""

    if type(body) is not str or body.count(_ISSUE_INTAKE_BEGIN) != 1:
        return None
    start = body.index(_ISSUE_INTAKE_BEGIN) + len(_ISSUE_INTAKE_BEGIN)
    finish = body.find(_ISSUE_INTAKE_END, start)
    if finish < 0:
        return None
    try:
        payload = json.loads(body[start:finish])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    fingerprint = payload.get("source_fingerprint")
    if (
        payload.get("schema") != ISSUE_INTAKE_SCHEMA
        or type(fingerprint) is not str
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        return None
    return fingerprint


class IssueDisposition(StrEnum):
    """The one control-plane disposition assigned to an open Issue."""

    SOURCE_PROBLEM = "source_problem"
    SECURITY_HOLD = "security_hold"
    OWNER_BOUND = "owner_bound"
    PUBLISHED_PR = "published_pr"
    TERMINAL_HISTORY = "terminal_history"
    DISPATCHABLE_CANDIDATE = "dispatchable_candidate"
    BLOCKED = "blocked"
    LEGACY_UNMAPPED = "legacy_unmapped"
    TRIAGE_REQUIRED = "triage_required"


@dataclass(frozen=True)
class DemandIssue:
    """One raw open Issue plus its read-only delivery projection."""

    number: int
    url: str
    node_id: str
    title: str
    labels: tuple[str, ...]
    body: str
    updated_at: datetime | None
    body_sha256: str
    disposition: IssueDisposition = IssueDisposition.TRIAGE_REQUIRED
    reason: str = "open Issue has not been triaged"
    candidate_spec: CandidateSpec | None = None
    mapped_external_ids: tuple[str, ...] = ()
    mapped_pull_request_numbers: tuple[int, ...] = ()
    # A malformed active registry record can still be joined by its explicit
    # external ID for audit. This is intentionally separate from valid lane
    # mappings and never authorizes owner recovery or dispatch.
    malformed_active_registry_external_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.number) is not int or self.number <= 0:
            raise ValueError("Issue number must be a positive integer")
        for name in ("url", "node_id", "title", "body", "body_sha256", "reason"):
            value = getattr(self, name)
            if type(value) is not str or (
                name in {"url", "node_id"}
                and (
                    not value.strip() or any(ord(character) < 32 for character in value)
                )
            ):
                raise TypeError(f"Issue {name} must be text")
        if len(self.body_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.body_sha256
        ):
            raise ValueError("Issue body_sha256 must be a lowercase SHA-256")
        if self.body_sha256 != sha256(self.body.encode("utf-8")).hexdigest():
            raise ValueError("Issue body_sha256 does not match body")
        if type(self.labels) is not tuple or any(
            type(label) is not str or not label.strip() for label in self.labels
        ):
            raise TypeError("Issue labels must be canonical text")
        if type(self.mapped_external_ids) is not tuple or any(
            type(item) is not str or not item.strip()
            for item in self.mapped_external_ids
        ):
            raise TypeError("Issue external IDs must be canonical text")
        if type(self.mapped_pull_request_numbers) is not tuple or any(
            type(item) is not int or item <= 0
            for item in self.mapped_pull_request_numbers
        ):
            raise TypeError("Issue pull request mappings must be positive integers")
        if type(self.malformed_active_registry_external_ids) is not tuple or any(
            type(item) is not str or not item.strip()
            for item in self.malformed_active_registry_external_ids
        ):
            raise TypeError(
                "Malformed registry Issue references must be canonical text"
            )
        if self.updated_at is not None and (
            not isinstance(self.updated_at, datetime)
            or self.updated_at.utcoffset() is None
        ):
            raise ValueError("Issue updated_at must be timezone-aware")
        object.__setattr__(self, "disposition", IssueDisposition(self.disposition))
        object.__setattr__(self, "labels", tuple(sorted(set(self.labels))))
        object.__setattr__(
            self,
            "mapped_external_ids",
            tuple(sorted(set(self.mapped_external_ids))),
        )
        object.__setattr__(
            self,
            "mapped_pull_request_numbers",
            tuple(sorted(set(self.mapped_pull_request_numbers))),
        )
        object.__setattr__(
            self,
            "malformed_active_registry_external_ids",
            tuple(sorted(set(self.malformed_active_registry_external_ids))),
        )

    @property
    def candidate(self) -> CandidateIssue | None:
        if self.candidate_spec is None or CANDIDATE_ISSUE_LABEL not in self.labels:
            return None
        return CandidateIssue(
            number=self.number,
            url=self.url,
            spec=self.candidate_spec,
        )

    @property
    def dispatchable(self) -> bool:
        return self.disposition is IssueDisposition.DISPATCHABLE_CANDIDATE


@dataclass(frozen=True)
class IssueIntakeReceipt:
    """Exact readback of one created raw Issue."""

    issue: DemandIssue
    source_fingerprint: str
    client_mutation_id: str

    def __post_init__(self) -> None:
        for name in ("source_fingerprint", "client_mutation_id"):
            value = getattr(self, name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"issue intake {name} must be a lowercase SHA-256")
        if self.source_fingerprint != self.client_mutation_id:
            raise ValueError("issue intake mutation identity must match fingerprint")
        if issue_intake_fingerprint(self.issue.body) != self.source_fingerprint:
            raise ValueError("created Issue body lacks the exact intake fingerprint")


@dataclass(frozen=True)
class DemandIssueSourceEntry:
    """One raw Issue page entry that could not become a full Issue record."""

    identity: str
    entry_index: int
    reason: str
    issue_number: int | None = None
    disposition: IssueDisposition = IssueDisposition.SOURCE_PROBLEM

    def __post_init__(self) -> None:
        for name in ("identity", "reason"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise TypeError(f"source entry {name} must be non-empty text")
        if type(self.entry_index) is not int or self.entry_index < 0:
            raise ValueError("source entry index must be non-negative")
        if self.issue_number is not None and (
            type(self.issue_number) is not int or self.issue_number <= 0
        ):
            raise ValueError("source entry Issue number must be positive")
        object.__setattr__(self, "disposition", IssueDisposition(self.disposition))
        if self.disposition is not IssueDisposition.SOURCE_PROBLEM:
            raise ValueError("raw source entries must remain source_problem")


@dataclass(frozen=True)
class DemandIssueInventory:
    """Complete raw Issue inventory; never a local lifecycle database."""

    records: tuple[DemandIssue, ...]
    # ``None`` means the source failed before GitHub returned a trustworthy
    # page count. It must not be rendered as zero: zero is a real empty
    # inventory and would hide an unknown backlog from the supervisor.
    raw_count: int | None
    problems: tuple[InventoryProblem, ...] = ()
    source_entries: tuple[DemandIssueSourceEntry, ...] = ()
    complete: bool = True

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            not isinstance(item, DemandIssue) for item in self.records
        ):
            raise TypeError("Issue records must be a tuple of DemandIssue")
        numbers = tuple(item.number for item in self.records)
        if len(numbers) != len(set(numbers)):
            raise ValueError("Issue inventory contains duplicate numbers")
        if self.raw_count is not None and (
            type(self.raw_count) is not int or self.raw_count < len(self.records)
        ):
            raise ValueError("raw_count must include every parsed and malformed entry")
        if type(self.problems) is not tuple or any(
            not isinstance(item, InventoryProblem) for item in self.problems
        ):
            raise TypeError("Issue problems must be InventoryProblem values")
        if type(self.source_entries) is not tuple or any(
            not isinstance(item, DemandIssueSourceEntry) for item in self.source_entries
        ):
            raise TypeError(
                "Issue source entries must be DemandIssueSourceEntry values"
            )
        if type(self.complete) is not bool:
            raise TypeError("Issue inventory completeness must be boolean")
        if self.raw_count is None and self.complete:
            raise ValueError("unknown raw_count requires an incomplete inventory")
        identities = tuple(item.identity for item in self.source_entries)
        if len(identities) != len(set(identities)):
            raise ValueError("Issue source entries contain duplicate identities")
        represented_entries = len(self.records) + len(self.source_entries)
        if self.raw_count is not None and self.raw_count < represented_entries:
            raise ValueError("raw_count must include every parsed and malformed entry")
        if (
            self.complete
            and self.raw_count is not None
            and (self.raw_count != represented_entries)
        ):
            raise ValueError("complete Issue inventory must represent every raw entry")
        object.__setattr__(
            self,
            "records",
            tuple(sorted(self.records, key=lambda item: item.number)),
        )

    @property
    def raw_open_issues(self) -> int | None:
        return self.raw_count

    @property
    def candidate_issues(self) -> tuple[CandidateIssue, ...]:
        return tuple(
            candidate
            for issue in self.records
            if (candidate := issue.candidate) is not None
        )

    @property
    def dispatchable_candidate_issues(self) -> tuple[CandidateIssue, ...]:
        return tuple(
            candidate
            for issue in self.records
            if issue.dispatchable and (candidate := issue.candidate) is not None
        )

    def count(self, disposition: IssueDisposition) -> int:
        parsed = sum(item.disposition is disposition for item in self.records)
        return parsed + (
            len(self.source_entries)
            if disposition is IssueDisposition.SOURCE_PROBLEM
            else 0
        )

    @property
    def disposition_counts(self) -> dict[str, int]:
        """Return all partition counts, including zero-valued dispositions."""

        return {
            disposition.value: self.count(disposition)
            for disposition in IssueDisposition
        }

    @property
    def unadmitted_open_issues(self) -> int | None:
        if self.raw_count is None:
            return None
        represented_entries = len(self.records) + len(self.source_entries)
        return (
            len(self.source_entries)
            + sum(
                item.disposition
                in {
                    IssueDisposition.TRIAGE_REQUIRED,
                    IssueDisposition.LEGACY_UNMAPPED,
                    IssueDisposition.SOURCE_PROBLEM,
                }
                for item in self.records
            )
            + max(0, self.raw_count - represented_entries)
        )

    @property
    def backlog_drained(self) -> bool:
        return self.complete and self.unadmitted_open_issues == 0


def issue_body_sha256(body: str) -> str:
    """Return the stable fingerprint used by admission preflight/readback."""

    if type(body) is not str:
        raise TypeError("Issue body must be text")
    return sha256(body.encode("utf-8")).hexdigest()


EMPTY_DEMAND_INVENTORY = DemandIssueInventory(records=(), raw_count=0)
