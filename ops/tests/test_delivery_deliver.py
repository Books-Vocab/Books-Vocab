from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import deliver


HEAD = "c" * 40
BOT = "chatgpt-codex-connector[bot]"


def _review(
    status: str = "completed",
    conclusion: str = "success",
    job: bool = False,
    run: int = 1,
):
    """One `agent-review` check run: the Actions job, or a verdict it posted.

    Both name the workflow run that made them: the job by its details_url, the
    posted verdict by its external_id marker (as agent-review.yml writes them).
    """
    url = f"https://github.com/o/r/actions/runs/{run}"
    return {
        "name": "agent-review",
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "external_id": "" if job else f"kg.agent-review.v1:{run}:{HEAD}",
        "details_url": f"{url}/job/9" if job else url,
    }


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
        self.changed_py = state.get("changed_py", ["ops/a.py", "ops/b.py"])
        self.format_rc = state.get("format_rc", 0)
        self.unformatted = state.get("unformatted", ["ops/a.py"])
        self.fail_commands: set[str] = set(state.get("fail_commands", set()))
        self.stderr_for: dict[str, str] = state.get("stderr_for", {})
        self.lock_busy: dict[str, int] = dict(state.get("lock_busy", {}))
        self.now = 0.0
        self.sleeps: list[float] = []
        self.head = state.get("head", HEAD)
        self.review_runs = list(
            state.get("review_runs", [[_review(job=True), _review()]])
        )
        self.review_comments: list[dict[str, Any]] = state.get("review_comments", [])
        # Workflow runs by id (None: GitHub answers 404); a run not listed here
        # belongs to the PR whose head was last read, as the real ones do.
        self.actions_runs: dict[int, dict[str, Any] | None] = state.get(
            "actions_runs", {}
        )
        self.head_ref = state.get("head_ref", self.branch)
        self.viewed_pr = 0
        # Mid-redelivery change: the replaced PR is MERGED once this verb ran.
        self.merge_old_after = state.get("merge_old_after")
        # Per-branch registry/PR/remote facts that react to the mutations.
        self.records_by_branch: dict[str, list[dict[str, Any]]] = state.get(
            "records_by_branch", {}
        )
        self.prs_by_branch: dict[str, list[dict[str, Any]]] = state.get(
            "prs_by_branch", {}
        )
        self.remote_heads: dict[str, str] = state.get("remote_heads", {})
        # Hold/queue facts of the replaced PR, one dict per read (last repeats).
        self.pr_guard: list[dict[str, Any]] = list(state.get("pr_guard", []))
        self.published_pr: dict[str, Any] | None = state.get(
            "published_pr", {"number": 77, "state": "OPEN", "url": "u"}
        )
        self.calls: list[list[str]] = []
        self.cwds: list[Path | None] = []
        self.work = Path(tempfile.mkdtemp())
        self.canon = Path(tempfile.mkdtemp())

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

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
                    0 if self.rebase_ok else 1,
                    ""
                    if self.rebase_ok
                    else "CONFLICT (content): Merge conflict in ops/a.py\n",
                    "" if self.rebase_ok else "error: could not apply c0ffee0\n",
                )
            if sub[0] == "worktree":
                return ok(f"worktree {self.canon}\nHEAD abc\n")
            if sub[0] == "diff" and "--name-only" in sub:
                return ok("".join(f"{name}\n" for name in self.changed_py))
            if sub[0] == "diff":
                return ok(self.diff)
            if sub[0] == "merge-base":
                return ok(self.fork)
            if sub[0] == "log":
                return ok("feat: the thing")
            if sub[0] == "rev-parse":
                return ok(str(self.canon))
            if sub[0] == "ls-remote":
                name = sub[2].removeprefix("refs/heads/")
                sha = self.remote_heads.get(name)
                return ok(f"{sha}\trefs/heads/{name}\n" if sha else "")
            if sub[0] == "push" and sub[-2] == "--delete":
                self.remote_heads.pop(sub[-1], None)
                return ok()
        if head == "uv":
            listed = "".join(f"Would reformat: {n}\n" for n in self.unformatted)
            return deliver.Proc(self.format_rc, listed if self.format_rc else "", "")
        if head == "gh":
            if cmd[1:3] == ["repo", "view"]:
                return ok("o/r")
            if cmd[1:3] == ["pr", "close"]:
                for pr in sum(self.prs_by_branch.values(), []):
                    if str(pr["number"]) == cmd[3]:
                        pr["state"] = "CLOSED"
                return ok()
            if cmd[1:3] == ["pr", "list"] and "--head" in cmd:
                listed = self.prs_by_branch.get(cmd[cmd.index("--head") + 1])
                if listed is not None:
                    return ok(json.dumps(listed))
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
            if cmd[1:3] == ["api", "graphql"]:
                number = int(_value(cmd, "number=", prefix=True))
                pr = next(
                    p
                    for p in sum(self.prs_by_branch.values(), [])
                    if p["number"] == number
                )
                guard = self.pr_guard
                extra = guard.pop(0) if len(guard) > 1 else (guard or [{}])[0]
                node = {
                    "number": number,
                    "state": pr["state"],
                    "body": "",
                    "labels": {"nodes": []},
                    "autoMergeRequest": None,
                    "mergeQueueEntry": None,
                    **extra,
                }
                return ok(json.dumps({"data": {"repository": {"pullRequest": node}}}))
            if cmd[1] == "api" and "/check-runs?" in cmd[-1]:
                runs = self.review_runs
                batch = runs.pop(0) if len(runs) > 1 else runs[0]
                return ok(
                    json.dumps([{"total_count": len(batch), "check_runs": batch}])
                )
            if cmd[1] == "api" and "/actions/runs/" in cmd[-1]:
                run_id = int(cmd[-1].rsplit("/", 1)[1])
                found = self.actions_runs.get(
                    run_id,
                    {
                        "event": "pull_request_target",
                        "head_branch": self.head_ref,
                        "pull_requests": [{"number": self.viewed_pr}],
                    },
                )
                if found is None:
                    return deliver.Proc(1, "", "gh: Not Found (HTTP 404)")
                return ok(json.dumps({"id": run_id, **found}))
            if cmd[1] == "api" and cmd[-1].endswith("/comments?per_page=100"):
                return ok(json.dumps([self.review_comments]))
            if cmd[1:3] == ["pr", "view"]:
                self.viewed_pr = int(cmd[3])
            if cmd[1:3] == ["pr", "view"] and "headRefOid,headRefName" in cmd:
                return ok(
                    json.dumps({"headRefOid": self.head, "headRefName": self.head_ref})
                )
            if cmd[1:3] == ["pr", "view"]:
                return ok(
                    self.pr_state.pop(0) if len(self.pr_state) > 1 else self.pr_state[0]
                )
        if head.endswith("worktree_registry.py"):
            branch = cmd[cmd.index("--branch") + 1] if "--branch" in cmd else None
            if branch in self.records_by_branch:
                return ok(json.dumps({"records": self.records_by_branch[branch]}))
            return ok(json.dumps({"records": [self.record] if self.record else []}))
        if head.endswith(("worktree_orchestrate.py", "delivery.py")):
            verb = cmd[1] if head.endswith("worktree_orchestrate.py") else cmd[3]
            if self.lock_busy.get(verb, 0) > 0:  # the lock is taken before any change
                self.lock_busy[verb] -= 1
                if head.endswith("delivery.py"):  # its CLI reports one JSON error
                    doc = {"command": verb, "error": _LOCKED, "ok": False}
                    return deliver.Proc(1, "", json.dumps(doc))
                return deliver.Proc(1, "", f"Traceback\nDeliverySourceError: {_LOCKED}")
            if verb == "resolve" and "--branch" in cmd:
                for record in self.records_by_branch.get(
                    cmd[cmd.index("--branch") + 1], []
                ):
                    record["status"] = cmd[cmd.index("--status") + 1]
            if verb == "publish":
                shutil.rmtree(
                    self.work, ignore_errors=True
                )  # publish retires the lane worktree
            if verb == self.merge_old_after:
                for old in self.prs_by_branch.get(OLD, []):
                    old["state"] = "MERGED"
            failing = verb in self.fail_commands
            if failing:
                return deliver.Proc(1, "", self.stderr_for.get(verb, "boom"))
            return ok("{}")
        raise AssertionError(f"unscripted call: {cmd}")


