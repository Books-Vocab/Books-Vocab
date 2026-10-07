#!/usr/bin/env -S uv run --python 3.13 python
"""Deliver one worktree branch through the official flow with a single command.

    ./ops/deliver.py --check "unit=uv run pytest -q" --merge

It only sequences the existing tools (`worktree_orchestrate.py`, `delivery.py`,
`gh`); it owns no state.  Where the lane stands is read back from the registry
and GitHub on every run, so a run that died halfway is simply run again.

Stages: checks -> adopt -> hand-back -> receipt -> publish -> wait-required ->
(with --merge) queue -> wait-merged -> cleanup -> sync-main.

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
from typing import Any

from lib import worktree_scope

SCHEMA = "kg.deliver.v1"
TRUNK = "origin/main"
OPS = Path(__file__).resolve().parent
PR_GATE = OPS.parent / ".github" / "workflows" / "pr-gate.yml"


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


def must(runner: Runner, cmd: list[str], cwd: Path | None, stage: str) -> Proc:
    done = runner(cmd, cwd)
    if done.returncode != 0:
        detail = failure_detail(done) or "no output"
        raise DeliverError(f"{stage} failed (rc={done.returncode}): {detail}")
    return done


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


def required_state(checks: list[dict[str, Any]]) -> str:
    states = [c.get("state") for c in checks if c.get("name") == "required"]
    if not states:
        return "PENDING"
    return str(states[0])


# --- stages -----------------------------------------------------------------


class Delivery:
    def __init__(
        self, args: argparse.Namespace, runner: Runner, sleep: Callable[[float], None]
    ):
        self.args = args
        self.runner = runner
        self.sleep = sleep
        self.work = Path(args.worktree).resolve()
        self.canon: Path | None = None
        self.log: list[str] = []

    @property
    def home(self) -> Path:
        """Where to run repo-wide commands: publish deletes the lane worktree mid-run."""
        return self.work if self.work.exists() else (self.canon or Path.cwd())

    def git(self, *argv: str, stage: str = "git") -> str:
        return must(self.runner, ["git", *argv], self.home, stage).stdout.strip()

    def say(self, message: str) -> None:
        self.log.append(message)
        print(f"deliver: {message}", file=sys.stderr, flush=True)

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

    def registry_record(self, branch: str) -> dict[str, Any] | None:
        out = must(
            self.runner,
            [str(OPS / "worktree_registry.py"), "list", "--json", "--branch", branch],
            self.home,
            "read registry",
        ).stdout
        data = json.loads(out)
        records = data["records"] if isinstance(data, dict) else data
        live = [
            r
            for r in records
            if r.get("branch") == branch and r.get("status") != "abandoned"
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
                f"branch is {behind} commit(s) behind {TRUNK} and does not rebase cleanly"
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
        listed = (done.stdout + done.stderr).strip()[-600:]
        fix = " ".join([*base, *files])
        raise DeliverError(
            "changed Python files are not formatted with the pr-gate's pinned ruff "
            f"(rc={done.returncode}):\n{listed}\nrun, commit, then re-run deliver:\n  {fix}"
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
        must(
            self.runner,
            [
                str(OPS / "worktree_orchestrate.py"),
                "resolve",
                "--branch",
                branch,
                "--path",
                str(self.work),
                "--status",
                "abandoned",
                "--expected-generation",
                str(record.get("claim_generation", 0)),
                "--expected-head-sha",
                str(sealed or head),
                "--json",
            ],
            self.work,
            "retire stale-base claim",
        )
        self.say(
            f"claim base {record.get('base_sha')} is not the fork point {fork}; "
            "claim retired, re-adopting"
        )
        return True

    def wait_for(self, what: str, probe: Callable[[], str | None]) -> str:
        deadline = time.monotonic() + self.args.timeout
        while True:
            result = probe()
            if result is not None:
                return result
            if time.monotonic() >= deadline:
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
                    must(
                        self.runner,
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
                    must(
                        self.runner,
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
                must(
                    self.runner,
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
        if stage == "receipt":
            must(
                self.runner,
                [*delivery, "receipt", "--lane", lane],
                self.home,
                "receipt",
            )
            title = self.args.title or self.git("log", "-1", "--format=%s")
            must(
                self.runner,
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
        if stage == "wait-required":
            self.wait_for("required check", lambda: self._required(repo, number))
            self.say(f"required passed on #{number}")
            if not self.args.merge:
                return self.summary(branch, lane, number, "ready-to-merge")
            must(
                self.runner,
                [*delivery, "queue", "--pr", str(number)],
                self.home,
                "queue",
            )
            self.say(f"queued #{number}")
            self.wait_for("merge", lambda: self._merged(repo, number))
            stage = "cleanup"
        if stage == "cleanup":
            # The worktree may be the very directory being retired; run from the canonical checkout.
            must(
                self.runner,
                [*delivery, "cleanup-merged", "--pr", str(number)],
                canon,
                "cleanup-merged",
            )
            must(self.runner, [*delivery, "sync-main"], canon, "sync-main")
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
        }


# --- gc ---------------------------------------------------------------------


def gc(args: argparse.Namespace, runner: Runner) -> dict[str, Any]:
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
        )
        retired.append({"branch": rec["branch"], "pr": int(found), "applied": True})
    return {"schema": SCHEMA, "retired": retired, "kept": kept}


# --- cli --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--worktree", default=".", help="lane worktree (default: cwd)")
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="LABEL=CMD",
        help="verification to run and record; repeatable",
    )
    parser.add_argument(
        "--branch", help="resume a published lane whose worktree is already gone"
    )
    parser.add_argument(
        "--scope-from-diff",
        action="store_true",
        help=(
            "derive Scope (add/modify/delete) from the worktree's diff against "
            f"{TRUNK}; a new lane always does, this also refreshes the Scope of "
            "an already-adopted lane (e.g. an agent worktree) before hand-back"
        ),
    )
    parser.add_argument("--lane", help="external id; derived from the branch when new")
    parser.add_argument("--title", help="PR title; default is the last commit subject")
    parser.add_argument(
        "--intent", help="lane intent; default is the last commit subject"
    )
    parser.add_argument(
        "--thread-id",
        default="deliver-cli",
        help="owner thread id recorded on the claim",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="queue, wait for the merge, clean up and sync",
    )
    parser.add_argument(
        "--timeout", type=int, default=1500, help="seconds per wait (default 1500)"
    )
    parser.add_argument(
        "--poll", type=int, default=30, help="seconds between polls (default 30)"
    )
    sub = parser.add_subparsers(dest="command")
    clean = sub.add_parser("gc", help="retire published lanes whose PR already merged")
    clean.add_argument("--dry-run", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    runner: Runner = run,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "gc":
            result = gc(args, runner)
        else:
            result = Delivery(args, runner, sleep).deliver()
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
