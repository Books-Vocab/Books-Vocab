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


def test_the_repository_is_within_its_complexity_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Same entry the operator runs: delta-aware on PRs, absolute on push to main."""
    code = complexity.main(["check", *complexity.ci_args()], repo=REPO)
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err


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


# ---- merge-base delta (#2679): a red base must not block a change that adds nothing ----


def _commit(repo: Path, message: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        + ["commit", "-q", "-m", message],
        check=True,
    )


def _over_base_repo(tmp_path: Path) -> Path:
    repo = _git_repo(tmp_path, {"ops/a.py": "1\n" * 30, "ios/a.swift": "1\n"})
    path = repo / complexity.BUDGET_FILE
    path.write_text(json.dumps(_budget(ops=10)))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    _commit(repo, "base")
    return repo


def test_evaluate_is_over_only_when_the_change_grew_the_area() -> None:
    measured = {**MEASURED, "ops": 1001}
    grew = {r["area"]: r for r in complexity.evaluate(measured, _budget(), {"ops": 51})}
    flat = {r["area"]: r for r in complexity.evaluate(measured, _budget(), {"ops": 0})}
    shrank = {
        r["area"]: r for r in complexity.evaluate(measured, _budget(), {"ops": -2})
    }
    assert grew["ops"]["over"] is True
    assert flat["ops"]["over"] is False and flat["ops"]["inherited"] is True
    assert shrank["ops"]["over"] is False and shrank["ops"]["inherited"] is True


def test_check_passes_when_the_base_is_already_over_and_the_change_adds_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _over_base_repo(tmp_path)
    assert complexity.main(["check", "--base", "HEAD"], repo=repo) == 0
    assert "inherited" in capsys.readouterr().out


def test_check_fails_when_a_change_grows_an_area_that_is_over(tmp_path: Path) -> None:
    repo = _over_base_repo(tmp_path)
    (repo / "ops" / "b.py").write_text("1\n" * 51)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    assert complexity.main(["check", "--base", "HEAD"], repo=repo) == 1


def test_check_passes_when_a_change_only_shrinks_an_area_that_is_over(
    tmp_path: Path,
) -> None:
    repo = _over_base_repo(tmp_path)
    (repo / "ops" / "a.py").write_text("1\n" * 20)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    assert complexity.main(["check", "--base", "HEAD"], repo=repo) == 0


def test_strict_ignores_the_delta_so_main_itself_can_still_go_red(
    tmp_path: Path,
) -> None:
    repo = _over_base_repo(tmp_path)
    assert complexity.main(["check", "--base", "HEAD", "--strict"], repo=repo) == 1


def test_delta_ignores_data_files_like_measure_does(tmp_path: Path) -> None:
    repo = _over_base_repo(tmp_path)
    (repo / "ops" / "world.json").write_text("1\n" * 500)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    assert complexity.line_deltas(repo, "HEAD") == {
        "ops": 0,
        "docs": 0,
        "workflows": 0,
    }


# ---- review fixes (#2679): lane gate is delta-vs-slack, CI goes through the same entry ----


def test_two_lanes_that_each_fit_the_headroom_both_pass_once_siblings_consumed_it() -> (
    None
):
    # siblings already consumed the headroom (main is red); each lane adds 60 <= slack 100
    budget = _budget()
    budget["slack"]["ops"] = 100
    red = {**MEASURED, "ops": 1090}
    a = complexity.evaluate(red, budget, {"ops": 60})
    b = complexity.evaluate({**red, "ops": 1150}, budget, {"ops": 60})
    assert not any(r["over"] for r in a + b)
    assert [r["inherited"] for r in a if r["area"] == "ops"] == [True]


def test_a_lane_whose_own_delta_exceeds_the_slack_still_fails_with_the_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _over_base_repo(tmp_path)
    (repo / "ops" / "big.py").write_text("1\n" * 60)  # slack ops=50
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    assert complexity.main(["check", "--base", "HEAD"], repo=repo) == 1
    assert "raise the ceiling" in capsys.readouterr().err


def test_no_usable_base_falls_back_to_absolute_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path, {"ops/a.py": "1\n" * 30, "ios/a.swift": "1\n"})
    path = repo / complexity.BUDGET_FILE
    path.write_text(json.dumps(_budget(ops=10)))
    assert complexity.main(["check"], repo=repo) == 1
    assert "absolute" in capsys.readouterr().err


def test_ci_entry_is_strict_on_push_and_delta_aware_on_pull_request() -> None:
    assert complexity.ci_args({"GITHUB_EVENT_NAME": "push"}) == ["--strict"]
    assert complexity.ci_args({"GITHUB_EVENT_NAME": "pull_request"}) == []
    assert complexity.ci_args({}) == []


def test_the_ci_test_uses_the_check_entry_point_with_a_red_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _over_base_repo(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert (
        complexity.main(["check", "--base", "HEAD", *complexity.ci_args()], repo=repo)
        == 0
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert (
        complexity.main(["check", "--base", "HEAD", *complexity.ci_args()], repo=repo)
        == 1
    )