_LOCKED = (
    "delivery mutation already in progress; command=sync-main; "
    "retry after the active operation exits"
)


def ship(world: FakeWorld, *flags: str) -> tuple[int, dict[str, Any]]:
    argv = ["--timeout", "5", "--poll", "1"]
    if "--worktree" not in flags:
        argv += ["--worktree", str(world.work)]
    command = ["redeliver"] if flags[:1] == ("redeliver",) else []
    argv = [*command, *argv, *flags[len(command) :]]  # options follow redeliver
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = deliver.main(
            argv, runner=world, sleep=world.sleep, clock=lambda: world.now
        )
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
    assert "CONFLICT (content): Merge conflict in ops/a.py" in result["error"]
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
    assert world.names().count("hand-back") == 1  # a real failure is not retried


_GITHUB = "GraphQL: Pull request is in unstable status (enqueuePullRequest)"
_ADAPTER = (
    "command failed with exit 1: gh api graphql -f query=mutation {"
    + "x" * 2000
    + "} -F pullRequestId=PR_1: "
    + _GITHUB
)
_TRACE = "Traceback (most recent call last):\n" + "  frame\n" * 100 + "Boom: cause"


@pytest.mark.parametrize(
    ("verb", "stderr", "detail"),
    [
        (  # delivery.py: progress lines, then one JSON error document
            "queue",
            "reading PR\n"
            + json.dumps({"command": "queue", "error": _ADAPTER, "ok": False}),
            _ADAPTER,
        ),
        ("adopt", _TRACE, _TRACE),  # anything else: the whole stream
    ],
    ids=["delivery-json-error", "traceback"],
)
def test_a_failed_stage_surfaces_the_whole_underlying_error(
    verb: str, stderr: str, detail: str
) -> None:
    world = FakeWorld(fail_commands={verb}, stderr_for={verb: stderr})
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1
    assert result["error"] == f"{verb} failed (rc=1): {detail}"


