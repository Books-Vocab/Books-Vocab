from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


def _state() -> dict:
    return {"schema": registry.SCHEMA, "records": []}


def _scope() -> dict:
    return {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ops/worktree_registry.py", "operation": "modify"}],
    }


def _terminal_proof(record: dict, *, pr_number: int = 9) -> dict:
    return registry.terminal_proof_with_digest(
        {
            "schema": registry.TERMINAL_PROOF_SCHEMA,
            "lane_id": record["external_ids"][0],
            "pr_number": pr_number,
            "pr_state": "MERGED",
            "base_branch": "main",
            "branch": record["branch"],
            "head_sha": record["handed_back_sha"],
        }
    )


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


def _handback_worktree(
    tmp_path: Path, *, with_origin: bool = True, advance_origin: bool = False,
) -> tuple[Path, dict, Path, str, str]:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "--quiet")
    _git(worktree, "checkout", "--quiet", "-b", "feat/handback")
    (worktree / "branch.txt").write_text("branch\n", encoding="utf-8")
    _git(worktree, "add", "branch.txt")
    _git(
        worktree,
        "-c", "user.name=Registry Test", "-c", "user.email=registry-test@example.invalid",
        "commit", "--quiet", "-m", "branch base",
    )
    base_sha = _git(worktree, "rev-parse", "HEAD")

    remote = tmp_path / "origin.git"
    if with_origin:
        _git(tmp_path, "init", "--bare", "--quiet", str(remote))
        _git(worktree, "remote", "add", "origin", str(remote))
        _git(worktree, "push", "--quiet", "origin", f"{base_sha}:refs/heads/main")

    (worktree / "branch.txt").write_text("branch\nchild\n", encoding="utf-8")
    _git(worktree, "add", "branch.txt")
    _git(
        worktree,
        "-c", "user.name=Registry Test", "-c", "user.email=registry-test@example.invalid",
        "commit", "--quiet", "-m", "branch tip",
    )
    tip_sha = _git(worktree, "rev-parse", "HEAD")

    if with_origin and advance_origin:
        upstream = tmp_path / "upstream"
        _git(tmp_path, "clone", "--quiet", "--branch", "main", str(remote), str(upstream))
        (upstream / "main.txt").write_text("main advanced\n", encoding="utf-8")
        _git(upstream, "add", "main.txt")
        _git(
            upstream,
            "-c", "user.name=Registry Test", "-c", "user.email=registry-test@example.invalid",
            "commit", "--quiet", "-m", "advance main",
        )
        _git(upstream, "push", "--quiet", "origin", "HEAD:refs/heads/main")

    record = {
        "branch": "feat/handback",
        "path": str(worktree),
        "status": registry.STATUS_ACTIVE,
        "external_ids": ["ISSUE-1290"],
        "scope": _scope(),
        "base": base_sha,
        "base_sha": base_sha,
        "claim_generation": 0,
        "handed_back_at": None,
        "handed_back_sha": None,
    }
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})
    return worktree, record, state_path, base_sha, tip_sha


def _run_handback(state_path: Path, worktree: Path, outcomes_path: Path) -> int:
    return registry.main([
        "hand-back", "--state", str(state_path), "--branch", "feat/handback",
        "--path", str(worktree), "--outcomes", str(outcomes_path),
        "--at", "2026-08-19T01:00:00Z", "--json",
    ])


def test_handback_seal_captures_live_origin_main_sha(tmp_path: Path) -> None:
    worktree, _, state_path, base_sha, tip_sha = _handback_worktree(tmp_path)
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text("[]", encoding="utf-8")

    assert _run_handback(state_path, worktree, outcomes_path) == registry.EXIT_OK

    handed_back = registry.load_state(state_path)["records"][0]
    seal = handed_back["handback_seal"]
    assert seal["origin_main_sha"] == base_sha
    assert seal["base_sha"] == base_sha
    assert seal["tip_sha"] == tip_sha
    assert registry.validate_handback_seal(handed_back) == []


def test_handback_fails_closed_when_origin_main_is_unreadable(tmp_path: Path) -> None:
    worktree, _, state_path, _, _ = _handback_worktree(tmp_path, with_origin=False)
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text("[]", encoding="utf-8")

    assert _run_handback(state_path, worktree, outcomes_path) == registry.EXIT_PARTIAL

    stored = registry.load_state(state_path)["records"][0]
    assert stored.get("handback_seal") is None
    assert stored["handed_back_at"] is None
    assert stored["handed_back_sha"] is None


