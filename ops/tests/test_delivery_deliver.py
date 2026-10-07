from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import deliver

CANON = Path("/canon")


class FakeWorld:
    """Scripts the answers of git/gh/registry/delivery and records every call."""

    def __init__(self, **state: Any) -> None:
        self.branch = state.get("branch", "feat/thing")
        self.dirty = state.get("dirty", False)
        self.ahead = state.get("ahead", "2")
        self.behind = state.get("behind", "0")
        self.rebase_ok = state.get("rebase_ok", True)
        self.record = state.get("record")
        self.prs = state.get("prs", [])
        self.checks = list(
            state.get("checks", [[{"name": "required", "state": "SUCCESS"}]])
        )
        self.pr_state = list(state.get("pr_state", ["MERGED"]))
        self.merged_prs = state.get("merged_prs", {})
        self.diff = state.get("diff", "M\tops/a.py\nA\tops/b.py\n")
        self.fail_commands: set[str] = set(state.get("fail_commands", set()))
        self.published_pr: dict[str, Any] | None = state.get(
            "published_pr", {"number": 77, "state": "OPEN", "url": "u"}
        )
        self.calls: list[list[str]] = []

    def names(self) -> list[str]:
        out = []
        for call in self.calls:
            if call[0].endswith("worktree_orchestrate.py"):
                out.append(call[1])
            elif call[0].endswith("delivery.py"):
                out.append(call[3])
        return out

    def __call__(self, cmd: list[str], cwd: Path | None) -> deliver.Proc:
        self.calls.append(cmd)

        def ok(out: str = "") -> deliver.Proc:
            return deliver.Proc(0, out, "")

        head = cmd[0]
        if head == "bash":
            return deliver.Proc(
                1 if cmd[2] in self.fail_commands else 0,
                f"out of {cmd[2]}\nlast line\n",
                "",
            )
        if head == "git":
            sub = cmd[1:]
            if sub[:2] == ["rev-parse", "--abbrev-ref"]:
                return ok(self.branch)
            if sub[0] == "status":
                return ok(" M file\n" if self.dirty else "")
            if sub[0] == "fetch":
                return ok()
            if sub[0] == "rev-list":
                return ok(self.ahead if sub[2].endswith("..HEAD") else self.behind)
            if sub[0] == "rebase":
                if sub[1] == "--abort":
                    return ok()
                return deliver.Proc(
                    0 if self.rebase_ok else 1, "", "" if self.rebase_ok else "conflict"
                )
            if sub[0] == "worktree":
                return ok(f"worktree {CANON}\nHEAD abc\n")
            if sub[0] == "diff":
                return ok(self.diff)
            if sub[0] == "log":
                return ok("feat: the thing")
            if sub[0] == "rev-parse":
                return ok(str(CANON))
        if head == "gh":
            if cmd[1:3] == ["repo", "view"]:
                return ok("o/r")
            if cmd[1:3] == ["pr", "list"]:
                if "merged" in cmd:
                    return ok(
                        str(self.merged_prs.get(cmd[cmd.index("--head") + 1], ""))
                    )
                if self.prs:
                    return ok(json.dumps(self.prs))
                published = (
                    [self.published_pr]
                    if self.published_pr
                    and any(
                        c[0].endswith("delivery.py") and c[3] == "publish"
                        for c in self.calls
                    )
                    else []
                )
                return ok(json.dumps(published))
            if cmd[1:3] == ["pr", "checks"]:
                batch = self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]
                return ok(json.dumps(batch))
            if cmd[1:3] == ["pr", "view"]:
                return ok(
                    self.pr_state.pop(0) if len(self.pr_state) > 1 else self.pr_state[0]
                )
        if head.endswith("worktree_registry.py"):
            return ok(json.dumps({"records": [self.record] if self.record else []}))
        if head.endswith(("worktree_orchestrate.py", "delivery.py")):
            verb = cmd[1] if head.endswith("worktree_orchestrate.py") else cmd[3]
            return deliver.Proc(
                1 if verb in self.fail_commands else 0,
                "{}",
                "boom" if verb in self.fail_commands else "",
            )
        raise AssertionError(f"unscripted call: {cmd}")


def ship(world: FakeWorld, *flags: str) -> tuple[int, dict[str, Any]]:
    out: list[str] = []
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = deliver.main(
            ["--timeout", "5", "--poll", "0", *flags],
            runner=world,
            sleep=lambda _s: None,
        )
    out.append(buf.getvalue())
    return code, json.loads(out[0].strip().splitlines()[-1])


