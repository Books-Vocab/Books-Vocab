"""Topology guard for the bounded campaign projection test surface."""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_TEST = "ops/tests/test_worktree_campaign_reservation.py"
EXPECTED_MARKERS = (
    "test_valid_r3_ticketed_active_record_has_one_canonical_projection",
    "test_missing_or_legacy_provenance_is_explicitly_fail_closed",
    "test_base_and_digest_drift_is_explicitly_fail_closed",
    "test_next_campaign_refuses_shared_path_against_valid_projection",
)


def _collect(path: str) -> Counter[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            path,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return Counter(
        line.strip().split("::", 1)[1]
        for line in result.stdout.splitlines()
        if "::" in line and line.strip().startswith("ops/tests/")
    )


def test_campaign_projection_regressions_are_collected_once():
    nodes = _collect(CAMPAIGN_TEST)
    assert nodes
    for marker in EXPECTED_MARKERS:
        assert sum(marker in node for node in nodes) >= 1, sorted(nodes)


def test_campaign_projection_surface_is_pure_and_runner_unchanged():
    source = (ROOT / "ops/lib/worktree_campaign.py").read_text(encoding="utf-8")
    runner = (ROOT / "ops/test_ops.sh").read_text(encoding="utf-8")

    assert "worktree_registry" not in source
    assert "worktree_campaign" not in runner