# ---- the delivery mutation lock -------------------------------------------


def test_a_busy_mutation_lock_is_waited_out_instead_of_failing() -> None:
    world = FakeWorld(lock_busy={"adopt": 1, "queue": 2})  # traceback / JSON shapes
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 0, result
    assert world.names().count("adopt") == 2
    assert world.names().count("queue") == 3
    waits = [line for line in result["log"] if "operation lock" in line]
    assert len(waits) == 3 and all("command=sync-main" in line for line in waits)


def test_the_lock_wait_is_bounded_and_names_the_holder() -> None:
    world = FakeWorld(lock_busy={"publish": 99})
    code, result = ship(world, "--check", "u=good", "--lock-timeout", "12")
    assert code == 1
    assert world.names().count("publish") == 4
    assert world.sleeps == [5, 5, 2]
    assert "lock is still held after 12s" in result["error"]
    assert _LOCKED in result["error"]


def test_the_lock_marker_is_the_lock_adapters_own_message() -> None:
    adapter = OPS / "delivery_control" / "adapters" / "operation_lock.py"
    assert deliver.LOCK_BUSY in adapter.read_text()


# ---- the agent-review gate on --merge -------------------------------------


def _calls_at(world: FakeWorld, wanted: Callable[[list[str]], bool]) -> list[int]:
    return [i for i, call in enumerate(world.calls) if wanted(call)]


def _is_review_read(call: list[str]) -> bool:
    return call[:2] == ["gh", "api"] and "/check-runs?" in call[-1]


def _is_queue(call: list[str]) -> bool:
    return call[0].endswith("delivery.py") and call[3] == "queue"


_FINDING = {
    "user": {"login": BOT},
    "commit_id": HEAD,
    "original_commit_id": HEAD,
    "path": "ops/a.py",
    "line": 12,
    "body": "**P2 Handle the empty case**\n\nWhy it breaks.",
    "html_url": "https://github.com/o/r/pull/77#discussion_r1",
}


def test_merge_waits_for_agent_review_to_complete_on_the_exact_head() -> None:
    orphan = _review("in_progress")  # the marker of a run that was cancelled
    world = FakeWorld(
        review_runs=[
            [],
            [_review("in_progress", job=True), orphan],
            [_review(job=True), orphan, _review()],
        ]
    )
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 0, result
    reads = _calls_at(world, _is_review_read)
    assert len(reads) == 3
    assert all(f"/commits/{HEAD}/check-runs?" in world.calls[i][-1] for i in reads)
    assert reads[-1] < _calls_at(world, _is_queue)[0]
    assert result["review"] == {
        "head": HEAD,
        "verdict": "success",
        "findings": [],
        "accepted": None,
        "accepted_no_review": None,
    }


def test_merge_refuses_to_queue_when_agent_review_failed() -> None:
    failed = [_review(conclusion="failure", job=True), _review(conclusion="failure")]
    world = FakeWorld(review_runs=[failed])
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1
    assert f"agent-review failed on {HEAD}" in result["error"]
    assert "--accept-review-findings" in result["error"]
    assert not _calls_at(world, _is_queue)


def test_merge_refuses_on_inline_review_comments_on_the_head_and_lists_them() -> None:
    ignored = [
        {**_FINDING, "user": {"login": "someone"}},  # not the review bot
        {**_FINDING, "commit_id": "d" * 40, "original_commit_id": "d" * 40},
    ]
    world = FakeWorld(review_comments=[_FINDING, *ignored])
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1
    assert f"1 inline review comment(s) on {HEAD}" in result["error"]
    assert (
        "ops/a.py:12: **P2 Handle the empty case** "
        "https://github.com/o/r/pull/77#discussion_r1"
    ) in result["error"]
    assert result["error"].count("ops/a.py:12") == 1
    assert not _calls_at(world, _is_queue)


