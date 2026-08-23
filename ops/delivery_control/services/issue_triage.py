"""Deterministic read-only Issue triage plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain.demand_issues import DemandIssue, DemandIssueInventory, IssueDisposition

_ORDER = {
    IssueDisposition.SOURCE_PROBLEM: 0,
    IssueDisposition.SECURITY_HOLD: 0,
    IssueDisposition.TRIAGE_REQUIRED: 1,
    IssueDisposition.DISPATCHABLE_CANDIDATE: 2,
    IssueDisposition.OWNER_BOUND: 3,
    IssueDisposition.PUBLISHED_PR: 3,
    # Terminal history is evidence to verify and clean, not a dispatch lane.
    # Keep it after recoverable legacy/blocked work so triage follows the
    # delivery pipeline rather than jumping to historical cleanup first.
    IssueDisposition.TERMINAL_HISTORY: 7,
    IssueDisposition.LEGACY_UNMAPPED: 5,
    IssueDisposition.BLOCKED: 6,
}


@dataclass(frozen=True)
class TriagePlanItem:
    number: int
    url: str
    disposition: IssueDisposition
    labels: tuple[str, ...]
    reason: str
    next_action: str
    required_evidence: tuple[str, ...]
    body_sha256: str
    updated_at: datetime | None


def _next_action(issue: DemandIssue) -> str:
    return {
        IssueDisposition.SECURITY_HOLD: "preserve_hold_and_route_security_clearance",
        IssueDisposition.TRIAGE_REQUIRED: "review_scope_acceptance_and_admit_or_block",
        IssueDisposition.DISPATCHABLE_CANDIDATE: "dispatch_issue_solver_when_capacity_allows",
        IssueDisposition.OWNER_BOUND: "route_original_owner_handback_or_reanchor",
        IssueDisposition.PUBLISHED_PR: "let_pi_process_pr_and_release_local_assets",
        IssueDisposition.LEGACY_UNMAPPED: "reconcile_legacy_history_without_takeover",
        IssueDisposition.BLOCKED: "preserve_exact_blocker_and_recover_owner",
        IssueDisposition.SOURCE_PROBLEM: "repair_source_contract_or_mark_unknown",
        IssueDisposition.TERMINAL_HISTORY: "verify_terminal_proof_and_cleanup",
    }[issue.disposition]


_REQUIRED_EVIDENCE: dict[IssueDisposition, tuple[str, ...]] = {
    IssueDisposition.SOURCE_PROBLEM: (
        "raw_issue_payload",
        "source_problem",
        "issue_fingerprint",
    ),
    IssueDisposition.SECURITY_HOLD: (
        "hold_evidence",
        "security_clearance",
        "issue_fingerprint",
    ),
    IssueDisposition.TRIAGE_REQUIRED: (
        "scope_acceptance",
        "severity_priority",
        "collision_check",
        "hold_clearance",
        "issue_fingerprint",
    ),
    IssueDisposition.DISPATCHABLE_CANDIDATE: (
        "candidate_contract",
        "exact_scope",
        "acceptance",
        "collision_check",
        "hold_clearance",
        "issue_fingerprint",
    ),
    IssueDisposition.OWNER_BOUND: (
        "owner_identity",
        "registry_claim",
        "exact_scope",
        "handback_or_reanchor",
        "issue_fingerprint",
    ),
    IssueDisposition.PUBLISHED_PR: (
        "owner_identity",
        "registry_receipt",
        "published_pr",
        "remote_head_readback",
        "local_asset_release",
        "issue_fingerprint",
    ),
    IssueDisposition.LEGACY_UNMAPPED: (
        "legacy_history",
        "migration_disposition",
        "owner_or_terminal_evidence",
        "issue_fingerprint",
    ),
    IssueDisposition.BLOCKED: (
        "exact_blocker",
        "owner_or_host_reachability",
        "scope_or_remote_readback",
        "issue_fingerprint",
    ),
    IssueDisposition.TERMINAL_HISTORY: (
        "terminal_history_mapping",
        "terminal_proof",
        "cleanup_readback",
        "issue_fingerprint",
    ),
}


def _required_evidence(issue: DemandIssue) -> tuple[str, ...]:
    """Return stable evidence requirements, never mutation authorization."""

    return _REQUIRED_EVIDENCE[issue.disposition]


def build_triage_plan(inventory: DemandIssueInventory) -> tuple[TriagePlanItem, ...]:
    """Return all parsed Issues in stable severity/disposition/number order."""

    return tuple(
        TriagePlanItem(
            number=issue.number,
            url=issue.url,
            disposition=issue.disposition,
            labels=issue.labels,
            reason=issue.reason,
            next_action=_next_action(issue),
            required_evidence=_required_evidence(issue),
            body_sha256=issue.body_sha256,
            updated_at=issue.updated_at,
        )
        for issue in sorted(
            inventory.records,
            key=lambda item: (_ORDER[item.disposition], item.number),
        )
    )
