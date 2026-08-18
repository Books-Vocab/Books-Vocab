"""Machine contract for the worktree-registry test topology.

The registry collector is a historical compatibility entry point.  Focused
groups may move test ownership, but they must not silently lose or duplicate a
pytest node id, and a selector that collects nothing must fail closed.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
LEGACY = "ops/tests/test_worktree_registry.py"
SPLIT = (
    "ops/tests/test_worktree_registry_lifecycle.py",
    "ops/tests/test_worktree_registry_recovery.py",
)
DISPATCHED_REGISTRY_FILES = (
    *SPLIT,
    "ops/tests/test_worktree_registry_topology.py",
    "ops/tests/test_worktree_registry_queries.py",
    "ops/tests/test_worktree_handback_outcomes.py",
    "ops/tests/test_worktree_campaign_reservation.py",
)


def _collect(path: str | Path) -> Counter[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 5:
        raise AssertionError(f"zero-selector collection for {path}")
    assert result.returncode == 0, result.stderr or result.stdout
    nodeids = Counter(
        line.strip().split("::", 1)[1]
        for line in result.stdout.splitlines()
        if "::" in line and line.strip().startswith("ops/tests/")
    )
    assert nodeids, f"zero-selector collection for {path}"
    return nodeids


def test_legacy_registry_collector_matches_focused_nodeid_union():
    legacy = _collect(LEGACY)
    focused = Counter()
    for path in SPLIT:
        focused.update(_collect(path))

    assert legacy == focused
    assert all(count == 1 for count in focused.values())


def test_registry_dispatcher_has_one_explicit_owner_for_each_group():
    source = (ROOT / "ops/test_ops.sh").read_text(encoding="utf-8")
    arm = source.split("worktree-orchestrator)", 1)[1].split(";;", 1)[0]

    for path in DISPATCHED_REGISTRY_FILES:
        assert arm.count(path) == 1, f"dispatcher ownership drift for {path}"
    # The old path remains callable as a compatibility collector, not as a
    # second normal group selector that would duplicate every node.
    assert LEGACY not in arm


def test_registry_group_is_in_default_ci_coverage_and_not_zero_selected():
    source = (ROOT / "ops/tests/test_ops_ci_coverage.sh").read_text(encoding="utf-8")
    linux_groups = source.split("LINUX_GROUPS=(", 1)[1].split(")", 1)[0]
    assert len(re.findall(r"^\s*worktree-orchestrator\s*$", linux_groups, re.MULTILINE)) == 1


def test_collection_probe_rejects_a_real_zero_selector(tmp_path):
    empty = tmp_path / "test_empty_selector.py"
    empty.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="zero-selector"):
        _collect(empty)


def test_campaign_active_projection_regressions_are_collected():
    nodes = _collect("ops/tests/test_worktree_campaign_reservation.py")

    assert any("active_campaign_projection" in node for node in nodes), sorted(nodes)
