"""Focused tests for the backlog store/locking seam."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("backlog_store_under_test", OPS / "backlog_store.py")
assert SPEC and SPEC.loader
STORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STORE
SPEC.loader.exec_module(STORE)


def test_store_seam_owns_serialization_and_paths(tmp_path):
    store = tmp_path / "backlog"
    payload = {"z": 1, "a": "值"}

    assert STORE.entry_path(store, "IMP-20260816-abcdef") == (
        store / "IMP-20260816-abcdef.json"
    )
    assert json.loads(STORE.dumps(payload)) == payload


def test_store_seam_writes_atomically_and_preserves_mode(tmp_path):
    target = tmp_path / "entry.json"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o644)

    STORE.write_atomic(target, '{"new": true}\n')

    assert target.read_text(encoding="utf-8") == '{"new": true}\n'
    assert target.stat().st_mode & 0o777 == 0o644
    assert not list(tmp_path.glob(".*tmp*"))


def test_store_resolver_accepts_an_external_path_without_reinterpreting_it(tmp_path):
    root = tmp_path / "kg"
    external = tmp_path / "kg-backlog"

    resolved = STORE.resolve_store(root, {STORE.STORE_ENV: str(external)})

    assert resolved == external.resolve()
    assert STORE.store_descriptor(resolved, root) == {
        "schema": "kg.backlog.store.v1",
        "path": str(external.resolve()),
        "mode": "external",
        "independent": True,
        "code_repo": str(root.resolve()),
    }


def test_store_resolver_preserves_legacy_default_until_external_store_is_selected(tmp_path):
    root = tmp_path / "kg"

    resolved = STORE.resolve_store(root, {})

    assert resolved == (root / "docs" / "runbook" / "backlog").resolve()
    assert STORE.store_descriptor(resolved, root)["mode"] == "repo-legacy"


def test_external_store_uses_a_view_next_to_the_store_not_inside_the_code_repo(tmp_path):
    root = tmp_path / "kg"
    external = tmp_path / "kg-backlog" / "entries"

    assert STORE.default_view(external, root) == (
        tmp_path / "kg-backlog" / "improvement_backlog.md"
    )
