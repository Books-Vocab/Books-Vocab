from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry  # noqa: E402


def _state() -> dict:
    return {"schema": registry.SCHEMA, "records": []}


def _scope() -> dict:
    return {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ops/worktree_registry.py", "operation": "modify"}],
    }


def _sealed_handed_back_record(
    path: Path, *, handed_back_sha: str = "b" * 40,
    branch: str = "feat/handed-back",
    base_sha: str = "a" * 40,
) -> dict:
    handed_back_at = "2026-08-19T00:00:00Z"
    record = {
        "branch": branch,
        "path": str(path),
        "status": registry.STATUS_ACTIVE,
        "external_ids": ["#123"],
        "scope": _scope(),
        "base_sha": base_sha,
        "handed_back_at": handed_back_at,
        "handed_back_sha": handed_back_sha,
    }
    record["handback_seal"] = registry._seal_with_digest(
        registry._seal_body(
            record,
            base_sha=base_sha,
            tip_sha=handed_back_sha,
            outcomes=[{"id": "#123", "status": "pass"}],
            handed_back_at=handed_back_at,
        )
    )
    return record


def _valid_handed_back_record(tmp_path: Path) -> dict:
    return _sealed_handed_back_record(tmp_path / "handed-back")


def _git(worktree: Path, *args: str) -> str:
    rc, output = registry._git(list(args), worktree)
    assert rc == 0, output
    return output


def _idle_handed_back_record(tmp_path: Path) -> dict:
    worktree = tmp_path / "handed-back"
    worktree.mkdir()
    _git(worktree, "init", "--quiet")
    _git(worktree, "checkout", "--quiet", "-b", "feat/handed-back")
    (worktree / "sealed.txt").write_text("sealed\n", encoding="utf-8")
    _git(worktree, "add", "sealed.txt")
    _git(
        worktree,
        "-c",
        "user.name=Registry Test",
        "-c",
        "user.email=registry-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "sealed hand-back",
    )
    tip_sha = _git(worktree, "rev-parse", "HEAD")
    return _sealed_handed_back_record(
        worktree, handed_back_sha=tip_sha, base_sha=tip_sha,
    )


def test_register_keeps_external_reference_opaque_and_detects_collision(tmp_path: Path) -> None:
    state = _state()
    rc, first = registry._register_record(
        state, branch="feat/one", path=str(tmp_path / "one"), intent="feature",
        base="main", external_ids=["#123"], scope=None,
    )
    assert rc == registry.EXIT_OK
    assert first["external_ids"] == ["#123"]

    rc, refused = registry._register_record(
        state, branch="feat/two", path=str(tmp_path / "two"), intent="feature",
        base="main", external_ids=["#123"], scope=None,
    )
    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == "feat/one"


def test_load_state_migrates_live_machine_claim_without_recreating_a_store(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"records": [{
        "branch": "feat/live", "path": str(tmp_path / "live"),
        "status": "active", "backlog": ["#7"],
    }]}), encoding="utf-8")
    state = registry.load_state(path)
    assert state["records"][0]["external_ids"] == ["#7"]
    assert "backlog" not in state["records"][0]


def test_load_state_drops_removed_delivery_envelopes(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "schema": "kg.worktree.registry.v1",
        "campaign_archives": [{"campaign_id": "old"}],
        "campaign_reservations": [{"campaign_id": "old"}],
        "records": [],
    }), encoding="utf-8")

    state = registry.load_state(path)

    assert state == {"schema": registry.SCHEMA, "records": []}


def test_compact_record_drops_removed_delivery_metadata() -> None:
    compacted = registry._compact_record({
        "branch": "feat/live",
        "path": "/tmp/live",
        "status": "active",
        "external_ids": ["#7"],
        "campaign_id": "old-campaign",
        "partition_id": "old-partition",
        "role": "child",
        "work_mode": "ticket-delivery",
        "integration_owner": "old-integrator",
    })

    assert compacted == {
        "branch": "feat/live",
        "path": "/tmp/live",
        "status": "active",
        "external_ids": ["#7"],
    }