# ---- pure helpers ---------------------------------------------------------


def test_scope_covers_add_modify_delete_and_splits_a_rename() -> None:
    scope = deliver.scope_from_name_status(
        "A\tnew.py\nM\told.py\nD\tgone.py\nR100\tfrom.py\tto.py\n"
    )
    assert scope["schema"] == "kg.worktree.scope.v1"
    assert scope["files"] == [
        {"operation": "add", "path": "new.py"},
        {"operation": "modify", "path": "old.py"},
        {"operation": "delete", "path": "gone.py"},
        {"operation": "delete", "path": "from.py"},
        {"operation": "add", "path": "to.py"},
    ]


def test_an_unknown_git_status_is_refused_not_guessed() -> None:
    with pytest.raises(deliver.DeliverError):
        deliver.scope_from_name_status("U\tconflict.py\n")


def test_lane_id_is_derived_from_the_branch() -> None:
    assert (
        deliver.lane_from_branch("fix/a_b.c", "20261007")
        == "DIRECT-DELIVERY-FIX-A-B-C-20261007"
    )


@pytest.mark.parametrize("spec", ["nocommand", "=cmd", "label=", ""])
def test_malformed_check_specs_are_rejected(spec: str) -> None:
    with pytest.raises(deliver.DeliverError):
        deliver.parse_check(spec)


def test_check_outcomes_come_from_exit_codes_and_run_to_the_end() -> None:
    world = FakeWorld(fail_commands={"bad"})
    outcomes = deliver.run_checks(
        ["one=good", "two=bad", "three=good"], Path("."), world
    )
    assert [o["status"] for o in outcomes] == ["passed", "failed", "passed"]
    assert outcomes[0]["detail"] == "last line"
    assert [o["check"] for o in outcomes] == ["one", "two", "three"]


@pytest.mark.parametrize(
    ("record", "pr", "expected"),
    [
        (None, None, "adopt"),
        ({"status": "active"}, None, "hand-back"),
        ({"status": "active", "handback_seal": {"x": 1}}, None, "receipt"),
        ({"status": "published"}, None, "wait-required"),
        (None, {"state": "OPEN", "number": 1}, "wait-required"),
        ({"status": "published"}, {"state": "MERGED", "number": 1}, "cleanup"),
    ],
)
def test_resume_point_follows_registry_and_github(
    record: Any, pr: Any, expected: str
) -> None:
    assert deliver.next_stage(record, pr) == expected


@pytest.mark.parametrize(
    ("record", "pr"),
    [({"status": "abandoned"}, None), (None, {"state": "CLOSED", "number": 3})],
)
def test_dead_lanes_and_closed_prs_are_not_resumed(record: Any, pr: Any) -> None:
    with pytest.raises(deliver.DeliverError):
        deliver.next_stage(record, pr)


def test_required_state_defaults_to_pending() -> None:
    assert deliver.required_state([]) == "PENDING"
    assert deliver.required_state([{"name": "other", "state": "SUCCESS"}]) == "PENDING"
    assert (
        deliver.required_state([{"name": "required", "state": "FAILURE"}]) == "FAILURE"
    )


# ---- the whole flow -------------------------------------------------------


def test_new_lane_runs_every_stage_in_order_and_stops_before_merge() -> None:
    world = FakeWorld()
    code, result = ship(world, "--check", "unit=good")
    assert code == 0
    assert result["result"] == "ready-to-merge"
    assert result["pr"] == 77
    assert world.names() == ["adopt", "hand-back", "receipt", "publish"]


def test_merge_flag_queues_waits_and_cleans_up_from_the_canonical_checkout() -> None:
    world = FakeWorld()
    code, result = ship(world, "--check", "unit=good", "--merge")
    assert code == 0
    assert result["result"] == "merged"
    assert world.names() == [
        "adopt",
        "hand-back",
        "receipt",
        "publish",
        "queue",
        "cleanup-merged",
        "sync-main",
    ]


def test_a_failing_check_stops_before_anything_is_claimed() -> None:
    world = FakeWorld(fail_commands={"bad"})
    code, result = ship(world, "--check", "ok=good", "--check", "broken=bad")
    assert code == 1
    assert "broken" in result["error"]
    assert world.names() == []


