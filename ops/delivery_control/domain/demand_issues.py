"""Raw GitHub Issue demand facts and deterministic disposition projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from .candidate_issues import CANDIDATE_ISSUE_LABEL, CandidateIssue, CandidateSpec
from .observations import InventoryProblem


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

    def __post_init__(self) -> None:
        if type(self.number) is not int or self.number <= 0:
            raise ValueError("Issue number must be a positive integer")
        for name in ("url", "node_id", "title", "body", "body_sha256", "reason"):
            value = getattr(self, name)
            if type(value) is not str or (
                name in {"url", "node_id"}
                and (not value.strip() or any(ord(character) < 32 for character in value))
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

    @property
    def candidate(self) -> CandidateIssue | None:
        if (
            self.candidate_spec is None
            or CANDIDATE_ISSUE_LABEL not in self.labels
        ):
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
            not isinstance(item, DemandIssueSourceEntry)
            for item in self.source_entries
        ):
            raise TypeError("Issue source entries must be DemandIssueSourceEntry values")
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
        return len(self.source_entries) + sum(
            item.disposition
            in {
                IssueDisposition.TRIAGE_REQUIRED,
                IssueDisposition.LEGACY_UNMAPPED,
                IssueDisposition.SOURCE_PROBLEM,
            }
            for item in self.records
        ) + max(0, self.raw_count - represented_entries)

    @property
    def backlog_drained(self) -> bool:
        return self.complete and self.unadmitted_open_issues == 0


def issue_body_sha256(body: str) -> str:
    """Return the stable fingerprint used by admission preflight/readback."""

    if type(body) is not str:
        raise TypeError("Issue body must be text")
    return sha256(body.encode("utf-8")).hexdigest()


EMPTY_DEMAND_INVENTORY = DemandIssueInventory(records=(), raw_count=0)
