from __future__ import annotations

import subprocess
import sys
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.adapters.telemetry_ndjson import (
    TelemetryNdjsonAdapter,
)
from delivery_control.application import (
    DeliveryApplication,
    build_application,
)
from delivery_control.controller.dogfood import DogfoodProfile
from delivery_control.controller.metrics import MergeCadence
from delivery_control.domain.branch_content import (
    BRANCH_REVIEW_PATH_LIMIT,
    BranchContentEvidence,
)
from delivery_control.domain.branch_lifecycle import BranchSide
from delivery_control.domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.demand_issues import (
    DemandIssue,
    DemandIssueInventory,
    IssueDisposition,
    issue_body_sha256,
)
from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    PullRequestInventory,
    RegistryCollisionInventory,
)
from delivery_control.services.branch_content import BranchContentService
from delivery_control.services.candidate_contract import (
    render_candidate_body,
)
from delivery_control.services.inspect import DeliveryInventory


def test_admit_candidate_retries_an_already_converged_candidate_without_mutation(
    tmp_path: Path,
) -> None:
    spec = CandidateSpec(
        severity=CandidateSeverity.P2,
        priority=1,
        scope=Scope.from_paths(modify=("ops/admission.py",)),
        acceptance=("Admission remains idempotent.",),
    )
    body = render_candidate_body(spec, original_body="Existing report")
    issue = DemandIssue(
        number=7,
        url="https://github.com/owner/repo/issues/7",
        node_id="I_7",
        title="Issue 7",
        labels=(CANDIDATE_ISSUE_LABEL,),
        body=body,
        updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
        body_sha256=issue_body_sha256(body),
        disposition=IssueDisposition.DISPATCHABLE_CANDIDATE,
        reason="Issue has an exact typed candidate contract and no active mapping",
        candidate_spec=spec,
    )

    class GitHub:
        def __init__(self) -> None:
            self.admission_calls = 0

        def list_open_pull_requests(self) -> PullRequestInventory:
            return PullRequestInventory(records=())

        def changed_paths(self, _number: int) -> tuple[str, ...]:
            return ()

        def admit_candidate(self, **_kwargs: object) -> DemandIssue:
            self.admission_calls += 1
            return issue

    github = GitHub()
    registry = Mock()
    registry.list_collision_claims.return_value = RegistryCollisionInventory(records=())
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=github,
        registry=registry,
        runtime=Mock(),
        telemetry=Mock(),
    )
    inventory = DemandIssueInventory(records=(issue,), raw_count=1)

    with patch.object(
        DeliveryApplication,
        "inspect",
        return_value=SimpleNamespace(demand_issues=inventory),
    ):
        result = application.admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2020-01-01T00:00:00+00:00"),
            expected_body_sha256="0" * 64,
            spec=spec,
            triage_reason="ignored on idempotent replay",
            operator="supervisor",
        )

    assert result is issue
    assert github.admission_calls == 1


def test_application_public_facade_preserves_constructor_contract() -> None:
    assert tuple(field.name for field in fields(DeliveryApplication)) == (
        "repo",
        "git",
        "github",
        "registry",
        "runtime",
        "telemetry",
        "clock",
    )
    assert DeliveryApplication.__dataclass_params__.frozen is True
    assert callable(DeliveryApplication.trigger_required)


def test_application_uses_co_versioned_registry_executable(tmp_path: Path) -> None:
    application = build_application(repo=tmp_path)

    assert isinstance(application.registry, RegistryCliAdapter)
    assert application.registry.script_path == OPS / "worktree_registry.py"
    assert application.registry.script_path != tmp_path / "ops" / "worktree_registry.py"
    assert (
        application.registry.state_path
        == tmp_path / ".cache" / "worktree_registry.json"
    )
    assert isinstance(application.telemetry, TelemetryNdjsonAdapter)
    assert (
        application.telemetry.path == tmp_path / ".cache" / "delivery_telemetry.ndjson"
    )
    assert application.registry.runner.target_repo == tmp_path.resolve()
    assert application.registry.runner.source_root == OPS.parent.resolve()


