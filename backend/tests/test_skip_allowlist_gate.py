"""Issue #2115: a backend test that skips in CI must be budgeted against an issue.

The podcast preview tests skipped on every CI run because the runner had no
ffmpeg, and nothing turned "5 skipped" into a failure. ``--skip-allowlist``
makes every skip either an issue-linked allowlist entry or a red run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import _skip_allowlist_gate as gate

TESTS_DIR = Path(__file__).resolve().parent
BACKEND = TESTS_DIR.parent
COMMITTED_ALLOWLIST = TESTS_DIR / "skip_allowlist.json"
ISSUE = "https://github.com/Books-Vocab/Books-Vocab/issues/2115"
PREVIEW = "tests/test_podcast_preview_backfill.py"
PREVIEW_FFMPEG_SKIPIF = (
    f"{PREVIEW}::test_make_preview_bytes_truncates_to_180s",
    f"{PREVIEW}::test_make_preview_bytes_shorter_than_window",
    f"{PREVIEW}::test_backfill_publishes_preview_and_flags_metadata",
    f"{PREVIEW}::test_backfill_is_idempotent",
)
PREVIEW_RUNTIME_SKIP = f"{PREVIEW}::test_backfill_dry_run_writes_nothing"
PREVIEW_ALWAYS_RUNS = f"{PREVIEW}::test_patch_preview_meta_flags_ep1_only"

SAMPLE_SUITE = """\
import pytest


def test_runs():
    pass


@pytest.mark.skip(reason="needs a tool the runner lacks")
def test_skipped():
    pass


@pytest.mark.xfail(reason="known defect", strict=True)
def test_known_defect():
    assert False