def test_scope_set_rejects_duplicate_file_declarations() -> None:
    with pytest.raises(ValueError, match="invalid scope"):
        registry.normalise_scope({
            "schema": "kg.worktree.scope.v1",
            "files": [
                {"path": "backend/app.py", "operation": "modify"},
                {"path": "backend/app.py", "operation": "modify"},
            ],
        })


def test_handback_seal_digest_is_verifiable() -> None:
    record = {"branch": "feat/seal", "path": "/tmp/seal", "external_ids": ["#9"]}
    body = registry._seal_body(
        record, base_sha="a" * 40, tip_sha="b" * 40,
        outcomes=[{"id": "#9", "status": "pass"}],
        handed_back_at="2026-08-19T00:00:00Z",
    )
    record["handback_seal"] = registry._seal_with_digest(body)
    assert registry.validate_handback_seal(record) == []
    record["handback_seal"]["tip_sha"] = "c" * 40
    assert {item["kind"] for item in registry.validate_handback_seal(record)} == {
        "handback-seal-digest-invalid"
    }


def test_valid_handed_back_record_releases_admission_and_remains_queryable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    handed_back = _idle_handed_back_record(tmp_path)
    state = {"schema": registry.SCHEMA, "records": [handed_back]}

    rc, admitted = registry._register_record(
        state,
        branch="feat/new-owner",
        path=str(tmp_path / "new-owner"),
        intent="feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_OK
    assert admitted["branch"] == "feat/new-owner"
    assert state["records"][0] is handed_back
    assert registry.validate_handback_seal(handed_back) == []

    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, state)
    assert registry.main([
        "list", "--state", str(state_path), "--branch", "feat/handed-back", "--json",
    ]) == registry.EXIT_OK
    queried = json.loads(capsys.readouterr().out)["records"][0]
    assert queried["handback_seal"]["digest"] == handed_back["handback_seal"]["digest"]
    assert queried["handed_back_sha"] == handed_back["handed_back_sha"]


