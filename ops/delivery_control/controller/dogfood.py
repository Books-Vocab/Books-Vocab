"""Pure launch policy for the four-role delivery dogfood."""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import MergeCadence, PipelineMetrics


@dataclass(frozen=True)
class DogfoodProfile:
    roles: tuple[str, ...] = ("backlog_scout", "pi", "cm", "supervisor")
    supervisor_poll_seconds: int = 60
    canary_solver_limit: int = 1
    promotion_merge_count: int = 3
    promotion_observation_seconds: int = 900
    target_inter_merge_seconds: int = 300


@dataclass(frozen=True)
class DogfoodReadiness:
    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    local_main_sha: str
    origin_main_sha: str
    physical_worktree_count: int
    canonical_worktree_present: bool
    metrics: PipelineMetrics
    cadence: MergeCadence
    profile: DogfoodProfile


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
    block(metrics.source_problems > 0, "delivery source inventory is incomplete")
    block(metrics.unmapped_open_prs > 0, "open PRs lack exact owner mapping")
    block(metrics.blocked_lanes > 0, "existing lanes still require disposition")
    block(metrics.active_development > 0, "pre-dogfood development lanes remain")
    block(metrics.handbacks_publishable > 0, "pre-dogfood handbacks remain local")
    block(metrics.published_local_cleanup > 0, "published PRs retain local assets")
    block(metrics.terminal_cleanup > 0, "merged assets retain terminal residue")
    block(metrics.pr_contract_failed > 0, "existing PR delivery contracts are invalid")
    block(metrics.required_failed > 0, "existing required checks are failed")
    block(metrics.open_prs > 0, "owner-mapped PR reservoir is not empty")
    block(
        physical_worktree_count != 1 or not canonical_worktree_present,
        "physical worktree baseline is not canonical-main only",
    )

    warnings: list[str] = []
    if cadence.merged_count < profile.promotion_merge_count:
        warnings.append("five-minute merge SLO is unproven until canary promotion")
    return DogfoodReadiness(
        ready=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        local_main_sha=local_main_sha,
        origin_main_sha=origin_main_sha,
        physical_worktree_count=physical_worktree_count,
        canonical_worktree_present=canonical_worktree_present,
        metrics=metrics,
        cadence=cadence,
        profile=profile,
    )