def test_application_uses_main_checkout_for_cleanup_from_linked_worktree(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    source_worktree = tmp_path / "source"
    repository.mkdir()
    subprocess.run(("git", "init", "-b", "main", str(repository)), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.email", "test@example.com"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.name", "Test"),
        check=True,
    )
    (repository / "README").write_text("test\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "README"), check=True)
    subprocess.run(("git", "-C", str(repository), "commit", "-m", "init"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "-b",
            "feature",
            str(source_worktree),
        ),
        check=True,
    )

    application = build_application(repo=source_worktree)

    assert application.repo == repository.resolve()
    assert application.git.repo == repository.resolve()
    assert application.registry.runner.target_repo == repository.resolve()


def test_dogfood_preflight_measures_the_configured_promotion_window(
    tmp_path: Path,
) -> None:
    git = Mock()
    git.canonical_checkout.return_value = SimpleNamespace(branch="main", clean=True)
    git.origin_main_sha.return_value = "a" * 40
    git.local_main_sha.return_value = "a" * 40
    git.list_worktrees.return_value = ()

    github = Mock()
    github.branch_is_protected.return_value = True
    github.required_status_contexts.return_value = ("required",)
    github.merge_queue_enabled.return_value = True
    github.recent_merge_times.return_value = ()

    application = DeliveryApplication(
        repo=tmp_path,
        git=git,
        github=github,
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    profile = DogfoodProfile(promotion_observation_seconds=600)
    cadence = MergeCadence(
        window_seconds=600,
        merged_count=0,
        merges_per_hour=0.0,
        p50_interval_seconds=None,
        p95_interval_seconds=None,
        seconds_since_last_merge=None,
    )

    with (
        patch.object(DeliveryApplication, "metrics", return_value=Mock()) as metrics,
        patch(
            "delivery_control.application_services.measure_merge_cadence",
            return_value=cadence,
        ) as measure,
        patch(
            "delivery_control.application_services.assess_dogfood_readiness",
            return_value=object(),
        ) as assess,
    ):
        result = application.dogfood_preflight(
            now=datetime(2026, 8, 22, tzinfo=UTC),
            profile=profile,
            supervision_worktree_paths=(Path("/supervision"),),
        )

    assert result is not None
    assert metrics.call_args.kwargs["supervision_worktree_paths"] == (
        Path("/supervision"),
    )
    assert measure.call_args.kwargs["window"] == timedelta(seconds=600)
    assert assess.call_args.kwargs["profile"] == profile


def test_plan_forwards_supervision_worktree_paths_to_metrics(tmp_path: Path) -> None:
    github = Mock()
    github.recent_merge_times.return_value = ()
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=github,
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    with (
        patch.object(DeliveryApplication, "metrics", return_value=Mock()) as metrics,
        patch(
            "delivery_control.application_services.measure_merge_cadence",
            return_value=MergeCadence(
                window_seconds=3600,
                merged_count=0,
                merges_per_hour=0.0,
                p50_interval_seconds=None,
                p95_interval_seconds=None,
                seconds_since_last_merge=None,
            ),
        ),
        patch(
            "delivery_control.application_services.decide_capacity",
            return_value=object(),
        ),
    ):
        application.plan(
            now=datetime(2026, 8, 22, tzinfo=UTC),
            supervision_worktree_paths=(Path("/supervision"),),
        )

    assert metrics.call_args.kwargs["supervision_worktree_paths"] == (
        Path("/supervision"),
    )


def test_branch_review_plan_pages_orphans_and_preserves_incomplete_audit(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    evidence = BranchContentEvidence(
        schema="kg.delivery.branch-content.v1",
        branch="backup/orphan",
        base_sha="a" * 40,
        head_sha="b" * 40,
        base_is_ancestor=False,
        ahead_commit_count=2,
        behind_commit_count=1,
        changed_paths=("feature.py",),
        changed_path_count=1,
        changed_paths_truncated=False,
        change_fingerprint="c" * 64,
        commit_subjects=("feature",),
        commit_subjects_truncated=False,
        complete=True,
    )
    action = SimpleNamespace(
        side=BranchSide.LOCAL,
        branch="backup/orphan",
        sha="b" * 40,
        category="local_orphan_blocked",
        review_command="./ops/delivery.py branch-inspect ...",
        orphan_preflight=SimpleNamespace(
            eligible=False,
            blockers=("orphan branch tip is not an ancestor of live origin/main",),
        ),
        next_step="review content",
    )
    audit = SimpleNamespace(
        actions=(action,),
        live_main_sha="a" * 40,
        complete=False,
        source_problem_actions=(object(),),
    )

    with (
        patch.object(DeliveryApplication, "branch_audit", return_value=audit),
        patch.object(
            BranchContentService,
            "inspect_many",
            return_value={"backup/orphan": evidence},
        ),
    ):
        plan = application.branch_review_plan(offset=0, limit=1)

    assert plan.schema == "kg.delivery.branch-content-review-plan.v1"
    assert plan.total_candidates == 1
    assert plan.remaining_count == 0
    assert plan.reviewable_complete is True
    assert plan.complete is False
    assert plan.items[0].content.head_sha == "b" * 40
    assert plan.items[0].next_step == (
        "review unlanded content; if explicit discard is chosen, invoke "
        "discard-unregistered-branch with branch=backup/orphan, "
        "expected-head-sha="
        + "b" * 40
        + ", expected-content-fingerprint="
        + "c" * 64
        + "; operator, reason, and --confirm-unmerged are required; "
        "no automatic deletion"
    )


def test_branch_review_plan_rejects_offset_beyond_total_candidates(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    action = SimpleNamespace(
        side=BranchSide.LOCAL,
        branch="backup/orphan",
        sha="b" * 40,
        category="local_orphan_blocked",
        review_command="./ops/delivery.py branch-inspect ...",
        orphan_preflight=SimpleNamespace(
            eligible=False,
            blockers=("orphan branch tip is not an ancestor of live origin/main",),
        ),
        next_step="review content",
    )
    audit = SimpleNamespace(
        actions=(action,),
        live_main_sha="a" * 40,
        complete=False,
        source_problem_actions=(),
    )

    with (
        patch.object(DeliveryApplication, "branch_audit", return_value=audit),
        pytest.raises(
            PolicyViolation,
            match="branch review offset exceeds total candidates",
        ),
    ):
        application.branch_review_plan(offset=2, limit=20)


def test_branch_review_plan_preserves_empty_end_page(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    action = SimpleNamespace(
        side=BranchSide.LOCAL,
        branch="backup/orphan",
        sha="b" * 40,
        category="local_orphan_blocked",
        review_command="./ops/delivery.py branch-inspect ...",
        orphan_preflight=SimpleNamespace(
            eligible=False,
            blockers=("orphan branch tip is not an ancestor of live origin/main",),
        ),
        next_step="review content",
    )
    audit = SimpleNamespace(
        actions=(action,),
        live_main_sha="a" * 40,
        complete=True,
        source_problem_actions=(),
    )

    with (
        patch.object(DeliveryApplication, "branch_audit", return_value=audit),
        patch.object(
            BranchContentService,
            "inspect_many",
            side_effect=AssertionError("empty end page must not inspect content"),
        ),
    ):
        plan = application.branch_review_plan(offset=1, limit=20)

    assert plan.offset == plan.total_candidates == plan.reviewed_count == 1
    assert plan.items == ()
    assert plan.remaining_count == 0
    assert plan.audit_complete is True
    assert plan.reviewable_complete is False
    assert plan.complete is False


def test_branch_review_plan_later_page_cannot_claim_reviewable_completion(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    evidence = BranchContentEvidence(
        schema="kg.delivery.branch-content.v1",
        branch="backup/second",
        base_sha="a" * 40,
        head_sha="c" * 40,
        base_is_ancestor=False,
        ahead_commit_count=1,
        behind_commit_count=0,
        changed_paths=("second.py",),
        changed_path_count=1,
        changed_paths_truncated=False,
        change_fingerprint="d" * 64,
        commit_subjects=("second feature",),
        commit_subjects_truncated=False,
        complete=True,
    )
    actions = tuple(
        SimpleNamespace(
            side=BranchSide.LOCAL,
            branch=branch,
            sha=head,
            category="local_orphan_blocked",
            review_command="./ops/delivery.py branch-inspect ...",
            orphan_preflight=SimpleNamespace(
                eligible=False,
                blockers=("orphan branch tip is not an ancestor of live origin/main",),
            ),
            next_step="review content",
        )
        for branch, head in (("backup/first", "b" * 40), ("backup/second", "c" * 40))
    )
    audit = SimpleNamespace(
        actions=actions,
        live_main_sha="a" * 40,
        complete=True,
        source_problem_actions=(),
    )

    with (
        patch.object(DeliveryApplication, "branch_audit", return_value=audit),
        patch.object(
            BranchContentService,
            "inspect_many",
            return_value={"backup/second": evidence},
        ),
    ):
        plan = application.branch_review_plan(offset=1, limit=1)

    assert plan.remaining_count == 0
    assert plan.reviewable_complete is False
    assert plan.complete is False


def test_branch_review_plan_bounds_path_sample_without_losing_fingerprint(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    changed_paths = tuple(
        f"file-{index:03d}.txt" for index in range(BRANCH_REVIEW_PATH_LIMIT + 5)
    )
    evidence = BranchContentEvidence(
        schema="kg.delivery.branch-content.v1",
        branch="backup/orphan",
        base_sha="a" * 40,
        head_sha="b" * 40,
        base_is_ancestor=False,
        ahead_commit_count=2,
        behind_commit_count=1,
        changed_paths=changed_paths,
        changed_path_count=len(changed_paths),
        changed_paths_truncated=False,
        change_fingerprint="c" * 64,
        commit_subjects=("feature",),
        commit_subjects_truncated=False,
        complete=True,
    )
    action = SimpleNamespace(
        side=BranchSide.LOCAL,
        branch="backup/orphan",
        sha="b" * 40,
        category="local_orphan_blocked",
        review_command="./ops/delivery.py branch-inspect ...",
        orphan_preflight=SimpleNamespace(
            eligible=False,
            blockers=("orphan branch tip is not an ancestor of live origin/main",),
        ),
        next_step="review content",
    )
    audit = SimpleNamespace(
        actions=(action,),
        live_main_sha="a" * 40,
        complete=False,
        source_problem_actions=(object(),),
    )

    with (
        patch.object(DeliveryApplication, "branch_audit", return_value=audit),
        patch.object(
            BranchContentService,
            "inspect_many",
            return_value={"backup/orphan": evidence},
        ),
    ):
        plan = application.branch_review_plan(offset=0, limit=1)

    content = plan.items[0].content
    assert len(content.changed_paths) == BRANCH_REVIEW_PATH_LIMIT
    assert content.changed_paths == changed_paths[:BRANCH_REVIEW_PATH_LIMIT]
    assert content.changed_path_count == len(changed_paths)
    assert content.changed_paths_truncated is True
    assert content.change_fingerprint == "c" * 64


def test_branch_review_plan_excludes_lifecycle_owned_orphans(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )

    def content(branch: str) -> BranchContentEvidence:
        return BranchContentEvidence(
            schema="kg.delivery.branch-content.v1",
            branch=branch,
            base_sha="a" * 40,
            head_sha="b" * 40,
            base_is_ancestor=False,
            ahead_commit_count=1,
            behind_commit_count=0,
            changed_paths=("feature.py",),
            changed_path_count=1,
            changed_paths_truncated=False,
            change_fingerprint="c" * 64,
            commit_subjects=("feature",),
            commit_subjects_truncated=False,
            complete=True,
        )

    def action(
        branch: str,
        blockers: tuple[str, ...],
        *,
        category: str = "local_orphan_blocked",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            side=BranchSide.LOCAL,
            branch=branch,
            sha="b" * 40,
            category=category,
            review_command="./ops/delivery.py branch-inspect ...",
            orphan_preflight=SimpleNamespace(
                eligible=False,
                blockers=blockers,
            ),
            next_step="review content",
        )

    reviewable = "backup/reviewable"
    with (
        patch.object(
            DeliveryApplication,
            "branch_audit",
            return_value=SimpleNamespace(
                actions=(
                    action(
                        reviewable,
                        ("orphan branch tip is not an ancestor of live origin/main",),
                    ),
                    action(
                        "backup/remote",
                        ("orphan branch still has a remote ref",),
                    ),
                    action(
                        "backup/pr-history",
                        ("orphan branch has PR history",),
                    ),
                    action(
                        "debug/owner",
                        (
                            "branch has a registry claim; use the owner-preserving lifecycle",
                        ),
                    ),
                    action(
                        "debug/source-problem",
                        ("orphan branch tip is not an ancestor of live origin/main",),
                        category="source_incomplete",
                    ),
                ),
                live_main_sha="a" * 40,
                complete=False,
                source_problem_actions=(object(),),
            ),
        ),
        patch.object(
            BranchContentService,
            "inspect_many",
            return_value={
                branch: content(branch)
                for branch in (
                    reviewable,
                    "backup/remote",
                    "backup/pr-history",
                    "debug/owner",
                    "debug/source-problem",
                )
            },
        ),
    ):
        plan = application.branch_review_plan(offset=0, limit=20)

    assert plan.total_candidates == 1
    assert plan.items[0].branch == reviewable


def test_metrics_forwards_supervision_worktree_paths_to_inspect(
    tmp_path: Path,
) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    telemetry = Mock()
    telemetry.rolling.return_value = Mock()
    with (
        patch.object(DeliveryApplication, "inspect", return_value=Mock()) as inspect,
        patch.object(
            DeliveryApplication, "_operation_telemetry", return_value=telemetry
        ),
        patch(
            "delivery_control.application_services.measure_pipeline",
            return_value=object(),
        ) as measure,
    ):
        assert (
            application.metrics(supervision_worktree_paths=(Path("/supervision"),))
            is not None
        )

    assert inspect.call_args.kwargs["supervision_worktree_paths"] == (
        Path("/supervision"),
    )
    assert measure.call_args.kwargs["excluded_worktree_paths"] == (
        Path("/supervision"),
    )


def test_metrics_result_preserves_inspected_main_baselines(tmp_path: Path) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    telemetry = Mock()
    telemetry.rolling.return_value = None
    inventory = DeliveryInventory(
        lanes=(),
        live_main_sha="a" * 40,
        local_main_sha="b" * 40,
    )

    with (
        patch.object(DeliveryApplication, "inspect", return_value=inventory),
        patch.object(
            DeliveryApplication, "_operation_telemetry", return_value=telemetry
        ),
    ):
        measured = application.metrics()

    assert measured.live_main_sha == "a" * 40
    assert measured.local_main_sha == "b" * 40


def test_inspect_forwards_supervision_worktree_paths(tmp_path: Path) -> None:
    application = DeliveryApplication(
        repo=tmp_path,
        git=Mock(),
        github=Mock(),
        registry=Mock(),
        runtime=Mock(),
        telemetry=Mock(),
    )
    with patch(
        "delivery_control.application_services.inspect.InspectService"
    ) as service:
        service.return_value.inspect.return_value = object()
        assert (
            application.inspect(supervision_worktree_paths=(Path("/supervision"),))
            is not None
        )

    assert service.return_value.inspect.call_args.kwargs[
        "supervision_worktree_paths"
    ] == (Path("/supervision"),)


@pytest.mark.parametrize("max_paths", (0, 21, 10**9, 1.5, True))
def test_branch_content_review_rejects_overlarge_path_samples(
    max_paths: object,
) -> None:
    evidence = BranchContentEvidence(
        schema="kg.delivery.branch-content.v1",
        branch="backup/orphan",
        base_sha="a" * 40,
        head_sha="b" * 40,
        base_is_ancestor=False,
        ahead_commit_count=1,
        behind_commit_count=0,
        changed_paths=tuple(f"file-{index:02d}.txt" for index in range(25)),
        changed_path_count=25,
        changed_paths_truncated=False,
        change_fingerprint="c" * 64,
        commit_subjects=("feature",),
        commit_subjects_truncated=False,
        complete=True,
    )

    with pytest.raises(ValueError, match="between 1 and 20"):
        BranchContentService.compact_for_review(evidence, max_paths=max_paths)


def test_branch_content_review_preserves_valid_bounded_samples() -> None:
    evidence = BranchContentEvidence(
        schema="kg.delivery.branch-content.v1",
        branch="backup/orphan",
        base_sha="a" * 40,
        head_sha="b" * 40,
        base_is_ancestor=False,
        ahead_commit_count=1,
        behind_commit_count=0,
        changed_paths=tuple(f"file-{index:02d}.txt" for index in range(25)),
        changed_path_count=25,
        changed_paths_truncated=False,
        change_fingerprint="c" * 64,
        commit_subjects=("feature",),
        commit_subjects_truncated=False,
        complete=True,
    )

    one = BranchContentService.compact_for_review(evidence, max_paths=1)
    twenty = BranchContentService.compact_for_review(evidence, max_paths=20)

    assert len(one.changed_paths) == 1
    assert len(twenty.changed_paths) == 20
    assert one.changed_path_count == twenty.changed_path_count == 25
    assert one.change_fingerprint == twenty.change_fingerprint == "c" * 64
