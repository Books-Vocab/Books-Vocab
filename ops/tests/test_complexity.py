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


# ---- lane gate (#2679): a lane is charged for its own growth, not for main's state ----


def _commit(repo: Path, message: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        + ["commit", "-q", "-m", message],
        check=True,
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _add(repo: Path, name: str, lines: int) -> None:
    (repo / name).write_text("1\n" * lines)
    _git(repo, "add", "-A")


def _headroom_repo(tmp_path: Path, ceiling: int = 40) -> Path:
    # base ops=30 lines; default ceiling 40 -> headroom 10 (slack 50 deliberately larger)
    repo = _git_repo(tmp_path, {"ops/a.py": "1\n" * 30, "ios/a.swift": "1\n"})
    (repo / complexity.BUDGET_FILE).write_text(json.dumps(_budget(ops=ceiling)))
    _git(repo, "add", "-A")
    _commit(repo, "base")
    return repo


def _check(repo: Path, *extra: str) -> int:
    return complexity.main(["check", "--base", "HEAD", *extra], repo=repo)


def test_a_lane_adding_more_than_the_base_headroom_fails_with_the_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _headroom_repo(tmp_path)
    _add(repo, "ops/big.py", 20)  # 20 > headroom 10, < slack 50
    assert _check(repo) == 1
    assert "raise the ceiling" in capsys.readouterr().err


def test_a_lane_adding_within_the_base_headroom_passes(tmp_path: Path) -> None:
    repo = _headroom_repo(tmp_path)
    _add(repo, "ops/small.py", 10)  # exactly the headroom
    assert _check(repo) == 0


def test_a_lane_that_raises_the_ceiling_passes_and_is_then_judged_against_it(
    tmp_path: Path,
) -> None:
    repo = _headroom_repo(tmp_path)
    _add(repo, "ops/big.py", 20)  # tree = 50
    (repo / complexity.BUDGET_FILE).write_text(json.dumps(_budget(ops=60)))
    assert _check(repo) == 0
    (repo / complexity.BUDGET_FILE).write_text(json.dumps(_budget(ops=45)))
    assert _check(repo) == 1  # bumped, but still not enough


def test_a_red_base_tolerates_only_a_change_that_adds_nothing_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _headroom_repo(tmp_path, ceiling=10)  # base 30 > ceiling 10
    assert _check(repo) == 0
    err = capsys.readouterr()
    assert "WARNING" in err.err and "rebaseline" in err.err
    _add(repo, "ops/b.py", 1)
    assert _check(repo) == 1


def test_two_sibling_lanes_each_fitting_the_base_headroom_both_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _headroom_repo(tmp_path)  # headroom 10
    trunk = _git(repo, "branch", "--show-current")
    _git(repo, "checkout", "-q", "-b", "lane-a")
    _add(repo, "ops/a_lane.py", 8)
    _commit(repo, "lane A")
    _git(repo, "checkout", "-q", trunk)
    _git(repo, "checkout", "-q", "-b", "lane-b")
    _add(repo, "ops/b_lane.py", 8)
    _commit(repo, "lane B")
    # trunk now contains A; B's merge-base with trunk is still the original base
    _git(repo, "checkout", "-q", trunk)
    _git(repo, "merge", "-q", "--no-ff", "-m", "A", "lane-a")
    _git(repo, "checkout", "-q", "lane-b")
    assert complexity.main(["check", "--base", trunk], repo=repo) == 0
    # the CI merge commit (trunk + B): absolute 46 > 40 is a warning, not a failure
    _git(repo, "checkout", "-q", trunk)
    _git(repo, "merge", "-q", "--no-ff", "-m", "B", "lane-b")
    assert complexity.main(["check", "--base", "HEAD^1"], repo=repo) == 0
    assert "WARNING" in capsys.readouterr().err


def _rebased_sibling(tmp_path: Path, own_lines: int) -> tuple[Path, str]:
    """Base headroom 10; lane A (8 lines) is merged to trunk; lane B (``own_lines``) is rebased on it."""
    repo = _headroom_repo(tmp_path)
    trunk = _git(repo, "branch", "--show-current")
    _git(repo, "checkout", "-q", "-b", "lane-a")
    _add(repo, "ops/a_lane.py", 8)
    _commit(repo, "lane A")
    _git(repo, "checkout", "-q", trunk)
    _git(repo, "checkout", "-q", "-b", "lane-b")
    _add(repo, "ops/b_lane.py", own_lines)
    _commit(repo, "lane B")
    _git(repo, "checkout", "-q", trunk)
    _git(repo, "merge", "-q", "--no-ff", "-m", "A", "lane-a")
    _git(repo, "checkout", "-q", "lane-b")
    _git(repo, "rebase", "-q", trunk)  # what deliver.py does before the checks
    return repo, trunk


def test_a_sibling_rebased_onto_main_keeps_its_original_fork_allowance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, trunk = _rebased_sibling(tmp_path, 8)
    assert complexity.main(["check", "--base", trunk], repo=repo) == 0
    assert "WARNING" in capsys.readouterr().err  # 46 > 40, but B's own 8 fits its 10


def test_a_rebased_sibling_whose_own_delta_exceeds_the_original_headroom_fails(
    tmp_path: Path,
) -> None:
    repo, trunk = _rebased_sibling(tmp_path, 12)
    assert complexity.main(["check", "--base", trunk], repo=repo) == 1


def test_fork_base_env_overrides_the_reflog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, trunk = _rebased_sibling(tmp_path, 8)
    original = _git(repo, "merge-base", "lane-b", "lane-a^")
    _git(repo, "checkout", "-q", "--detach")  # no branch -> no reflog fork
    assert complexity.main(["check", "--base", trunk], repo=repo) == 1
    monkeypatch.setenv("KG_COMPLEXITY_FORK_BASE", original)
    assert complexity.main(["check", "--base", trunk], repo=repo) == 0


def test_a_missing_object_at_the_base_falls_back_to_absolute_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _headroom_repo(tmp_path)

    def broken(*_a, **_k):
        raise IndexError("missing")

    monkeypatch.setattr(complexity, "count_lines_at", broken)
    assert _check(repo) == 0
    assert "absolute" in capsys.readouterr().err


def test_main_itself_over_budget_fails_without_a_base_flag(tmp_path: Path) -> None:
    repo = _headroom_repo(tmp_path, ceiling=10)
    assert complexity.main(["check"], repo=repo) == 1  # HEAD is the base: absolute


def test_absolute_mode_fails_when_over_budget_whatever_the_lane_added(
    tmp_path: Path,
) -> None:
    repo = _headroom_repo(tmp_path, ceiling=10)
    assert _check(repo, "--absolute") == 1
    assert _check(repo, "--strict") == 1


def test_base_count_uses_the_same_counting_rule_as_the_tree(tmp_path: Path) -> None:
    repo = _git_repo(
        tmp_path,
        {
            "ops/a.py": "one\ntwo",  # no trailing newline
            "ops/world.json": "1\n" * 50,  # data, ignored
            "docs/x.md": "1\n",
            ".github/workflows/w.yml": "1\n",
        },
    )
    _commit(repo, "base")
    for name, prefix in complexity.AREAS.items():
        assert complexity.count_lines_at(
            repo, "HEAD", prefix
        ) == complexity.count_lines(repo, prefix), name


def test_a_change_to_a_data_file_costs_nothing(tmp_path: Path) -> None:
    repo = _headroom_repo(tmp_path)
    _add(repo, "ops/world.json", 500)
    assert _check(repo) == 0


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
    repo = _headroom_repo(tmp_path, ceiling=10)
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
