"""Current GitHub candidate Issue observations; never a local backlog."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from .models import Scope
from .observations import InventoryProblem

CANDIDATE_ISSUE_LABEL = "delivery:candidate"
_ISSUE_REFERENCE_RE = re.compile(
    r"(?:#|issue(?:[-:# ]?))?(?P<number>[1-9][0-9]*)",
    re.IGNORECASE,
)


class CandidateSeverity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


_SEVERITY_RANK = {
    CandidateSeverity.P0: 0,
    CandidateSeverity.P1: 1,
    CandidateSeverity.P2: 2,
    CandidateSeverity.P3: 3,
}


@dataclass(frozen=True)
class CandidateSpec:
    severity: CandidateSeverity
    priority: int
    scope: Scope
    acceptance: tuple[str, ...]
    initial_holds: tuple[str, ...] = ()
    schema: str = "kg.delivery.candidate.v1"

    def __post_init__(self) -> None:
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("candidate priority must be a non-negative integer")
        if (
            type(self.acceptance) is not tuple
            or not self.acceptance
            or any(
                type(item) is not str
                or not item.strip()
                or item != item.strip()
                or any(
                    ord(character) < 32 or ord(character) == 127 for character in item
                )
                for item in self.acceptance
            )
        ):
            raise ValueError("candidate acceptance must contain canonical text")
        if len(set(self.acceptance)) != len(self.acceptance):
            raise ValueError("candidate acceptance must not contain duplicates")
        if (
            type(self.initial_holds) is not tuple
            or any(item not in {"p0", "p1", "security"} for item in self.initial_holds)
            or len(set(self.initial_holds)) != len(self.initial_holds)
        ):
            raise ValueError("candidate initial_holds must be unique and supported")
        object.__setattr__(self, "initial_holds", tuple(sorted(self.initial_holds)))

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> CandidateSpec:
        if not isinstance(payload, Mapping):
            raise ValueError("candidate contract payload must be an object")
        if set(payload) != {
            "schema",
            "severity",
            "priority",
            "scope",
            "acceptance",
            "initial_holds",
        }:
            raise ValueError("candidate contract fields are not exact")
        if payload.get("schema") != "kg.delivery.candidate.v1":
            raise ValueError("candidate contract schema is unsupported")
        raw_scope = payload.get("scope")
        raw_acceptance = payload.get("acceptance")
        raw_initial_holds = payload.get("initial_holds")
        if (
            not isinstance(raw_scope, Mapping)
            or not isinstance(raw_acceptance, list)
            or not isinstance(raw_initial_holds, list)
        ):
            raise TypeError("candidate Scope or acceptance is malformed")
        try:
            severity = CandidateSeverity(payload.get("severity"))
            scope = Scope.from_payload(raw_scope)
        except (TypeError, ValueError) as error:
            raise ValueError("candidate severity or Scope is invalid") from error
        return cls(
            severity=severity,
            priority=payload.get("priority"),  # type: ignore[arg-type]
            scope=scope,
            acceptance=tuple(raw_acceptance),
            initial_holds=tuple(raw_initial_holds),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "severity": self.severity.value,
            "priority": self.priority,
            "scope": self.scope.to_payload(),
            "acceptance": list(self.acceptance),
            "initial_holds": list(self.initial_holds),
        }


def _issue_url_key(value: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    match = re.search(r"/issues/(?P<number>[1-9][0-9]*)$", path)
    if match is None:
        return None
    return parsed.netloc.casefold(), path.casefold(), int(match.group("number"))


@dataclass(frozen=True)
class CandidateIssue:
    number: int
    url: str
    spec: CandidateSpec

    def __post_init__(self) -> None:
        if type(self.number) is not int or self.number <= 0:
            raise ValueError("candidate Issue number must be a positive integer")
        if (
            type(self.url) is not str
            or not self.url.strip()
            or any(
                ord(character) < 32 or ord(character) == 127 for character in self.url
            )
        ):
            raise ValueError("candidate Issue URL must be canonical text")
        key = _issue_url_key(self.url)
        if key is None or key[2] != self.number:
            raise ValueError("candidate Issue URL must match its Issue number")
        object.__setattr__(self, "url", self.url.strip().rstrip("/"))

    @property
    def dispatch_key(self) -> tuple[int, int, int, str]:
        return (
            _SEVERITY_RANK[self.spec.severity],
            self.spec.priority,
            self.number,
            self.url,
        )


@dataclass(frozen=True)
class CandidateIssueInventory:
    records: tuple[CandidateIssue, ...]
    problems: tuple[InventoryProblem, ...] = ()

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            not isinstance(item, CandidateIssue) for item in self.records
        ):
            raise TypeError("candidate Issue records must be a tuple")
        if type(self.problems) is not tuple or any(
            not isinstance(item, InventoryProblem) for item in self.problems
        ):
            raise TypeError("candidate Issue problems must be a tuple")
        object.__setattr__(
            self,
            "records",
            tuple(sorted(self.records, key=lambda item: item.dispatch_key)),
        )


def _claims_issue(issue: CandidateIssue, external_id: str) -> bool:
    value = external_id.strip()
    url_key = _issue_url_key(value)
    if url_key is not None:
        return url_key == _issue_url_key(issue.url)
    match = _ISSUE_REFERENCE_RE.fullmatch(value)
    return match is not None and int(match.group("number")) == issue.number


def unclaimed_candidate_issues(
    candidates: tuple[CandidateIssue, ...],
    *,
    external_ids: tuple[str, ...],
) -> tuple[CandidateIssue, ...]:
    """Exclude candidates occupied by nonterminal registry external IDs."""

    references = tuple(
        item for item in external_ids if type(item) is str and item.strip()
    )
    return tuple(
        issue
        for issue in sorted(candidates, key=lambda item: item.dispatch_key)
        if not any(_claims_issue(issue, reference) for reference in references)
    )
