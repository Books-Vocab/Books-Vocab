"""Contract tests for campaign child receipts and parent reservation.

These tests intentionally exercise the pre-worktree boundary.  A parent must prove
that the complete child set is immutable before opening an integration checkout;
missing or ambiguous evidence must not leave a registry claim behind.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAMPAIGN = _load("worktree_campaign_parent_tests", ROOT / "ops/lib/worktree_campaign.py")
REGISTRY = _load("worktree_registry_parent_tests", ROOT / "ops/worktree_registry.py")
ORCHESTRATE = _load(
    "worktree_orchestrate_parent_tests", ROOT / "ops/worktree_orchestrate.py"
)

BASE = "a" * 40


def reservation(*, campaign_id: str = "campaign-parent", digest: str = "manifest-1"):
    return {
        "schema": CAMPAIGN.RESERVATION_SCHEMA,
        "campaign_id": campaign_id,
        "coordinator": "team-a",
        "base": BASE,
        "manifest_digest": digest,
        "partitions": {
            "p1": {"quota": 1, "ticket_ids": ["IMP-p1"],
                   "claimed": {"IMP-p1": {"branch": "feat/p1"}}},
            "p2": {"quota": 1, "ticket_ids": ["IMP-p2"],
                   "claimed": {"IMP-p2": {"branch": "feat/p2"}}},
            "p3": {"quota": 1, "ticket_ids": ["IMP-p3"],
                   "claimed": {"IMP-p3": {"branch": "feat/p3"}}},
        },
        "ticket_ids": ["IMP-p1", "IMP-p2", "IMP-p3"],
    }


def child(res: dict, partition: str, *, branch: str | None = None,
          tip: str | None = None, digest: str | None = None,
          tickets: list[str] | None = None, seal: bool = True,
          campaign_id: str | None = None):
    ticket_ids = tickets or list(res["partitions"][partition]["ticket_ids"])
    tip = tip or (partition + "0") * 20
    branch = branch or f"feat/{partition}"
    receipt = {
        "schema": CAMPAIGN.CHILD_RECEIPT_SCHEMA,
        "role": "child",
        "campaign_id": campaign_id or res["campaign_id"],
        "partition_id": partition,
        "branch": branch,
        "manifest_digest": digest or res["manifest_digest"],
        "manifest_head_sha": tip,
        "source_branches": [branch],
        "ticket_ids": ticket_ids,
        "outcomes": [
            {"ticket_id": ticket_id, "outcome": "changed",
             "acceptance_status": "green", "closure": "fixed"}
            for ticket_id in ticket_ids
        ],
        "outcome_seal_digest": "seal-" + partition,
    }
    record = {
        "status": "active",
        "branch": branch,
        "path": f"/tmp/{partition}",
        "base": res["base"],
        "base_sha": res["base"],
        "backlog": ticket_ids,
        "handed_back_sha": tip,
        "claimed_at": "2026-08-11T00:00:00Z",
        "handed_back_at": "2026-08-11T00:00:00Z",
        "handback_seal": None,
        "campaign_id": campaign_id or res["campaign_id"],
        "partition_id": partition,
        "role": "child",
        "child_receipt": receipt,
    }
    if seal:
        body = REGISTRY._seal_body(
            record, base_sha=res["base"], tip_sha=tip,
            outcomes=receipt["outcomes"], handed_back_at=record["handed_back_at"],
        )
        record["handback_seal"] = REGISTRY._seal_with_digest(body)
        record["handback_outcomes"] = receipt["outcomes"]
        record["child_receipt"]["outcome_seal_digest"] = record["handback_seal"]["digest"]
    return record


def complete_records(res: dict) -> list[dict]:
    return [child(res, partition) for partition in ("p1", "p2", "p3")]


def test_parent_snapshot_accepts_exact_child_partition_set():
    result = CAMPAIGN.parent_child_snapshot(
        reservation(), complete_records(reservation()),
        campaign_id="campaign-parent", base_sha=BASE,
    )
    assert result["ok"] is True, result
    assert result["source_refs"] == {
        "feat/p1": "p10" * 20,
        "feat/p2": "p20" * 20,
        "feat/p3": "p30" * 20,
    }
    assert result["ticket_map"]["IMP-p2"]["child_sha"] == "p20" * 20


def test_parent_snapshot_rejects_record_metadata_drift():
    res = reservation()
    rows = complete_records(res)
    rows[0]["campaign_id"] = "other-campaign"
    result = CAMPAIGN.parent_child_snapshot(
        res, rows, campaign_id="campaign-parent", base_sha=BASE,
    )
    assert result["ok"] is False, result
    assert any(problem["kind"] == "child-record-campaign-mismatch"
               for problem in result["problems"]), result


def test_parent_snapshot_requires_campaign_manifest_digest():
    res = reservation()
    res.pop("manifest_digest")
    result = CAMPAIGN.parent_child_snapshot(
        res, complete_records(reservation()),
        campaign_id="campaign-parent", base_sha=BASE,
    )
    assert result["ok"] is False, result
    assert any(problem["kind"] == "manifest-digest-missing"
               for problem in result["problems"]), result


def test_parent_snapshot_rejects_source_branch_outside_partition_claims():
    res = reservation()
    rows = complete_records(res)
    rows[0]["child_receipt"]["source_branches"] = ["feat/not-claimed"]
    result = CAMPAIGN.parent_child_snapshot(
        res, rows, campaign_id="campaign-parent", base_sha=BASE,
    )
    assert result["ok"] is False, result
    assert any(problem["kind"] == "manifest-source-foreign"
               for problem in result["problems"]), result


def test_parent_snapshot_rejects_receipt_outcome_drift_from_seal():
    res = reservation()
    rows = complete_records(res)
    rows[0]["child_receipt"]["outcomes"] = [
        {**rows[0]["child_receipt"]["outcomes"][0], "closure": "accepted"},
    ]
    result = CAMPAIGN.parent_child_snapshot(
        res, rows, campaign_id="campaign-parent", base_sha=BASE,
    )
    assert result["ok"] is False, result
    assert any(problem["kind"] == "outcome-seal-receipt-mismatch"
               for problem in result["problems"]), result


@pytest.mark.parametrize(
    ("mutate", "kind"),
    [
        (lambda rows: rows.pop(), "missing-child"),
        (lambda rows: rows.append(rows[0].copy()), "duplicate-partition"),
        (lambda rows: rows[1]["child_receipt"].update(campaign_id="other"),
         "foreign-campaign"),
        (lambda rows: rows[1].update(handed_back_sha="b" * 40), "stale-tip"),
        (lambda rows: rows[1]["child_receipt"].update(manifest_digest="drift"),
         "manifest-digest-drift"),
        (lambda rows: rows[1]["child_receipt"].pop("outcome_seal_digest"),
         "outcome-seal-missing"),
        (lambda rows: rows[1]["child_receipt"].update(ticket_ids=["IMP-extra"]),
         "ticket-count-mismatch"),
    ],
)
def test_parent_snapshot_fail_closed_without_mutating_children(mutate, kind):
    res = reservation()
    rows = complete_records(res)
    before = json.dumps(rows, sort_keys=True)
    mutate(rows)
    result = CAMPAIGN.parent_child_snapshot(res, rows,
                                            campaign_id="campaign-parent",
                                            base_sha=BASE)
    assert result["ok"] is False, result
    assert any(problem["kind"] == kind for problem in result["problems"]), result
    assert json.dumps(rows, sort_keys=True) != before or kind == "missing-child"


def test_parent_reservation_is_atomic_and_second_owner_is_refused(tmp_path):
    state = tmp_path / "registry.json"
    res = reservation()
    state.write_text(json.dumps({
        "schema": REGISTRY.SCHEMA,
        "records": complete_records(res),
        "campaign_reservations": [res],
    }))
    first = REGISTRY.claim_parent_integration(
        state, campaign_id="campaign-parent", parent_branch="feat/parent",
        parent_slug="parent-one", base_sha=BASE, request_id="req-1",
    )
    assert first["ok"] is True, first
    second = REGISTRY.claim_parent_integration(
        state, campaign_id="campaign-parent", parent_branch="feat/parent-2",
        parent_slug="parent-two", base_sha=BASE, request_id="req-2",
    )
    assert second["ok"] is False, second
    assert any(item["kind"] == "parent-already-owned"
               for item in second["problems"]), second
    # A same-request retry is an idempotent read, not a second owner.
    retry = REGISTRY.claim_parent_integration(
        state, campaign_id="campaign-parent", parent_branch="feat/parent",
        parent_slug="parent-one", base_sha=BASE, request_id="req-1",
    )
    assert retry["ok"] is True and retry["mode"] == "idempotent", retry
    payload = json.loads(state.read_text())
    assert len(payload["parent_reservations"]) == 1
    assert payload["parent_reservations"][0]["owner"]["branch"] == "feat/parent"


def test_parent_reservation_refusal_leaves_registry_byte_identical(tmp_path):
    state = tmp_path / "registry.json"
    res = reservation()
    rows = complete_records(res)[:-1]
    state.write_text(json.dumps({
        "schema": REGISTRY.SCHEMA,
        "records": rows,
        "campaign_reservations": [res],
    }, indent=2) + "\n")
    before = state.read_bytes()
    result = REGISTRY.claim_parent_integration(
        state, campaign_id="campaign-parent", parent_branch="feat/parent",
        parent_slug="parent-one", base_sha=BASE, request_id="req-1",
    )
    assert result["ok"] is False, result
    assert state.read_bytes() == before


def test_integrate_parent_and_branches_are_parser_mutually_exclusive():
    parser = ORCHESTRATE.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "integrate", "--slug", "parent-one", "--branches", "feat/child",
            "--campaign", "campaign-parent", "--parent",
        ])
    parsed = parser.parse_args([
        "integrate", "--slug", "parent-one", "--campaign", "campaign-parent",
        "--parent",
    ])
    assert parsed.parent is True
    assert parsed.branches is None
    assert parsed.campaign == "campaign-parent"


def test_parent_command_refuses_missing_campaign_without_traceback(tmp_path, capsys):
    args = ORCHESTRATE.build_parser().parse_args([
        "integrate", "--slug", "parent-one", "--campaign", "campaign-parent",
        "--parent", "--state", str(tmp_path / "registry.json"), "--json",
    ])
    assert ORCHESTRATE.cmd_integrate(args) == ORCHESTRATE.EXIT_BLOCK
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["problems"][0]["kind"] == "campaign-reservation-missing"


def test_child_manifest_projects_to_receipt_with_tip_and_typed_outcomes(tmp_path):
    res = reservation()
    record = child(res, "p1")
    manifest_path = tmp_path / "child-completed.json"
    manifest_path.write_text(json.dumps({
        "head_sha": record["handed_back_sha"],
        "branches": [record["branch"]],
        "campaign_manifest_digest": res["manifest_digest"],
    }))
    receipt = REGISTRY._child_receipt_from_manifest(
        record, campaign_id=res["campaign_id"], partition_id="p1", role="child",
        manifest_path=manifest_path, tip_sha=record["handed_back_sha"],
        seal={"digest": "outcome-seal", "outcomes": record["child_receipt"]["outcomes"]},
    )
    assert receipt["schema"] == CAMPAIGN.CHILD_RECEIPT_SCHEMA
    assert receipt["manifest_head_sha"] == record["handed_back_sha"]
    assert receipt["manifest_digest"]
    assert receipt["campaign_manifest_digest"] == res["manifest_digest"]
    assert receipt["ticket_ids"] == ["IMP-p1"]
