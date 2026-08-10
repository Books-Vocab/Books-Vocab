"""Contract tests for campaign-scoped worktree reservations.

The reservation plane is deliberately tested separately from the later parent
integration plane: a campaign owns ticket/site allocation, while active registry
records own individual child worktrees.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CAMPAIGN = _load("worktree_campaign", ROOT / "ops/lib/worktree_campaign.py")
REGISTRY = _load("worktree_registry_campaign_tests", ROOT / "ops/worktree_registry.py")
ORCHESTRATE = _load(
    "worktree_orchestrate_campaign_tests", ROOT / "ops/worktree_orchestrate.py"
)

BASE = "a" * 40


def ticket(ticket_id: str, partition: str, path: str, *, mode: str = "write",
           symbol: str | None = None, blocked_by: list[str] | None = None,
           co_land_group: str | None = None) -> dict:
    site = {"path": path, "mode": mode}
    if symbol is not None:
        site["symbol"] = symbol
    return {
        "id": ticket_id,
        "status": "triaged",
        "groomed_by": "test",
        "partition": partition,
        "write_sites": [site],
        "blocked_by": blocked_by or [],
        "co_land_group": co_land_group,
    }


def manifest(*, campaign_id: str = "campaign-1", coordinator: str = "coord-a",
             base: str = BASE, tickets: list[dict] | None = None,
             quotas: dict[str, int] | None = None) -> dict:
    entries = tickets or [
        ticket("IMP-20260810-aa0001", "p1", "ops/a.py"),
        ticket("IMP-20260810-bb0002", "p1", "ops/b.py"),
        ticket("IMP-20260810-cc0003", "p2", "ops/c.py"),
    ]
    quota = quotas or {"p1": 2, "p2": 1}
    return {
        "schema": CAMPAIGN.SCHEMA,
        "campaign_id": campaign_id,
        "coordinator": coordinator,
        "base": base,
        "partitions": [
            {"id": partition_id, "quota": partition_quota}
            for partition_id, partition_quota in quota.items()
        ],
        "tickets": entries,
    }


def reserve(state: Path, request: dict, *, entries: list[dict] | None = None,
            current_base: str = BASE, commit: bool = True) -> dict:
    return REGISTRY.reserve_campaign(
        state,
        request,
        current_base=current_base,
        backlog_entries=entries or request["tickets"],
        commit=commit,
        now_iso="2026-08-10T00:00:00+00:00",
    )


def test_validator_accepts_complete_partition_manifest():
    request = manifest()
    assert CAMPAIGN.validate_manifest(
        request, current_base=BASE, backlog_entries=request["tickets"]
    ) == []


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda m: m.update(base="b" * 40), "stale-base"),
        (lambda m: m["partitions"][0].update(quota=1), "quota-mismatch"),
        (lambda m: m["tickets"].append(m["tickets"][0].copy()), "duplicate-ticket"),
        (lambda m: m["tickets"][0].update(write_sites=[{"path": "ops/a.py", "mode": "unknown"}]),
         "unknown-site-mode"),
    ],
)
def test_validator_names_structural_refusals(mutate, reason):
    request = manifest()
    mutate(request)
    problems = CAMPAIGN.validate_manifest(
        request, current_base=BASE, backlog_entries=request["tickets"]
    )
    assert any(problem["kind"] == reason for problem in problems), problems


def test_validator_requires_declared_write_site_collision_to_be_safe():
    first = ticket("IMP-20260810-aa0001", "p1", "ops/shared.py")
    second = ticket("IMP-20260810-bb0002", "p2", "ops/shared.py")
    request = manifest(tickets=[first, second], quotas={"p1": 1, "p2": 1})
    problems = CAMPAIGN.validate_manifest(
        request, current_base=BASE, backlog_entries=request["tickets"]
    )
    assert any(problem["kind"] == "write-site-collision" for problem in problems)


def test_validator_allows_ordered_dependency_and_same_co_land_group_overlap():
    first = ticket("IMP-20260810-aa0001", "p1", "ops/shared.py",
                   symbol="one", co_land_group="g1")
    second = ticket("IMP-20260810-bb0002", "p2", "ops/shared.py",
                    symbol="two", blocked_by=[first["id"]], co_land_group="g1")
    request = manifest(tickets=[first, second], quotas={"p1": 1, "p2": 1})
    assert CAMPAIGN.validate_manifest(
        request,
        current_base=BASE,
        backlog_entries=[{**item, "blocked_by": []} for item in request["tickets"]],
    ) == []


def test_reservation_is_atomic_and_hides_reserved_tickets_from_dispatch(tmp_path):
    state = tmp_path / "registry.json"
    request = manifest()
    before = state.read_bytes() if state.exists() else None
    result = reserve(state, request)
    assert result["ok"] is True, result
    assert result["partitions"]["p1"]["remaining"] == 2
    assert result["manifest_path"].endswith("worktree_campaigns/campaign-1.json")
    payload = json.loads(state.read_text())
    assert payload["campaign_reservations"][0]["campaign_id"] == "campaign-1"
    assert set(ORCHESTRATE._held_from_registry_state(payload)) == {
        "IMP-20260810-aa0001", "IMP-20260810-bb0002", "IMP-20260810-cc0003"
    }
    assert before is None


@pytest.mark.parametrize("change", [
    lambda m: m.update(coordinator="coord-b"),
    lambda m: m.update(base="b" * 40),
    lambda m: m["tickets"].append(ticket("IMP-20260810-dd0004", "p1", "ops/d.py")),
])
def test_failed_reservation_leaves_registry_and_manifest_unchanged(tmp_path, change):
    state = tmp_path / "registry.json"
    request = manifest()
    assert reserve(state, request)["ok"] is True
    before_state = state.read_bytes()
    manifest_path = tmp_path / "worktree_campaigns" / "campaign-1.json"
    before_manifest = manifest_path.read_bytes()

    changed = json.loads(json.dumps(request))
    change(changed)
    result = reserve(state, changed, current_base=BASE)
    assert result["ok"] is False, result
    assert state.read_bytes() == before_state
    assert manifest_path.read_bytes() == before_manifest


def test_second_campaign_cannot_reserve_same_ticket_and_race_has_one_winner(tmp_path):
    state = tmp_path / "registry.json"
    first = manifest(campaign_id="campaign-a", tickets=[
        ticket("IMP-20260810-aa0001", "p1", "ops/a.py")
    ], quotas={"p1": 1})
    second = manifest(campaign_id="campaign-b", tickets=[
        ticket("IMP-20260810-aa0001", "p1", "ops/a.py")
    ], quotas={"p1": 1})

    def attempt(request):
        return reserve(state, request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first, second]))
    assert sorted(result["ok"] for result in results) == [False, True]
    payload = json.loads(state.read_text())
    assert len(payload["campaign_reservations"]) == 1
    assert len(list((tmp_path / "worktree_campaigns").glob("*.json"))) == 1


def test_open_campaign_claim_is_scoped_to_its_partition(tmp_path):
    state = tmp_path / "registry.json"
    actual_base = subprocess.run(
        ["git", "rev-parse", "main"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    request = manifest(base=actual_base)
    assert reserve(state, request, current_base=actual_base)["ok"] is True
    rc, payload, wanted, selection = ORCHESTRATE._claim_next_campaign_backlog(
        root=ROOT,
        state_arg=str(state),
        path=tmp_path / "child",
        branch="debug/campaign-child",
        intent="campaign child",
        base="main",
        campaign_id="campaign-1",
        partition_id="p2",
    )
    assert rc == REGISTRY.EXIT_OK, payload
    assert wanted == ["IMP-20260810-cc0003"]
    assert selection["partition"] == "p2"
    assert selection["remaining"] == 0
    records = json.loads(state.read_text())["records"]
    assert records[0]["backlog"] == wanted
    reservation = json.loads(state.read_text())["campaign_reservations"][0]
    assert reservation["partitions"]["p2"]["claimed"][wanted[0]]["branch"] == (
        "debug/campaign-child"
    )
