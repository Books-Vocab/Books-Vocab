from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-review.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_agent_review_runs_from_trusted_events_only() -> None:
    source = _workflow()

    assert "pull_request_target:" in source
    assert "pull_request_review:" in source
    assert "pull_request_review_comment:" in source
    assert "issue_comment:" in source
    assert "\n  pull_request:\n" not in source
    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1" in source
    )
    assert (
        "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1"
        in source
    )
    assert "ref: ${{ github.event.repository.default_branch }}" in source
    assert "github.event.pull_request.head.sha" not in source
    assert "github.event.comment.body, '@codex review'" in source


def test_agent_review_has_read_only_source_permissions_and_check_write() -> None:
    source = _workflow()

    assert "contents: read" in source
    assert "issues: read" in source
    assert "pull-requests: read" in source
    assert "checks: write" in source
    assert "REVIEW_BOT: chatgpt-codex-connector[bot]" in source


def test_agent_review_is_bound_to_pr_head_and_emits_exact_check() -> None:
    source = _workflow()

    assert 'head_sha="$(jq -r' in source
    assert 'gh api "repos/$REPOSITORY/commits/$head_sha"' in source
    assert '--arg head_sha "$head_sha"' in source
    assert 'status:"completed"' in source
    assert "conclusion:$conclusion" in source
    assert "repos/$REPOSITORY/check-runs" in source


def test_agent_review_rejects_hard_findings_but_accepts_nonblocking_review() -> None:
    source = _workflow()

    assert "P(0|1)" in source
    assert "security" in source
    assert "blocker_evidence" in source
    assert 'review_evidence" -gt 0 || "$reaction_evidence" -gt 0' in source
    assert "P2" not in source


def test_agent_review_evidence_has_one_required_check_identity() -> None:
    source = _workflow()

    # The workflow posts the required ``agent-review`` check explicitly.  Its
    # Actions job must use a different name; otherwise a cancelled job check
    # and the evidence check share one required context and can block native
    # merge-queue admission even when the evidence check is green.
    assert "\n  agent-review:\n" not in source
    assert "\n  agent-review-evidence:\n" in source