def test_an_explicit_reason_accepts_the_review_findings_and_queues() -> None:
    world = FakeWorld(review_comments=[_FINDING])
    reason = "P2 tracked in #123"
    code, result = ship(
        world, "--check", "u=good", "--merge", "--accept-review-findings", reason
    )
    assert code == 0, result
    assert _calls_at(world, _is_queue)
    assert result["review"]["accepted"] == reason
    assert result["review"]["findings"][0]["where"] == "ops/a.py:12"
    assert any(reason in line for line in result["log"])


_NEUTRAL = [_review(job=True), _review(conclusion="neutral")]


def test_a_neutral_review_is_not_a_verdict_and_refuses_to_queue() -> None:
    """`neutral` only means the workflow stopped waiting for the bot (5 min)."""
    world = FakeWorld(review_runs=[_NEUTRAL])
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1, result
    assert len(_calls_at(world, _is_review_read)) > 1  # kept polling to --timeout
    assert "never settled" in result["error"]
    assert "--accept-no-review" in result["error"]
    assert not _calls_at(world, _is_queue)


def test_a_neutral_review_followed_by_a_blocker_is_not_queued() -> None:
    """PR #2082: neutral at 13:15, the bot's P1 failure verdict at 13:17."""
    later = [*_NEUTRAL, _review(conclusion="failure")]
    world = FakeWorld(review_runs=[_NEUTRAL, later])
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1, result
    assert f"agent-review failed on {HEAD}" in result["error"]
    assert not _calls_at(world, _is_queue)


def test_a_neutral_review_followed_by_a_review_is_queued() -> None:
    world = FakeWorld(review_runs=[_NEUTRAL, [*_NEUTRAL, _review()]])
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 0, result
    assert result["review"]["verdict"] == "success"
    assert result["review"]["accepted_no_review"] is None


def test_an_explicit_reason_queues_without_a_review_and_records_it() -> None:
    world = FakeWorld(review_runs=[_NEUTRAL])
    reason = "codex quota exhausted; reviewed by hand"
    code, result = ship(
        world, "--check", "u=good", "--merge", "--accept-no-review", reason
    )
    assert code == 0, result
    assert _calls_at(world, _is_queue)
    assert result["review"]["verdict"] == "neutral"
    assert result["review"]["accepted_no_review"] == reason
    assert any(reason in line for line in result["log"])


def test_accepting_no_review_never_queues_while_the_review_is_still_running() -> None:
    world = FakeWorld(review_runs=[[_review("in_progress", job=True)]])
    code, result = ship(
        world, "--check", "u=good", "--merge", "--accept-no-review", "no bot"
    )
    assert code == 1, result
    assert "timed out" in result["error"]
    assert not _calls_at(world, _is_queue)


def test_without_merge_the_review_is_not_awaited() -> None:
    world = FakeWorld(review_runs=[[]])
    assert ship(world, "--check", "u=good")[0] == 0
    assert not _calls_at(world, _is_review_read)


_OF_PR_50 = {
    "event": "pull_request_target",
    "head_branch": "feat/old",
    "pull_requests": [{"number": 50}],
}


def test_a_review_run_of_another_pr_on_the_same_head_is_not_accepted() -> None:
    """redeliver's PR shares the replaced PR's head sha, so the commit-level
    check list also holds the replaced PR's runs: its success says nothing about
    this PR, and this PR was never reviewed."""
    world = FakeWorld(
        review_runs=[[_review(job=True), _review()]], actions_runs={1: _OF_PR_50}
    )
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1, result
    assert "belong to other PRs" in result["error"]
    assert "#77" in result["error"]
    assert not _calls_at(world, _is_queue)


def test_only_the_runs_of_this_pr_decide_among_runs_on_a_shared_head() -> None:
    """Positive control: the replaced PR's runs (here a failure) are ignored and
    this PR's own success is accepted."""
    old = [_review(job=True, run=1), _review(conclusion="failure", run=1)]
    own = [_review(job=True, run=2), _review(run=2)]
    world = FakeWorld(review_runs=[[*old, *own]], actions_runs={1: _OF_PR_50})
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 0, result
    assert result["review"]["verdict"] == "success"
    assert _calls_at(world, _is_queue)
    runs_read = [c[-1] for c in world.calls if "/actions/runs/" in c[-1]]
    assert sorted(set(runs_read)) == [
        "repos/o/r/actions/runs/1",
        "repos/o/r/actions/runs/2",
    ]