def test_a_new_lane_without_any_check_is_refused() -> None:
    code, result = ship(FakeWorld())
    assert code == 1
    assert "--check" in result["error"]


def test_a_published_lane_resumes_without_rerunning_checks() -> None:
    world = FakeWorld(
        record={
            "branch": "feat/thing",
            "status": "published",
            "external_ids": ["LANE-1"],
        },
        prs=[{"number": 9, "state": "OPEN"}],
    )
    code, result = ship(world)
    assert code == 0
    assert result["lane"] == "LANE-1"
    assert not any(c[0] == "bash" for c in world.calls)
    assert world.names() == []


def test_a_merged_pr_goes_straight_to_cleanup() -> None:
    world = FakeWorld(prs=[{"number": 9, "state": "MERGED"}])
    code, _result = ship(world, "--merge")
    assert code == 0
    assert world.names() == ["cleanup-merged", "sync-main"]


def test_dirty_trees_and_trunk_branches_are_refused() -> None:
    assert ship(FakeWorld(dirty=True), "--check", "u=good")[0] == 1
    assert ship(FakeWorld(branch="main"), "--check", "u=good")[0] == 1
    assert ship(FakeWorld(ahead="0"), "--check", "u=good")[0] == 1


def test_a_branch_that_cannot_rebase_is_aborted_and_not_claimed() -> None:
    world = FakeWorld(behind="3", rebase_ok=False)
    code, result = ship(world, "--check", "u=good")
    assert code == 1
    assert "rebase" in result["error"]
    assert ["git", "rebase", "--abort"] in world.calls
    assert world.names() == []


def test_a_red_required_check_fails_the_run() -> None:
    world = FakeWorld(checks=[[{"name": "required", "state": "FAILURE"}]])
    code, result = ship(world, "--check", "u=good")
    assert code == 1
    assert "FAILURE" in result["error"]


def test_it_waits_while_required_is_pending() -> None:
    pending = [{"name": "required", "state": "IN_PROGRESS"}]
    world = FakeWorld(
        checks=[pending, pending, [{"name": "required", "state": "SUCCESS"}]]
    )
    code, _ = ship(world, "--check", "u=good")
    assert code == 0
    assert sum(1 for c in world.calls if c[1:3] == ["pr", "checks"]) == 3


def test_a_stage_failure_names_the_stage() -> None:
    world = FakeWorld(fail_commands={"hand-back"})
    code, result = ship(world, "--check", "u=good")
    assert code == 1
    assert result["error"].startswith("hand-back failed")


# ---- gc -------------------------------------------------------------------


def _gc_world(tmp_path: Path) -> FakeWorld:
    gone = tmp_path / "gone"
    present = tmp_path / "present"
    present.mkdir()
    world = FakeWorld(merged_prs={"feat/merged": 41})
    records = [
        {"branch": "feat/merged", "status": "published", "path": str(gone)},
        {"branch": "feat/open", "status": "published", "path": str(gone)},
        {"branch": "feat/live", "status": "published", "path": str(present)},
        {"branch": "feat/active", "status": "active", "path": str(gone)},
    ]
    world.record = None
    original = world.__call__

    def with_records(cmd: list[str], cwd: Path | None) -> deliver.Proc:
        if cmd[0].endswith("worktree_registry.py"):
            world.calls.append(cmd)
            return deliver.Proc(0, json.dumps({"records": records}), "")
        return original(cmd, cwd)

    world.__call__ = with_records  # type: ignore[method-assign]
    return world


def test_gc_retires_only_published_lanes_whose_pr_merged(tmp_path: Path) -> None:
    world = _gc_world(tmp_path)
    import argparse

    result = deliver.gc(
        argparse.Namespace(dry_run=False), lambda cmd, cwd: world.__call__(cmd, cwd)
    )
    assert result["retired"] == [{"branch": "feat/merged", "pr": 41, "applied": True}]
    assert [k["branch"] for k in result["kept"]] == ["feat/open"]


def test_gc_dry_run_changes_nothing(tmp_path: Path) -> None:
    world = _gc_world(tmp_path)
    import argparse

    result = deliver.gc(
        argparse.Namespace(dry_run=True), lambda cmd, cwd: world.__call__(cmd, cwd)
    )
    assert result["retired"] == [{"branch": "feat/merged", "pr": 41, "applied": False}]
    assert "cleanup-merged" not in world.names()
