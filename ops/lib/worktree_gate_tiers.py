"""Pure policy for the five-level delivery verification ladder.

The orchestrator already knows how to execute individual checks.  This module only
answers two policy questions:

* which checks belong to S0..S4; and
* when a failed check may be carried as a named backlog deferral.

It deliberately does not read the backlog, git, or the environment.  Callers validate
ticket ids and attach the resulting evidence to the gate receipt.
"""

from __future__ import annotations

from typing import Any


GATE_TIERS = ("S0", "S1", "S2", "S3", "S4")
TIER_RANK = {name: index for index, name in enumerate(GATE_TIERS)}
DEFAULT_GATE_TIER = "S2"
MIN_CUTOVER_TIER = "S0"


class GateTierError(ValueError):
    """The caller supplied a tier outside the closed policy vocabulary."""


def normalize_gate_tier(value: str | None, *, default: str = DEFAULT_GATE_TIER) -> str:
    candidate = default if value is None else str(value).upper()
    if candidate not in TIER_RANK:
        raise GateTierError(
            f"unknown gate tier {value!r}; expected one of {', '.join(GATE_TIERS)}"
        )
    return candidate


def tier_at_most(spec: dict[str, Any], requested: str) -> bool:
    """Return whether a planned gate is a candidate at ``requested`` depth."""
    tier = normalize_gate_tier(str(spec.get("tier", "S2")))
    return TIER_RANK[tier] <= TIER_RANK[requested]


def _is_whole_ops_suite(spec: dict[str, Any]) -> bool:
    cmd = spec.get("cmd")
    return isinstance(cmd, list) and "ops/tests" in cmd


def classify_gate_tier(spec: dict[str, Any]) -> str:
    """Assign an existing gate family to the cheapest honest delivery tier.

    S0 is static/tool-contract validation, S1 is one focused functional path, S2 is
    module regression, and S3 is cross-target or cross-module validation.  S4 is
    reserved for release-only checks; ordinary impact planning does not invent an S4
    gate merely because a file changed.

    Unknown future gates conservatively land in S2 so a new route cannot silently
    become cheaper than the policy understands.
    """
    name = str(spec.get("name") or "")

    s0_exact = {
        "official-decks-check",
        "ui-quality-fast",
        "design-system",
        "docs-lint",
        "docs-conflict-markers",
        "docs-verified-against",
        "docs-removed",
        "ops-python-scan",
        "ops-shell-syntax",
        "ops-shell-scan",
        "ops-shell-untested",
        "data-plane-unowned",
        "data-plane-deleted",
        "backlog-validate",
        "agent-constitution",
        "coverage",
    }
    if name in s0_exact or name.startswith("data-plane:"):
        return "S0"

    if name == "ios-build":
        return "S1"
    if name.startswith("ios-test-ui:"):
        return "S1"
    if name == "backend-pytest":
        return "S1"
    if name.startswith("ops-shell:"):
        return "S1"
    if name in {"ops-pytest-focused", "ops-pytest"} and not _is_whole_ops_suite(spec):
        return "S1"
    if name == "ops-pytest-orchestrator-focused":
        return "S1"
    if name == "ops-pytest-orchestrator-group":
        return "S2"

    if name == "ios-build-catalyst":
        return "S3"
    if name in {"ios-live-demo-uitest-compile", "ios-live-demo-runtime-advisory"}:
        return "S3"
    if name == "ops-pytest" and _is_whole_ops_suite(spec):
        return "S2"
    if name in {"ios-test-unit", "ui-quality-slow-pending", "ios-ui-tests-removed"}:
        return "S2"
    if name in {"backend-tests-advisory", "backend-tests-removed"}:
        return "S2"

    return "S2"