def test_reregister_revokes_current_handback_admission_and_retains_receipt(
    tmp_path: Path,
) -> None:
    handed_back = _idle_handed_back_record(tmp_path)
    receipt_at = handed_back["handed_back_at"]
    receipt_sha = handed_back["handed_back_sha"]
    receipt_seal = json.loads(json.dumps(handed_back["handback_seal"]))
    state = {"schema": registry.SCHEMA, "records": [handed_back]}

    rc, reregistered = registry._register_record(
        state,
        branch=handed_back["branch"],
        path=handed_back["path"],
        intent="resumed feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_OK
    assert reregistered is handed_back
    assert reregistered["claim_generation"] == 1
    assert reregistered.get("handback_claim_generation", 0) == 0
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, state)
    audited = registry.load_state(state_path)["records"][0]
    assert audited["handed_back_at"] == receipt_at
    assert audited["handed_back_sha"] == receipt_sha
    assert audited["handback_seal"] == receipt_seal
    assert not registry._has_valid_handback(audited)

    rc, refused = registry._register_record(
        {"schema": registry.SCHEMA, "records": [audited]},
        branch="feat/competitor",
        path=str(tmp_path / "competitor"),
        intent="competing feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == handed_back["branch"]


def test_new_handback_releases_reregistered_claim(tmp_path: Path) -> None:
    handed_back = _idle_handed_back_record(tmp_path)
    state = {"schema": registry.SCHEMA, "records": [handed_back]}

    assert registry._register_record(
        state,
        branch=handed_back["branch"],
        path=handed_back["path"],
        intent="resumed feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )[0] == registry.EXIT_OK

    state_path = tmp_path / "registry.json"
    outcomes_path = tmp_path / "outcomes.json"
    registry.save_state(state_path, state)
    outcomes_path.write_text("[]", encoding="utf-8")
    assert registry.main([
        "hand-back", "--state", str(state_path), "--branch", handed_back["branch"],
        "--path", handed_back["path"], "--outcomes", str(outcomes_path),
        "--at", "2026-08-19T01:00:00Z", "--json",
    ]) == registry.EXIT_OK

    renewed = registry.load_state(state_path)["records"][0]
    assert renewed["claim_generation"] == 1
    assert renewed["handback_claim_generation"] == 1
    assert registry._has_valid_handback(renewed)

    rc, admitted = registry._register_record(
        {"schema": registry.SCHEMA, "records": [renewed]},
        branch="feat/competitor",
        path=str(tmp_path / "competitor"),
        intent="competing feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_OK
    assert admitted["branch"] == "feat/competitor"


@pytest.mark.parametrize("worktree_state", ("dirty", "head-advanced", "branch-mismatch"))
def test_changed_registered_worktree_fails_closed_for_admission(
    tmp_path: Path, worktree_state: str
) -> None:
    handed_back = _idle_handed_back_record(tmp_path)
    worktree = Path(handed_back["path"])
    if worktree_state == "dirty":
        (worktree / "sealed.txt").write_text("dirty\n", encoding="utf-8")
    elif worktree_state == "head-advanced":
        (worktree / "sealed.txt").write_text("advanced\n", encoding="utf-8")
        _git(worktree, "add", "sealed.txt")
        _git(
            worktree,
            "-c",
            "user.name=Registry Test",
            "-c",
            "user.email=registry-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "advance worktree",
        )
    else:
        _git(worktree, "checkout", "--quiet", "-b", "feat/advanced")

    state = {"schema": registry.SCHEMA, "records": [handed_back]}
    rc, refused = registry._register_record(
        state,
        branch="feat/new-owner",
        path=str(tmp_path / "new-owner"),
        intent="feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == "feat/handed-back"


@pytest.mark.parametrize("worktree_state", ("missing", "not-a-worktree"))
def test_unavailable_registered_worktree_fails_closed_for_admission(
    tmp_path: Path, worktree_state: str
) -> None:
    worktree = tmp_path / worktree_state
    if worktree_state == "not-a-worktree":
        worktree.mkdir()
    handed_back = _sealed_handed_back_record(worktree)
    state = {"schema": registry.SCHEMA, "records": [handed_back]}

    rc, refused = registry._register_record(
        state,
        branch="feat/new-owner",
        path=str(tmp_path / "new-owner"),
        intent="feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == "feat/handed-back"


def test_unhanded_active_record_still_blocks_admission(tmp_path: Path) -> None:
    unhanded = _valid_handed_back_record(tmp_path)
    unhanded.pop("handback_seal")
    unhanded["handed_back_at"] = None
    unhanded["handed_back_sha"] = None
    state = {"schema": registry.SCHEMA, "records": [unhanded]}

    rc, refused = registry._register_record(
        state,
        branch="feat/new-owner",
        path=str(tmp_path / "new-owner"),
        intent="feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == "feat/handed-back"


@pytest.mark.parametrize("corruption", ("digest", "tip-sha", "timestamp"))
def test_invalid_handed_back_seal_fails_closed_for_admission(
    tmp_path: Path, corruption: str
) -> None:
    invalid = _valid_handed_back_record(tmp_path)
    if corruption == "digest":
        invalid["handback_seal"]["digest"] = "invalid"
    elif corruption == "tip-sha":
        invalid["handed_back_sha"] = "c" * 40
    else:
        invalid["handed_back_at"] = "2026-08-19T01:00:00Z"
    state = {"schema": registry.SCHEMA, "records": [invalid]}

    rc, refused = registry._register_record(
        state,
        branch="feat/new-owner",
        path=str(tmp_path / "new-owner"),
        intent="feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_CLAIMED
    assert refused["owners"][0]["branch"] == "feat/handed-back"


@pytest.mark.parametrize("terminal_status", registry.RESOLVE_STATUS)
def test_resolve_terminal_status_preserves_handed_back_receipt(
    tmp_path: Path, terminal_status: str
) -> None:
    handed_back = _valid_handed_back_record(tmp_path)
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [handed_back]})

    assert registry.main([
        "resolve", "--state", str(state_path), "--branch", "feat/handed-back",
        "--status", terminal_status, "--at", "2026-08-19T01:00:00Z", "--json",
    ]) == registry.EXIT_OK

    resolved = registry.load_state(state_path)["records"][0]
    assert resolved["status"] == terminal_status
    assert resolved["handed_back_sha"] == handed_back["handed_back_sha"]
    assert resolved["handback_seal"] == handed_back["handback_seal"]