def test_handback_records_advanced_live_main_without_requiring_rebase(
    tmp_path: Path,
) -> None:
    worktree, _, state_path, base_sha, tip_sha = _handback_worktree(
        tmp_path, advance_origin=True
    )
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text("[]", encoding="utf-8")

    assert _run_handback(state_path, worktree, outcomes_path) == registry.EXIT_OK

    stored = registry.load_state(state_path)["records"][0]
    seal = stored["handback_seal"]
    assert seal["base_sha"] == base_sha
    assert seal["tip_sha"] == tip_sha
    assert seal["origin_main_sha"] != base_sha
    assert stored["handed_back_sha"] == tip_sha


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
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--quiet", str(remote))
    _git(worktree, "remote", "add", "origin", str(remote))
    _git(worktree, "push", "--quiet", "origin", f"{tip_sha}:refs/heads/main")
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


def test_scope_set_invalidates_old_handback_and_is_idempotent(tmp_path: Path) -> None:
    record = _sealed_handed_back_record(tmp_path / "scope-owner")
    record["claim_generation"] = 3
    record["handback_claim_generation"] = 3
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})
    scope = {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ops/new_scope.py", "operation": "modify"}],
    }
    argv = [
        "scope-set", "--state", str(state_path), "--branch", record["branch"],
        "--scope", json.dumps(scope), "--json",
    ]

    assert registry.main(argv) == registry.EXIT_OK
    assert registry.main(argv) == registry.EXIT_OK

    updated = registry.load_state(state_path)["records"][0]
    assert updated["claim_generation"] == 4
    assert updated["scope"] == registry.normalise_scope(scope)
    assert updated["handed_back_at"] is None
    assert updated["handed_back_sha"] is None
    assert "handback_claim_generation" not in updated
    assert "handback_seal" not in updated
    assert "handback_outcomes" not in updated


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


def test_owner_change_advances_generation_and_invalidates_handback(
    tmp_path: Path,
) -> None:
    record = _sealed_handed_back_record(tmp_path / "owner-change")
    record["codex_thread_id"] = "owner-old"
    record["claim_generation"] = 3
    record["handback_claim_generation"] = 3
    record["handback_seal"] = registry._seal_with_digest(
        registry._seal_body(
            record,
            base_sha=record["base_sha"],
            tip_sha=record["handed_back_sha"],
            outcomes=[{"status": "pass"}],
            handed_back_at=record["handed_back_at"],
        )
    )
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    assert registry.main(
        [
            "owner-bind",
            "--state",
            str(state_path),
            "--branch",
            record["branch"],
            "--codex-thread-id",
            "owner-new",
            "--json",
        ]
    ) == registry.EXIT_OK

    updated = registry.load_state(state_path)["records"][0]
    assert updated["codex_thread_id"] == "owner-new"
    assert updated["claim_generation"] == 4
    assert updated["handed_back_at"] is None
    assert updated["handed_back_sha"] is None
    assert "handback_claim_generation" not in updated
    assert "handback_seal" not in updated


def test_valid_handed_back_record_retains_admission_until_pr_is_durable(
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

    assert rc == registry.EXIT_CLAIMED
    assert admitted["owners"][0]["branch"] == "feat/handed-back"
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
    assert refused["owners"][0]["branch"] == "feat/handed-back"
    assert refused["owners"][0]["branch"] == handed_back["branch"]


def test_new_handback_retains_reregistered_claim_until_pr_is_durable(
    tmp_path: Path,
) -> None:
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

    assert rc == registry.EXIT_CLAIMED
    assert admitted["owners"][0]["branch"] == "feat/handed-back"


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
    rc, _ = registry._register_record(
        state,
        branch="feat/new-owner",
        path=str(tmp_path / "new-owner"),
        intent="feature",
        base="main",
        external_ids=["#123"],
        scope=_scope(),
    )

    assert rc == registry.EXIT_CLAIMED


def test_cleanup_lease_blocks_reclaim_until_exact_completion(tmp_path: Path) -> None:
    handed_back = _idle_handed_back_record(tmp_path)
    handed_back["status"] = registry.STATUS_CLEANUP_PENDING
    state = {"schema": registry.SCHEMA, "records": [handed_back]}

    rc, refusal = registry._register_record(
        state,
        branch=handed_back["branch"],
        path=handed_back["path"],
        intent="racing reclaim",
        base=handed_back["base_sha"],
        external_ids=handed_back["external_ids"],
        scope=handed_back["scope"],
    )

    assert rc == registry.EXIT_CLAIMED
    assert refusal["reason"] == "local assets are protected by an exact cleanup lease"
    assert state["records"] == [handed_back]


def test_old_published_receipt_cannot_lease_assets_after_new_claim(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    published = _idle_handed_back_record(tmp_path)
    published["status"] = "published"
    published["claim_generation"] = 2
    published["handback_claim_generation"] = 2
    state = {"schema": registry.SCHEMA, "records": [published]}

    rc, reclaimed = registry._register_record(
        state,
        branch=published["branch"],
        path=published["path"],
        intent="new claim",
        base=published["base_sha"],
        external_ids=published["external_ids"],
        scope=published["scope"],
    )

    assert rc == registry.EXIT_OK
    assert reclaimed["claim_generation"] == 3
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, state)

    assert registry.main(
        [
            "resolve",
            "--state",
            str(state_path),
            "--branch",
            published["branch"],
            "--path",
            published["path"],
            "--status",
            registry.STATUS_CLEANUP_PENDING,
            "--expected-generation",
            "2",
            "--expected-head-sha",
            published["handed_back_sha"],
            "--json",
        ]
    ) == registry.EXIT_CLAIMED
    assert "newer registry claim" in capsys.readouterr().err
    stored = registry.load_state(state_path)["records"]
    assert [item["status"] for item in stored] == ["published", "active"]


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


@pytest.mark.parametrize("terminal_status", ("merged", "abandoned"))
def test_resolve_terminal_status_preserves_handed_back_receipt(
    tmp_path: Path, terminal_status: str
) -> None:
    handed_back = _valid_handed_back_record(tmp_path)
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [handed_back]})

    argv = [
        "resolve", "--state", str(state_path), "--branch", "feat/handed-back",
        "--status", terminal_status, "--at", "2026-08-19T01:00:00Z", "--json",
        "--expected-generation", str(handed_back.get("claim_generation", 0)),
        "--expected-head-sha", handed_back["handed_back_sha"],
    ]
    if terminal_status == "merged":
        argv += ["--terminal-proof", json.dumps(_terminal_proof(handed_back))]
    assert registry.main(argv) == registry.EXIT_OK

    resolved = registry.load_state(state_path)["records"][0]
    assert resolved["status"] == terminal_status
    assert resolved["handed_back_sha"] == handed_back["handed_back_sha"]
    assert resolved["handback_seal"] == handed_back["handback_seal"]


