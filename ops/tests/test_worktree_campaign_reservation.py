"""Bounded contract tests for campaign active-record projections."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))
from lib import worktree_campaign as campaign

BASE = "a" * 40


def _ticket(ticket_id: str, path: str = "ops/shared.py") -> dict:
    return {
        "id": ticket_id,
        "partition": "p1",
        "write_sites": [{"path": path, "mode": "write"}],
        "blocked_by": [],
        "co_land_group": None,
    }


def _manifest(*, campaign_id: str = "campaign-1", path: str = "ops/shared.py") -> dict:
    return {
        "schema": campaign.SCHEMA,
        "campaign_id": campaign_id,
        "coordinator": "coord-a",
        "base": BASE,
        "partitions": [{"id": "p1", "quota": 1}],
        "tickets": [_ticket("T-1", path)],
    }


def _reservation(tmp_path: Path, *, path: str = "ops/shared.py") -> tuple[dict, dict]:
    manifest = _manifest(path=path)
    manifest_path = tmp_path / "campaign.json"
    payload = campaign.json_bytes(campaign.canonical_manifest(manifest))
    manifest_path.write_bytes(payload)
    reservation = campaign.reservation_record(manifest, str(manifest_path), "now")
    reservation["partitions"]["p1"]["claimed"] = {
        "T-1": {"branch": "feat/campaign-1", "path": "child"}
    }
    record = {
        "status": "active",
        "campaign_id": "campaign-1",
        "partition_id": "p1",
        "ticket_id": "T-1",
        "branch": "feat/campaign-1",
        "base_sha": BASE,
        "manifest_digest": hashlib.sha256(payload).hexdigest(),
    }
    return reservation, record


def test_valid_r3_ticketed_active_record_has_one_canonical_projection(tmp_path):
    reservation, record = _reservation(tmp_path)

    details, owner, problems = campaign.project_active_record(
        record, [reservation], current_base=BASE
    )

    assert problems == []
    assert owner is reservation
    assert details == {
        "T-1": {
            "id": "T-1",
            "partition": "p1",
            "write_sites": [{"path": "ops/shared.py", "mode": "write"}],
            "blocked_by": [],
            "co_land_group": None,
        }
    }


@pytest.mark.parametrize(
    "record",
    [
        {"status": "active", "branch": "feat/ordinary", "backlog": ["T-1"]},
        {
            "status": "active",
            "campaign_id": "active:feat/campaign-1",
            "branch": "feat/campaign-1",
            "backlog": ["T-1"],
        },
    ],
)
def test_missing_or_legacy_provenance_is_explicitly_fail_closed(tmp_path, record):
    reservation, _ = _reservation(tmp_path)

    details, owner, problems = campaign.project_active_record(
        record, [reservation], current_base=BASE
    )

    assert details is None
    assert owner is None
    assert any(
        problem["kind"] == "existing-active-provenance-unknown" for problem in problems
    )


def test_missing_manifest_is_explicitly_fail_closed(tmp_path):
    reservation, record = _reservation(tmp_path)
    reservation["manifest_path"] = str(tmp_path / "missing.json")

    details, owner, problems = campaign.project_active_record(
        record, [reservation], current_base=BASE
    )

    assert details is None
    assert owner is reservation
    assert any(problem["kind"] == "existing-manifest-missing" for problem in problems)


@pytest.mark.parametrize(
    ("mutate", "kind"),
    [
        (
            lambda reservation, record: record.update(base_sha="b" * 40),
            "existing-manifest-base-drift",
        ),
        (
            lambda reservation, record: record.update(manifest_digest="0" * 64),
            "existing-manifest-digest-drift",
        ),
        (
            lambda reservation, record: reservation.update(base="b" * 40),
            "existing-manifest-base-drift",
        ),
        (
            lambda reservation, record: reservation.update(manifest_digest="0" * 64),
            "existing-manifest-digest-drift",
        ),
    ],
)
def test_base_and_digest_drift_is_explicitly_fail_closed(tmp_path, mutate, kind):
    reservation, record = _reservation(tmp_path)
    mutate(reservation, record)

    details, _, problems = campaign.project_active_record(
        record, [reservation], current_base=BASE
    )

    assert details is None
    assert any(problem["kind"] == kind for problem in problems)


def test_ticket_or_write_site_scope_drift_is_explicitly_fail_closed(tmp_path):
    reservation, record = _reservation(tmp_path)
    reservation["ticket_details"]["T-1"]["write_sites"] = [
        {"path": "ops/drifted.py", "mode": "write"}
    ]

    details, _, problems = campaign.project_active_record(
        record, [reservation], current_base=BASE
    )

    assert details is None
    assert any(
        problem["kind"] == "existing-manifest-scope-drift" for problem in problems
    )


def test_next_campaign_refuses_shared_path_against_valid_projection(tmp_path):
    reservation, record = _reservation(tmp_path)
    requested = _manifest(campaign_id="campaign-2")

    problems = campaign.validate_manifest(
        requested,
        current_base=BASE,
        backlog_entries=requested["tickets"],
        existing_reservations=[reservation, record],
    )

    assert any(problem["kind"] == "write-site-collision" for problem in problems), (
        problems
    )


def test_projection_does_not_mutate_record_or_reservation(tmp_path):
    reservation, record = _reservation(tmp_path)
    before = json.dumps([record, reservation], sort_keys=True)

    campaign.project_active_record(record, [reservation], current_base=BASE)

    assert json.dumps([record, reservation], sort_keys=True) == before