def test_a_run_without_pull_requests_is_owned_by_its_head_branch() -> None:
    world = FakeWorld(
        actions_runs={
            1: {"event": "pull_request_target", "head_branch": "feat/thing"},
        }
    )
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 0, result


@pytest.mark.parametrize(
    "unattributed",
    [
        None,  # GitHub no longer has the run (404)
        {"event": "issue_comment", "head_branch": "main", "pull_requests": []},
        {"event": "pull_request_target", "head_branch": "feat/old"},
    ],
    ids=["run-not-found", "comment-run-names-no-pr", "head-branch-of-another-pr"],
)
def test_a_review_whose_owner_cannot_be_determined_is_not_accepted(
    unattributed: dict[str, Any] | None,
) -> None:
    world = FakeWorld(actions_runs={1: unattributed})
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1, result
    assert "belong to other PRs or could not be attributed" in result["error"]
    assert not _calls_at(world, _is_queue)


def test_a_review_run_naming_no_workflow_run_is_not_accepted() -> None:
    bare = {**_review(job=True), "details_url": None}
    marker_only = {**_review(), "external_id": "", "details_url": ""}
    world = FakeWorld(review_runs=[[bare, marker_only]])
    code, result = ship(world, "--check", "u=good", "--merge")
    assert code == 1, result
    assert not _calls_at(world, _is_queue)


@pytest.mark.parametrize(
    ("runs", "verdict"),
    [
        ([], None),
        ([_review("in_progress")], None),  # only an orphaned verdict marker
        ([_review(conclusion="cancelled", job=True)], None),
        ([_review("in_progress", job=True), _review()], None),  # still evaluating
        ([_review(job=True), _review(conclusion="neutral"), _review()], "success"),
        ([_review(job=True), _review(conclusion="neutral")], "neutral"),
        ([_review(job=True)], "success"),
        ([_review(job=True), _review(conclusion="failure"), _review()], "failure"),
    ],
)
def test_the_review_verdict_reads_every_run_on_the_head(
    runs: list[dict[str, Any]], verdict: str | None
) -> None:
    assert deliver.review_verdict(runs) == verdict


def test_the_review_bots_are_read_from_the_workflow() -> None:
    workflow = deliver.AGENT_REVIEW.read_text()
    assert deliver.review_bots(workflow) == (BOT, "chatgpt-codex-connector")
    with pytest.raises(deliver.DeliverError, match="cannot read the review bot"):
        deliver.review_bots("env: {}")


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


def test_stale_local_main_base_is_detected_in_a_real_agent_style_checkout(
    tmp_path: Path,
) -> None:
    """Agent worktrees fork from a newer origin/main than the local main the
    claim was adopted against; the claim base is then not the fork point."""
    import subprocess

    def sh(*argv: str, cwd: Path = tmp_path) -> str:
        done = subprocess.run(
            list(argv), cwd=cwd, capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    repo = tmp_path / "repo"
    repo.mkdir()
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "config", "user.email", "t@example.com", cwd=repo)
    sh("git", "config", "user.name", "T", cwd=repo)
    (repo / "a.txt").write_text("1")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "one", cwd=repo)
    stale = sh("git", "rev-parse", "HEAD", cwd=repo)
    (repo / "merged_later.txt").write_text("2")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "two", cwd=repo)
    sh("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)
    sh("git", "checkout", "-q", "-b", "worktree-agent-x", cwd=repo)
    (repo / "mine.txt").write_text("3")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "mine", cwd=repo)
    sh("git", "update-ref", "refs/heads/main", stale, cwd=repo)  # stale local main

    args = deliver.build_parser().parse_args(["--worktree", str(repo)])
    delivery = deliver.Delivery(args, deliver.run, lambda _s: None)
    retired: list[list[str]] = []

    def spy(cmd: list[str], cwd: Path | None) -> deliver.Proc:
        if cmd[0].endswith("worktree_orchestrate.py"):
            retired.append(cmd)
            return deliver.Proc(0, "{}", "")
        return deliver.run(cmd, cwd)

    delivery.runner = spy
    assert delivery.reclaim_if_base_stale(
        {"base_sha": stale, "handed_back_sha": "e" * 40}, "worktree-agent-x"
    )
    assert retired and "abandoned" in retired[0]
    fork = sh("git", "merge-base", "HEAD", "origin/main", cwd=repo)
    assert not delivery.reclaim_if_base_stale(
        {"base_sha": fork, "handed_back_sha": "e" * 40}, "worktree-agent-x"
    )


