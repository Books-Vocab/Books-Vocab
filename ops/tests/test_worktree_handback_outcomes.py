"""Closed-loop hand-back outcome and seal contracts for IMP-20260809-a54df4."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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


REGISTRY = _load("worktree_registry_handback_tests", ROOT / "ops/worktree_registry.py")
ORCHESTRATE = _load(
    "worktree_orchestrate_handback_tests", ROOT / "ops/worktree_orchestrate.py"
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test")
    (repo / "ops").mkdir()
    audit = repo / "ops" / "review_audit.sh"
    audit.write_text("#!/bin/sh\nexit 0\n")
    audit.chmod(0o755)
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "main")


def _register_feature(repo: Path, state: Path, base_sha: str) -> str:
    _git(repo, "checkout", "-qb", "feat/a")
    (repo / "changed.txt").write_text("changed\n")
    _git(repo, "add", "changed.txt")
    _git(repo, "commit", "-qm", "change")
    assert REGISTRY.main([
        "register", "--state", str(state), "--path", str(repo),
        "--branch", "feat/a", "--intent", "test", "--base", "main",
        "--backlog", "IMP-TEST-1",
    ]) == REGISTRY.EXIT_OK
    record = json.loads(state.read_text())["records"][0]
    assert record["base_sha"] == base_sha
    return _git(repo, "rev-parse", "HEAD")


def _write_outcomes(path: Path, *, outcome: str = "changed",
                    status: str = "green", evidence: str = "pytest passed") -> None:
    path.write_text(json.dumps({"outcomes": [{
        "ticket_id": "IMP-TEST-1",
        "outcome": outcome,
        "acceptance_status": status,
        "evidence": evidence,
    }]}))


def test_changed_hand_back_creates_sealed_typed_outcome(tmp_path, capsys):
    repo, base_sha = _repo(tmp_path)
    state = tmp_path / "registry.json"
    tip_sha = _register_feature(repo, state, base_sha)
    capsys.readouterr()
    outcomes = tmp_path / "outcomes.json"
    _write_outcomes(outcomes)

    rc = REGISTRY.main([
        "hand-back", "--state", str(state), "--path", str(repo),
        "--branch", "feat/a", "--outcomes", str(outcomes), "--json",
    ])
    assert rc == REGISTRY.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    seal = payload["handback_seal"]
    assert seal["schema"] == "kg.worktree.handback.v1"
    assert seal["base_sha"] == base_sha
    assert seal["tip_sha"] == tip_sha
    assert seal["outcomes"][0]["outcome"] == "changed"
    assert len(seal["digest"]) == 64
    record = json.loads(state.read_text())["records"][0]
    assert REGISTRY.validate_handback_seal(record, repo=repo) == []


def test_register_without_born_worktree_records_base_sha(tmp_path, capsys):
    repo, base_sha = _repo(tmp_path)
    state = repo / ".cache" / "registry.json"
    missing_worktree = tmp_path / "not-born"
    rc = REGISTRY.main([
        "register", "--state", str(state), "--repo-root", str(repo),
        "--path", str(missing_worktree),
        "--branch", "feat/not-born", "--intent", "test", "--base", "main",
        "--backlog", "IMP-TEST-1", "--json",
    ])
    assert rc == REGISTRY.EXIT_OK
    capsys.readouterr()
    record = json.loads(state.read_text())["records"][0]
    assert record["base_sha"] == base_sha


def test_register_without_born_worktree_uses_explicit_repo_root(tmp_path, capsys):
    repo, base_sha = _repo(tmp_path)
    state = tmp_path / "arbitrary" / "registry.json"
    missing_worktree = tmp_path / "not-born-explicit-root"
    rc = REGISTRY.main([
        "register", "--state", str(state), "--repo-root", str(repo),
        "--path", str(missing_worktree), "--branch", "feat/not-born-explicit",
        "--intent", "test", "--base", "main", "--backlog", "IMP-TEST-1", "--json",
    ])
    assert rc == REGISTRY.EXIT_OK
    capsys.readouterr()
    record = json.loads(state.read_text())["records"][0]
    assert record["base_sha"] == base_sha


def test_validate_seal_rechecks_semantic_outcome_problems(tmp_path):
    repo, base_sha = _repo(tmp_path)
    record = {
        "path": str(repo), "branch": "feat/a", "base": "main",
        "base_sha": base_sha, "claimed_at": "2026-08-10T00:00:00Z",
        "backlog": ["IMP-TEST-1"], "handed_back_sha": base_sha,
        "handed_back_at": "2026-08-10T00:01:00Z",
    }
    body = REGISTRY._seal_body(
        record, base_sha=base_sha, tip_sha=base_sha,
        outcomes=[{"ticket_id": "IMP-TEST-1", "outcome": "changed",
                    "acceptance_status": "blocked", "evidence": "red"}],
        handed_back_at=record["handed_back_at"],
    )
    record["handback_seal"] = REGISTRY._seal_with_digest(body)
    problems = REGISTRY.validate_handback_seal(record, repo=repo)
    assert any(item["kind"] == "acceptance-not-green" for item in problems)


def test_validate_seal_rejects_non_dict_outcome_fail_closed(tmp_path):
    repo, base_sha = _repo(tmp_path)
    record = {
        "path": str(repo), "branch": "feat/a", "base": "main",
        "base_sha": base_sha, "claimed_at": "2026-08-10T00:00:00Z",
        "backlog": [], "handed_back_sha": base_sha,
        "handed_back_at": "2026-08-10T00:01:00Z",
    }
    body = REGISTRY._seal_body(
        record, base_sha=base_sha, tip_sha=base_sha, outcomes=[None],
        handed_back_at=record["handed_back_at"],
    )
    record["handback_seal"] = REGISTRY._seal_with_digest(body)
    problems = REGISTRY.validate_handback_seal(record, repo=repo)
    assert any(item["kind"] == "handback-outcome-item-invalid" for item in problems)


@pytest.mark.parametrize("bad_outcome", [[], {}])
def test_validate_seal_rejects_non_string_outcome_fail_closed(tmp_path, bad_outcome):
    repo, base_sha = _repo(tmp_path)
    record = {
        "path": str(repo), "branch": "feat/a", "base": "main",
        "base_sha": base_sha, "claimed_at": "2026-08-10T00:00:00Z",
        "backlog": ["IMP-TEST-1"], "handed_back_sha": base_sha,
        "handed_back_at": "2026-08-10T00:01:00Z",
    }
    body = REGISTRY._seal_body(
        record, base_sha=base_sha, tip_sha=base_sha,
        outcomes=[{"ticket_id": "IMP-TEST-1", "outcome": bad_outcome,
                    "acceptance_status": "pass", "evidence": "x"}],
        handed_back_at=record["handed_back_at"],
    )
    record["handback_seal"] = REGISTRY._seal_with_digest(body)
    problems = REGISTRY.validate_handback_seal(record, repo=repo)
    assert any(item["kind"] == "handback-outcome-not-integrable" for item in problems)


def test_validate_seal_rejects_mixed_ticket_id_types_fail_closed(tmp_path):
    repo, base_sha = _repo(tmp_path)
    record = {
        "path": str(repo), "branch": "feat/a", "base": "main",
        "base_sha": base_sha, "claimed_at": "2026-08-10T00:00:00Z",
        "backlog": ["IMP-TEST-1", "IMP-TEST-2"], "handed_back_sha": base_sha,
        "handed_back_at": "2026-08-10T00:01:00Z",
    }
    body = REGISTRY._seal_body(
        record, base_sha=base_sha, tip_sha=base_sha,
        outcomes=[
            {"ticket_id": ["IMP-TEST-1"], "outcome": "changed",
             "acceptance_status": "pass", "evidence": "x"},
            {"ticket_id": "IMP-TEST-2", "outcome": "changed",
             "acceptance_status": "pass", "evidence": "x"},
        ],
        handed_back_at=record["handed_back_at"],
    )
    record["handback_seal"] = REGISTRY._seal_with_digest(body)
    problems = REGISTRY.validate_handback_seal(record, repo=repo)
    assert any(item["kind"] == "handback-outcome-metadata-invalid"
               and item["field"] == "ticket_id" for item in problems)


def test_register_repairs_stale_base_sha_from_branch_merge_base(tmp_path, capsys):
    repo, original_base = _repo(tmp_path)
    _git(repo, "checkout", "-qb", "feat/a")
    (repo / "changed.txt").write_text("branch\n")
    _git(repo, "add", "changed.txt")
    _git(repo, "commit", "-qm", "branch change")
    branch_tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    (repo / "main.txt").write_text("peer\n")
    _git(repo, "add", "main.txt")
    _git(repo, "commit", "-qm", "peer change")
    current_main = _git(repo, "rev-parse", "main")
    assert current_main != original_base

    state = tmp_path / "registry.json"
    state.write_text(json.dumps({"schema": REGISTRY.SCHEMA, "records": [{
        "path": str(repo), "branch": "feat/a", "intent": "test",
        "base": "main", "base_sha": current_main, "status": "active",
        "backlog": ["IMP-TEST-1"], "claimed_at": "2026-08-10T00:00:00Z",
    }]}))
    rc = REGISTRY.main([
        "register", "--state", str(state), "--path", str(repo),
        "--branch", "feat/a", "--intent", "test", "--base", "main",
        "--backlog", "IMP-TEST-1", "--json",
    ])
    assert rc == REGISTRY.EXIT_OK
    capsys.readouterr()
    record = json.loads(state.read_text())["records"][0]
    assert branch_tip != current_main
    assert record["base_sha"] == original_base


@pytest.mark.parametrize(
    ("outcome", "status", "expected"),
    [
        ("changed", "blocked", "acceptance-not-green"),
        ("changed-but-not-closable", "green", "nonintegrable-outcome-is-green"),
        ("blocked", "green", "nonintegrable-outcome-is-green"),
    ],
)
def test_hand_back_refuses_semantically_inconsistent_outcomes(
    tmp_path, outcome, status, expected, capsys,
):
    repo, base_sha = _repo(tmp_path)
    state = tmp_path / "registry.json"
    _register_feature(repo, state, base_sha)
    capsys.readouterr()
    outcomes = tmp_path / "outcomes.json"
    _write_outcomes(outcomes, outcome=outcome, status=status)
    rc = REGISTRY.main([
        "hand-back", "--state", str(state), "--path", str(repo),
        "--branch", "feat/a", "--outcomes", str(outcomes), "--json",
    ])
    assert rc == REGISTRY.EXIT_PARTIAL
    payload = json.loads(capsys.readouterr().out)
    assert any(item["kind"] == expected for item in payload["problems"])
    record = json.loads(state.read_text())["records"][0]
    assert "handback_seal" not in record


def test_hand_back_refuses_unreadable_review_audit_structured(tmp_path, capsys):
    repo, base_sha = _repo(tmp_path)
    (repo / "ops" / "review_audit.sh").chmod(0o644)
    state = tmp_path / "registry.json"
    _register_feature(repo, state, base_sha)
    capsys.readouterr()
    outcomes = tmp_path / "outcomes.json"
    _write_outcomes(outcomes)

    rc = REGISTRY.main([
        "hand-back", "--state", str(state), "--path", str(repo),
        "--branch", "feat/a", "--outcomes", str(outcomes), "--json",
    ])
    assert rc == REGISTRY.EXIT_PARTIAL
    payload = json.loads(capsys.readouterr().out)
    assert any(item["kind"] == "review-audit-unreadable"
               for item in payload["problems"])
    record = json.loads(state.read_text())["records"][0]
    assert "handback_seal" not in record


def test_hand_back_refuses_dirty_tree_and_ticket_set_drift(tmp_path, capsys):
    repo, base_sha = _repo(tmp_path)
    state = tmp_path / "registry.json"
    _register_feature(repo, state, base_sha)
    capsys.readouterr()
    (repo / "uncommitted.txt").write_text("dirty\n")
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps({"outcomes": [{
        "ticket_id": "IMP-NOT-CLAIMED",
        "outcome": "changed",
        "acceptance_status": "green",
        "evidence": "pytest passed",
    }]}))
    rc = REGISTRY.main([
        "hand-back", "--state", str(state), "--path", str(repo),
        "--branch", "feat/a", "--outcomes", str(outcomes), "--json",
    ])
    assert rc == REGISTRY.EXIT_PARTIAL
    payload = json.loads(capsys.readouterr().out)
    kinds = {item["kind"] for item in payload["problems"]}
    assert {"worktree-dirty", "ticket-not-claimed", "ticket-set-mismatch"} <= kinds


def test_noop_requires_verifiable_provenance_and_integrate_rejects_non_code_seal(tmp_path):
    repo, base_sha = _repo(tmp_path)
    record = {
        "path": str(repo), "branch": "feat/a", "base": "main",
        "base_sha": base_sha, "claimed_at": "2026-08-10T00:00:00Z",
        "backlog": ["IMP-TEST-1"], "handed_back_sha": base_sha,
    }
    problems, _ = REGISTRY._outcome_problems(
        [{"ticket_id": "IMP-TEST-1", "outcome": "no-op-existing-fix",
          "acceptance_status": "green", "evidence": "acceptance passed"}],
        claimed=record["backlog"], base_sha=base_sha, worktree=repo,
        tip_sha=base_sha, run_review=False,
    )
    assert any(item["kind"] == "no-op-provenance-missing" for item in problems)

    body = REGISTRY._seal_body(record, base_sha=base_sha, tip_sha=base_sha,
                               outcomes=[{
                                   "ticket_id": "IMP-TEST-1",
                                   "outcome": "blocked",
                                   "acceptance_status": "red",
                                   "evidence": "acceptance blocked",
                               }], handed_back_at=record["claimed_at"])
    record["handback_seal"] = REGISTRY._seal_with_digest(body)
    assert any(item["kind"] == "handback-outcome-not-integrable"
               for item in REGISTRY.validate_handback_seal(record, repo=repo))


def test_integrate_requires_seal_but_explicit_legacy_bypass_remains_warning(tmp_path):
    repo, base_sha = _repo(tmp_path)
    _git(repo, "branch", "feat/a", base_sha)
    record = {
        "path": str(repo), "branch": "feat/a", "base": "main",
        "backlog": [], "handed_back_sha": base_sha,
        "status": "active",
    }
    state = tmp_path / "registry.json"
    state.write_text(json.dumps({"schema": REGISTRY.SCHEMA, "records": [record]}))
    strict = ORCHESTRATE._integrate_handoff_check(
        str(state), ["feat/a"], allow_unhanded=False, repo=repo,
    )
    assert any(item["kind"] == "handback-seal-missing"
               for item in strict["problems"])
    legacy = ORCHESTRATE._integrate_handoff_check(
        str(state), ["feat/a"], allow_unhanded=True, repo=repo,
    )
    assert not legacy["problems"]
    assert any(item["kind"] == "handback-seal-missing"
               for item in legacy["warnings"])