"""


def _entry(nodeid: str, *, issue: str = ISSUE, reason: str = "runner lacks the tool") -> dict[str, str]:
    return {"nodeid": nodeid, "issue": issue, "reason": reason}


def _allowlist(path: Path, *nodeids: str) -> Path:
    path.write_text(
        json.dumps({"schema": gate.SCHEMA, "skips": [_entry(nodeid) for nodeid in nodeids]}),
        encoding="utf-8",
    )
    return path


def _child_env(**overrides: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST_", "COV_", "COVERAGE_"))}
    env.update(overrides)
    return env


def _run_sample(tmp_path: Path, *args: str, files: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run an isolated pytest session with only the gate plugin loaded."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name, source in (files or {"test_sample.py": SAMPLE_SUITE}).items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "-p", "_skip_allowlist_gate", *args],
        cwd=tmp_path,
        env=_child_env(PYTHONPATH=str(TESTS_DIR), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        capture_output=True,
        text=True,
        timeout=120,
    )


# ── gate semantics on a synthetic suite ──────────────────────────────────────


def test_gate_is_inactive_without_the_option(tmp_path: Path) -> None:
    result = _run_sample(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "skip allowlist" not in result.stdout


def test_skip_outside_the_allowlist_fails_the_run(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path / "allow.json")

    result = _run_sample(tmp_path, f"--skip-allowlist={allowlist}")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "unexpected skip: test_sample.py::test_skipped" in result.stdout
    assert "test_known_defect" not in result.stdout.split("skip allowlist", 1)[1]


def test_allowlisted_skip_passes_and_xfail_is_not_budgeted(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path / "allow.json", "test_sample.py::test_skipped")

    result = _run_sample(tmp_path, f"--skip-allowlist={allowlist}")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 skipped, 1 xfailed" in result.stdout
    assert "skip allowlist: 1 skipped, all covered by" in result.stdout


def test_allowlist_entry_for_a_test_that_ran_is_stale(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path / "allow.json", "test_sample.py::test_skipped", "test_sample.py::test_runs")

    result = _run_sample(tmp_path, f"--skip-allowlist={allowlist}")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "stale allowlist entry: test_sample.py::test_runs" in result.stdout
    assert "unexpected skip" not in result.stdout


def test_module_level_skip_is_budgeted(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path / "allow.json")
    module_skip = 'import pytest\n\npytest.skip("optional dependency missing", allow_module_level=True)\n'

    result = _run_sample(
        tmp_path,
        f"--skip-allowlist={allowlist}",
        files={"test_optional.py": module_skip, "test_plain.py": "def test_ok():\n    pass\n"},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "unexpected skip: test_optional.py" in result.stdout


def test_collect_only_does_not_evaluate_the_budget(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path / "allow.json", "test_sample.py::test_runs")

    result = _run_sample(tmp_path, "--collect-only", f"--skip-allowlist={allowlist}")

    assert result.returncode == 0, result.stdout + result.stderr


def test_untrusted_allowlist_is_a_usage_error(tmp_path: Path) -> None:
    allowlist = tmp_path / "allow.json"
    allowlist.write_text(json.dumps({"schema": gate.SCHEMA, "skips": [{"nodeid": "test_sample.py::test_skipped"}]}))

    result = _run_sample(tmp_path, f"--skip-allowlist={allowlist}")

    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "skips[0]" in result.stderr


# ── allowlist schema ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "expected"),
        ({"schema": "other.v1", "skips": []}, "expected"),
        ({"schema": gate.SCHEMA, "skips": [], "note": "x"}, "expected"),
        ({"schema": gate.SCHEMA, "skips": [{"nodeid": "t.py::a", "reason": "r"}]}, "exactly"),
        ({"schema": gate.SCHEMA, "skips": [{**_entry("t.py::a"), "owner": "me"}]}, "exactly"),
        ({"schema": gate.SCHEMA, "skips": [_entry("t.py::a", reason=" ")]}, "non-empty"),
        ({"schema": gate.SCHEMA, "skips": [_entry("t.py::a", issue="#2115")]}, "Books-Vocab issue"),
        (
            {"schema": gate.SCHEMA, "skips": [_entry("t.py::a", issue=ISSUE.replace("issues", "pull"))]},
            "Books-Vocab issue",
        ),
        (
            {"schema": gate.SCHEMA, "skips": [_entry("t.py::a", issue=ISSUE.replace("Books-Vocab/Books", "x/Books"))]},
            "Books-Vocab issue",
        ),
        ({"schema": gate.SCHEMA, "skips": [_entry("t.py::a"), _entry("t.py::a")]}, "duplicate"),
    ],
)
def test_allowlist_rejects_entries_without_a_linked_issue(tmp_path: Path, payload: object, message: str) -> None:
    path = tmp_path / "allow.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(gate.AllowlistError, match=message):
        gate.load_allowlist(path)


def test_committed_allowlist_links_an_issue_for_every_existing_test() -> None:
    allowed = gate.load_allowlist(COMMITTED_ALLOWLIST)

    for nodeid, entry in allowed.items():
        file_part, _, test_part = nodeid.partition("::")
        source = BACKEND / file_part
        assert source.is_file(), f"{nodeid}: allowlisted test file does not exist ({entry.issue})"
        if test_part:
            name = test_part.split("::")[-1].split("[", 1)[0]
            assert re.search(rf"(?m)^\s*(?:async )?def {re.escape(name)}\(", source.read_text(encoding="utf-8")), (
                f"{nodeid}: allowlisted test is not defined ({entry.issue})"
            )


# ── the real backend wiring on the tests that motivated #2115 ────────────────


def test_backend_conftest_enforces_the_budget_on_ffmpeg_skips(tmp_path: Path) -> None:
    """Hide ffmpeg and run the real preview tests through backend/tests/conftest.py.

    Four ffmpeg skips are allowlisted, the runtime ``pytest.skip`` one is not,
    and one always-running test is wrongly allowlisted: the run must name
    exactly the unexpected skip and the stale entry.
    """
    allowlist = _allowlist(tmp_path / "allow.json", *PREVIEW_FFMPEG_SKIPIF, PREVIEW_ALWAYS_RUNS)
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
            f"--skip-allowlist={allowlist}",
            PREVIEW,
        ],
        cwd=BACKEND,
        env=_child_env(PATH=str(empty_bin)),
        capture_output=True,
        text=True,
        timeout=300,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "5 skipped" in result.stdout, output
    violations = sorted(line for line in result.stdout.splitlines() if line.startswith(("unexpected skip:", "stale")))
    assert len(violations) == 2, output
    assert violations[0].startswith(f"stale allowlist entry: {PREVIEW_ALWAYS_RUNS} ")
    assert violations[1].startswith(f"unexpected skip: {PREVIEW_RUNTIME_SKIP} ")
