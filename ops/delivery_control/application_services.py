"""User-command facade over deterministic delivery services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from .application_ports import (
    DeliveryGitHubPort,
    DeliveryGitPort,
    DeliveryRegistryPort,
    _utc_now,
)
from .controller.capacity import decide_capacity
from .controller.dogfood import (
    DEFAULT_DOGFOOD_PROFILE,
    DogfoodProfile,
    assess_dogfood_readiness,
)
from .controller.metrics import measure_merge_cadence, measure_pipeline
from .controller.runtime_watchdog import evaluate_runtime_watchdog
from .controller.worktree_boundary import partition_worktrees
from .domain.branch_lifecycle import BranchDisposition
from .domain.branch_content import (
    BRANCH_REVIEW_PAGE_LIMIT,
    BranchContentEvidence,
    BranchContentReviewItem,
    BranchContentReviewPlan,
)
from .domain.branch_lifecycle import BranchSide
from .domain import errors, models, observations, states
from .domain.candidate_issues import CandidateSpec
from .domain.demand_issues import IssueDisposition
from .domain.runtime_models import RuntimeReceipt, WatchdogAction
from .domain.unreachable_commits import (
    EMPTY_UNREACHABLE_COMMIT_INVENTORY,
    UnreachableCommitInventory,
)
from .ports.github import GitHubIssueCommandPort
from .ports.runtime import (
    AgentRuntimePort,
    RuntimeReceiptPort,
    RuntimeReceiptStorePort,
)
from .ports.telemetry import TelemetryStorePort
from .services import (
    abandon,
    abandoned_handback,
    branch_content,
    branch_audit,
    cleanup,
    inspect,
    legacy_cleanup,
    metadata,
    queue,
    required_repair,
    orphan_branch,
    sync_main,
    telemetry_operations,
    unregistered_branch,
    unreachable_commit,
)
from .services import holds as hold_services
from .services.issue_admission import assert_candidate_scope_available
from .services.issue_triage import build_triage_plan
from .services.pr_contract import parse_pull_request_body
from .services.publish import PublishService, receipt_from_active_claim
from .services.publish_preflight import PublishPreflightService


_REVIEWABLE_LOCAL_ORPHAN_BLOCKERS = frozenset(
    {"orphan branch tip is not an ancestor of live origin/main"}
)


def _is_reviewable_local_orphan(action: object) -> bool:
    """Keep owner/remote/source blockers out of the content-review queue."""

    preflight = getattr(action, "orphan_preflight", None)
    blockers = getattr(preflight, "blockers", ()) if preflight is not None else ()
    return (
        getattr(action, "side", None) is BranchSide.LOCAL
        and getattr(action, "category", None) == "local_orphan_blocked"
        and getattr(action, "review_command", None) is not None
        and preflight is not None
        and not preflight.eligible
        and set(blockers) == _REVIEWABLE_LOCAL_ORPHAN_BLOCKERS
    )


def _branch_review_next_step(action: object, content: BranchContentEvidence) -> str:
    """Connect reviewed unlanded content to its explicit discard lifecycle.

    The review plan remains read-only: this guidance exposes the exact
    fingerprint and required confirmation inputs, but never authorizes or
    performs deletion.  Keeping the decision here prevents a complete content
    packet from ending in an unbounded "review" state.
    """

    if content.complete and content.unlanded:
        branch = getattr(action, "branch")
        return (
            "review unlanded content; if explicit discard is chosen, invoke "
            "discard-unregistered-branch with "
            f"branch={branch}, expected-head-sha={content.head_sha}, "
            f"expected-content-fingerprint={content.change_fingerprint}; "
            "operator, reason, and --confirm-unmerged are required; "
            "no automatic deletion"
        )
    return str(getattr(action, "next_step"))


@dataclass(frozen=True)
class DeliveryApplication:
    repo: Path
    git: DeliveryGitPort
    github: DeliveryGitHubPort
    registry: DeliveryRegistryPort
    runtime: AgentRuntimePort
    telemetry: TelemetryStorePort
    clock: Callable[[], datetime] = _utc_now

    def inspect(self, *, supervision_worktree_paths: tuple[Path, ...] = ()) -> object:
        return inspect.InspectService(
            registry=self.registry,
            git=self.git,
            github=self.github,
            runtime=self.runtime,
        ).inspect(supervision_worktree_paths=supervision_worktree_paths)

    def issue_inventory(self) -> object:
        """Return the complete raw Issue projection without mutation."""

        return self.inspect().demand_issues

    def branch_audit(
        self,
        *,
        supervision_worktree_paths: tuple[Path, ...] = (),
    ) -> object:
        """Return one deterministic action for every observed branch ref."""

        inventory = self.inspect(supervision_worktree_paths=supervision_worktree_paths)
        orphan_service = orphan_branch.OrphanBranchDiscardService(
            registry=self.registry,
            git_query=self.git,
            git_command=self.git,
            github=self.github,
        )
        orphan_assets = tuple(
            asset
            for asset in inventory.branch_lifecycle.local
            if asset.disposition is BranchDisposition.ORPHAN_LOCAL_RECONCILE
        )
        branch_history_snapshot = None
        list_pull_requests_for_branches = getattr(
            self.github, "list_pull_requests_for_branches", None
        )
        if orphan_assets and callable(list_pull_requests_for_branches):
            try:
                branch_history_snapshot = list_pull_requests_for_branches(
                    tuple(asset.branch for asset in orphan_assets)
                )
            except errors.DeliverySourceError as error:
                branch_history_snapshot = observations.PullRequestInventory(
                    records=(),
                    problems=(
                        observations.InventoryProblem(
                            "github", "branch-history-snapshot", str(error)
                        ),
                    ),
                )
        orphan_preflights = orphan_service.preflight_many(
            branches=tuple((asset.branch, asset.sha) for asset in orphan_assets),
            pr_history=branch_history_snapshot,
        )
        unreachable_commits = EMPTY_UNREACHABLE_COMMIT_INVENTORY
        unreachable_inventory = getattr(self.git, "unreachable_commit_inventory", None)
        if callable(unreachable_inventory):
            try:
                unreachable_commits = unreachable_inventory()
            except errors.DeliverySourceError as error:
                unreachable_commits = UnreachableCommitInventory(
                    problems=(str(error),),
                    complete=False,
                )
        return branch_audit.build_branch_audit(
            inventory,
            orphan_preflights=orphan_preflights,
            unreachable_commits=unreachable_commits,
        )

    def branch_inspect(
        self,
        *,
        branch: str,
        expected_head_sha: str | None = None,
    ) -> object:
        """Return one bounded content packet for an unlanded local branch."""

        main_sha = self.git.origin_main_sha()
        evidence = branch_content.BranchContentService(git=self.git).inspect(
            branch=branch,
            base_sha=main_sha,
        )
        if expected_head_sha is not None and evidence.complete:
            if evidence.head_sha != expected_head_sha:
                raise errors.PolicyViolation(
                    "branch content HEAD differs from expected inspection SHA"
                )
        return evidence

    def unreachable_commit_inspect(
        self,
        *,
        commit_sha: str,
        max_paths: int = 200,
    ) -> object:
        """Return bounded evidence without creating a ref or delivery claim."""

        return unreachable_commit.UnreachableCommitService(git=self.git).inspect(
            commit_sha,
            max_paths=max_paths,
        )

    def branch_review_plan(
        self,
        *,
        offset: int = 0,
        limit: int = BRANCH_REVIEW_PAGE_LIMIT,
    ) -> object:
        """Page blocked local-orphan content for review without mutation."""

        if offset < 0:
            raise errors.PolicyViolation("branch review offset must be non-negative")
        if limit <= 0 or limit > 20:
            raise errors.PolicyViolation("branch review limit must be between 1 and 20")
        audit = self.branch_audit()
        candidates = tuple(
            sorted(
                (
                    action
                    for action in audit.actions
                    if _is_reviewable_local_orphan(action)
                ),
                key=lambda action: (action.branch, action.sha),
            )
        )
        selected = (
            candidates[offset : offset + limit]
            if audit.live_main_sha is not None
            else ()
        )
        contents = {}
        if audit.live_main_sha is not None and selected:
            contents = branch_content.BranchContentService(git=self.git).inspect_many(
                branches=tuple(action.branch for action in selected),
                base_sha=audit.live_main_sha,
            )
            contents = {
                branch: branch_content.BranchContentService.compact_for_review(evidence)
                for branch, evidence in contents.items()
            }

        def build_review_item(action: object) -> BranchContentReviewItem:
            content = contents.get(
                action.branch,
                branch_content.BranchContentService._error(
                    branch=action.branch,
                    base_sha=audit.live_main_sha or "0" * 40,
                    error="branch content was not inspected",
                ),
            )
            return BranchContentReviewItem(
                schema="kg.delivery.branch-content-review-item.v1",
                branch=action.branch,
                expected_head_sha=action.sha,
                preflight_eligible=action.orphan_preflight.eligible,
                preflight_blockers=tuple(sorted(action.orphan_preflight.blockers)),
                content=content,
                next_step=_branch_review_next_step(action, content),
            )

        items = tuple(build_review_item(action) for action in selected)
        reviewed_count = offset + len(items)
        remaining_count = max(len(candidates) - reviewed_count, 0)
        return BranchContentReviewPlan(
            schema="kg.delivery.branch-content-review-plan.v1",
            live_main_sha=audit.live_main_sha,
            audit_complete=audit.complete,
            complete=(
                audit.complete
                and audit.live_main_sha is not None
                and remaining_count == 0
                and all(item.content.complete for item in items)
            ),
            offset=offset,
            limit=limit,
            total_candidates=len(candidates),
            reviewed_count=reviewed_count,
            remaining_count=remaining_count,
            source_problem_count=len(audit.source_problem_actions),
            items=items,
        )

    def discard_unregistered_branch(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        expected_content_fingerprint: str,
        operator: str,
        reason: str,
        confirm_unmerged: bool,
    ) -> object:
        """Discard only one explicitly reviewed unlanded local-only branch."""

        return unregistered_branch.UnregisteredBranchDiscardService(
            registry=self.registry,
            git_query=self.git,
            git_content=self.git,
            git_command=self.git,
            github=self.github,
        ).discard(
            branch=branch,
            expected_head_sha=expected_head_sha,
            expected_content_fingerprint=expected_content_fingerprint,
            operator=operator,
            reason=reason,
            confirm_unmerged=confirm_unmerged,
        )

    def triage_plan(self) -> object:
        """Return deterministic Issue IDs and next actions without mutation."""

        return build_triage_plan(self.inspect().demand_issues)

    def admit_candidate(
        self,
        *,
        issue_number: int,
        expected_updated_at: datetime,
        expected_body_sha256: str,
        spec: CandidateSpec,
        triage_reason: str,
        operator: str,
    ) -> object:
        """Admit exactly one triaged Issue through the GitHub command port."""

        inventory = self.inspect().demand_issues
        matches = [item for item in inventory.records if item.number == issue_number]
        if len(matches) != 1:
            raise errors.PolicyViolation(
                f"Issue #{issue_number} is not present in the complete raw inventory"
            )
        issue = matches[0]
        if issue.disposition is not IssueDisposition.TRIAGE_REQUIRED:
            raise errors.PolicyViolation(
                f"Issue #{issue_number} disposition is {issue.disposition.value}, "
                "not triage_required"
            )
        assert_candidate_scope_available(
            scope=spec.scope,
            demand_issues=inventory.records,
            registry=self.registry.list_collision_claims(),
            pull_requests=self.github.list_open_pull_requests(),
            changed_paths=self.github.changed_paths,
        )
        if not isinstance(self.github, GitHubIssueCommandPort):
            raise errors.PolicyViolation(
                "GitHub adapter does not expose one-Issue admission capability"
            )
        return self.github.admit_candidate(
            issue_number=issue_number,
            expected_updated_at=expected_updated_at,
            expected_body_sha256=expected_body_sha256,
            spec=spec,
            triage_reason=triage_reason,
            operator=operator,
        )

    def metrics(
        self,
        *,
        now: datetime | None = None,
        supervision_worktree_paths: tuple[Path, ...] = (),
    ) -> object:
        observed_at = now or self.clock()
        telemetry = self._operation_telemetry().rolling(now=observed_at)
        inventory = self.inspect(supervision_worktree_paths=supervision_worktree_paths)
        return measure_pipeline(
            inventory,
            telemetry=telemetry,
            now=observed_at,
            excluded_worktree_paths=supervision_worktree_paths,
        )

    def plan(
        self,
        *,
        now: datetime | None = None,
        supervision_worktree_paths: tuple[Path, ...] = (),
    ) -> object:
        observed_at = now or self.clock()
        metrics = self.metrics(
            now=observed_at,
            supervision_worktree_paths=supervision_worktree_paths,
        )
        cadence = measure_merge_cadence(
            self.github.recent_merge_times(), now=observed_at
        )
        return {
            "metrics": metrics,
            "cadence": cadence,
            "decision": decide_capacity(metrics, cadence),
        }

    def watchdog(
        self,
        *,
        supervisor_thread_id: str,
        now: datetime | None = None,
        stale_after_seconds: int = 300,
    ) -> object:
        """Return a liveness decision; the caller owns Codex thread dispatch."""

        if not isinstance(self.runtime, RuntimeReceiptPort):
            raise errors.PolicyViolation(
                "runtime status source has no structured liveness receipt"
            )
        observed_at = now or self.clock()
        return evaluate_runtime_watchdog(
            self.runtime.runtime_receipt(supervisor_thread_id),
            now=observed_at,
            stale_after_seconds=stale_after_seconds,
        )

    def watchdog_claim(
        self,
        *,
        supervisor_thread_id: str,
        now: datetime | None = None,
        stale_after_seconds: int = 300,
    ) -> object:
        """Reserve one stale wake; an external scheduler still performs dispatch."""

        if not isinstance(self.runtime, RuntimeReceiptStorePort):
            raise errors.PolicyViolation(
                "watchdog wake claims require --runtime-status-file"
            )
        observed_at = now or self.clock()
        receipt = self.runtime.runtime_receipt(supervisor_thread_id)
        decision = evaluate_runtime_watchdog(
            receipt,
            now=observed_at,
            stale_after_seconds=stale_after_seconds,
        )
        if decision.action is not WatchdogAction.WAKE or decision.wake_id is None:
            return decision
        try:
            self.runtime.claim_wake(
                thread_id=supervisor_thread_id,
                wake_id=decision.wake_id,
                now=observed_at,
                expected_cycle_id=receipt.cycle_id if receipt is not None else None,
            )
        except errors.CompareAndSwapConflict:
            current = self.runtime.runtime_receipt(supervisor_thread_id)
            return evaluate_runtime_watchdog(
                current,
                now=observed_at,
                stale_after_seconds=stale_after_seconds,
            )
        return replace(decision, wake_claimed=True)

    def write_runtime_receipt(
        self,
        *,
        receipt: RuntimeReceipt,
        expected_cycle_id: str | None = None,
    ) -> RuntimeReceipt:
        """Write caller-owned liveness evidence, never dispatch an agent."""

        if not isinstance(self.runtime, RuntimeReceiptStorePort):
            raise errors.PolicyViolation(
                "runtime receipt writes require --runtime-status-file"
            )
        return self.runtime.write(
            receipt,
            expected_cycle_id=expected_cycle_id,
        )

    def dogfood_preflight(
        self,
        *,
        now: datetime | None = None,
        profile: DogfoodProfile = DEFAULT_DOGFOOD_PROFILE,
        supervision_worktree_paths: tuple[Path, ...] = (),
    ) -> object:
        observed_at = now or self.clock()
        checkout = self.git.canonical_checkout()
        origin_main_sha = self.git.origin_main_sha()
        physical_worktrees = self.git.list_worktrees()
        worktree_partition = partition_worktrees(
            physical_worktrees,
            canonical_path=self.repo,
            supervision_paths=supervision_worktree_paths,
        )
        main_protected = self.github.branch_is_protected("main")
        required_status_contexts = (
            self.github.required_status_contexts("main") if main_protected else ()
        )
        metrics = self.metrics(
            now=observed_at,
            supervision_worktree_paths=supervision_worktree_paths,
        )
        cadence = measure_merge_cadence(
            self.github.recent_merge_times(),
            now=observed_at,
            window=timedelta(seconds=profile.promotion_observation_seconds),
        )
        return assess_dogfood_readiness(
            local_main_sha=self.git.local_main_sha(),
            origin_main_sha=origin_main_sha,
            canonical_branch=checkout.branch,
            canonical_clean=checkout.clean,
            main_protected=main_protected,
            required_status_contexts=required_status_contexts,
            merge_queue_enabled=self.github.merge_queue_enabled("main"),
            physical_worktree_count=len(worktree_partition.delivery),
            canonical_worktree_present=(worktree_partition.canonical_count == 1),
            metrics=metrics,
            cadence=cadence,
            profile=profile,
            supervision_worktree_count=len(worktree_partition.supervision),
            total_physical_worktree_count=len(physical_worktrees),
        )

    def receipt(self, lane_id: str) -> models.HandbackReceipt:
        receipt, _ = self._receipt_and_record(lane_id)
        return receipt

    def _receipt_and_record(
        self, lane_id: str
    ) -> tuple[models.HandbackReceipt, observations.RegistrySnapshot]:
        record = self.registry.get(lane_id)
        if record is None:
            raise errors.PolicyViolation(
                f"no unique active registry record for {lane_id}"
            )
        snapshot = self.git.inspect_worktree(record.path, record.base_sha)
        return receipt_from_active_claim(record, snapshot), record

    def publish(self, *, lane_id: str, title: str) -> object:
        receipt, record = self._receipt_and_record(lane_id)
        publication = PublishService(
            preflight=PublishPreflightService(
                registry=self.registry,
                git=self.git,
                github=self.github,
            ),
            git=self.git,
            github_query=self.github,
            github_command=self.github,
            github_workflow=self.github,
        ).publish(receipt=receipt, title=title)
        published_base = self.record_published_base(publication.pull_request.number)
        warnings = self._operation_telemetry().after_publish(
            receipt=receipt,
            record=record,
            publication=publication,
        )
        release = self._cleanup().release_after_publish(
            receipt=receipt,
            pull_request_number=publication.pull_request.number,
        )
        return {
            "receipt": receipt,
            "publication": publication,
            "published_base": published_base,
            "release": release,
            "telemetry_warnings": warnings,
        }

    def record_published_base(self, pull_request_number: int) -> object:
        """Persist the exact PR target OID without rewriting handback provenance."""

        before = self.github.get_pull_request(pull_request_number)
        receipt = parse_pull_request_body(before.body)
        record = self.registry.find_exact_claim(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            claim_generation=receipt.claim_generation,
        )
        if record is None:
            raise errors.PolicyViolation(
                "published PR has no exact registry claim for base recording"
            )
        if (
            record.status not in {"active", "cleanup_pending", "published"}
            or record.base_sha != receipt.base_sha
            or record.scope != receipt.scope
            or record.owner_thread_id != receipt.owner_thread_id
            or record.handed_back_sha != receipt.head_sha
            or record.handback_claim_generation != receipt.claim_generation
            or not record.handback_valid
            or record.handback_digest != receipt.content_digest
            or record.handback_origin_main_sha != receipt.origin_main_sha
        ):
            raise errors.PolicyViolation(
                "published PR does not map to one exact typed registry handback"
            )
        branch_inventory = self.github.list_pull_requests_for_branch(receipt.branch)
        if branch_inventory.problems or len(branch_inventory.records) != 1:
            raise errors.PolicyViolation(
                "published branch does not map to one unique PR"
            )
        mapped = branch_inventory.records[0]
        if (
            mapped.number != before.number
            or mapped.state != "OPEN"
            or mapped.draft
            or mapped.base_branch != "main"
            or mapped.branch != receipt.branch
            or mapped.base_sha != before.base_sha
            or mapped.head_sha != receipt.head_sha
            or mapped.body != before.body
            or tuple(sorted(self.github.changed_paths(before.number)))
            != tuple(sorted(receipt.scope.paths))
        ):
            raise errors.PolicyViolation(
                "published PR tuple changed before base recording"
            )
        self.registry.record_published_base(
            lane_id=receipt.lane_id,
            expected_claim_generation=receipt.claim_generation,
            expected_branch=receipt.branch,
            expected_path=receipt.worktree_path,
            expected_head_sha=receipt.head_sha,
            expected_handback_base_sha=receipt.base_sha,
            published_base_sha=before.base_sha,
        )
        after = self.github.get_pull_request(pull_request_number)
        final_record = self.registry.find_exact_claim(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            claim_generation=receipt.claim_generation,
        )
        if (
            after.base_sha != before.base_sha
            or final_record is None
            or final_record.published_base_sha != before.base_sha
        ):
            raise errors.PolicyViolation(
                "published PR base readback changed during registry recording"
            )
        return {
            "pull_request": after,
            "published_base_sha": final_record.published_base_sha,
            "claim_generation": final_record.claim_generation,
        }

    def release_published(self, pull_request_number: int) -> object:
        receipt = self._receipt_from_pr(pull_request_number)
        return self._cleanup().release_after_publish(
            receipt=receipt, pull_request_number=pull_request_number
        )

    def enqueue(
        self,
        *,
        pull_request_number: int,
        holds: frozenset[states.HoldKind] = frozenset(),
    ) -> object:
        receipt = self._receipt_from_pr(pull_request_number)
        record = self._record_for_receipt(receipt)
        result = queue.QueueService(
            registry=self.registry,
            git=self.git,
            github_query=self.github,
            github_command=self.github,
        ).enqueue(
            receipt=receipt,
            pull_request_number=pull_request_number,
            holds=holds,
        )
        warnings = self._operation_telemetry().after_enqueue(
            receipt=receipt,
            record=record,
            result=result,
        )
        return {"queue": result, "telemetry_warnings": warnings}

    def reconcile_holds(
        self,
        *,
        pull_request_number: int,
        holds: frozenset[states.HoldKind],
        clear_all: bool,
    ) -> object:
        return hold_services.HoldService(
            query=self.github, command=self.github
        ).reconcile(
            number=pull_request_number,
            holds=holds,
            clear_all=clear_all,
        )

    def repair_metadata(self, pull_request_number: int) -> object:
        return metadata.MetadataRepairService(
            registry=self.registry,
            query=self.github,
            command=self.github,
        ).repair(pull_request_number)

    def trigger_required(self, pull_request_number: int) -> object:
        return required_repair.RequiredRepairService(
            registry=self.registry,
            query=self.github,
            command=self.github,
        ).trigger(pull_request_number)

    def cleanup_merged(self, pull_request_number: int) -> object:
        pull_request = self.github.get_pull_request(pull_request_number)
        if "<!-- kg.delivery.receipt.v1" not in pull_request.body:
            return self._legacy_cleanup().cleanup_merged_pr(pull_request_number)
        receipt = parse_pull_request_body(pull_request.body)
        record = self._record_for_receipt(receipt)
        result = self._cleanup().finalize_merged(
            receipt=receipt, pull_request_number=pull_request_number
        )
        warnings = self._operation_telemetry().after_cleanup(
            pull_request=pull_request,
            was_already_terminal=record.status == "merged",
        )
        return {"cleanup": result, "telemetry_warnings": warnings}

    def abandon_pr(self, pull_request_number: int) -> object:
        pull_request = self.github.get_pull_request(pull_request_number)
        if "<!-- kg.delivery.receipt.v1" not in pull_request.body:
            return self._legacy_cleanup().abandon_open_pr(pull_request_number)
        return abandon.AbandonService(
            registry_query=self.registry,
            registry_command=self.registry,
            git_query=self.git,
            git_command=self.git,
            github_query=self.github,
            github_command=self.github,
        ).abandon(pull_request_number=pull_request_number)

    def cleanup_abandoned(self, branch: str) -> object:
        return self._legacy_cleanup().cleanup_abandoned_branch(branch)

    def discard_abandoned_handback(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> object:
        return abandoned_handback.AbandonedHandbackDiscardService(
            registry_query=self.registry,
            registry_command=self.registry,
            git_query=self.git,
            git_command=self.git,
            github=self.github,
        ).discard(
            branch=branch,
            expected_head_sha=expected_head_sha,
            operator=operator,
            reason=reason,
        )

    def discard_orphan_branch(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> object:
        return orphan_branch.OrphanBranchDiscardService(
            registry=self.registry,
            git_query=self.git,
            git_command=self.git,
            github=self.github,
        ).discard(
            branch=branch,
            expected_head_sha=expected_head_sha,
            operator=operator,
            reason=reason,
        )

    def sync_main(self) -> object:
        result = sync_main.MainSyncService(
            canonical_path=self.repo,
            query=self.git,
            command=self.git,
        ).sync()
        warnings = self._operation_telemetry().after_sync(result)
        return {"sync": result, "telemetry_warnings": warnings}

    def _receipt_from_pr(self, number: int) -> models.HandbackReceipt:
        return parse_pull_request_body(self.github.get_pull_request(number).body)

    def _record_for_receipt(
        self, receipt: models.HandbackReceipt
    ) -> observations.RegistrySnapshot:
        record = self.registry.find_exact_claim(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            claim_generation=receipt.claim_generation,
        )
        if record is None:
            raise errors.PolicyViolation("typed receipt has no exact registry claim")
        return record

    def _operation_telemetry(self) -> telemetry_operations.OperationTelemetry:
        return telemetry_operations.OperationTelemetry(
            store=self.telemetry,
            github=self.github,
            git=self.git,
            clock=self.clock,
        )

    def _cleanup(self) -> cleanup.CleanupService:
        return cleanup.CleanupService(
            registry_query=self.registry,
            registry_command=self.registry,
            git_query=self.git,
            git_command=self.git,
            github=self.github,
        )

    def _legacy_cleanup(self) -> legacy_cleanup.LegacyTerminalCleanupService:
        return legacy_cleanup.LegacyTerminalCleanupService(
            registry=self.registry,
            git_query=self.git,
            git_command=self.git,
            github_query=self.github,
            github_command=self.github,
        )
