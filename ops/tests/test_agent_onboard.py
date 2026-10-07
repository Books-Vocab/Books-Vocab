from __future__ import annotations

import importlib.util
import json
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
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="delivery",
        entry="direct-assignment",
        evidence=EVIDENCE["direct-assignment"],
    )

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
        "project",
        "identity",
        "assignment",
        "skill",
        "domain",
    ]
    assert (
        payload["assignment"]["evidence"]["acceptance"] == "route and tests are green"
    )
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


def test_worker_user_dispatch_requires_im_selection_before_hand_back_when_unspecified() -> (
    None
):
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
                "dispatch_owner": "CM",
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
    payload = mod.build_onboarding(
        ROOT,
        identity="issue-solver",
        intent="backend",
        entry="issue",
        evidence=EVIDENCE["issue"],
    )

    assert payload["identity"]["id"] == "issue-solver"
    assert payload["task"]["intent"] == "backend"
    assert payload["task"]["skill_intent"] == "delivery-worktree"
    assert payload["assignment"]["required_external"] == [
        "Issue assignment packet",
        "Issue acceptance",
        "structured Scope",
    ]
    assert "docs/sop/backend.md" in payload["domain_sources"]


def test_ios_worker_loads_delivery_dependency_and_ios_specialist():
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="ios",
        entry="direct-assignment",
        evidence=EVIDENCE["direct-assignment"],
    )

    assert payload["skills"]["primary"] == "ios-simulator-verification"
    assert payload["skills"]["selected"] == [
        "kg-router",
        "worktree-flow",
        "ios-simulator-verification",
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
        mod.build_onboarding(
            ROOT, identity="Worker", intent="review", entry="pr-review"
        )

    with pytest.raises(mod.OnboardingError, match="entry 不符合 identity"):
        mod.build_onboarding(
            ROOT, identity="Issue Solver", intent="backend", entry="direct-assignment"
        )


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
def test_every_canonical_identity_has_a_real_onboarding_route(
    identity, intent, entry, primary
):
    evidence_key = "ds-pr-review" if identity == "DS" else entry
    payload = mod.build_onboarding(
        ROOT,
        identity=identity,
        intent=intent,
        entry=entry,
        evidence=EVIDENCE[evidence_key],
    )
    assert payload["status"] == "ready"
    assert payload["skills"]["primary"] == primary
    assert [step["phase"] for step in payload["load_order"]] == [
        "project",
        "identity",
        "assignment",
        "skill",
        "domain",
    ]


def test_missing_project_onboarding_source_fails_closed(tmp_path: Path):
    manifest = (ROOT / "ops" / "context_plane.json").read_text(encoding="utf-8")
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "context_plane.json").write_text(manifest, encoding="utf-8")
    with pytest.raises(mod.OnboardingError, match="onboarding source"):
        mod.build_onboarding(
            tmp_path, identity="Worker", intent="delivery", entry="direct-assignment"
        )


def test_missing_assignment_evidence_blocks_before_skill_loading() -> None:
    payload = mod.build_onboarding(
        ROOT, identity="Worker", intent="delivery", entry="direct-assignment"
    )
    assert payload["status"] == "awaiting-assignment"
    assert payload["blocked_at"] == "assignment"
    assert payload["assignment"]["missing"] == [
        "User/IM assignment",
        "acceptance",
        "structured Scope",
        "dispatch_channel",
    ]
    assert [step["phase"] for step in payload["load_order"]] == [
        "project",
        "identity",
        "assignment",
    ]
    assert "skills" not in payload


def _fill_placeholders(value, key: str = ""):
    """Replace every template placeholder with a value a real assignment would carry."""
    if isinstance(value, dict):
        return {name: _fill_placeholders(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_fill_placeholders(item, key) for item in value]
    if isinstance(value, str) and value.startswith("<") and value.endswith(">"):
        return {
            "dispatch_channel": "im",
            "dispatch_owner": "IM-1",
            "operation": "modify",
            "path": "ops/agent_onboard.py",
        }.get(key, f"filled {key}")
    return value


def _route_matrix() -> list[tuple[str, str, str]]:
    manifest = json.loads(
        (ROOT / "ops" / "context_plane.json").read_text(encoding="utf-8")
    )
    return [
        (definition["label"], definition["allowed_intents"][0], entry)
        for definition in manifest["identities"].values()
        for entry in definition["entry_modes"]
    ]


def test_missing_evidence_reports_every_key_and_a_ready_to_copy_template_at_once() -> (
    None
):
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="delivery",
        entry="direct-assignment",
        evidence={"dispatch_channel": "im"},
    )

    assignment = payload["assignment"]
    assert payload["status"] == "awaiting-assignment"
    # The conditional dispatch_owner is reported in the same round as the
    # manifest keys instead of surfacing as a later, separate error.
    assert assignment["missing"] == [
        "User/IM assignment",
        "acceptance",
        "structured Scope",
        "dispatch_owner",
    ]
    assert assignment["invalid"] == []
    assert assignment["evidence_spec"]["conditional"][0]["key"] == "dispatch_owner"
    assert assignment["evidence_spec"]["allowed_values"]["dispatch_channel"] == [
        "im",
        "user",
    ]
    template = assignment["evidence_template"]
    assert list(template) == [
        "User/IM assignment",
        "acceptance",
        "structured Scope",
        "dispatch_channel",
        "dispatch_owner",
    ]
    assert template["dispatch_channel"] == "im"
    assert template["structured Scope"]["schema"] == "kg.worktree.scope.v1"
    command = assignment["retry_command"]
    assert command.startswith(
        "./ops/agent_onboard.py --identity Worker --intent delivery --entry direct-assignment --evidence '"
    )
    assert command.endswith(" --json")