def _format_calls(world: FakeWorld) -> list[list[str]]:
    return [c for c in world.calls if c[0] == "uv"]


def test_the_format_gate_runs_the_pr_gate_pinned_ruff_on_changed_python() -> None:
    world = FakeWorld()
    assert ship(world, "--check", "unit=good")[0] == 0
    (call,) = _format_calls(world)
    assert (
        "ruff==0.16.3" in deliver.PR_GATE.read_text()
    )  # the pin lives in the workflow
    assert call[call.index("--with") + 1] == "ruff==0.16.3"
    assert call[call.index("--python") + 1] == "3.13"
    assert "--no-project" in call and "format" in call
    assert call[call.index("--check") :] == ["--check", "ops/a.py", "ops/b.py"]


def test_the_pin_is_read_from_the_workflow_not_restated() -> None:
    bumped = deliver.ruff_format_command(
        "run: uv run --no-project --python 3.14 --with 'ruff==9.9.9' ruff format --check x"
    )
    assert "ruff==9.9.9" in bumped and "3.14" in bumped


def test_a_long_format_failure_names_every_file() -> None:
    names = [f"ops/module_{i:03d}.py" for i in range(60)]
    world = FakeWorld(format_rc=1, unformatted=names)
    code, result = ship(world, "--check", "unit=good")
    assert code == 1
    assert all(f"Would reformat: {n}" in result["error"] for n in names)


def test_an_unreadable_pin_fails_closed() -> None:
    with pytest.raises(deliver.DeliverError, match="cannot read the pinned ruff"):
        deliver.ruff_format_command("run: ruff format --check x")


def test_unformatted_python_stops_before_checks_and_names_the_fix() -> None:
    world = FakeWorld(format_rc=1)
    code, result = ship(world, "--check", "unit=good")
    assert code == 1
    error = result["error"]
    assert "pinned ruff" in error and "Would reformat: ops/a.py" in error
    assert "ruff==0.16.3 ruff format ops/a.py ops/b.py" in error
    assert not [c for c in world.calls if c[0] == "bash"]  # no check ran
    assert world.names() == []  # nothing claimed, nothing handed back
    assert not [c for c in world.calls if c[:2] == ["git", "commit"]]  # never rewrites


def test_a_branch_without_python_changes_skips_the_format_gate() -> None:
    world = FakeWorld(changed_py=[])
    assert ship(world, "--check", "unit=good")[0] == 0
    assert _format_calls(world) == []


# ---- redeliver: replace a published PR with a fixed lane ------------------

OLD = "feat/old"
PUBLISHED = "a" * 40
_HOLDS_BLOCK = (
    'body\n<!-- kg.delivery.holds.v1\n{"schema": "kg.delivery.holds.v1", '
    '"holds": ["security"]}\n-->\n'
)


def _replacement_world(
    *,
    generation: int = 0,
    old_status: str = "published",
    old_pr_state: str = "OPEN",
    remote: str | None = PUBLISHED,
    **state: Any,
) -> FakeWorld:
    lane = {
        "branch": OLD,
        "status": old_status,
        "claim_generation": generation,
        "handed_back_sha": PUBLISHED,
        "path": "/gone/old-lane",
        "external_ids": ["LANE-OLD"],
    }
    pr = {"number": 50, "state": old_pr_state, "url": "https://x/pull/50"}
    return FakeWorld(
        records_by_branch={
            OLD: state.pop("old_records", [lane]),
            **state.pop("new_records", {}),
        },
        prs_by_branch={OLD: state.pop("old_prs", [pr]), **state.pop("new_prs", {})},
        remote_heads={OLD: remote} if remote else {},
        **state,
    )


def redeliver(world: FakeWorld, *flags: str) -> tuple[int, dict[str, Any]]:
    worktree = [] if "--worktree" in flags else ["--worktree", str(world.work)]
    common = ["--timeout", "5", "--poll", "1", *worktree]
    return ship(world, "redeliver", "--branch", OLD, *common, *flags)


def _call(world: FakeWorld, *prefix: str) -> list[str] | None:
    return next((c for c in world.calls if c[: len(prefix)] == list(prefix)), None)


def _value(call: list[str], flag: str, prefix: bool = False) -> str:
    if prefix:  # a `-F name=value` field
        return next(a for a in call if a.startswith(flag)).removeprefix(flag)
    return call[call.index(flag) + 1]


