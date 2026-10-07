#!/usr/bin/env -S uv run --python 3.13 python
"""Deliver one worktree branch through the official flow with a single command.

    ./ops/deliver.py --check "unit=uv run pytest -q" --merge

It only sequences the existing tools (`worktree_orchestrate.py`, `delivery.py`,
`gh`); it owns no state.  Where the lane stands is read back from the registry
and GitHub on every run, so a run that died halfway is simply run again.

Stages: checks -> adopt -> hand-back -> receipt -> publish -> wait-required ->
(with --merge) wait agent-review -> queue -> wait-merged -> cleanup -> sync-main.
--merge waits until agent-review on the exact head settles to success or
failure (`neutral` is the workflow giving up on the bot, not a verdict; only
--accept-no-review '<reason>' queues on it), and refuses to queue while it
failed or the review bot left inline comments on the head, unless
--accept-review-findings gives a reason.  A mutation that meets a busy delivery lock retries (--lock-timeout).
A failed stage reports the underlying error whole.

Before the hand-back seals HEAD, the changed ``*.py`` files must pass the very
``ruff format --check`` the pr-gate runs (version read from pr-gate.yml, never
restated here).  A failure stops the run and names the files and the exact
format command; deliver never rewrites the branch itself, because a silent
rewrite after the author committed would hand back code nobody ran the checks on.

Outcomes written into the hand-back receipt come only from the ``--check``
commands this run executed: status from the exit code, detail from the last
line of output.  There is no way to pass an outcome in by hand.

``deliver.py gc`` retires lanes whose PR is already merged (the ghost claims
`doctor.py` reports) via `delivery.py cleanup-merged`.

``deliver.py redeliver --branch <published-lane-branch> --worktree <fixed-tip>
[--lane <new-lane>] --check ... [--merge]`` replaces a published PR after review
fixes (see ``Replacement``); delivery options go after ``redeliver``.

Exit code: 0 delivered (or stopped where asked), 1 a stage failed, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from delivery_control.domain.errors import PolicyViolation
from delivery_control.services.pr_contract import (
    parse_body_holds,
    pull_request_label_holds,
)
from lib import worktree_scope

SCHEMA = "kg.deliver.v1"
TRUNK = "origin/main"
OPS = Path(__file__).resolve().parent
PR_GATE = OPS.parent / ".github" / "workflows" / "pr-gate.yml"
# Raised by delivery_control/adapters/operation_lock.py (a test pins the text).
LOCK_BUSY = "delivery mutation already in progress"
LOCK_RETRY_SECONDS = 5.0
AGENT_REVIEW = OPS.parent / ".github" / "workflows" / "agent-review.yml"
REVIEW_CHECK = "agent-review"
# The workflow posts its verdicts as extra check runs carrying this external_id
# prefix; a run cancelled by a newer event leaves its in_progress one behind.
REVIEW_MARKER = "kg.agent-review.v1:"
REVIEW_FAILED = frozenset(
    {"failure", "timed_out", "action_required", "startup_failure"}
)
SHA = re.compile(r"[0-9a-f]{40}")
# What delivery.py abandon-pr refuses on, read for the PR redeliver replaces.
PR_GUARD_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!) {"
    " repository(owner: $owner, name: $name) { pullRequest(number: $number) {"
    " number state body labels(first: 100) { nodes { name } }"
    " autoMergeRequest { enabledAt } mergeQueueEntry { id } } } }"
)


class DeliverError(Exception):
    """A stage failed; the message says which and why."""


@dataclass(frozen=True)
class Proc:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], Path | None], Proc]


def run(cmd: list[str], cwd: Path | None = None) -> Proc:
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return Proc(done.returncode, done.stdout, done.stderr)


def progress(message: str) -> None:
    """Progress goes to stderr; stdout stays one JSON document."""
    print(f"deliver: {message}", file=sys.stderr, flush=True)


def failure_detail(done: Proc) -> str:
    """Everything a failed command said, never a tail.

    ``delivery.py`` reports a failure as one JSON document (``ok: false``) after
    its progress lines; its ``error`` is the underlying cause, often a GitHub
    message that follows a long GraphQL query, so it is returned whole.  Any
    other command's streams are returned whole.
    """
    for stream in (done.stderr, done.stdout):
        for line in reversed(stream.strip().splitlines()):
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("ok") is False:
                if isinstance(doc.get("error"), str):
                    return doc["error"]
    return "\n".join(s.strip() for s in (done.stderr, done.stdout) if s.strip())


@dataclass(frozen=True)
class LockWait:
    """Bounded wait while another delivery mutation holds the operation lock.

    Every delivery/registry/worktree mutation takes the lock before it changes
    anything, so an attempt refused with ``LOCK_BUSY`` did nothing and is safe
    to repeat.
    """

    timeout: float
    sleep: Callable[[float], None]
    clock: Callable[[], float]
    say: Callable[[str], None]


def must(
    runner: Runner,
    cmd: list[str],
    cwd: Path | None,
    stage: str,
    lock: LockWait | None = None,
) -> Proc:
    started = lock.clock() if lock else 0.0
    while True:
        done = runner(cmd, cwd)
        if done.returncode == 0:
            return done
        detail = failure_detail(done) or "no output"
        if lock is None or LOCK_BUSY not in detail:
            raise DeliverError(f"{stage} failed (rc={done.returncode}): {detail}")
        left = started + lock.timeout - lock.clock()
        if left <= 0:
            raise DeliverError(
                f"{stage}: the delivery mutation lock is still held after "
                f"{lock.timeout:g}s: {detail}"
            )
        lock.say(
            f"{stage}: another delivery mutation holds the operation lock "
            f"({detail}); retrying for up to {left:g}s more"
        )
        lock.sleep(min(LOCK_RETRY_SECONDS, left))


# --- pure helpers -----------------------------------------------------------


def scope_from_name_status(text: str) -> dict[str, Any]:
    """`git diff --name-status` -> a kg.worktree.scope.v1 document.

    A rename is a delete of the old path plus an add of the new one, which is
    how Scope overlap has to see it.
    """
    try:
        return worktree_scope.scope_from_name_status(text)
    except ValueError as exc:
        raise DeliverError(str(exc)) from exc


def _scope_key(scope: object) -> list[tuple[str, str]]:
    files = scope.get("files") if isinstance(scope, dict) else None
    return sorted(
        (str(item.get("path")), str(item.get("operation")))
        for item in files or []
        if isinstance(item, dict)
    )


def lane_from_branch(branch: str, stamp: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", branch).strip("-").upper()
    return (
        f"DIRECT-DELIVERY-{slug}"
        if slug.endswith(stamp)
        else f"DIRECT-DELIVERY-{slug}-{stamp}"
    )


def parse_check(spec: str) -> tuple[str, str]:
    label, sep, command = spec.partition("=")
    if not sep or not label.strip() or not command.strip():
        raise DeliverError(f"--check wants 'label=command', got {spec!r}")
    return label.strip(), command.strip()


def run_checks(specs: list[str], cwd: Path, runner: Runner) -> list[dict[str, str]]:
    """Run every check (no early exit) and report what actually happened."""
    outcomes = []
    for spec in specs:
        label, command = parse_check(spec)
        done = runner(["bash", "-c", command], cwd)
        lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
        outcomes.append(
            {
                "check": label,
                "status": "passed" if done.returncode == 0 else "failed",
                "detail": (lines[-1] if lines else f"rc={done.returncode}")[:120],
            }
        )
    return outcomes


def ruff_format_command(workflow: str) -> list[str]:
    """The pr-gate's pinned format invocation, minus the files and the mode flag.

    The workflow is the single source of the pin; if its shape changes so this
    can no longer find it, fail closed instead of guessing a version.
    """
    found = re.search(
        r"uv run --no-project --python (\S+) --with 'ruff==([0-9][^']*)' ruff format",
        workflow,
    )
    if not found:
        raise DeliverError(
            f"cannot read the pinned ruff from {PR_GATE.name}; "
            "update deliver.ruff_format_command with the workflow"
        )
    python, version = found.groups()
    return [
        "uv",
        "run",
        "--no-project",
        "--python",
        python,
        "--with",
        f"ruff=={version}",
        "ruff",
        "format",
    ]


def next_stage(record: dict[str, Any] | None, pr: dict[str, Any] | None) -> str:
    """Where a (re)run has to start, given what the registry and GitHub already hold."""
    if pr is not None:
        if pr.get("state") == "MERGED":
            return "cleanup"
        if pr.get("state") == "OPEN":
            return "wait-required"
        raise DeliverError(
            f"PR #{pr.get('number')} is {pr.get('state')}; open a fresh lane"
        )
    if record is None:
        return "adopt"
    status = record.get("status")
    if status == "active":
        return "receipt" if record.get("handback_seal") else "hand-back"
    if status == "published":
        return "wait-required"
    raise DeliverError(f"lane is {status!r}; resolve it before delivering again")


def review_bots(workflow: str) -> tuple[str, ...]:
    """The reviewer logins agent-review.yml trusts; read there, never restated."""
    bots = re.findall(r"^\s*REVIEW_BOT(?:_CURRENT)?:\s*(\S+)\s*$", workflow, re.M)
    if not bots:
        raise DeliverError(
            f"cannot read the review bot from {AGENT_REVIEW.name}; "
            "update deliver.review_bots with the workflow"
        )
    return tuple(bots)


def review_verdict(runs: list[dict[str, Any]]) -> str | None:
    """The settled `agent-review` verdict of one head, or None while pending.

    Pending while an Actions job run is unfinished or nothing has concluded
    (orphaned in_progress verdict markers are ignored); failure if any run
    failed; otherwise the best posted verdict, or the job's own conclusion
    when it posted none.
    """
    runs = [r for r in runs if r.get("name") == REVIEW_CHECK]

    def marker(run: dict[str, Any]) -> bool:
        return str(run.get("external_id") or "").startswith(REVIEW_MARKER)

    if any(r.get("status") != "completed" and not marker(r) for r in runs):
        return None
    done = [r for r in runs if r.get("status") == "completed"]
    if any(r.get("conclusion") in REVIEW_FAILED for r in done):
        return "failure"
    verdicts = {r.get("conclusion") for r in done if marker(r)} or {
        r.get("conclusion") for r in done
    }
    return next((v for v in ("success", "neutral") if v in verdicts), None)


def review_run_id(run: dict[str, Any]) -> int | None:
    """The Actions workflow run behind one `agent-review` check run, if it names one.

    The verdict marker is ``kg.agent-review.v1:<run id>:<sha>``; the Actions
    job's own check run links ``.../actions/runs/<run id>/job/<job id>``.
    """
    marker = str(run.get("external_id") or "")
    if marker.startswith(REVIEW_MARKER):
        found = re.match(r"(\d+):", marker.removeprefix(REVIEW_MARKER))
    else:
        found = re.search(r"/actions/runs/(\d+)", str(run.get("details_url") or ""))
    return int(found.group(1)) if found else None


def workflow_run_is_of(run: dict[str, Any], number: int, head_ref: str) -> bool:
    """Whether a workflow run was triggered by PR ``number``.

    A head sha is not enough: redeliver's replacement PR shares the replaced
    PR's sha, and the commit-level check list holds both PRs' runs.  The run's
    ``pull_requests`` names its PR; a run that names none (GitHub leaves it
    empty at times) is owned only by its ``head_branch`` being this PR's head
    ref.  Comment-triggered runs carry the default branch, so they match
    neither and are never attributed.
    """
    numbers = [p.get("number") for p in run.get("pull_requests") or []]
    if numbers:
        return number in numbers
    return bool(head_ref) and run.get("head_branch") == head_ref


def review_findings(
    comments: list[dict[str, Any]], head: str, bots: tuple[str, ...]
) -> list[dict[str, str]]:
    """The inline comments the review bot left on this exact head."""
    return [
        {
            "where": ":".join(
                str(part)
                for part in (c.get("path"), c.get("line") or c.get("original_line"))
                if part
            ),
            "summary": next(
                (s.strip() for s in str(c.get("body") or "").splitlines() if s.strip()),
                "",
            ),
            "url": str(c.get("html_url") or ""),
        }
        for c in comments
        if (c.get("user") or {}).get("login") in bots
        and head in (c.get("commit_id"), c.get("original_commit_id"))
    ]


def required_state(checks: list[dict[str, Any]]) -> str:
    states = [c.get("state") for c in checks if c.get("name") == "required"]
    if not states:
        return "PENDING"
    return str(states[0])


# --- stages -----------------------------------------------------------------


class Delivery:
    def __init__(
        self,
        args: argparse.Namespace,
        runner: Runner,
        sleep: Callable[[float], None],
        clock: Callable[[], float] = time.monotonic,
    ):
        self.args = args
        self.runner = runner
        self.sleep = sleep
        self.clock = clock
        self.work = Path(args.worktree).resolve()
        self.canon: Path | None = None
        self.log: list[str] = []
        self.extra: dict[str, Any] = {}
        self.lock = LockWait(args.lock_timeout, sleep, clock, self.say)
        # redeliver's hooks: retire the replaced lane before this one claims
        # its Scope, and supersede the replaced PR once this one exists.
        self.before_claim: Callable[[], object] = lambda: None
        self.after_publish: Callable[[dict[str, Any]], object] = lambda _pr: None

    def mutate(self, cmd: list[str], cwd: Path | None, stage: str) -> Proc:
        """Run a delivery/registry/worktree mutation, waiting out a busy lock."""
        return must(self.runner, cmd, cwd, stage, self.lock)

    @property
    def home(self) -> Path:
        """Where to run repo-wide commands: publish deletes the lane worktree mid-run."""
        return self.work if self.work.exists() else (self.canon or Path.cwd())

    def git(self, *argv: str, stage: str = "git") -> str:
        return must(self.runner, ["git", *argv], self.home, stage).stdout.strip()

    def say(self, message: str) -> None:
        self.log.append(message)
        progress(message)

    def canonical(self) -> Path:
        out = self.git(
            "worktree", "list", "--porcelain", stage="locate canonical checkout"
        )
        return Path(out.splitlines()[0].removeprefix("worktree ").strip())

    def gh_repo(self) -> str:
        return must(
            self.runner,
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            self.home,
            "resolve repository",
        ).stdout.strip()

    def registry_records(self, branch: str) -> list[dict[str, Any]]:
        out = must(
            self.runner,
            [str(OPS / "worktree_registry.py"), "list", "--json", "--branch", branch],
            self.home,
            "read registry",
        ).stdout
        data = json.loads(out)
        records = data["records"] if isinstance(data, dict) else data
        return [r for r in records if r.get("branch") == branch]

    def registry_record(self, branch: str) -> dict[str, Any] | None:
        live = [
            r for r in self.registry_records(branch) if r.get("status") != "abandoned"
        ]
        return live[-1] if live else None

    def pull_request(self, repo: str, branch: str) -> dict[str, Any] | None:
        out = must(
            self.runner,
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number,state,url",
                "-q",
                "sort_by(.number) | reverse",
            ],
            self.home,
            "look up PR",
        ).stdout.strip()
        prs = json.loads(out or "[]")
        return prs[0] if prs else None

    def preflight(self) -> str:
        branch = self.git("rev-parse", "--abbrev-ref", "HEAD", stage="preflight")
        if branch in ("main", "HEAD"):
            raise DeliverError(
                f"refusing to deliver from {branch!r}; use a lane worktree branch"
            )
        if self.git("status", "--porcelain", stage="preflight"):
            raise DeliverError("worktree has uncommitted changes; commit them first")
        self.git("fetch", "-q", "origin", "main", stage="preflight")
        if self.git("rev-list", "--count", f"{TRUNK}..HEAD", stage="preflight") == "0":
            raise DeliverError(f"branch has no commits ahead of {TRUNK}")
        return branch

    def rebase_if_behind(self) -> None:
        behind = self.git("rev-list", "--count", f"HEAD..{TRUNK}", stage="preflight")
        if behind == "0":
            return
        done = self.runner(["git", "rebase", TRUNK], self.work)
        if done.returncode != 0:
            self.runner(["git", "rebase", "--abort"], self.work)
            raise DeliverError(
                f"branch is {behind} commit(s) behind {TRUNK} and does not rebase "
                f"cleanly (rebase aborted):\n{failure_detail(done) or 'no output'}"
            )
        self.say(f"rebased onto {TRUNK} ({behind} commit(s))")

    def check_format(self) -> None:
        """Run the pr-gate's pinned `ruff format --check` on the changed Python files."""
        names = self.git(
            "diff", "--name-only", "--diff-filter=d", f"{TRUNK}...HEAD", "--", "*.py"
        )
        files = [line for line in names.splitlines() if line.strip()]
        if not files:
            self.say("format: no changed Python files")
            return
        try:
            base = ruff_format_command(PR_GATE.read_text())
        except OSError as exc:
            raise DeliverError(f"cannot read {PR_GATE}: {exc}") from exc
        done = self.runner([*base, "--check", *files], self.work)
        if done.returncode == 0:
            self.say(f"format ok: {len(files)} changed Python file(s)")
            return
        listed = failure_detail(done)
        fix = " ".join([*base, *files])
        raise DeliverError(
            "changed Python files are not formatted with the pr-gate's pinned ruff "
            f"(rc={done.returncode}):\n{listed}\nrun, commit, then re-run deliver:\n  {fix}"
        )

    def abandon(
        self, branch: str, path: str | None, generation: object, head: str, stage: str
    ) -> None:
        """Retire one exact claim through the registry's compare-and-swap."""
        self.mutate(
            [str(OPS / "worktree_orchestrate.py"), "resolve", "--branch", branch]
            + (["--path", path] if path else [])
            + ["--status", "abandoned", "--expected-generation", str(generation)]
            + ["--expected-head-sha", head, "--json"],
            self.home,
            stage,
        )

    def reclaim_if_base_stale(self, record: dict[str, Any], branch: str) -> bool:
        """Abandon an active claim whose base is not the branch's fork point.

        A claim adopted against a stale local ``main`` records that old base;
        once the branch sits on a newer ``origin/main`` the three-dot diff then
        includes merged main commits and the receipt refuses.  The registry's
        own ``resolve --status abandoned`` retires the claim; the caller then
        re-adopts against ``origin/main``.
        """
        fork = self.git("merge-base", "HEAD", TRUNK, stage="preflight")
        if record.get("base_sha") == fork:
            return False
        head = self.git("rev-parse", "HEAD", stage="preflight")
        sealed = record.get("handed_back_sha")
        self.abandon(
            branch,
            str(self.work),
            record.get("claim_generation", 0),
            str(sealed or head),
            "retire stale-base claim",
        )
        self.say(
            f"claim base {record.get('base_sha')} is not the fork point {fork}; "
            "claim retired, re-adopting"
        )
        return True

    def wait_for(self, what: str, probe: Callable[[], str | None]) -> str:
        deadline = self.clock() + self.args.timeout
        while True:
            result = probe()
            if result is not None:
                return result
            if self.clock() >= deadline:
                raise DeliverError(
                    f"timed out after {self.args.timeout}s waiting for {what}"
                )
            self.sleep(self.args.poll)

    def deliver(self) -> dict[str, Any]:
        if self.work.exists():
            branch = self.preflight()
            if self.args.branch and self.args.branch != branch:
                raise DeliverError(
                    f"--branch {self.args.branch!r} is not the checked-out branch {branch!r}"
                )
        elif self.args.branch:
            branch = self.args.branch
        else:
            raise DeliverError(
                f"worktree {self.work} is gone; pass --branch to resume a published lane"
            )
        repo = self.gh_repo()
        canon = self.canon = self.canonical()
        delivery = [str(canon / "ops" / "delivery.py"), "--repo", str(canon)]
        record = self.registry_record(branch)
        pr = self.pull_request(repo, branch)
        if (
            self.args.branch
            and pr is not None
            and pr.get("state") == "MERGED"
            and (record is None or record.get("status") in ("merged", "abandoned"))
        ):
            raise DeliverError(
                f"PR #{pr.get('number')} already merged; start a new lane from {TRUNK}"
            )
        stage = next_stage(record, pr)
        lane = self.args.lane or (
            record["external_ids"][0] if record and record.get("external_ids") else None
        )
        lane = lane or lane_from_branch(branch, time.strftime("%Y%m%d", time.gmtime()))
        self.say(f"branch={branch} lane={lane} starts at {stage}")
        if stage in ("adopt", "hand-back", "receipt") and not self.work.exists():
            raise DeliverError(
                f"worktree {self.work} is gone before the lane was published; recreate it"
            )

        if stage in ("adopt", "hand-back", "receipt"):
            self.rebase_if_behind()
        if (
            stage in ("hand-back", "receipt")
            and record is not None
            and self.reclaim_if_base_stale(record, branch)
        ):
            record, stage = None, "adopt"
        if stage in ("adopt", "hand-back"):
            if not self.args.check:
                raise DeliverError(
                    "pass at least one --check: an outcome has to come from a command that ran"
                )
            self.check_format()
            outcomes = run_checks(self.args.check, self.work, self.runner)
            failed = [o for o in outcomes if o["status"] != "passed"]
            for o in outcomes:
                self.say(f"check {o['status']}: {o['check']}")
            if failed:
                raise DeliverError(
                    "check(s) failed: " + ", ".join(o["check"] for o in failed)
                )
            self.before_claim()
            with tempfile.TemporaryDirectory() as tmp:
                scope = scope_from_name_status(
                    self.git("diff", "--name-status", f"{TRUNK}...HEAD")
                )
                scope_file, outcome_file = (
                    Path(tmp, "scope.json"),
                    Path(tmp, "outcomes.json"),
                )
                scope_file.write_text(json.dumps(scope))
                outcome_file.write_text(json.dumps(outcomes))
                orchestrate = str(OPS / "worktree_orchestrate.py")
                if (
                    stage == "hand-back"
                    and self.args.scope_from_diff
                    and _scope_key(record and record.get("scope")) != _scope_key(scope)
                ):
                    # The lane grew past the Scope it was adopted with.
                    self.mutate(
                        [
                            str(OPS / "worktree_registry.py"),
                            "scope-set",
                            "--branch",
                            branch,
                            "--path",
                            str(self.work),
                            "--scope-file",
                            str(scope_file),
                        ],
                        self.work,
                        "scope-set",
                    )
                    self.say("scope refreshed from the diff")
                if stage == "adopt":
                    intent = self.args.intent or self.git("log", "-1", "--format=%s")
                    self.mutate(
                        [
                            orchestrate,
                            "adopt",
                            "--worktree",
                            str(self.work),
                            "--base",
                            TRUNK,
                            "--intent",
                            intent,
                            "--external-id",
                            lane,
                            "--scope-file",
                            str(scope_file),
                            "--codex-thread-id",
                            self.args.thread_id,
                            "--delegated",
                            "--json",
                        ],
                        self.work,
                        "adopt",
                    )
                    self.say("adopted")
                self.mutate(
                    [
                        orchestrate,
                        "hand-back",
                        "--branch",
                        branch,
                        "--path",
                        str(self.work),
                        "--outcomes",
                        str(outcome_file),
                        "--json",
                    ],
                    self.home,
                    "hand-back",
                )
                self.say("handed back")
            stage = "receipt"
        elif stage == "receipt":
            self.before_claim()
        if stage == "receipt":
            self.mutate(
                [*delivery, "receipt", "--lane", lane],
                self.home,
                "receipt",
            )
            title = self.args.title or self.git("log", "-1", "--format=%s")
            self.mutate(
                [*delivery, "publish", "--lane", lane, "--title", title],
                self.home,
                "publish",
            )
            pr = self.pull_request(repo, branch)
            if pr is None:
                raise DeliverError(
                    "publish reported success but no PR exists for the branch"
                )
            self.say(f"published PR #{pr['number']}")
            stage = "wait-required"
        if pr is None:
            raise DeliverError("no PR to wait on")
        number = int(pr["number"])
        self.after_publish(pr)
        if stage == "wait-required":
            self.wait_for("required check", lambda: self._required(repo, number))
            self.say(f"required passed on #{number}")
            if not self.args.merge:
                return self.summary(branch, lane, number, "ready-to-merge")
            self.extra["review"] = self.review_gate(repo, number)
            self.mutate(
                [*delivery, "queue", "--pr", str(number)],
                self.home,
                "queue",
            )
            self.say(f"queued #{number}")
            self.wait_for("merge", lambda: self._merged(repo, number))
            stage = "cleanup"
        if stage == "cleanup":
            # The worktree may be the very directory being retired; run from the canonical checkout.
            self.mutate(
                [*delivery, "cleanup-merged", "--pr", str(number)],
                canon,
                "cleanup-merged",
            )
            self.mutate([*delivery, "sync-main"], canon, "sync-main")
            self.say(f"merged #{number}; lane cleaned and main synced")
        return self.summary(branch, lane, number, "merged")

    def _required(self, repo: str, number: int) -> str | None:
        out = must(
            self.runner,
            ["gh", "pr", "checks", str(number), "--repo", repo, "--json", "name,state"],
            self.home,
            "read checks",
        ).stdout
        state = required_state(json.loads(out or "[]"))
        if state == "SUCCESS":
            return state
        if state in ("FAILURE", "ERROR", "CANCELLED"):
            raise DeliverError(f"required check is {state} on #{number}; see the PR")
        return None

    def _merged(self, repo: str, number: int) -> str | None:
        out = must(
            self.runner,
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "state",
                "-q",
                ".state",
            ],
            self.home,
            "read PR state",
        ).stdout.strip()
        if out == "MERGED":
            return out
        if out == "CLOSED":
            raise DeliverError(f"#{number} was closed without merging")
        return None

    def gh_pages(self, endpoint: str, key: str | None = None) -> list[dict[str, Any]]:
        """Every item of a paginated REST list (``key``: the list inside a page)."""
        out = must(
            self.runner,
            ["gh", "api", "--paginate", "--slurp", endpoint],
            self.home,
            f"read {endpoint}",
        ).stdout
        return [
            item
            for page in json.loads(out or "[]")
            for item in (page.get(key, []) if key else page)
        ]

    def runs_of_pr(
        self,
        repo: str,
        number: int,
        head_ref: str,
        runs: list[dict[str, Any]],
        owners: dict[int, bool],
    ) -> list[dict[str, Any]]:
        """The `agent-review` check runs triggered by PR ``number``.

        Fail closed: a run whose workflow run cannot be read, or that names no
        PR of this one, is dropped.  ``owners`` caches decided runs only, so a
        failed read is retried on the next poll.
        """
        mine = []
        for run in runs:
            run_id = review_run_id(run) if run.get("name") == REVIEW_CHECK else None
            if run_id is None:
                continue
            if run_id not in owners:
                done = self.runner(
                    ["gh", "api", f"repos/{repo}/actions/runs/{run_id}"], self.home
                )
                try:
                    doc = json.loads(done.stdout) if done.returncode == 0 else None
                except ValueError:
                    doc = None
                if not isinstance(doc, dict):
                    continue
                owners[run_id] = workflow_run_is_of(doc, number, head_ref)
            if owners[run_id]:
                mine.append(run)
        return mine

    def review_gate(self, repo: str, number: int) -> dict[str, Any]:
        """Settle `agent-review` on the PR's exact head before it may be queued."""
        view = json.loads(
            must(
                self.runner,
                ["gh", "pr", "view", str(number), "--repo", repo]
                + ["--json", "headRefOid,headRefName"],
                self.home,
                "read PR head",
            ).stdout
        )
        head, head_ref = str(view["headRefOid"]), str(view["headRefName"])
        try:
            bots = review_bots(AGENT_REVIEW.read_text())
        except OSError as exc:
            raise DeliverError(f"cannot read {AGENT_REVIEW}: {exc}") from exc
        runs = f"repos/{repo}/commits/{head}/check-runs?check_name={REVIEW_CHECK}"
        seen: list[str | None] = [None]
        owners: dict[int, bool] = {}
        foreign = [0]

        def settled() -> str | None:
            # `neutral` only says the workflow stopped waiting (20 x 15s) for
            # the bot; the bot often reviews later and a new run posts the
            # real verdict, so only success/failure ends the wait.
            listed = self.gh_pages(f"{runs}&filter=all&per_page=100", "check_runs")
            mine = self.runs_of_pr(repo, number, head_ref, listed, owners)
            foreign[0] = sum(r.get("name") == REVIEW_CHECK for r in listed) - len(mine)
            seen[0] = review_verdict(mine)
            return seen[0] if seen[0] in ("success", "failure") else None

        no_review = (self.args.accept_no_review or "").strip()
        try:
            verdict = self.wait_for(f"{REVIEW_CHECK} on {head}", settled)
        except DeliverError as exc:
            if seen[0] is None and foreign[0]:
                raise DeliverError(
                    f"refusing to queue #{number}: {foreign[0]} {REVIEW_CHECK} "
                    f"run(s) on {head} belong to other PRs or could not be "
                    f"attributed to #{number} (a PR sharing this head), and none "
                    f"of #{number}'s own settled within {self.args.timeout}s"
                ) from exc
            if seen[0] != "neutral":
                raise
            if not no_review:
                raise DeliverError(
                    f"refusing to queue #{number}: {REVIEW_CHECK} on {head} never "
                    f"settled to success/failure within {self.args.timeout}s; "
                    f"'neutral' only means the workflow stopped waiting for "
                    f"{bots[0]}, not that it reviewed the head\nwait and re-run, "
                    "or pass --accept-no-review '<reason>'"
                ) from exc
            verdict = "neutral"
            self.say(f"accepted #{number} without an exact-head review ({no_review})")
        findings = review_findings(
            self.gh_pages(f"repos/{repo}/pulls/{number}/comments?per_page=100"),
            head,
            bots,
        )
        self.say(f"{REVIEW_CHECK} {verdict} on #{number} at {head}")
        problems = [f"{REVIEW_CHECK} failed on {head}"] if verdict == "failure" else []
        if findings:
            listed = "".join(
                f"\n  {f['where']}: {f['summary']} {f['url']}" for f in findings
            )
            problems.append(
                f"{len(findings)} inline review comment(s) on {head}:{listed}"
            )
        reason = (self.args.accept_review_findings or "").strip()
        if problems and not reason:
            raise DeliverError(
                f"refusing to queue #{number}: "
                + "; ".join(problems)
                + "\nfix and redeliver, or pass --accept-review-findings '<reason>'"
            )
        if problems:
            self.say(f"accepted for #{number} ({reason}): " + "; ".join(problems))
        return {
            "head": head,
            "verdict": verdict,
            "findings": findings,
            "accepted": reason if problems else None,
            "accepted_no_review": no_review if verdict == "neutral" else None,
        }

    def summary(
        self, branch: str, lane: str, number: int, result: str
    ) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "branch": branch,
            "lane": lane,
            "pr": number,
            "result": result,
            "log": self.log,
            **self.extra,
        }


