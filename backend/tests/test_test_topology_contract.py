# ruff: noqa: F401, F403, F405, I001
"""Guard the backend test ownership and collection manifest contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
AGGREGATES = (
    TESTS / "test_dictionary_v1.py",
    TESTS / "test_ops_cli.py",
    TESTS / "test_ops_edit.py",
)
MANIFEST = TESTS / "test_topology_manifest.json"
MAX_MODULE_LINES = 900


def _collect_ids() -> list[str]:
    paths = sorted(
        {
            *TESTS.glob("test_dictionary*.py"),
            *TESTS.glob("test_ops_cli*.py"),
            *TESTS.glob("test_ops_edit*.py"),
        }
    )
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        *(str(path.relative_to(ROOT.parent)) for path in paths),
    ]
    result = subprocess.run(command, cwd=ROOT.parent, check=True, text=True, capture_output=True)
    return sorted(
        line.strip().split("::", 1)[1]
        for line in result.stdout.splitlines()
        if "::" in line and not line.endswith(" tests collected")
    )


def test_aggregate_modules_are_sharded_by_ownership() -> None:
    oversized = {
        str(path.relative_to(ROOT.parent)): len(path.read_text(encoding="utf-8").splitlines())
        for path in AGGREGATES
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_MODULE_LINES
    }
    assert not oversized, f"test ownership aggregates exceed {MAX_MODULE_LINES} lines: {oversized}"


def test_collection_manifest_preserves_every_case_and_signature() -> None:
    assert MANIFEST.is_file(), f"missing collection manifest: {MANIFEST}"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = manifest["cases"]
    actual = _collect_ids()
    assert manifest["case_count"] == len(expected)
    # Existing split modules may already contribute cases outside the three
    # aggregates.  The contract is preservation: every baseline case must
    # still be collectable after it moves, while unrelated cases may remain.
    assert len(actual) >= manifest["case_count"]
    assert set(expected).issubset(actual)
