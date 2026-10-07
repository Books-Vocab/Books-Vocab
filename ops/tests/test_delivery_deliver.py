from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import deliver


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
        self.fork = state.get("fork", "f" * 40)
        self.fail_commands: set[str] = set(state.get("fail_commands", set()))
        self.published_pr: dict[str, Any] | None = state.get(
            "published_pr", {"number": 77, "state": "OPEN", "url": "u"}
        )
        self.calls: list[list[str]] = []
        self.cwds: list[Path | None] = []
        self.work = Path(tempfile.mkdtemp())
        self.canon = Path(tempfile.mkdtemp())

    def names(self) -> list[str]:
        out = []
        for call in self.calls:
            if call[0].endswith("worktree_orchestrate.py"):
                out.append(call[1])
            elif call[0].endswith("delivery.py"):
                out.append(call[3])
        return out

    def __call__(self, cmd: list[str], cwd: Path | None) -> deliver.Proc:
        if cwd is not None and not cwd.exists():
            raise FileNotFoundError(cwd)  # what subprocess does in the real world
        self.calls.append(cmd)
        self.cwds.append(cwd)

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
                return ok(f"worktree {self.canon}\nHEAD abc\n")
            if sub[0] == "diff":
                return ok(self.diff)
            if sub[0] == "merge-base":
                return ok(self.fork)
            if sub[0] == "log":
                return ok("feat: the thing")
            if sub[0] == "rev-parse":
                return ok(str(self.canon))
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
            if verb == "publish":
                shutil.rmtree(
                    self.work, ignore_errors=True
                )  # publish retires the lane worktree
            return deliver.Proc(
                1 if verb in self.fail_commands else 0,
                "{}",
                "boom" if verb in self.fail_commands else "",
            )
        raise AssertionError(f"unscripted call: {cmd}")


def ship(world: FakeWorld, *flags: str) -> tuple[int, dict[str, Any]]:
    argv = ["--timeout", "5", "--poll", "0"]
    if "--worktree" not in flags:
        argv += ["--worktree", str(world.work)]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = deliver.main([*argv, *flags], runner=world, sleep=lambda _s: None)
    return code, json.loads(buf.getvalue().strip().splitlines()[-1])


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


# ---- surviving the worktree's removal -------------------------------------


def test_nothing_runs_in_the_worktree_after_publish_removes_it() -> None:
    world = FakeWorld()
    code, _ = ship(world, "--check", "u=good", "--merge")
    assert code == 0  # FakeWorld raises FileNotFoundError for a vanished cwd
    published_at = next(
        i
        for i, c in enumerate(world.calls)
        if c[0].endswith("delivery.py") and c[3] == "publish"
    )
    assert all(cwd != world.work for cwd in world.cwds[published_at + 1 :])


def test_a_published_lane_resumes_from_its_branch_when_the_worktree_is_gone() -> None:
    world = FakeWorld(
        record={
            "branch": "feat/thing",
            "status": "published",
            "external_ids": ["LANE-1"],
        },
        prs=[{"number": 9, "state": "OPEN"}],
    )
    gone = str(world.work / "never-existed")
    code, result = ship(world, "--worktree", gone, "--branch", "feat/thing")
    assert code == 0
    assert result["lane"] == "LANE-1"
    assert not any(
        c[:2] == ["git", "status"] for c in world.calls
    )  # no preflight without a tree


def test_a_gone_worktree_without_a_branch_is_an_explicit_error() -> None:
    code, result = ship(FakeWorld(), "--worktree", "/definitely/not/here")
    assert code == 1
    assert "--branch" in result["error"]


def test_a_gone_worktree_cannot_start_a_new_lane() -> None:
    world = FakeWorld()  # no record, no PR -> would start at adopt
    code, result = ship(
        world, "--worktree", "/definitely/not/here", "--branch", "feat/thing"
    )
    assert code == 1
    assert "gone before the lane was published" in result["error"]


