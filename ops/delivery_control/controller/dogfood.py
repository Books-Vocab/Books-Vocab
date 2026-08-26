"""Pure launch policy for the four-role delivery dogfood."""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import MergeCadence, PipelineMetrics


@dataclass(frozen=True)
class DogfoodProfile:
    roles: tuple[str, ...] = ("backlog_scout", "pi", "cm", "supervisor")
    # This is a coarse liveness tick, not the delivery execution cadence.
    watchdog_tick_seconds: int = 300
    canary_solver_limit: int = 1
    promotion_merge_count: int = 3
    promotion_observation_seconds: int = 900
    target_inter_merge_seconds: int = 300


@dataclass(frozen=True)
class DogfoodReadiness:
    ready: bool
    canary_promotable: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    local_main_sha: str
    origin_main_sha: str
    physical_worktree_count: int
    canonical_worktree_present: bool
    metrics: PipelineMetrics
    cadence: MergeCadence
    profile: DogfoodProfile
    supervision_worktree_count: int = 0
    total_physical_worktree_count: int | None = None
    backlog_drained: bool = False
    pipeline_ready: bool = False
    ramp_ready: bool = False


DEFAULT_DOGFOOD_PROFILE = DogfoodProfile()


def assess_dogfood_readiness(
    *,
    local_main_sha: str,
    origin_main_sha: str,
    canonical_branch: str | None,
    canonical_clean: bool,
    main_protected: bool,
    required_status_contexts: tuple[str, ...],
    merge_queue_enabled: bool,
    physical_worktree_count: int,
    canonical_worktree_present: bool,
    metrics: PipelineMetrics,
    cadence: MergeCadence,
    profile: DogfoodProfile = DEFAULT_DOGFOOD_PROFILE,
    supervision_worktree_count: int = 0,
    total_physical_worktree_count: int | None = None,
) -> DogfoodReadiness:
    blockers: list[str] = []

    def block(condition: bool, message: str) -> None:
        if condition:
            blockers.append(message)

    block(canonical_branch != "main", "canonical checkout is not on main")
    block(not canonical_clean, "canonical checkout is dirty")
    block(local_main_sha != origin_main_sha, "local main differs from origin/main")
    block(not main_protected, "main is not protected")
    block(
        "required" not in required_status_contexts,
        "main does not require the short required context",
    )
    block(not merge_queue_enabled, "main has no native merge queue rule")
    actionable_source_problems = metrics.actionable_source_problems or 0
    actionable_global_source_problems = (
        metrics.actionable_global_source_problems
        if metrics.actionable_global_source_problems is not None
        else actionable_source_problems
    )
    block(
        actionable_global_source_problems > 0,
        "delivery source inventory is incomplete",
    )
    block(
        metrics.actionable_unmapped_open_prs > 0,
        "open PRs lack exact owner mapping",
    )
    block(
        metrics.actionable_blocked_lanes > 0,
        "existing lanes still require disposition",
    )
    block(metrics.active_development > 0, "pre-dogfood development lanes remain")
    block(metrics.handbacks_publishable > 0, "pre-dogfood handbacks remain local")
    block(metrics.published_local_cleanup > 0, "published PRs retain local assets")
    block(
        metrics.actionable_terminal_cleanup > 0,
        "merged assets retain terminal residue",
    )
    block(metrics.pr_contract_failed > 0, "existing PR delivery contracts are invalid")
    block(metrics.required_failed > 0, "existing required checks are failed")
    block(
        metrics.security_hold_issues > 0 or metrics.security_hold_lanes > 0,
        "explicit P0/P1/security holds require terminal disposition",
    )
    block(metrics.open_prs > 0, "owner-mapped PR reservoir is not empty")
    if metrics.review_gate_unresolved:
        block(
            True,
            (
                "open PR review gate is unresolved: "
                f"{metrics.review_gate_unresolved} observation(s); "
                "review status is not required-check or merge approval"
            ),
        )
    block(
        physical_worktree_count != 1 or not canonical_worktree_present,
        "physical worktree baseline is not canonical-main only",
    )

    exact_promotion_window = (
        cadence.window_seconds == profile.promotion_observation_seconds
    )
    cadence_within_target = (
        cadence.p95_interval_seconds is not None
        and cadence.p95_interval_seconds <= profile.target_inter_merge_seconds
        and cadence.seconds_since_last_merge is not None
        and cadence.seconds_since_last_merge <= profile.target_inter_merge_seconds
    )
    canary_promotable = (
        exact_promotion_window
        and cadence.merged_count >= profile.promotion_merge_count
        and cadence_within_target
    )
    warnings: list[str] = []
    scoped_source_problems = max(
        0, actionable_source_problems - actionable_global_source_problems
    )
    if scoped_source_problems:
        scoped_details = ", ".join(
            f"{scope}={count}"
            for scope, count in metrics.source_problem_scope_counts
            if scope != "global" and count
        )
        detail = (
            f" (raw source observations: {scoped_details})" if scoped_details else ""
        )
        warnings.append(
            f"{scoped_source_problems} actionable scoped delivery source observation(s)"
            " remain"
            f"{detail}; affected branch/object cleanup stays frozen and this is not "
            "dispatch, cleanup, takeover, or wake authorization"
        )
    if metrics.unadmitted_open_issues is None:
        warnings.append(
            "raw open Issue inventory is incomplete; backlog cardinality is unknown"
        )
    elif metrics.unadmitted_open_issues:
        warnings.append(
            "raw open Issues remain unadmitted; dogfood launch is not backlog-drained"
        )
    if metrics.open_prs and metrics.review_gate_unresolved is None:
        warnings.append(
            "open PR review-gate inventory is unknown; review status was not measured"
        )
    if not metrics.issue_inventory_complete:
        warnings.append("raw open Issue inventory is incomplete")
    if (
        cadence.merged_count
        and metrics.timings.merge_to_sync_samples < cadence.merged_count
    ):
        missing_sync_samples = (
            cadence.merged_count - metrics.timings.merge_to_sync_samples
        )
        warnings.append(
            f"{missing_sync_samples} recent merge landing(s) lack "
            "merge-to-main sync telemetry"
        )
    if not exact_promotion_window:
        warnings.append(
            "canary promotion requires an exact "
            f"{profile.promotion_observation_seconds}-second cadence observation"
        )
    elif cadence.merged_count < profile.promotion_merge_count:
        warnings.append(
            "canary has fewer than "
            f"{profile.promotion_merge_count} merges in the promotion window"
        )
    elif not cadence_within_target:
        warnings.append(
            "canary inter-merge p95 or latest landing exceeds "
            f"{profile.target_inter_merge_seconds} seconds"
        )
    return DogfoodReadiness(
        ready=not blockers,
        canary_promotable=canary_promotable,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        local_main_sha=local_main_sha,
        origin_main_sha=origin_main_sha,
        physical_worktree_count=physical_worktree_count,
        canonical_worktree_present=canonical_worktree_present,
        metrics=metrics,
        cadence=cadence,
        profile=profile,
        supervision_worktree_count=supervision_worktree_count,
        total_physical_worktree_count=(
            physical_worktree_count + supervision_worktree_count
            if total_physical_worktree_count is None
            else total_physical_worktree_count
        ),
        backlog_drained=metrics.backlog_drained,
        pipeline_ready=metrics.pipeline_ready,
        ramp_ready=metrics.ramp_ready and not blockers,
    )
