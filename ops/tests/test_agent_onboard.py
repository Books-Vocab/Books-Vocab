from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "agent_onboard.py"
SPEC = importlib.util.spec_from_file_location("agent_onboard", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


EVIDENCE = {
    "direct-assignment": {
        "User/IM assignment": "audit the onboarding route",
        "acceptance": "route and tests are green",
        "structured Scope": "ops/agent_onboard.py and route tests",
        "dispatch_channel": "im",
        "dispatch_owner": "IM-1",
    },
    "issue": {
        "Issue assignment packet": "#boundary-contract",
        "Issue acceptance": "route and tests are green",
        "structured Scope": "ops/agent_onboard.py and route tests",
    },
    "pr-review": {
        "GitHub PR": "#123",
        "exact HEAD": "51ce9228ce64c1897850b8fcab672364b17f8731",
        "required checks": "context-routing",
    },
    "ds-pr-review": {
        "GitHub PR diff": "#123 diff",
        "changed paths": "ops/agent_onboard.py",
    },
    "release": {
        "explicit approval": "approved for dry-run only",
        "target": "test target",
        "rollback candidate": "previous test version",
        "health gate": "test health gate",
    },
    "merge": {
        "GitHub PR": "#123",
        "required checks": "context-routing",
        "CR/DS result": "review complete",
    },
    "issue-planning": {
        "GitHub Issue": "#123",
        "Project priority/triage": "P1",
    },
}


def test_worker_direct_assignment_loads_project_identity_skill_then_domain() -> None:
    payload = mod.build_onboarding(ROOT, identity="Worker", intent="delivery", entry="direct-assignment", evidence=EVIDENCE["direct-assignment"])

    assert payload["schema"] == "kg.agent_onboarding.v2"
    assert payload["status"] == "ready"
    assert payload["identity"]["id"] == "worker"
    assert "machine_role" not in payload["identity"]
    assert payload["task"]["entry"] == "direct-assignment"
    assert payload["skills"]["primary"] == "worktree-flow"
    assert "route_command" not in payload["skills"]
    assert payload["load_order"][0] == {
        "phase": "project",
        "required": True,
        "sources": ["docs/reference/project_onboarding.md"],
    }
    assert [step["phase"] for step in payload["load_order"]] == [
        "project", "identity", "assignment", "skill", "domain"
    ]
    assert payload["assignment"]["evidence"]["acceptance"] == "route and tests are green"
    assert len(payload["assignment"]["evidence_digest"]) == 64
    assert payload["authority"]["granted"] is False
    assert payload["assignment"]["dispatch"] == {
        "channel": "im",
        "discussion_with": "IM-1",
        "handback": {
            "policy": "same-dispatching-im",
            "requested_target": None,
            "resolved_target": "IM-1",
            "selection_required": False,
        },
    }


def test_worker_user_dispatch_discusses_with_user_and_hands_back_to_named_im() -> None:
    evidence = {
        **EVIDENCE["direct-assignment"],
        "dispatch_channel": "user",
        "handback_target": "IM-2",
    }
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="delivery",
        entry="direct-assignment",
        evidence=evidence,
    )

    assert payload["assignment"]["dispatch"] == {
        "channel": "user",
        "discussion_with": "User",
        "handback": {
            "policy": "specified-or-worker-selected-im",
            "requested_target": "IM-2",
            "resolved_target": "IM-2",
            "selection_required": False,
        },
    }


def test_worker_user_dispatch_requires_im_selection_before_hand_back_when_unspecified() -> None:
    evidence = {
        **EVIDENCE["direct-assignment"],
        "dispatch_channel": "user",
    }
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="delivery",
        entry="direct-assignment",
        evidence=evidence,
    )

    assert payload["assignment"]["dispatch"]["discussion_with"] == "User"
    assert payload["assignment"]["dispatch"]["handback"] == {
        "policy": "specified-or-worker-selected-im",
        "requested_target": None,
        "resolved_target": None,
        "selection_required": True,
    }


def test_worker_dispatch_contract_rejects_invalid_channel_or_mismatched_im() -> None:
    with pytest.raises(mod.OnboardingError, match="dispatch_channel"):
        mod.build_onboarding(
            ROOT,
            identity="Worker",
            intent="delivery",
            entry="direct-assignment",
            evidence={**EVIDENCE["direct-assignment"], "dispatch_channel": "cm"},
        )

    with pytest.raises(mod.OnboardingError, match="dispatch_owner"):
        mod.build_onboarding(
            ROOT,
            identity="Worker",
            intent="delivery",
            entry="direct-assignment",
            evidence={
                **EVIDENCE["direct-assignment"],
                "dispatch_channel": "im",
                "dispatch_owner": None,
            },
        )

    with pytest.raises(mod.OnboardingError, match="same dispatching IM"):
        mod.build_onboarding(
            ROOT,
            identity="Worker",
            intent="delivery",
            entry="direct-assignment",
            evidence={
                **EVIDENCE["direct-assignment"],
                "dispatch_channel": "im",
                "dispatch_owner": "IM-1",
                "handback_target": "IM-2",
            },
        )

    with pytest.raises(mod.OnboardingError, match="handback_target"):
        mod.build_onboarding(
            ROOT,
            identity="Worker",
            intent="delivery",
            entry="direct-assignment",
            evidence={
                **EVIDENCE["direct-assignment"],
                "dispatch_channel": "user",
                "handback_target": "CM",
            },
        )


