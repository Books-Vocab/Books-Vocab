from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "github_issue_bridge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("github_issue_bridge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_entry(store: Path, entry_id: str, **overrides) -> None:
    payload = {
        "schema": "kg.backlog.entry.v1",
        "id": entry_id,
        "stream": "IMP",
        "date": "2026-08-19",
        "source": "migration test",
        "category": "tooling",
        "severity": "med",
        "status": "triaged",
        "brief": "把本地票務接到 GitHub Issues。",
        "detail": "本地 backlog 目前保存工作項目，遷移後由 GitHub Issue 作為工作項目 SoT。",
        "plan": "建立 deterministic export，再由人工確認後匯入。",
        "acceptance": "匯出 payload 可被 GitHub API 接受，且不包含可執行 shell command。",
        "acceptance_cmd": "touch /tmp/should-never-be-exported",
        "acceptance_expect_rc": 0,
        "fix_site": "ops/github_issue_bridge.py",
        "scope": {
            "schema": "kg.backlog.scope.v1",
            "files": [{"path": "ops/github_issue_bridge.py", "operation": "modify"}],
        },
        "blocked_by": [],
    }
    payload.update(overrides)
    (store / f"{entry_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_build_issue_uses_key_not_shell_command():
    mod = load_module()
    entry = {
        "id": "IMP-20260819-a1b2c3",
        "stream": "IMP",
        "status": "triaged",
        "severity": "med",
        "brief": "把本地票務接到 GitHub Issues。",
        "detail": "GitHub Issue 只保存人讀內容。",
        "plan": "先匯出，再匯入。",
        "acceptance": "payload 可重現。",
        "acceptance_cmd": "touch /tmp/secret-side-effect",
        "scope": {
            "schema": "kg.backlog.scope.v1",
            "files": [{"path": "ops/github_issue_bridge.py", "operation": "modify"}],
        },
    }

    issue = mod.build_issue(entry)

    assert issue["legacy_id"] == "IMP-20260819-a1b2c3"
    assert issue["acceptance_key"] == "legacy/IMP-20260819-a1b2c3"
    assert issue["acceptance_mode"] == "command"
    assert "touch /tmp/secret-side-effect" not in issue["body"]
    assert "legacy/IMP-20260819-a1b2c3" in issue["body"]
    assert "kg:stream-imp" in issue["labels"]
    assert "kg:scope-known" in issue["labels"]


def test_export_active_only_is_deterministic_and_excludes_closed(tmp_path):
    mod = load_module()
    store = tmp_path / "backlog"
    store.mkdir()
    write_entry(store, "IMP-20260819-a1b2c3")
    write_entry(
        store,
        "APP-20260819-d4e5f6",
        stream="APP",
        status="fixed",
        severity="low",
        brief="已完成的歷史票。",
        acceptance_cmd="printf historical",
    )

    first = mod.export_manifest(store, active_only=True, repository="MaxChen228/Books-Vocab")
    second = mod.export_manifest(store, active_only=True, repository="MaxChen228/Books-Vocab")

    assert first == second
    assert first["schema"] == "kg.github.issue-migration.v1"
    assert first["source"]["total"] == 2
    assert first["source"]["active"] == 1
    assert first["source"]["closed"] == 1
    assert len(first["issues"]) == 1
    assert first["issues"][0]["legacy_id"] == "IMP-20260819-a1b2c3"
    assert first["skipped"] == []


def test_scope_status_does_not_guess_from_legacy_prose():
    mod = load_module()

    assert mod.scope_status("ops/backlog.py:dispatch") == "unknown"
    assert mod.scope_status({"files": []}) == "invalid"
    assert mod.scope_status(
        {"files": [{"path": "ops/backlog.py", "operation": "modify"}]}
    ) == "known"


def test_export_rejects_duplicate_or_mismatched_entry_identity(tmp_path):
    mod = load_module()
    store = tmp_path / "backlog"
    store.mkdir()
    write_entry(store, "IMP-20260819-a1b2c3")
    bad = json.loads((store / "IMP-20260819-a1b2c3.json").read_text(encoding="utf-8"))
    bad["id"] = "IMP-20260819-different"
    (store / "IMP-20260819-bad999.json").write_text(
        json.dumps(bad, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(mod.BridgeError, match="identity mismatch"):
        mod.export_manifest(store, active_only=True, repository="MaxChen228/Books-Vocab")
