from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import worktree_registry as registry
from worktree_reanchor_core import registry_ops

BASE = "a" * 40
HEAD = "b" * 40
PUBLISHED_BASE = "c" * 40


def _record(tmp_path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "branch": "feat/published-base",
        "path": str(tmp_path / "worktree"),
        "intent": "record published PR target",
        "base": BASE,
        "base_sha": BASE,
        "status": "active",
        "external_ids": ["DIRECT-PUBLISHED-BASE"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/a.py", "operation": "modify"}],
        },
        "codex_thread_id": "owner-thread",
        "delegated": True,
        "claim_generation": 2,
        "handed_back_at": "2026-08-22T00:00:00Z",
        "handed_back_sha": HEAD,
        "handback_claim_generation": 2,
    }
    record["handback_seal"] = registry._seal_with_digest(
        registry._seal_body(
            record,
            base_sha=BASE,
            tip_sha=HEAD,
            outcomes=[{"name": "focused", "status": "success"}],
            handed_back_at="2026-08-22T00:00:00Z",
            origin_main_sha=BASE,
        )
    )
    return record


def _argv(
    state: Path, record: dict[str, object], published: str = PUBLISHED_BASE
) -> list[str]:
    return [
        "record-published-base",
        "--state",
        str(state),
        "--lane",
        "DIRECT-PUBLISHED-BASE",
        "--branch",
        str(record["branch"]),
        "--path",
        str(record["path"]),
        "--expected-generation",
        "2",
        "--expected-head-sha",
        HEAD,
        "--expected-handback-base-sha",
        BASE,
        "--published-base-sha",
        published,
        "--json",
    ]


def test_record_published_base_is_cas_guarded_and_idempotent(tmp_path: Path) -> None:
    state = tmp_path / "registry.json"
    record = _record(tmp_path)
    registry.save_state(state, {"schema": registry.SCHEMA, "records": [record]})

    assert registry.main(_argv(state, record)) == registry.EXIT_OK
    first = registry.load_state(state)["records"][0]
    assert first["base_sha"] == BASE
    assert first["published_base_sha"] == PUBLISHED_BASE
    assert first["handback_seal"] == record["handback_seal"]

    assert registry.main(_argv(state, record)) == registry.EXIT_OK
    second = registry.load_state(state)["records"][0]
    assert second["published_base_sha"] == PUBLISHED_BASE


def test_record_published_base_refuses_conflicting_observation(tmp_path: Path) -> None:
    state = tmp_path / "registry.json"
    record = _record(tmp_path)
    record["published_base_sha"] = "d" * 40
    registry.save_state(state, {"schema": registry.SCHEMA, "records": [record]})

    assert registry.main(_argv(state, record)) == registry.EXIT_CLAIMED
    assert registry.load_state(state)["records"][0]["published_base_sha"] == "d" * 40


def test_reanchor_uses_exact_base_sha_when_legacy_base_is_a_ref(tmp_path: Path) -> None:
    state = tmp_path / "registry.json"
    record = _record(tmp_path)
    record["status"] = "published"
    record["base"] = "origin/main"
    registry.save_state(state, {"schema": registry.SCHEMA, "records": [record]})

    result = registry_ops._preflight_published(
        state_path=state,
        lane_id="DIRECT-PUBLISHED-BASE",
        branch=str(record["branch"]),
        owner_thread_id="owner-thread",
        claim_generation=2,
        expected_remote_head=HEAD,
        target=tmp_path / "reanchored",
        replacement_base="e" * 40,
        replacement_base_sha="e" * 40,
    )

    assert result.base_sha == BASE
    assert result.published_base_sha == BASE
