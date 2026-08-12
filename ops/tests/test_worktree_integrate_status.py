"""Read-only integration status projection contract (IMP-20260809-6f38c6)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "worktree_integration_status_target",
    ROOT / "ops" / "lib" / "worktree_integration_status.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

ORCH_SPEC = importlib.util.spec_from_file_location(
    "worktree_orchestrate_status_target", ROOT / "ops" / "worktree_orchestrate.py"
)
assert ORCH_SPEC and ORCH_SPEC.loader
ORCH = importlib.util.module_from_spec(ORCH_SPEC)
sys.modules[ORCH_SPEC.name] = ORCH
ORCH_SPEC.loader.exec_module(ORCH)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        capture_output=True,
    )
    return result.stdout.strip()


@pytest.fixture
def fixture(tmp_path: Path) -> dict[str, Path | str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Status Test")
    (repo / "README").write_text("base\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    branch = "feat/status-source"
    _git(repo, "branch", branch)
    state_path = tmp_path / "worktree_registry.json"
    state_path.write_text(json.dumps({"records": [], "campaign_reservations": []}))
    return {"repo": repo, "base": base, "branch": branch, "state": state_path}


def _write_state(fixture: dict[str, Path | str], *, phase: str = "picking") -> Path:
    repo = fixture["repo"]
    state_path = fixture["state"]
    branch = str(fixture["branch"])
    base = str(fixture["base"])
    worktree = str(repo)
    integration_state = state_path.parent / "worktree_integrations" / "status.json"
    integration_state.parent.mkdir()
    integration_state.write_text(json.dumps({
        "schema": "kg.worktree.integrate.v1",
        "slug": "status",
        "base": "main",
        "trunk": "main",
        "worktree": worktree,
        "branch": "main",
        "branches": [branch],
        "handoff": {"source_refs": {branch: base}},
        "queue": [{"branch": branch, "sha": "f" * 40, "subject": "pending"}],
        "picked": [],
        "skipped": [],
        "planned_total": 1,
        "opened_at": "2026-08-12T00:00:00Z",
        "gate_pending": phase in {"gate-pending", "gate-blocked"},
        **({"stopped": {"branch": branch, "sha": "f" * 40,
                        "head_before": base}} if phase == "conflicted" else {}),
    }))
    return integration_state


def test_status_projector_reports_picking_and_is_stable(fixture):
    _write_state(fixture)
    rc, first = MODULE.project_status(
        slug="status", state_path=fixture["state"], repo=fixture["repo"],
    )
    rc2, second = MODULE.project_status(
        slug="status", state_path=fixture["state"], repo=fixture["repo"],
    )
    assert rc == rc2 == 0
    assert first == second
    assert first["phase"] == "picking"
    assert first["picked"] == []
    assert len(first["remaining"]) == 1
    assert first["conflicts"] == []
    assert isinstance(first["source_tips"], dict)
    assert first["next_action"] == "continue"


def test_integrate_status_cli_is_read_only_and_mutation_flags_refuse(fixture, capsys):
    _write_state(fixture)
    args = [
        "integrate", "--slug", "status", "--status", "--state",
        str(fixture["state"]), "--json",
    ]
    rc = ORCH.main(args)
    first = json.loads(capsys.readouterr().out)
    rc2 = ORCH.main(args)
    second = json.loads(capsys.readouterr().out)
    assert rc == rc2 == 0
    assert first == second
    assert first["next_action"] == "continue"

    rc = ORCH.main(args[:-1] + ["--commit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == ORCH.EXIT_USAGE
    assert payload["conflicts"] == ["--commit"]

    rc = ORCH.main([
        "integrate", "--slug", "status", "--status", "--state",
        str(fixture["state"]), "--base", "not-the-default", "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert rc == ORCH.EXIT_USAGE
    assert payload["conflicts"] == ["--base"]

    rc = ORCH.main([
        "integrate", "--slug", "status", "--status", "--state",
        str(fixture["state"]), "--base", "main", "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert rc == ORCH.EXIT_USAGE
    assert payload["conflicts"] == ["--base"]


def test_status_projection_does_not_create_or_mutate_control_plane_files(fixture):
    state_file = _write_state(fixture)
    registry = fixture["state"]
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (state_file, registry)
    }
    gate_dir = fixture["state"].parent / "worktree_gates"
    history = gate_dir / "history.jsonl"
    assert not gate_dir.exists()
    rc, _ = MODULE.project_status(
        slug="status", state_path=registry, repo=fixture["repo"],
    )
    assert rc == 0
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (state_file, registry)} == before
    assert not gate_dir.exists()
    assert not history.exists()


def test_status_projector_distinguishes_unknown_and_unreadable(fixture):
    rc, payload = MODULE.project_status(
        slug="missing", state_path=fixture["state"], repo=fixture["repo"],
    )
    assert rc == 64
    assert payload["problems"][0]["kind"] == "state-missing"

    state = fixture["state"].parent / "worktree_integrations" / "status.json"
    state.parent.mkdir()
    state.write_text("{not-json")
    rc, payload = MODULE.project_status(
        slug="status", state_path=fixture["state"], repo=fixture["repo"],
    )
    assert rc == 64
    assert payload["problems"][0]["kind"] == "state-unreadable"

    state.write_text(json.dumps({"schema": "kg.worktree.integrate.legacy"}))
    rc, payload = MODULE.project_status(
        slug="status", state_path=fixture["state"], repo=fixture["repo"],
    )
    assert rc == 64
    assert payload["problems"][0]["kind"] == "state-schema"


def test_owner_projection_accepts_legacy_top_level_source_refs(fixture):
    state = {
        "branch": "main",
        "handoff": "legacy-non-object",
        "source_refs": {fixture["branch"]: fixture["base"]},
    }
    registry = {
        "records": [{
            "status": "active",
            "path": str(fixture["repo"]),
            "integration_owner": {
                "branch": "main", "slug": "status",
            },
        }],
    }
    owners = MODULE._owner_map(registry, state, [str(fixture["branch"])])
    assert owners[str(fixture["branch"])] == {
        "branch": "main", "slug": "status", "path": str(fixture["repo"].resolve()),
    }


@pytest.mark.parametrize(
    ("phase", "expected_phase", "expected_action"),
    [
        ("conflicted", "conflicted", "resolve-and-continue"),
        ("gate-pending", "gate-pending", "continue-to-gate"),
        ("gate-blocked", "gate-blocked", "continue-to-gate"),
    ],
)
def test_status_projector_covers_stopped_and_gate_phases(
    fixture, monkeypatch, phase, expected_phase, expected_action,
):
    state_file = _write_state(fixture, phase=phase)
    raw = json.loads(state_file.read_text())
    raw["queue"] = []
    raw["picked"] = [{"branch": fixture["branch"], "sha": fixture["base"],
                      "new_sha": fixture["base"], "subject": "picked"}]
    raw["head_sha"] = fixture["base"]
    raw["gate_pending"] = phase != "conflicted"
    state_file.write_text(json.dumps(raw))
    if phase == "gate-blocked":
        gate = MODULE.gate_record_path(fixture["state"], str(fixture["repo"]))
        gate.parent.mkdir()
        gate.write_text(json.dumps({"head_sha": fixture["base"], "verdict": "block"}))
    if phase == "conflicted":
        monkeypatch.setattr(MODULE, "_conflicts", lambda _repo: ["README"])
    rc, payload = MODULE.project_status(
        slug="status", state_path=fixture["state"], repo=fixture["repo"],
    )
    assert rc == (1 if phase == "conflicted" else 0)
    assert payload["phase"] == expected_phase
    assert payload["next_action"] == expected_action
    assert len([payload["next_action"]]) == 1


@pytest.mark.parametrize("drift_kind", ["branch", "head", "source", "owner"])
def test_status_projector_names_each_drift(fixture, drift_kind):
    _write_state(fixture)
    if drift_kind == "branch":
        state = fixture["state"].parent / "worktree_integrations" / "status.json"
        raw = json.loads(state.read_text())
        raw["branch"] = "feat/moved"
        state.write_text(json.dumps(raw))
    elif drift_kind == "head":
        state = fixture["state"].parent / "worktree_integrations" / "status.json"
        raw = json.loads(state.read_text())
        raw["head_sha"] = "0" * 40
        state.write_text(json.dumps(raw))
    elif drift_kind == "source":
        _git(fixture["repo"], "branch", "feat/source-moved")
        state = fixture["state"].parent / "worktree_integrations" / "status.json"
        raw = json.loads(state.read_text())
        raw["handoff"]["source_refs"][fixture["branch"]] = "0" * 40
        state.write_text(json.dumps(raw))
    else:
        state = fixture["state"].parent / "worktree_integrations" / "status.json"
        raw = json.loads(state.read_text())
        raw["source_claim"] = {"ok": False, "problems": [{"reason": "foreign"}]}
        state.write_text(json.dumps(raw))
    rc, payload = MODULE.project_status(
        slug="status", state_path=fixture["state"], repo=fixture["repo"],
    )
    assert rc == 1
    assert any(problem["kind"] == f"{drift_kind}-drift" for problem in payload["problems"])