@pytest.mark.parametrize("generation", [0, 1])
def test_redeliver_abandons_the_old_lane_with_the_registrys_generation_and_head(
    generation: int,
) -> None:
    world = _replacement_world(generation=generation)
    code, result = redeliver(world, "--check", "u=good", "--lane", "LANE-NEW")
    assert code == 0, result
    assert world.names() == ["resolve", "adopt", "hand-back", "receipt", "publish"]
    resolve = next(c for c in world.calls if c[1:2] == ["resolve"])
    assert _value(resolve, "--branch") == OLD
    assert _value(resolve, "--path") == "/gone/old-lane"
    assert _value(resolve, "--status") == "abandoned"
    assert _value(resolve, "--expected-generation") == str(generation)
    assert _value(resolve, "--expected-head-sha") == PUBLISHED
    close = _call(world, "gh", "pr", "close")
    assert close is not None and close[3] == "50"
    assert _value(close, "--comment").startswith("Superseded by #77 (u)")
    publish = next(
        i
        for i, c in enumerate(world.calls)
        if c[0].endswith("delivery.py") and c[3] == "publish"
    )
    assert world.calls.index(close) > publish  # the link exists before the close
    assert _call(world, "git", "push") == [
        "git",
        "push",
        f"--force-with-lease=refs/heads/{OLD}:{PUBLISHED}",
        "origin",
        "--delete",
        OLD,
    ]
    assert result["replaced"] == {
        "branch": OLD,
        "pr": 50,
        "claim_generation": generation,
        "published_head": PUBLISHED,
        "remote_branch": "deleted",
    }


def test_redeliver_keeps_an_old_remote_branch_that_moved_off_the_published_head() -> (
    None
):
    moved = "b" * 40
    world = _replacement_world(remote=moved)
    code, result = redeliver(world, "--check", "u=good")
    assert code == 0, result
    assert _call(world, "git", "push") is None
    assert result["replaced"]["remote_branch"] == (
        f"kept: at {moved}, not the published head {PUBLISHED}"
    )


@pytest.mark.parametrize(
    ("state", "flags", "message"),
    [
        ({"branch": OLD}, [], "commit the fix on a new branch"),
        ({"old_pr_state": "MERGED"}, [], "PR #50 is already merged"),
        ({"old_status": "active"}, [], "redeliver replaces a published lane"),
        ({"old_records": []}, [], f"no registry lane for {OLD}"),
        ({"old_prs": []}, [], f"no PR for {OLD}"),
        ({}, ["--lane", "LANE-OLD"], "is the replaced lane's id"),
        (
            {"pr_guard": [{"labels": {"nodes": [{"name": "delivery-hold:p1"}]}}]},
            [],
            "PR #50 carries a hard hold (p1)",
        ),
        (
            {"pr_guard": [{"body": _HOLDS_BLOCK}]},
            [],
            "PR #50 carries a hard hold (security)",
        ),
        (
            {"pr_guard": [{"autoMergeRequest": {"enabledAt": "t"}}]},
            [],
            "PR #50 is scheduled to merge",
        ),
        (
            {"pr_guard": [{"mergeQueueEntry": {"id": "q"}}]},
            [],
            "PR #50 is scheduled to merge",
        ),
    ],
)
def test_redeliver_refuses_before_touching_anything(
    state: dict[str, Any], flags: list[str], message: str
) -> None:
    world = _replacement_world(**state)
    code, result = redeliver(world, "--check", "u=good", *flags)
    assert code == 1
    assert message in result["error"]
    assert world.names() == []
    assert _call(world, "gh", "pr", "close") is None
    assert _call(world, "git", "push") is None


def test_redeliver_rereads_the_old_pr_before_abandoning_its_lane() -> None:
    """The checks can run for minutes; the old PR may get queued meanwhile."""
    world = _replacement_world(pr_guard=[{}, {"mergeQueueEntry": {"id": "q"}}])
    code, result = redeliver(world, "--check", "u=good")
    assert code == 1, result
    assert "PR #50 is scheduled to merge" in result["error"]
    assert "resolve" not in world.names()
    assert _call(world, "gh", "pr", "close") is None
    graphql = [c for c in world.calls if c[1:3] == ["api", "graphql"]]
    assert len(graphql) == 2


def test_redeliver_aborts_when_the_replaced_pr_merges_during_redelivery() -> None:
    """Checked at the lookup, not by the OPEN-only guard: a merged PR must not
    be reported as superseded, nor have its branch deleted."""
    world = _replacement_world(merge_old_after="publish")
    code, result = redeliver(world, "--check", "u=good")
    assert code == 1, result
    assert "PR #50 merged while #77 was replacing it" in result["error"]
    assert "not deleted" in result["error"]
    assert _call(world, "gh", "pr", "close") is None
    assert _call(world, "git", "push") is None
    assert world.remote_heads == {OLD: PUBLISHED}


