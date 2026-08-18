"""Machine contract for the backlog legacy-test collector.

The large historical ``test_backlog.py`` file remains a compatibility source.
The dispatcher must execute its tests through the named collector and the
focused seam files exactly once, so a topology edit cannot silently lose or
duplicate a node id.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import sys

import pytest
import test_backlog as legacy


ROOT = Path(__file__).resolve().parents[2]
LEGACY = "ops/tests/test_backlog.py"
COLLECTOR = "ops/tests/test_backlog_legacy_collector.py"
SEAMS = (
    "ops/tests/test_backlog_migration.py",
    "ops/tests/test_backlog_acceptance.py",
    "ops/tests/test_backlog_contract.py",
    "ops/tests/test_backlog_legacy_view_seams.py",
    "ops/tests/test_backlog_mutations.py",
    "ops/tests/test_backlog_query_seam.py",
    "ops/tests/test_backlog_reanchor.py",
    "ops/tests/test_backlog_store.py",
    "ops/tests/test_backlog_verification.py",
    "ops/tests/test_backlog_wave.py",
)
AUDIT_TESTS = {
    "test_legacy_collector_preserves_all_source_nodeids",
    "test_backlog_dispatcher_has_one_explicit_owner_per_path",
    "test_collection_probe_rejects_zero_selector",
}


# Keep the historical test module as the source of truth while giving the
# dispatcher a named compatibility route.  Re-exporting the function objects
# preserves parametrization, fixture markers, and the original function names
# without copying 8k lines of legacy test setup into a second collector.
_fake_object_database = legacy._fake_object_database
for _name, _value in vars(legacy).items():
    if _name.startswith("test_"):
        globals()[_name] = _value


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


def test_legacy_collector_preserves_all_source_nodeids():
    legacy = _collect(LEGACY)
    collector = _collect(COLLECTOR)
    compatibility = Counter(
        {nodeid: count for nodeid, count in collector.items()
         if nodeid not in AUDIT_TESTS}
    )

    assert legacy == compatibility
    assert all(count == 1 for count in compatibility.values())


def test_backlog_dispatcher_has_one_explicit_owner_per_path():
    source = (ROOT / "ops/test_ops.sh").read_text(encoding="utf-8")
    arm = source.split("backlog)", 1)[1].split(";;", 1)[0]

    for path in (COLLECTOR, *SEAMS):
        assert arm.count(path) == 1, f"dispatcher ownership drift for {path}"
    assert LEGACY not in arm


def test_collection_probe_rejects_zero_selector(tmp_path: Path):
    empty = tmp_path / "test_empty_selector.py"
    empty.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="zero-selector"):
        _collect(empty)


del _name
del _value