# --- redeliver --------------------------------------------------------------


class Replacement:
    """Replace a published PR with a new lane built from a fixed worktree.

    Pushing review fixes onto a published PR makes its head differ from the
    sealed hand-back, which ``delivery.py queue`` refuses.  The fixes go on a
    new branch and are delivered as a new lane instead.  The published lane
    still owns its Scope, so it is abandoned before the new lane claims, with
    the generation and head read from the registry; once the new PR exists the
    old one is closed with a link to it, and its remote branch is deleted only
    while it is still the published head.  Every step re-reads its facts, so a
    rerun resumes where the last one stopped.  (``delivery.py abandon-pr`` does
    not fit: it refuses a PR whose head moved, and closes before the
    replacement exists.  Its other refusals are kept: see ``guard``.)
    """

    def __init__(self, delivery: Delivery, old_branch: str) -> None:
        self.d = delivery
        self.old = old_branch
        self.new_branch = ""
        self.old_number = 0

    def guard(self, repo: str) -> dict[str, Any]:
        """Refuse to retire an old PR that is held or already scheduled to merge.

        A hard hold lives on the PR (label or typed body block) and is cleared
        only by ``delivery.py reconcile-holds``; closing the PR would drop it.
        A PR with auto-merge or a merge-queue entry may merge under us.  Read
        fresh before each step that retires something, as ``abandon-pr`` does.
        """
        owner, _, name = repo.partition("/")
        out = must(
            self.d.runner,
            ["gh", "api", "graphql", "-f", f"query={PR_GUARD_QUERY}"]
            + ["-f", f"owner={owner}", "-f", f"name={name}"]
            + ["-F", f"number={self.old_number}"],
            self.d.home,
            "read the replaced PR",
        ).stdout
        node = json.loads(out)["data"]["repository"]["pullRequest"]
        labels = tuple(str(n.get("name")) for n in node["labels"]["nodes"])
        try:
            holds = parse_body_holds(str(node.get("body") or ""))
            holds |= pull_request_label_holds(SimpleNamespace(labels=labels))
        except PolicyViolation as exc:
            raise DeliverError(f"PR #{self.old_number}: {exc}") from exc
        if holds and node.get("state") == "OPEN":
            raise DeliverError(
                f"PR #{self.old_number} carries a hard hold "
                f"({', '.join(sorted(h.value for h in holds))}); replacing it would "
                "drop the hold: clear it with `delivery.py reconcile-holds` first"
            )
        if node.get("autoMergeRequest") or node.get("mergeQueueEntry"):
            raise DeliverError(
                f"PR #{self.old_number} is scheduled to merge (auto-merge or merge "
                "queue); dequeue it before replacing it"
            )
        if node.get("state") == "MERGED":
            raise DeliverError(f"PR #{self.old_number} merged; nothing to replace")
        return node

    def lane(self) -> dict[str, Any]:
        records = self.d.registry_records(self.old)
        if not records:
            raise DeliverError(f"no registry lane for {self.old}")
        record = records[-1]
        if record.get("status") not in ("published", "abandoned"):
            raise DeliverError(
                f"lane {self.old} is {record.get('status')!r}; "
                "redeliver replaces a published lane"
            )
        return record

    def run(self) -> dict[str, Any]:
        d = self.d
        if d.work.exists():
            self.new_branch = d.git("rev-parse", "--abbrev-ref", "HEAD")
        elif d.args.branch:
            self.new_branch = d.args.branch
        else:
            raise DeliverError(
                f"worktree {d.work} is gone; pass --new-branch to resume the replacement"
            )
        if self.new_branch == self.old:
            raise DeliverError(
                f"{self.old} is the published lane being replaced; commit the fix "
                "on a new branch (git switch -c <name>) and redeliver from there"
            )
        repo = d.gh_repo()
        record = self.lane()
        if d.args.lane and d.args.lane in (record.get("external_ids") or []):
            raise DeliverError(f"--lane {d.args.lane} is the replaced lane's id")
        pr = d.pull_request(repo, self.old)
        if pr is None:
            raise DeliverError(f"no PR for {self.old}; nothing to replace")
        if pr.get("state") == "MERGED":
            raise DeliverError(
                f"PR #{pr['number']} is already merged; nothing to replace"
            )
        self.old_number = int(pr["number"])
        self.guard(repo)
        d.before_claim = lambda: self.retire(repo)
        d.after_publish = lambda new: self.supersede(repo, new)
        return d.deliver()

    def retire(self, repo: str) -> dict[str, Any]:
        """Abandon the replaced lane with the registry's own CAS facts."""
        record = self.lane()
        if record.get("status") == "abandoned":
            return record
        self.guard(repo)  # the checks ran meanwhile; the PR may have moved on
        generation = record.get("claim_generation", 0)
        head = str(record.get("handed_back_sha") or "")
        if type(generation) is not int or generation < 0 or not SHA.fullmatch(head):
            raise DeliverError(
                f"lane {self.old} has no exact claim_generation/handed_back_sha "
                f"to abandon it with ({generation!r}, {head!r})"
            )
        path = str(record["path"]) if record.get("path") else None
        self.d.abandon(self.old, path, generation, head, "abandon the replaced lane")
        self.d.say(f"abandoned lane {self.old} (generation {generation}, head {head})")
        return record

    def supersede(self, repo: str, new: dict[str, Any]) -> None:
        """Close the replaced PR with a link to ``new``; drop its published branch."""
        record = self.retire(repo)  # a resumed run can start past the claim
        old = self.d.pull_request(repo, self.old)
        if old is not None and old.get("state") == "MERGED":
            # guard() only reads an OPEN PR; a merge during the redelivery
            # must stop here, before anything is closed or deleted.
            raise DeliverError(
                f"PR #{old['number']} merged while #{new['number']} was replacing "
                f"it; the old remote branch {self.old} was not deleted and "
                f"#{new['number']} is published: close it if the merged PR "
                "already carries the change"
            )
        if old is not None and old.get("state") == "OPEN":
            self.guard(repo)
            note = (
                f"Superseded by #{new['number']} ({new.get('url')}): the review "
                f"fixes were redelivered from `{self.new_branch}`; this PR's lane "
                "was abandoned by `ops/deliver.py redeliver`."
            )
            must(
                self.d.runner,
                ["gh", "pr", "close", str(old["number"]), "--repo", repo]
                + ["--comment", note],
                self.d.home,
                "close the replaced PR",
            )
            self.d.say(f"closed #{old['number']}, superseded by #{new['number']}")
        head = str(record.get("handed_back_sha") or "")
        self.d.extra["replaced"] = {
            "branch": self.old,
            "pr": old["number"] if old else None,
            "claim_generation": record.get("claim_generation", 0),
            "published_head": head,
            "remote_branch": self.drop_remote_branch(head),
        }

    def drop_remote_branch(self, head: str) -> str:
        """Delete the replaced branch on origin only while it is the published head."""
        out = self.d.git("ls-remote", "origin", f"refs/heads/{self.old}")
        remote = out.split()[0] if out else None
        if remote is None:
            return "absent"
        if remote != head or not SHA.fullmatch(head):
            kept = f"kept: at {remote}, not the published head {head}"
            self.d.say(f"remote {self.old} {kept}")
            return kept
        self.delete_remote_branch(head)
        self.d.say(f"deleted remote {self.old} at {head}")
        return "deleted"

    def delete_remote_branch(self, head: str) -> None:
        """The lease makes the delete a compare-and-swap on the remote ref."""
        self.d.git(
            "push",
            f"--force-with-lease=refs/heads/{self.old}:{head}",
            "origin",
            "--delete",
            self.old,
            stage="delete the replaced remote branch",
        )


