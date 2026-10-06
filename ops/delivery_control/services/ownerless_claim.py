"""Fail-closed disposal of one ownerless active registry claim.

An active claim whose owner is gone, with no worktree, PR history, handback,
remote drift, or hold, carries no recoverable work.  It still blocks Scope
admission, so it is terminalized as ``abandoned`` through the registry's
existing exact CAS transition.  Every precondition is evaluated and reported;
nothing is written unless every one holds and the caller pinned the observed
claim generation and head.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..domain.errors import (
    CompareAndSwapConflict,
    DeliveryContractError,
    DeliverySourceError,
)
from ..domain.observations import RegistrySnapshot
from ..ports.dispositions import DispositionReceiptPort
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryCommandPort, RegistryQueryPort

RECEIPT_SCHEMA = "kg.delivery.disposition.v1"
RECEIPT_KIND = "ownerless-claim-abandon"


@dataclass(frozen=True)
class DisposalCheck:
    id: str
    ok: bool | None
    detail: str


@dataclass(frozen=True)
class OwnerlessDisposalReport:
    verdict: str
    mode: str
    branch: str
    eligible: bool
    applied: bool
    checks: tuple[DisposalCheck, ...]
    lane_id: str | None = None
    claim_generation: int | None = None
    head_sha: str | None = None
    path: str | None = None
    registry_status: str | None = None
    next_step: str | None = None


def _clock() -> datetime:
    return datetime.now(tz=UTC)


class OwnerlessClaimDisposalService:
    def __init__(
        self,
        *,
        registry: RegistryQueryPort,
        registry_command: RegistryCommandPort,
        git_query: GitQueryPort,
        github: GitHubQueryPort,
        receipts: DispositionReceiptPort,
        clock: Callable[[], datetime] = _clock,
    ) -> None:
        self.registry = registry
        self.registry_command = registry_command
        self.git_query = git_query
        self.github = github
        self.receipts = receipts
        self.clock = clock

    def _find_claim(
        self, branch: str
    ) -> tuple[RegistrySnapshot | None, list[DisposalCheck]]:
        records = tuple(
            item for item in self.registry.list_records().records if item.branch == branch
        )
        active = [item for item in records if item.status == "active"]
        checks = [
            DisposalCheck(
                "claim_unique",
                bool(records) and len(active) <= 1,
                (
                    "exactly one registry claim lineage on the branch"
                    if records and len(active) <= 1
                    else f"{len(records)} registry claims, {len(active)} active on {branch}"
                ),
            ),
            DisposalCheck(
                "claim_active",
                len(active) == 1,
                (
                    "claim is active"
                    if len(active) == 1
                    else "no active claim; statuses: "
                    + (", ".join(sorted({item.status for item in records})) or "none")
                ),
            ),
        ]
        return (active[0] if len(active) == 1 else None), checks

    def _canonical_main(self) -> DisposalCheck:
        checkout = self.git_query.canonical_checkout()
        ok = checkout.branch == "main" and checkout.clean
        return DisposalCheck(
            "canonical_main_clean",
            ok,
            (
                "canonical checkout is clean on main"
                if ok
                else f"canonical checkout is on {checkout.branch!r}, "
                f"clean={checkout.clean}"
            ),
        )

    def _record_checks(
        self, record: RegistrySnapshot
    ) -> tuple[list[DisposalCheck], str]:
        local = self.git_query.local_branch_sha(record.branch)
        remote = self.git_query.remote_branch_sha(record.branch)
        head = local or record.base_sha
        checks: list[DisposalCheck] = []

        owner = (record.owner_thread_id or "").strip()
        checks.append(
            DisposalCheck(
                "owner_absent",
                not owner,
                "claim has no owner thread" if not owner else f"owner {owner!r} is bound",
            )
        )

        resolved = record.path.resolve()
        physical = [
            item
            for item in self.git_query.list_worktrees()
            if item.branch == record.branch or item.path.resolve() == resolved
        ]
        on_disk = record.path.exists()
        checks.append(
            DisposalCheck(
                "no_physical_worktree",
                not physical and not on_disk,
                (
                    "no registered worktree and no directory on disk"
                    if not physical and not on_disk
                    else "worktree still present: "
                    + ", ".join(
                        [str(item.path) for item in physical]
                        + ([str(record.path)] if on_disk else [])
                    )
                ),
            )
        )

        inventory = self.github.list_pull_requests_for_branch(record.branch)
        if inventory.problems:
            pr_check = DisposalCheck(
                "no_pr_history",
                False,
                "GitHub branch PR inventory is incomplete: "
                + "; ".join(problem.reason for problem in inventory.problems),
            )
        elif inventory.records:
            pr_check = DisposalCheck(
                "no_pr_history",
                False,
                "branch has PR history: "
                + ", ".join(f"#{pr.number}:{pr.state}" for pr in inventory.records),
            )
        else:
            pr_check = DisposalCheck("no_pr_history", True, "branch has no PR history")
        checks.append(pr_check)

        has_handback = record.handback_valid or record.handed_back_sha is not None
        checks.append(
            DisposalCheck(
                "no_valid_handback",
                not has_handback,
                "claim carries no handback"
                if not has_handback
                else "claim carries a handback; recover or discard it instead",
            )
        )

        allowed_remote = {record.base_sha, head}
        drift = remote is not None and remote not in allowed_remote
        checks.append(
            DisposalCheck(
                "no_remote_drift",
                not drift,
                (
                    "remote branch is absent or matches the claim"
                    if not drift
                    else f"remote branch {remote} differs from claim head {head}"
                ),
            )
        )

        holds = tuple(record.handback_initial_holds)
        checks.append(
            DisposalCheck(
                "no_hold",
                not holds,
                "no hold recorded" if not holds else "holds: " + ", ".join(holds),
            )
        )
        return checks, head

    def dispose(
        self,
        *,
        branch: str,
        apply: bool,
        expected_claim_generation: int | None = None,
        expected_head_sha: str | None = None,
        operator: str | None = None,
        reason: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> OwnerlessDisposalReport:
        say = progress or (lambda _message: None)
        if apply:
            if not (operator and operator.strip()) or not (reason and reason.strip()):
                raise DeliveryContractError(
                    "--apply requires a non-empty --operator and --reason"
                )
            if expected_claim_generation is None or not expected_head_sha:
                raise DeliveryContractError(
                    "--apply requires --expected-claim-generation and "
                    "--expected-head-sha from a prior dry-run"
                )
        say(f"inspecting registry claim for {branch}")
        record, checks = self._find_claim(branch)
        checks.insert(0, self._canonical_main())
        head: str | None = None
        if record is not None:
            say("evaluating disposal preconditions")
            record_checks, head = self._record_checks(record)
            checks.extend(record_checks)
            if apply:
                checks.append(
                    DisposalCheck(
                        "expected_claim_generation",
                        expected_claim_generation == record.claim_generation,
                        f"observed {record.claim_generation}, "
                        f"pinned {expected_claim_generation}",
                    )
                )
                checks.append(
                    DisposalCheck(
                        "expected_head_sha",
                        expected_head_sha == head,
                        f"observed {head}, pinned {expected_head_sha}",
                    )
                )
        else:
            checks.extend(
                DisposalCheck(item, None, "not evaluated: no unique active claim")
                for item in (
                    "owner_absent",
                    "no_physical_worktree",
                    "no_pr_history",
                    "no_valid_handback",
                    "no_remote_drift",
                    "no_hold",
                )
            )
        eligible = all(item.ok is True for item in checks)
        base = {
            "mode": "apply" if apply else "dry-run",
            "branch": branch,
            "checks": tuple(checks),
            "lane_id": record.lane_id if record else None,
            "claim_generation": record.claim_generation if record else None,
            "head_sha": head,
            "path": str(record.path) if record else None,
        }
        if not eligible:
            return OwnerlessDisposalReport(
                verdict="refused", eligible=False, applied=False, **base
            )
        assert record is not None and head is not None
        if not apply:
            return OwnerlessDisposalReport(
                verdict="eligible",
                eligible=True,
                applied=False,
                next_step=(
                    "re-run with --apply --expected-claim-generation "
                    f"{record.claim_generation} --expected-head-sha {head} "
                    "--operator <name> --reason <text>"
                ),
                **base,
            )
        assert operator is not None and reason is not None
        receipt_body = {
            "schema": RECEIPT_SCHEMA,
            "kind": RECEIPT_KIND,
            "operator": operator.strip(),
            "reason": reason.strip(),
            "branch": branch,
            "lane_id": record.lane_id,
            "claim_generation": record.claim_generation,
            "base_sha": record.base_sha,
            "head_sha": head,
            "path": str(record.path),
            "checks": [
                {"id": item.id, "ok": item.ok, "detail": item.detail} for item in checks
            ],
        }
        say("writing intent receipt")
        self.receipts.append(
            {**receipt_body, "phase": "intent", "at": self.clock().isoformat()}
        )
        try:
            say("terminalizing claim through registry CAS")
            self.registry_command.resolve(
                record.lane_id,
                "abandoned",
                expected_claim_generation=record.claim_generation,
                expected_branch=record.branch,
                expected_path=str(record.path),
                expected_head_sha=head,
            )
            final = self.registry.find_exact_claim(
                lane_id=record.lane_id,
                branch=record.branch,
                path=Path(record.path),
                claim_generation=record.claim_generation,
            )
            if final is None or final.status != "abandoned":
                raise CompareAndSwapConflict(
                    "abandoned registry transition did not read back exactly"
                )
        except (DeliverySourceError, OSError) as error:
            try:
                self.receipts.append(
                    {
                        **receipt_body,
                        "phase": "failed",
                        "error": str(error),
                        "at": self.clock().isoformat(),
                    }
                )
            except (DeliverySourceError, OSError):
                pass
            raise
        self.receipts.append(
            {
                **receipt_body,
                "phase": "committed",
                "registry_status": final.status,
                "at": self.clock().isoformat(),
            }
        )
        return OwnerlessDisposalReport(
            verdict="applied",
            eligible=True,
            applied=True,
            registry_status=final.status,
            next_step=(
                "run cleanup-abandoned --branch "
                f"{branch} if a residual branch ref remains"
            ),
            **base,
        )


__all__ = [
    "DisposalCheck",
    "OwnerlessClaimDisposalService",
    "OwnerlessDisposalReport",
]
