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


def test_worker_direct_assignment_loads_project_identity_skill_then_domain() -> None:
    payload = mod.build_onboarding(ROOT, identity="Worker", intent="delivery", entry="direct-assignment")

    assert payload["schema"] == "kg.agent_onboarding.v1"
    assert payload["status"] == "ready"
    assert payload["identity"]["id"] == "worker"
    assert payload["identity"]["machine_role"] == "contributor"
    assert payload["task"]["entry"] == "direct-assignment"
    assert payload["skills"]["primary"] == "worktree-flow"
    assert payload["load_order"][0] == {
        "phase": "project",
        "required": True,
        "sources": ["docs/reference/project_onboarding.md"],
    }
    assert [step["phase"] for step in payload["load_order"]] == [
        "project", "identity", "assignment", "skill", "domain"
    ]
    assert payload["authority"]["granted"] is False


def test_issue_solver_requires_issue_entry_and_domain_sources():
    payload = mod.build_onboarding(ROOT, identity="issue-solver", intent="backend", entry="issue")

    assert payload["identity"]["id"] == "issue-solver"
    assert payload["task"]["intent"] == "backend"
    assert payload["task"]["skill_intent"] == "delivery-worktree"
    assert payload["assignment"]["required_external"] == [
        "GitHub Issue", "Issue acceptance", "structured Scope"
    ]
    assert "docs/sop/backend.md" in payload["domain_sources"]


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
    payload = mod.build_onboarding(ROOT, identity=identity, intent=intent, entry=entry)
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