def test_redeliver_rereads_the_old_pr_before_closing_it() -> None:
    world = _replacement_world(
        pr_guard=[{}, {}, {"labels": {"nodes": [{"name": "delivery-hold:p0"}]}}]
    )
    code, result = redeliver(world, "--check", "u=good")
    assert code == 1, result
    assert "PR #50 carries a hard hold (p0)" in result["error"]
    assert _call(world, "gh", "pr", "close") is None
    assert _call(world, "git", "push") is None


def test_delivery_options_before_redeliver_are_refused_not_dropped() -> None:
    argv = ["--worktree", "/fixed", "--merge", "redeliver", "--branch", OLD]
    with (
        contextlib.redirect_stderr(io.StringIO()) as err,
        pytest.raises(SystemExit) as stop,
    ):
        deliver.main(argv, runner=FakeWorld())
    assert stop.value.code == 2
    assert "--worktree, --merge" in err.getvalue()
    assert "after `redeliver`" in err.getvalue()
    parsed = deliver.build_parser().parse_args(
        ["redeliver", "--branch", OLD, "--worktree", "/fixed", "--merge"]
    )
    assert (parsed.worktree, parsed.merge) == ("/fixed", True)


def test_a_redeliver_rerun_skips_what_is_already_retired() -> None:
    world = _replacement_world(
        old_status="abandoned", old_pr_state="CLOSED", remote=None
    )
    code, result = redeliver(world, "--check", "u=good")
    assert code == 0, result
    assert world.names() == ["adopt", "hand-back", "receipt", "publish"]
    assert _call(world, "gh", "pr", "close") is None
    assert result["replaced"]["remote_branch"] == "absent"


def test_redeliver_resumes_from_the_new_branch_once_its_worktree_is_gone() -> None:
    world = _replacement_world(
        old_status="abandoned",
        new_records={"feat/new": [{"branch": "feat/new", "status": "published"}]},
        new_prs={"feat/new": [{"number": 77, "state": "OPEN", "url": "u"}]},
    )
    gone = str(world.work / "gone")
    code, result = redeliver(world, "--worktree", gone)
    assert code == 1 and "--new-branch" in result["error"]
    code, result = redeliver(world, "--worktree", gone, "--new-branch", "feat/new")
    assert code == 0, result
    assert world.names() == []  # already published: nothing re-claimed
    assert _call(world, "gh", "pr", "close") is not None
    assert result["pr"] == 77 and result["replaced"]["remote_branch"] == "deleted"


def test_the_old_remote_branch_is_deleted_only_at_the_published_head(
    tmp_path: Path,
) -> None:
    """Real git: the lease makes the delete a compare-and-swap on the remote."""
    import subprocess

    def sh(*argv: str, cwd: Path) -> str:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    remote, repo = tmp_path / "remote.git", tmp_path / "repo"
    sh("git", "init", "-q", "--bare", str(remote), cwd=tmp_path)
    sh("git", "init", "-q", "-b", "main", str(repo), cwd=tmp_path)
    sh("git", "config", "user.email", "t@example.com", cwd=repo)
    sh("git", "config", "user.name", "T", cwd=repo)
    sh("git", "remote", "add", "origin", str(remote), cwd=repo)
    (repo / "a.txt").write_text("1")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "published", cwd=repo)
    published = sh("git", "rev-parse", "HEAD", cwd=repo)
    sh("git", "push", "-q", "origin", f"HEAD:refs/heads/{OLD}", cwd=repo)

    args = deliver.build_parser().parse_args(["--worktree", str(repo)])
    replacement = deliver.Replacement(
        deliver.Delivery(args, deliver.run, lambda _s: None), OLD
    )
    (repo / "a.txt").write_text("2")
    sh("git", "commit", "-qam", "pushed onto the PR", cwd=repo)
    moved = sh("git", "rev-parse", "HEAD", cwd=repo)
    sh("git", "push", "-q", "origin", f"HEAD:refs/heads/{OLD}", cwd=repo)
    assert replacement.drop_remote_branch(published) == (
        f"kept: at {moved}, not the published head {published}"
    )
    with pytest.raises(deliver.DeliverError, match="stale info|rejected"):
        replacement.delete_remote_branch(published)  # the lease refuses a moved ref
    assert sh("git", "ls-remote", "origin", f"refs/heads/{OLD}", cwd=repo)

    assert replacement.drop_remote_branch(moved) == "deleted"
    assert sh("git", "ls-remote", "origin", f"refs/heads/{OLD}", cwd=repo) == ""
    assert replacement.drop_remote_branch(moved) == "absent"