def redeliver(
    args: argparse.Namespace,
    runner: Runner,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, Any]:
    lane_args = argparse.Namespace(**{**vars(args), "branch": args.new_branch})
    return Replacement(Delivery(lane_args, runner, sleep, clock), args.old_branch).run()


# --- gc ---------------------------------------------------------------------


def gc(
    args: argparse.Namespace, runner: Runner, lock: LockWait | None = None
) -> dict[str, Any]:
    canon = Path(
        must(
            runner, ["git", "rev-parse", "--show-toplevel"], None, "locate repo"
        ).stdout.strip()
    )
    repo = must(
        runner,
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        canon,
        "resolve repository",
    ).stdout.strip()
    data = json.loads(
        must(
            runner,
            [str(OPS / "worktree_registry.py"), "list", "--json"],
            canon,
            "read registry",
        ).stdout
    )
    records = data["records"] if isinstance(data, dict) else data
    retired, kept = [], []
    for rec in records:
        if rec.get("status") != "published" or Path(str(rec.get("path", ""))).exists():
            continue
        found = runner(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                str(rec["branch"]),
                "--state",
                "merged",
                "--json",
                "number",
                "-q",
                ".[0].number",
            ],
            canon,
        ).stdout.strip()
        if not found:
            kept.append(
                {
                    "branch": rec["branch"],
                    "why": "published, worktree gone, PR not merged",
                }
            )
            continue
        if args.dry_run:
            retired.append(
                {"branch": rec["branch"], "pr": int(found), "applied": False}
            )
            continue
        must(
            runner,
            [
                str(canon / "ops" / "delivery.py"),
                "--repo",
                str(canon),
                "cleanup-merged",
                "--pr",
                found,
            ],
            canon,
            "cleanup-merged",
            lock,
        )
        retired.append({"branch": rec["branch"], "pr": int(found), "applied": True})
    return {"schema": SCHEMA, "retired": retired, "kept": kept}