def test_invalid_values_are_reported_together_with_missing_keys() -> None:
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="delivery",
        entry="direct-assignment",
        evidence={"dispatch_channel": "cm"},
    )

    assert payload["status"] == "awaiting-assignment"
    assert payload["assignment"]["missing"] == [
        "User/IM assignment",
        "acceptance",
        "structured Scope",
    ]
    assert [problem["key"] for problem in payload["assignment"]["invalid"]] == [
        "dispatch_channel"
    ]


def test_non_string_dispatch_channel_is_invalid_not_ignored() -> None:
    with pytest.raises(mod.EvidenceError, match="dispatch_channel"):
        mod.build_onboarding(
            ROOT,
            identity="Worker",
            intent="delivery",
            entry="direct-assignment",
            evidence={**EVIDENCE["direct-assignment"], "dispatch_channel": 1},
        )


@pytest.mark.parametrize(("identity", "intent", "entry"), _route_matrix())
def test_unedited_template_fails_closed_and_filled_template_is_ready(
    identity, intent, entry
) -> None:
    template_payload = mod.build_evidence_template(
        ROOT, identity=identity, intent=intent, entry=entry
    )
    template = template_payload["evidence_template"]
    assert template_payload["schema"] == "kg.agent_onboarding.evidence_template.v1"
    assert set(template_payload["evidence_spec"]["required"]) <= set(template)

    # Copying the template verbatim must never satisfy the assignment boundary.
    unedited = mod.build_onboarding(
        ROOT, identity=identity, intent=intent, entry=entry, evidence=template
    )
    assert unedited["status"] == "awaiting-assignment"
    assert set(unedited["assignment"]["required_external"]) <= set(
        unedited["assignment"]["missing"]
    )

    filled = mod.build_onboarding(
        ROOT,
        identity=identity,
        intent=intent,
        entry=entry,
        evidence=_fill_placeholders(template),
    )
    assert filled["status"] == "ready"


def test_placeholder_left_in_an_optional_key_blocks_ready() -> None:
    payload = mod.build_onboarding(
        ROOT,
        identity="Worker",
        intent="delivery",
        entry="direct-assignment",
        evidence={
            **EVIDENCE["direct-assignment"],
            "dispatch_channel": "user",
            "dispatch_owner": "<dispatching IM>",
        },
    )

    assert payload["status"] == "awaiting-assignment"
    assert payload["assignment"]["missing"] == []
    assert payload["assignment"]["unfilled"] == ["dispatch_owner"]
    assert "dispatch_owner" not in payload["assignment"]["evidence_template"]


def test_cli_prints_evidence_template_without_assignment(capsys) -> None:
    code = mod.main(
        [
            "--identity",
            "Issue Solver",
            "--intent",
            "backend",
            "--entry",
            "issue",
            "--print-evidence-template",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence_spec"]["required"] == [
        "Issue assignment packet",
        "Issue acceptance",
        "structured Scope",
    ]
    assert payload["command"].startswith(
        "./ops/agent_onboard.py --identity 'Issue Solver' --intent backend --entry issue --evidence '"
    )


def test_cli_awaiting_assignment_names_every_missing_key_on_stderr(capsys) -> None:
    code = mod.main(
        [
            "--identity",
            "Worker",
            "--intent",
            "delivery",
            "--entry",
            "direct-assignment",
            "--json",
        ]
    )

    assert code == 3
    err = capsys.readouterr().err
    assert (
        "missing: User/IM assignment, acceptance, structured Scope, dispatch_channel"
        in err
    )
    # The last stderr line is the raw, unescaped command an agent can copy.
    assert err.splitlines()[-1].startswith(
        "./ops/agent_onboard.py --identity Worker --intent delivery --entry direct-assignment "
        '--evidence \'{"User/IM assignment":'
    )


def test_cli_plain_template_ends_with_unescaped_command(capsys) -> None:
    code = mod.main(
        [
            "--identity",
            "Worker",
            "--intent",
            "ios",
            "--entry",
            "direct-assignment",
            "--print-evidence-template",
        ]
    )

    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    assert (
        lines[0]
        == "required: User/IM assignment, acceptance, structured Scope, dispatch_channel"
    )
    assert any(
        line.startswith("conditional: dispatch_owner (when dispatch_channel=im)")
        for line in lines
    )
    assert lines[-1].startswith(
        "./ops/agent_onboard.py --identity Worker --intent ios --entry direct-assignment --evidence '{"
    )


def test_cli_invalid_evidence_json_fails_closed_with_template_hint(capsys) -> None:
    code = mod.main(
        [
            "--identity",
            "Worker",
            "--intent",
            "delivery",
            "--entry",
            "direct-assignment",
            "--evidence",
            "{not json",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "--evidence" in err and "JSON" in err
    assert "--print-evidence-template" in err


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