def test_a_branch_flag_that_disagrees_with_the_checkout_is_refused() -> None:
    code, result = ship(FakeWorld(), "--check", "u=good", "--branch", "other")
    assert code == 1
    assert "not the checked-out branch" in result["error"]


def test_a_branch_that_already_carries_the_date_does_not_repeat_it() -> None:
    assert (
        deliver.lane_from_branch("feat/x-20261007", "20261007")
        == "DIRECT-DELIVERY-FEAT-X-20261007"
    )


def _agent_record(**extra: Any) -> dict[str, Any]:
    return {
        "branch": "worktree-agent-abc123",
        "status": "active",
        "external_ids": ["LANE-A"],
        "claim_generation": 0,
        "handed_back_sha": "e" * 40,
        "base_sha": "1" * 40,  # adopted against a stale local main
        **extra,
    }


def test_an_agent_claim_with_a_stale_base_is_retired_and_readopted_on_trunk() -> None:
    world = FakeWorld(branch="worktree-agent-abc123", record=_agent_record())
    code, result = ship(world, "--check", "docs=good")
    assert code == 0, result
    assert world.names() == ["resolve", "adopt", "hand-back", "receipt", "publish"]
    resolve = next(c for c in world.calls if c[1:2] == ["resolve"])
    assert resolve[resolve.index("--status") + 1] == "abandoned"
    assert resolve[resolve.index("--expected-head-sha") + 1] == "e" * 40
    adopt = next(c for c in world.calls if c[1:2] == ["adopt"])
    assert adopt[adopt.index("--base") + 1] == deliver.TRUNK


def test_a_claim_whose_base_is_the_fork_point_is_kept() -> None:
    world = FakeWorld(
        branch="worktree-agent-abc123", record=_agent_record(base_sha="f" * 40)
    )
    code, _ = ship(world, "--check", "docs=good")
    assert code == 0
    assert "resolve" not in world.names()
    assert "adopt" not in world.names()


def test_scope_from_diff_refreshes_a_drifted_active_claim_scope() -> None:
    record = _agent_record(
        base_sha="f" * 40,
        scope={"files": [{"path": "ops/a.py", "operation": "modify"}]},
    )
    world = FakeWorld(branch="worktree-agent-abc123", record=record)
    code, _ = ship(world, "--check", "docs=good", "--scope-from-diff")
    assert code == 0
    refresh = [
        c
        for c in world.calls
        if c[0].endswith("worktree_registry.py") and "scope-set" in c
    ]
    assert len(refresh) == 1

    same = FakeWorld(
        branch="worktree-agent-abc123",
        record=_agent_record(
            base_sha="f" * 40,
            scope=deliver.scope_from_name_status("M\tops/a.py\nA\tops/b.py\n"),
        ),
    )
    assert ship(same, "--check", "docs=good", "--scope-from-diff")[0] == 0
    assert not [c for c in same.calls if "scope-set" in c]
    plain = FakeWorld(branch="worktree-agent-abc123", record=record)
    ship(plain, "--check", "docs=good")
    assert not [c for c in plain.calls if "scope-set" in c]


def test_branch_resume_of_an_already_merged_lane_stops_with_a_clear_message() -> None:
    world = FakeWorld(prs=[{"number": 41, "state": "MERGED"}])
    code, result = ship(world, "--branch", "feat/thing", "--check", "u=good")
    assert code == 1
    assert result["error"] == "PR #41 already merged; start a new lane from origin/main"
    assert world.names() == []


def test_branch_resume_still_cleans_a_merged_lane_that_is_not_yet_retired() -> None:
    world = FakeWorld(
        prs=[{"number": 41, "state": "MERGED"}],
        record={"branch": "feat/thing", "status": "cleanup_pending"},
    )
    code, _ = ship(world, "--branch", "feat/thing")
    assert code == 0
    assert world.names() == ["cleanup-merged", "sync-main"]