# --- cli --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument("--worktree", default=".", help="lane worktree (default: cwd)")
    options.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="LABEL=CMD",
        help="verification to run and record; repeatable",
    )
    options.add_argument(
        "--scope-from-diff",
        action="store_true",
        help=(
            "derive Scope (add/modify/delete) from the worktree's diff against "
            f"{TRUNK}; a new lane always does, this also refreshes the Scope of "
            "an already-adopted lane (e.g. an agent worktree) before hand-back"
        ),
    )
    options.add_argument("--lane", help="external id; derived from the branch when new")
    options.add_argument("--title", help="PR title; default is the last commit subject")
    options.add_argument(
        "--intent", help="lane intent; default is the last commit subject"
    )
    options.add_argument(
        "--thread-id",
        default="deliver-cli",
        help="owner thread id recorded on the claim",
    )
    options.add_argument(
        "--merge",
        action="store_true",
        help=(
            f"wait for {REVIEW_CHECK} on the exact head, then queue, wait for "
            "the merge, clean up and sync"
        ),
    )
    options.add_argument(
        "--accept-review-findings",
        metavar="REASON",
        help=(
            f"with --merge: queue although {REVIEW_CHECK} failed or the review "
            "bot left inline comments on the head; the reason is logged"
        ),
    )
    options.add_argument(
        "--accept-no-review",
        metavar="REASON",
        help=(
            f"with --merge: queue although {REVIEW_CHECK} only reached neutral "
            "(the bot never reviewed the head) by --timeout; the reason is logged"
        ),
    )
    options.add_argument(
        "--timeout", type=int, default=1500, help="seconds per wait (default 1500)"
    )
    options.add_argument(
        "--poll", type=int, default=30, help="seconds between polls (default 30)"
    )
    options.add_argument(
        "--lock-timeout",
        type=int,
        default=600,
        help=(
            "seconds a mutation keeps retrying while another delivery mutation "
            "holds the operation lock (default 600)"
        ),
    )
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[options],
    )
    parser.add_argument(
        "--branch", help="resume a published lane whose worktree is already gone"
    )
    sub = parser.add_subparsers(dest="command")
    clean = sub.add_parser("gc", help="retire published lanes whose PR already merged")
    clean.add_argument("--dry-run", action="store_true")
    again = sub.add_parser(
        "redeliver",
        parents=[options],
        help="replace a published PR with a new lane from a fixed worktree",
        description="Delivery options go after `redeliver`.",
    )
    again.add_argument(
        "--branch",
        dest="old_branch",
        required=True,
        help="branch of the published lane whose PR is replaced",
    )
    again.add_argument(
        "--new-branch", help="resume a replacement whose worktree is already gone"
    )
    return parser


def main(
    argv: list[str] | None = None,
    runner: Runner = run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "redeliver":
        # The subcommand re-declares every delivery option and its defaults
        # overwrite anything given before it; refuse instead of dropping it.
        raw = list(sys.argv[1:] if argv is None else argv)
        flags = {s for a in parser._actions for s in a.option_strings} - {
            "-h",
            "--help",
        }
        early = [t.split("=", 1)[0] for t in raw[: raw.index("redeliver")]]
        early = list(dict.fromkeys(t for t in early if t in flags))
        if early:
            parser.error(
                f"{', '.join(early)} must go after `redeliver`; "
                "options before it would be ignored"
            )
    try:
        if args.command == "gc":
            lock = LockWait(args.lock_timeout, sleep, clock, progress)
            result = gc(args, runner, lock)
        elif args.command == "redeliver":
            result = redeliver(args, runner, sleep, clock)
        else:
            result = Delivery(args, runner, sleep, clock).deliver()
    except DeliverError as exc:
        print(
            json.dumps({"schema": SCHEMA, "ok": False, "error": str(exc)}),
            file=sys.stdout,
        )
        print(f"deliver: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({**result, "ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