def test_issue_solver_requires_issue_entry_and_domain_sources():
    payload = mod.build_onboarding(ROOT, identity="issue-solver", intent="backend", entry="issue", evidence=EVIDENCE["issue"])

    assert payload["identity"]["id"] == "issue-solver"
    assert payload["task"]["intent"] == "backend"
    assert payload["task"]["skill_intent"] == "delivery-worktree"
    assert payload["assignment"]["required_external"] == [
        "Issue assignment packet", "Issue acceptance", "structured Scope"
    ]
    assert "docs/sop/backend.md" in payload["domain_sources"]


def test_ios_worker_loads_delivery_dependency_and_ios_specialist():
    payload = mod.build_onboarding(ROOT, identity="Worker", intent="ios", entry="direct-assignment", evidence=EVIDENCE["direct-assignment"])

    assert payload["skills"]["primary"] == "ios-simulator-verification"
    assert payload["skills"]["selected"] == [
        "kg-router", "worktree-flow", "ios-simulator-verification"
    ]


def test_backend_worker_can_select_an_explicit_debug_specialist():
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="backend",
        entry="direct-assignment",
        specialist_intent="bug",
        evidence=EVIDENCE["direct-assignment"],
    )

    assert payload["task"]["skill_intent"] == "delivery-worktree"
    assert payload["task"]["specialist_intent"] == "bug"
    assert payload["task"]["effective_skill_intent"] == "bug"
    assert payload["skills"]["control_primary"] == "worktree-flow"
    assert payload["skills"]["primary"] == "app-debug"
    assert "control_route_command" not in payload["skills"]
    assert payload["skills"]["selected"] == ["kg-router", "worktree-flow", "app-debug"]
    assert "docs/sop/debug.md" in payload["domain_sources"]


def test_specialist_domain_sources_follow_the_effective_route():
    payload = mod.build_onboarding(
        ROOT,
        identity="Release operator",
        intent="release",
        entry="release",
        specialist_intent="podcast-publish",
        evidence=EVIDENCE["release"],
    )

    assert payload["skills"]["primary"] == "podcast-publish"
    assert "docs/sop/podcast_pipeline.md" in payload["domain_sources"]
    assert "docs/sop/podcast_pipeline.md" in payload["load_order"][-1]["sources"]


def test_cm_can_route_read_only_cost_analysis_without_loading_delivery_tools():
    payload = mod.build_onboarding(
        ROOT,
        identity="CM",
        intent="delivery",
        entry="coordination",
        specialist_intent="billing",
        evidence={
            "GitHub Issue/PR or direct assignment": "monthly cost review",
            "Scope decision": "read-only provider and baseline data",
        },
    )

    assert payload["skills"]["primary"] == "billing"
    assert payload["skills"]["selected"] == ["kg-router", "billing"]
    assert "docs/sop/cost_review.md" in payload["domain_sources"]


def test_specialist_route_is_identity_scoped():
    with pytest.raises(mod.OnboardingError, match="不允許 specialist"):
        mod.build_onboarding(
            ROOT,
            identity="DS",
            intent="docs",
            entry="pr-review",
            specialist_intent="bug",
            evidence=EVIDENCE["ds-pr-review"],
        )


def test_identity_intent_entry_mismatch_fails_closed():
    with pytest.raises(mod.OnboardingError, match="identity 不允許 intent"):
        mod.build_onboarding(ROOT, identity="Worker", intent="review", entry="pr-review")

    with pytest.raises(mod.OnboardingError, match="entry 不符合 identity"):
        mod.build_onboarding(ROOT, identity="Issue Solver", intent="backend", entry="direct-assignment")


@pytest.mark.parametrize(
    ("identity", "intent", "entry", "primary"),
    [
        ("CR", "review", "pr-review", "code-review"),
        ("DS", "docs", "pr-review", "kg-docs-control-plane"),
        ("Release operator", "release", "release", "source-command-release"),
        ("IM", "delivery", "issue-planning", "github-coordination"),
        ("CM", "release", "merge", "source-command-release"),
    ],
)
def test_every_canonical_identity_has_a_real_onboarding_route(identity, intent, entry, primary):
    evidence_key = "ds-pr-review" if identity == "DS" else entry
    payload = mod.build_onboarding(ROOT, identity=identity, intent=intent, entry=entry, evidence=EVIDENCE[evidence_key])
    assert payload["status"] == "ready"
    assert payload["skills"]["primary"] == primary
    assert [step["phase"] for step in payload["load_order"]] == [
        "project", "identity", "assignment", "skill", "domain"
    ]


def test_missing_project_onboarding_source_fails_closed(tmp_path: Path):
    manifest = (ROOT / "ops" / "context_plane.json").read_text(encoding="utf-8")
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "context_plane.json").write_text(manifest, encoding="utf-8")
    with pytest.raises(mod.OnboardingError, match="onboarding source"):
        mod.build_onboarding(tmp_path, identity="Worker", intent="delivery", entry="direct-assignment")


def test_missing_assignment_evidence_blocks_before_skill_loading() -> None:
    payload = mod.build_onboarding(ROOT, identity="Worker", intent="delivery", entry="direct-assignment")
    assert payload["status"] == "awaiting-assignment"
    assert payload["blocked_at"] == "assignment"
    assert payload["assignment"]["missing"] == [
        "User/IM assignment", "acceptance", "structured Scope", "dispatch_channel"
    ]
    assert [step["phase"] for step in payload["load_order"]] == ["project", "identity", "assignment"]
    assert "skills" not in payload


def test_missing_assignment_blocks_before_invalid_specialist_resolution() -> None:
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="backend",
        entry="direct-assignment",
        specialist_intent="not-a-real-specialist",
    )
    assert payload["status"] == "awaiting-assignment"
    assert payload["blocked_at"] == "assignment"
    assert "skills" not in payload