def annotate_gate(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with the policy tier attached."""
    result = dict(spec)
    result["tier"] = classify_gate_tier(result)
    return result


def annotate_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [annotate_gate(spec) for spec in plan]


def _superseded_gate_names(plan: list[dict[str, Any]]) -> set[str]:
    """Return lower-level gate names explicitly covered by selected gates."""
    by_name = {str(spec.get("name")): spec for spec in plan}
    names: set[str] = set()
    for spec in plan:
        supersedes = spec.get("supersedes", ())
        if isinstance(supersedes, (list, tuple, set, frozenset)):
            superseding_tier = normalize_gate_tier(str(spec.get("tier", "S2")))
            for name in supersedes:
                target_name = str(name)
                target = by_name.get(target_name)
                if target is None:
                    continue
                target_tier = normalize_gate_tier(str(target.get("tier", "S2")))
                if TIER_RANK[target_tier] < TIER_RANK[superseding_tier]:
                    names.add(target_name)
    return names


def select_plan(plan: list[dict[str, Any]], requested: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a complete plan into executed, coalesced, and deferred checks.

    Tiers remain cumulative for checks without a higher-level replacement: S2 must
    still execute S0 and any S1 check that its plan does not cover.  A higher-level
    gate may explicitly declare ``supersedes`` to prevent an equivalent lower-level
    check from running twice.  Coalesced checks are neither executed nor deferred;
    their coverage is represented by the selected superseding gate.
    """
    tier = normalize_gate_tier(requested)
    candidates = [spec for spec in plan if tier_at_most(spec, tier)]
    superseded = _superseded_gate_names(candidates)
    executed = [spec for spec in candidates if str(spec.get("name")) not in superseded]
    deferred = [spec for spec in plan if not tier_at_most(spec, tier)]
    return executed, deferred


def release_gate_plan() -> list[dict[str, Any]]:
    """Return the release-only full validation profile.

    S4 is intentionally explicit and expensive.  It is not inferred from an
    ordinary changed-file plan and it is never a target for deferral.  The commands
    are the repository's existing release/readiness entry points, not a second test
    runner hidden inside the orchestrator.
    """
    return [
        {
            "name": "release-backend-full",
            "category": "release",
            "kind": "shell",
            "level": "block",
            "tier": "S4",
            "cmd": ["uv", "run", "--project", "backend", "python", "-m", "pytest", "-q"],
        },
        {
            "name": "release-ops-full",
            "category": "release",
            "kind": "shell",
            "level": "block",
            "tier": "S4",
            "cmd": ["./ops/test_ops.sh"],
        },
        {
            "name": "release-ios-all-targets",
            "category": "release",
            "kind": "shell",
            "level": "block",
            "tier": "S4",
            "cmd": ["./ops/ios_ops.sh", "test", "--all-targets", "--lease", "--json"],
        },
        {
            "name": "release-ios-readiness",
            "category": "release",
            "kind": "shell",
            "level": "block",
            "tier": "S4",
            "cmd": ["./ops/ios_ops.sh", "gate", "release", "--json"],
        },
    ]


def parse_deferral(value: str) -> tuple[str, str]:
    """Parse the CLI shape ``gate-name=TICKET-ID``."""
    gate_name, separator, ticket_id = str(value).partition("=")
    if not separator or not gate_name.strip() or not ticket_id.strip():
        raise GateTierError(
            f"invalid deferral {value!r}; use <gate-name>=<backlog-ticket-id>"
        )
    return gate_name.strip(), ticket_id.strip()


def deferral_allowed(spec: dict[str, Any], severity: str) -> tuple[bool, str | None]:
    """Return whether a named ticket may carry this failure past cutover."""
    tier = normalize_gate_tier(str(spec.get("tier", "S2")))
    if TIER_RANK[tier] < TIER_RANK["S2"]:
        return False, f"{spec.get('name')} is {tier}; S0/S1 failures always block"
    if tier == "S4":
        return False, "S4 release checks cannot be deferred"
    if severity == "high":
        return False, "high-severity tickets cannot defer a failing gate"
    if severity not in {"low", "med"}:
        return False, f"unsupported ticket severity {severity!r}"
    return True, None


def required_cutover_tier(
    changed_files: list[str],
    planned_plan: list[dict[str, Any]] | None = None,
) -> str:
    """Select the minimum daily cutover tier for a changed-file set.

    Neutral/docs-only changes need only their S0 contract checks.  A change that
    crosses product/ops surfaces needs the S3 cross-module floor when the selected
    impact plan contains a real S3 check.  If the repository has not yet wired an
    honest S3 check for that combination, keep the floor at S2 rather than claiming
    that a numeric label performed cross-module verification.  Everything else that
    can affect runtime requires S2.  Release S4 is a separate release decision.

    ``planned_plan`` is optional for callers that only need the scope baseline.  The
    executable gate path supplies its complete annotated plan, including checks that
    are deferred by a lower requested tier, so the required floor is based on an
    available real check rather than on the caller's selected subset.
    """
    functional_roots = {
        rel.split("/", 1)[0]
        for rel in changed_files
        if rel.split("/", 1)[0] in {"backend", "ios", "lab", "ops", "design-system"}
    }
    if len(functional_roots) >= 2:
        has_real_s3 = any(
            classify_gate_tier(spec) == "S3"
            for spec in (planned_plan or [])
        )
        return "S3" if has_real_s3 else "S2"
    if functional_roots:
        return "S2"
    return "S0"
