from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
REPO = OPS.parent
sys.path.insert(0, str(OPS))

import complexity
import doctor


def _budget(ops: int = 1000, docs: int = 500, workflows: int = 100) -> dict:
    return {
        "schema": complexity.SCHEMA,
        "slack": {"ops": 50, "docs": 20, "workflows": 5},
        "ceilings": {"ops": ops, "docs": docs, "workflows": workflows},
    }


MEASURED = {"ops": 900, "docs": 400, "workflows": 90, "reference": 300}


def _git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


# ---- the repository itself must honour its budget (this is the teeth) ----------


def test_the_repository_is_within_its_complexity_budget() -> None:
    budget = complexity.load_budget(REPO / complexity.BUDGET_FILE)
    over = [
        row
        for row in complexity.evaluate(complexity.measure(REPO), budget)
        if row["over"]
    ]
    assert not over, (
        "over the complexity budget: "
        + ", ".join(f"{r['area']} {r['lines']:,} > {r['ceiling']:,}" for r in over)
        + f". Delete something, or raise the ceiling in {complexity.BUDGET_FILE} in this PR and say why."
    )


# ---- measuring -----------------------------------------------------------------


def test_measure_counts_authored_lines_per_area_and_ignores_untracked_and_data_files(
    tmp_path: Path,
) -> None:
    repo = _git_repo(
        tmp_path,
        {
            "ops/a.py": "1\n2\n3\n",
            "ops/tests/b.py": "1\n",
            "docs/x.md": "1\n2\n",
            ".github/workflows/w.yml": "1\n",
            "ios/App.swift": "1\n2\n3\n4\n",
            "backend/ignored.py": "1\n" * 50,
            "ops/fixtures/world.json": "1\n" * 500,
            "ops/ui.plist": "1\n" * 40,
        },
    )
    (repo / "ops" / "untracked.py").write_text("1\n" * 99)
    assert complexity.measure(repo) == {
        "ops": 4,
        "docs": 2,
        "workflows": 1,
        "reference": 4,
    }


def test_a_file_without_a_trailing_newline_counts_like_wc(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path, {"ops/a.py": "one\ntwo"})
    assert complexity.count_lines(repo, "ops/") == 1


# ---- evaluating ----------------------------------------------------------------


def test_each_area_is_judged_against_its_own_ceiling() -> None:
    rows = {
        r["area"]: r for r in complexity.evaluate({**MEASURED, "ops": 1001}, _budget())
    }
    assert rows["ops"]["over"] is True
    assert rows["ops"]["headroom"] == -1
    assert rows["docs"]["over"] is False
    assert rows["docs"]["headroom"] == 100


def test_exactly_at_the_ceiling_is_allowed() -> None:
    assert not any(
        r["over"] for r in complexity.evaluate({**MEASURED, "ops": 1000}, _budget())
    )


# ---- ratchet -------------------------------------------------------------------


def test_ratchet_lowers_to_measured_plus_slack() -> None:
    assert complexity.ratcheted(MEASURED, _budget()) == {
        "ops": 950,
        "docs": 420,
        "workflows": 95,
    }


def test_ratchet_never_raises_a_ceiling() -> None:
    grown = {**MEASURED, "ops": 5000, "docs": 5000, "workflows": 5000}
    assert complexity.ratcheted(grown, _budget()) == {
        "ops": 1000,
        "docs": 500,
        "workflows": 100,
    }


def test_ratchet_command_rewrites_the_file_only_when_something_drops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(
        tmp_path,
        {
            "ops/a.py": "1\n" * 10,
            "docs/x.md": "1\n",
            ".github/workflows/w.yml": "1\n",
            "ios/a.swift": "1\n",
        },
    )
    path = repo / complexity.BUDGET_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(_budget()))
    assert complexity.main(["ratchet"], repo=repo) == 0
    after = json.loads(path.read_text())["ceilings"]
    assert after == {"ops": 60, "docs": 21, "workflows": 6}
    assert "ratchet: wrote" in capsys.readouterr().out
    before = path.read_text()
    assert complexity.main(["ratchet"], repo=repo) == 0
    assert path.read_text() == before
    assert "nothing to lower" in capsys.readouterr().out


# ---- budget file validation ------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(schema="wrong"),
        lambda b: b["ceilings"].pop("docs"),
        lambda b: b["slack"].pop("ops"),
    ],
)
def test_a_malformed_budget_is_rejected(tmp_path: Path, mutate) -> None:
    budget = _budget()
    mutate(budget)
    path = tmp_path / "b.json"
    path.write_text(json.dumps(budget))
    with pytest.raises(complexity.BudgetError):
        complexity.load_budget(path)


def test_an_unreadable_budget_is_a_usage_error_not_a_pass(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path, {"ops/a.py": "1\n"})
    assert complexity.main(["check"], repo=repo) == 2


def test_check_fails_with_the_remedy_when_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path, {"ops/a.py": "1\n" * 30, "ios/a.swift": "1\n"})
    path = repo / complexity.BUDGET_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(_budget(ops=10)))
    assert complexity.main(["check"], repo=repo) == 1
    err = capsys.readouterr().err
    assert "over budget: ops" in err
    assert "raise the ceiling" in err


# ---- doctor integration ----------------------------------------------------------


def test_doctor_reports_over_budget_areas_by_name() -> None:
    rows = complexity.evaluate({**MEASURED, "docs": 600}, _budget())
    finding = doctor.evaluate_complexity(rows, 1.7)
    assert finding.level == "warn"
    assert finding.detail == ["docs: 600 lines > ceiling 500"]


def test_doctor_reports_the_tightest_area_when_within_budget() -> None:
    finding = doctor.evaluate_complexity(complexity.evaluate(MEASURED, _budget()), 1.72)
    assert finding.level == "ok"
    assert "workflows" in finding.summary
    assert "ops:ios 1.72" in finding.summary


def test_doctor_warns_when_the_budget_cannot_be_read() -> None:
    assert doctor.evaluate_complexity(None, None).level == "warn"
