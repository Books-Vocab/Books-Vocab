"""Phase-aware launch observations for production-mode dogfood.

The legacy :mod:`dogfood` policy answers a clean-slate qualification question.
This module answers a different question: which phase can safely run while
unrelated lane work, raw demand, and historical residue remain visible.  It is
read-only evidence; ``ready`` never grants session, worktree, PR, or merge
authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .dogfood import DogfoodProfile, DogfoodReadiness
from .metrics import MergeCadence, PipelineMetrics

PHASE_READINESS_SCHEMA = "kg.delivery.dogfood-readiness.v2"
STEADY_WINDOW_SECONDS = 3600
STEADY_MERGE_TARGET = 12
STEADY_INTER_MERGE_P95_SECONDS = 300.0
STEADY_LAST_MERGE_SECONDS = 300.0
STEADY_REQUIRED_SAMPLES = 12
STEADY_REQUIRED_P95_SECONDS = 240.0
STEADY_HANDBACK_TO_PR_P95_SECONDS = 60.0
STEADY_PR_TO_REQUIRED_START_P95_SECONDS = 60.0
STEADY_REQUIRED_SUCCESS_TO_ENQUEUE_P95_SECONDS = 30.0
STEADY_MERGE_TO_SYNC_P95_SECONDS = 30.0
STEADY_MERGE_TO_CLEANUP_P95_SECONDS = 60.0
STEADY_ACTIVE_SOLVER_TARGET = 8
STEADY_ACTIVE_SOLVER_MAX = 12
STEADY_CANDIDATE_MIN = 20


class DogfoodMode(StrEnum):
    """The explicit operating phase requested by the caller."""

    QUALIFICATION = "qualification"
    PILOT = "pilot"
    RAMP = "ramp"
    STEADY = "steady"


@dataclass(frozen=True)
class PhaseDogfoodReadiness:
    """Additive phase observation; it does not authorize any mutation."""

    mode: str
    ready: bool
    global_freeze: bool
    global_blockers: tuple[str, ...]
    lane_blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    next_actions: tuple[str, ...]
    raw_open_issues: int | None
    dispatchable_candidate_issues: int | None
    active_implementations: int
    publishable_handbacks: int
    durable_prs: int
    merge_ready: int
    backlog_classified: bool | None
    backlog_drained: bool
    pilot_ready: bool
    ramp_ready: bool
    steady_state_verified: bool
    # Compatibility/evidence fields keep the legacy result visible beside the
    # phase decision rather than silently replacing its semantics.
    blockers: tuple[str, ...]
    canary_promotable: bool
    pipeline_ready: bool
    local_main_sha: str
    origin_main_sha: str
    physical_worktree_count: int
    canonical_worktree_present: bool
    metrics: PipelineMetrics
    cadence: MergeCadence
    profile: DogfoodProfile
    direct_assignment_available: bool = False
    dispatch_authorized: bool = field(default=False, init=False)
    schema: str = field(default=PHASE_READINESS_SCHEMA, init=False)


_GLOBAL_BLOCKER_TEXT = frozenset(
    {
        "canonical checkout is not on main",
        "canonical checkout is dirty",
        "local main differs from origin/main",
        "main is not protected",
        "main does not require the short required context",
        "main has no native merge queue rule",
        "delivery source inventory is incomplete",
        "raw open Issue inventory is incomplete",
        "open PRs lack exact owner mapping",
        "PR mappings are not unique",
        "explicit P0/P1/security hold scope is global or unknown",
        "canonical worktree is missing",
        "canonical worktree baseline is unavailable",
    }
)

_OBSERVATION_ONLY_BLOCKER_TEXT = frozenset(
    {
        "pre-dogfood development lanes remain",
        "pre-dogfood handbacks remain local",
        "owner-mapped PR reservoir is not empty",
        "physical worktree baseline is not canonical-main only",
    }
)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _backlog_classified(metrics: PipelineMetrics, explicit: bool | None) -> bool | None:
    if explicit is not None:
        return explicit
    if (
        not metrics.issue_inventory_complete
        or metrics.raw_open_issues is None
        or metrics.unadmitted_open_issues is None
    ):
        return None
    # The measured metrics expose the complete raw cardinality and its
    # unadmitted partition.  The domain projection's stronger disposition
    # cardinality check is therefore represented as a known observation here.
    return True


def _global_blockers(base: DogfoodReadiness) -> list[str]:
    metrics = base.metrics
    blockers: list[str] = []

    for blocker in base.blockers:
        if blocker in _GLOBAL_BLOCKER_TEXT:
            _append_unique(blockers, blocker)

    if not base.canonical_worktree_present:
        _append_unique(blockers, "canonical worktree is missing")
    elif base.physical_worktree_count < 1:
        _append_unique(blockers, "canonical worktree baseline is unavailable")

    if (metrics.actionable_global_source_problems or 0) > 0:
        _append_unique(blockers, "delivery source inventory is incomplete")
    if not metrics.issue_inventory_complete:
        _append_unique(blockers, "raw open Issue inventory is incomplete")
    if (metrics.actionable_unmapped_open_prs or 0) > 0:
        _append_unique(blockers, "open PRs lack exact owner mapping")
    if metrics.duplicate_pr_mappings > 0:
        _append_unique(blockers, "PR mappings are not unique")

    hard_holds = metrics.security_hold_issues + metrics.security_hold_lanes
    if hard_holds and metrics.security_hold_global is not False:
        _append_unique(
            blockers, "explicit P0/P1/security hold scope is global or unknown"
        )
    return blockers


def _lane_blockers(
    base: DogfoodReadiness,
    *,
    mode: DogfoodMode,
    pilot_ready: bool,
    ramp_ready: bool,
    steady_state_verified: bool,
) -> list[str]:
    metrics = base.metrics
    blockers: list[str] = []
    for blocker in base.blockers:
        if (
            blocker not in _GLOBAL_BLOCKER_TEXT
            and blocker not in _OBSERVATION_ONLY_BLOCKER_TEXT
        ):
            _append_unique(blockers, blocker)
    if (metrics.actionable_blocked_lanes or 0) > 0:
        _append_unique(blockers, "existing lanes still require disposition")
    if metrics.pr_contract_failed > 0:
        _append_unique(blockers, "existing PR delivery contracts are invalid")
    if metrics.required_failed > 0:
        _append_unique(blockers, "existing required checks are failed")
    if metrics.required_absent > 0:
        _append_unique(blockers, "published PRs have no required run")
    if metrics.security_hold_global is False and (
        metrics.security_hold_issues or metrics.security_hold_lanes
    ):
        _append_unique(blockers, "a scoped P0/P1/security lane requires disposition")
    if metrics.published_local_cleanup > 0:
        _append_unique(blockers, "published PRs retain local assets")
    if (metrics.actionable_terminal_cleanup or 0) > 0:
        _append_unique(blockers, "merged assets retain terminal residue")
    if mode is DogfoodMode.PILOT and not pilot_ready:
        _append_unique(
            blockers,
            "no dispatchable candidate or explicit direct assignment is available",
        )
    if mode is DogfoodMode.RAMP and not ramp_ready:
        _append_unique(blockers, "pilot promotion proof is not present")
    if mode is DogfoodMode.STEADY and not steady_state_verified:
        _append_unique(
            blockers, "one-hour throughput or transport SLO evidence is insufficient"
        )
    return blockers


def _warnings(base: DogfoodReadiness) -> list[str]:
    metrics = base.metrics
    warnings = list(base.warnings)
    scoped_source_count = max(
        0,
        (metrics.actionable_source_problems or 0)
        - (metrics.actionable_global_source_problems or 0),
    )
    if scoped_source_count:
        details = ", ".join(
            f"{scope}={count}"
            for scope, count in metrics.source_problem_scope_counts
            if scope != "global" and count
        )
        suffix = f" ({details})" if details else ""
        _append_unique(
            warnings,
            "scoped source observations remain"
            f"{suffix}; only affected branch/object cleanup is frozen",
        )
    if metrics.raw_open_issues is None or not metrics.issue_inventory_complete:
        _append_unique(warnings, "raw Issue backlog cardinality is unknown")
    elif metrics.raw_open_issues > 0:
        _append_unique(
            warnings,
            f"raw backlog remains visible ({metrics.raw_open_issues} open Issues)",
        )
    if (metrics.unadmitted_open_issues or 0) > 0:
        _append_unique(warnings, "unadmitted raw Issues remain; backlog is not drained")
    if metrics.legacy_open_issues > 0:
        _append_unique(
            warnings, "legacy Issues remain and require explicit recovery evidence"
        )
    if metrics.open_prs > 0:
        _append_unique(
            warnings,
            f"durable PR reservoir remains ({metrics.open_prs}); it is not a global freeze",
        )
    return warnings


def phase_next_actions(
    metrics: PipelineMetrics,
    *,
    backlog_classified: bool | None = None,
) -> tuple[str, ...]:
    """Return deterministic supply/flow actions without granting authority."""

    actions: list[str] = []
    raw_open_issues = metrics.raw_open_issues
    if (
        raw_open_issues is None
        or not metrics.issue_inventory_complete
        or raw_open_issues > 0
        or (metrics.unadmitted_open_issues or 0) > 0
    ):
        actions.append("triage_existing_issues")
    if metrics.legacy_open_issues > 0:
        actions.append("recover_legacy_issues")
    if (metrics.active_registry_without_worktree_owner_reachable or 0) > 0:
        actions.append("recover_owner_bound_lane")
    if metrics.handbacks_publishable > 0:
        actions.append("publish_handbacks")
    if metrics.required_green > 0:
        actions.append("enqueue_green")
    if metrics.cleanup_pending or metrics.published_local_cleanup:
        actions.append("cleanup_local")
    if (metrics.actionable_terminal_cleanup or 0) > 0:
        actions.append("cleanup_terminal")

    dispatchable = metrics.dispatchable_candidate_issues
    if (
        dispatchable is not None
        and dispatchable > 0
        and metrics.active_development < STEADY_ACTIVE_SOLVER_MAX
    ):
        actions.append("dispatch_solvers")
    if (
        backlog_classified is True
        and dispatchable is not None
        and dispatchable < STEADY_CANDIDATE_MIN
    ):
        actions.append("replenish_candidates")
    return tuple(dict.fromkeys(actions)) or ("healthy",)


def _timing_meets(
    *,
    samples: int,
    p95: float | None,
    threshold: float,
) -> bool:
    return samples >= STEADY_REQUIRED_SAMPLES and p95 is not None and p95 <= threshold


def _steady_state_verified(base: DogfoodReadiness) -> bool:
    cadence = base.cadence
    timings = base.metrics.timings
    if (
        cadence.window_seconds != STEADY_WINDOW_SECONDS
        or cadence.merged_count < STEADY_MERGE_TARGET
        or cadence.merges_per_hour < STEADY_MERGE_TARGET
        or cadence.p95_interval_seconds is None
        or cadence.p95_interval_seconds > STEADY_INTER_MERGE_P95_SECONDS
        or cadence.seconds_since_last_merge is None
        or cadence.seconds_since_last_merge > STEADY_LAST_MERGE_SECONDS
    ):
        return False
    return all(
        (
            _timing_meets(
                samples=timings.handback_to_pr_samples,
                p95=timings.handback_to_pr_p95_seconds,
                threshold=STEADY_HANDBACK_TO_PR_P95_SECONDS,
            ),
            _timing_meets(
                samples=timings.pr_to_required_start_samples,
                p95=timings.pr_to_required_start_p95_seconds,
                threshold=STEADY_PR_TO_REQUIRED_START_P95_SECONDS,
            ),
            _timing_meets(
                samples=timings.required_duration_samples,
                p95=timings.required_duration_p95_seconds,
                threshold=STEADY_REQUIRED_P95_SECONDS,
            ),
            _timing_meets(
                samples=timings.required_success_to_enqueue_samples,
                p95=timings.required_success_to_enqueue_p95_seconds,
                threshold=STEADY_REQUIRED_SUCCESS_TO_ENQUEUE_P95_SECONDS,
            ),
            _timing_meets(
                samples=timings.merge_to_sync_samples,
                p95=timings.merge_to_sync_p95_seconds,
                threshold=STEADY_MERGE_TO_SYNC_P95_SECONDS,
            ),
            _timing_meets(
                samples=timings.merge_to_cleanup_samples,
                p95=timings.merge_to_cleanup_p95_seconds,
                threshold=STEADY_MERGE_TO_CLEANUP_P95_SECONDS,
            ),
        )
    )


def assess_phase_readiness(
    base: DogfoodReadiness,
    *,
    mode: DogfoodMode | str,
    direct_assignment_available: bool = False,
    backlog_classified: bool | None = None,
) -> PhaseDogfoodReadiness:
    """Project legacy observations into an explicit qualification/pilot/ramp/steady phase."""

    selected_mode = DogfoodMode(mode)
    metrics = base.metrics
    classified = _backlog_classified(metrics, backlog_classified)
    global_blockers = _global_blockers(base)
    candidate_available = (
        metrics.dispatchable_candidate_issues is not None
        and metrics.dispatchable_candidate_issues > 0
    )
    pilot_ready = not global_blockers and (
        candidate_available or direct_assignment_available
    )
    steady_verified = _steady_state_verified(base)
    ramp_ready = pilot_ready and base.canary_promotable and not global_blockers
    lane_blockers = _lane_blockers(
        base,
        mode=selected_mode,
        pilot_ready=pilot_ready,
        ramp_ready=ramp_ready,
        steady_state_verified=steady_verified,
    )
    warnings = _warnings(base)
    actions = phase_next_actions(metrics, backlog_classified=classified)
    if selected_mode is DogfoodMode.STEADY and not steady_verified:
        _append_unique(
            warnings, "steady mode is an observation of one-hour throughput and SLOs"
        )

    if selected_mode is DogfoodMode.QUALIFICATION:
        ready = base.ready
    elif selected_mode is DogfoodMode.PILOT:
        ready = pilot_ready
    elif selected_mode is DogfoodMode.RAMP:
        ready = ramp_ready
    else:
        ready = steady_verified and not global_blockers

    return PhaseDogfoodReadiness(
        mode=selected_mode.value,
        ready=ready,
        global_freeze=bool(global_blockers),
        global_blockers=tuple(dict.fromkeys(global_blockers)),
        lane_blockers=tuple(dict.fromkeys(lane_blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        next_actions=actions,
        raw_open_issues=metrics.raw_open_issues,
        dispatchable_candidate_issues=metrics.dispatchable_candidate_issues,
        active_implementations=metrics.active_development,
        publishable_handbacks=metrics.handbacks_publishable,
        durable_prs=metrics.open_prs,
        merge_ready=metrics.required_green,
        backlog_classified=classified,
        backlog_drained=metrics.backlog_drained,
        pilot_ready=pilot_ready,
        ramp_ready=ramp_ready,
        steady_state_verified=steady_verified,
        blockers=base.blockers,
        canary_promotable=base.canary_promotable,
        pipeline_ready=metrics.pipeline_ready,
        local_main_sha=base.local_main_sha,
        origin_main_sha=base.origin_main_sha,
        physical_worktree_count=base.physical_worktree_count,
        canonical_worktree_present=base.canonical_worktree_present,
        metrics=metrics,
        cadence=base.cadence,
        profile=base.profile,
        direct_assignment_available=direct_assignment_available,
    )


__all__ = [
    "PHASE_READINESS_SCHEMA",
    "DogfoodMode",
    "PhaseDogfoodReadiness",
    "assess_phase_readiness",
    "phase_next_actions",
]