def test_cleanup_lease_requires_physical_handback_then_publishes_stored_receipt(
    tmp_path: Path,
) -> None:
    record = _idle_handed_back_record(tmp_path)
    record["claim_generation"] = 4
    record["handback_claim_generation"] = 4
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    stale = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--path", record["path"], "--status", "cleanup_pending",
        "--expected-generation", "3", "--expected-head-sha", record["handed_back_sha"],
        "--json",
    ])
    exact = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--path", record["path"], "--status", "cleanup_pending",
        "--expected-generation", "4", "--expected-head-sha", record["handed_back_sha"],
        "--json",
    ])

    assert stale == registry.EXIT_CLAIMED
    assert exact == registry.EXIT_OK
    shutil.rmtree(record["path"])

    published = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--path", record["path"], "--status", "published",
        "--expected-generation", "4", "--expected-head-sha", record["handed_back_sha"],
        "--json",
    ])

    assert published == registry.EXIT_OK
    assert registry.load_state(state_path)["records"][0]["status"] == "published"


def test_published_record_can_transition_to_merged_with_exact_tuple(
    tmp_path: Path,
) -> None:
    record = _valid_handed_back_record(tmp_path)
    record.update({
        "status": "published",
        "claim_generation": 2,
        "handback_claim_generation": 2,
    })
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    rc = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--path", record["path"], "--status", "merged",
        "--expected-generation", "2", "--expected-head-sha", record["handed_back_sha"],
        "--terminal-proof", json.dumps(_terminal_proof(record)),
        "--json",
    ])

    assert rc == registry.EXIT_OK
    assert registry.load_state(state_path)["records"][0]["status"] == "merged"


@pytest.mark.parametrize("terminal_status", ("merged", "abandoned"))
def test_terminal_transition_requires_exact_generation_and_head(
    tmp_path: Path, terminal_status: str
) -> None:
    record = _valid_handed_back_record(tmp_path)
    record["claim_generation"] = 5
    record["handback_claim_generation"] = 5
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    missing = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--status", terminal_status,
    ])
    stale_generation = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--status", terminal_status, "--expected-generation", "4",
        "--expected-head-sha", record["handed_back_sha"],
    ])
    stale_head = registry.main([
        "resolve", "--state", str(state_path), "--branch", record["branch"],
        "--status", terminal_status, "--expected-generation", "5",
        "--expected-head-sha", "f" * 40,
    ])

    assert missing == registry.EXIT_USAGE
    assert stale_generation == registry.EXIT_CLAIMED
    assert stale_head == registry.EXIT_CLAIMED
    assert registry.load_state(state_path)["records"][0]["status"] == "active"


def test_sweep_commit_is_read_only_and_requires_exact_per_record_transition(
    tmp_path: Path,
) -> None:
    record = _valid_handed_back_record(tmp_path)
    record["path"] = str(tmp_path / "missing")
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    rc = registry.main(["sweep", "--state", str(state_path), "--commit"])

    assert rc == registry.EXIT_USAGE
    assert registry.load_state(state_path)["records"][0]["status"] == "active"
