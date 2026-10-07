#!/usr/bin/env -S uv run --python 3.13 python
"""Deliver one worktree branch through the official flow with a single command.

    ./ops/deliver.py --check "unit=uv run pytest -q" --merge

It only sequences the existing tools (`worktree_orchestrate.py`, `delivery.py`,
`gh`); it owns no state.  Where the lane stands is read back from the registry
and GitHub on every run, so a run that died halfway is simply run again.

Stages: checks -> adopt -> hand-back -> receipt -> publish -> wait-required ->
(with --merge) queue -> wait-merged -> cleanup -> sync-main.

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

SCHEMA = "kg.deliver.v1"
TRUNK = "origin/main"
OPS = Path(__file__).resolve().parent
_OPERATIONS = {"A": "add", "M": "modify", "D": "delete", "T": "modify"}


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


def must(runner: Runner, cmd: list[str], cwd: Path | None, stage: str) -> Proc:
    done = runner(cmd, cwd)
    if done.returncode != 0:
        tail = (done.stderr.strip() or done.stdout.strip())[-400:]
        raise DeliverError(f"{stage} failed (rc={done.returncode}): {tail}")
    return done


# --- pure helpers -----------------------------------------------------------


def scope_from_name_status(text: str) -> dict[str, Any]:
    """`git diff --name-status` -> a kg.worktree.scope.v1 document.

    A rename is a delete of the old path plus an add of the new one, which is
    how Scope overlap has to see it.
    """
    files: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0][0]
        if code in "RC":
            if code == "R":
                files.append({"operation": "delete", "path": parts[1]})
            files.append({"operation": "add", "path": parts[2]})
        elif code in _OPERATIONS:
            files.append({"operation": _OPERATIONS[code], "path": parts[1]})
        else:
            raise DeliverError(
                f"unrecognised git status {parts[0]!r} for {parts[-1]!r}"
            )
    return {"schema": "kg.worktree.scope.v1", "files": files}


def lane_from_branch(branch: str, stamp: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", branch).strip("-").upper()
    return f"DIRECT-DELIVERY-{slug}-{stamp}"


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
        self.log: list[str] = []

    def git(self, *argv: str, stage: str = "git") -> str:
        return must(self.runner, ["git", *argv], self.work, stage).stdout.strip()

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
            self.work,
            "resolve repository",
        ).stdout.strip()

    def registry_record(self, branch: str) -> dict[str, Any] | None:
        out = must(
            self.runner,
            [str(OPS / "worktree_registry.py"), "list", "--json", "--branch", branch],
            self.work,
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
            self.work,
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
        branch = self.preflight()
        repo = self.gh_repo()
        canon = self.canonical()
        delivery = [str(canon / "ops" / "delivery.py"), "--repo", str(canon)]
        record = self.registry_record(branch)
        pr = self.pull_request(repo, branch)
        stage = next_stage(record, pr)
        lane = self.args.lane or (
            record["external_ids"][0] if record and record.get("external_ids") else None
        )
        lane = lane or lane_from_branch(branch, time.strftime("%Y%m%d", time.gmtime()))
        self.say(f"branch={branch} lane={lane} starts at {stage}")

        if stage in ("adopt", "hand-back", "receipt"):
            self.rebase_if_behind()
        if stage in ("adopt", "hand-back"):
            if not self.args.check:
                raise DeliverError(
                    "pass at least one --check: an outcome has to come from a command that ran"
                )
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
                if stage == "adopt":
                    intent = self.args.intent or self.git("log", "-1", "--format=%s")
                    must(
                        self.runner,
                        [
                            orchestrate,
                            "adopt",
                            "--worktree",
                            str(self.work),
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
                    self.work,
                    "hand-back",
                )
                self.say("handed back")
            stage = "receipt"
        if stage == "receipt":
            must(
                self.runner,
                [*delivery, "receipt", "--lane", lane],
                self.work,
                "receipt",
            )
            title = self.args.title or self.git("log", "-1", "--format=%s")
            must(
                self.runner,
                [*delivery, "publish", "--lane", lane, "--title", title],
                self.work,
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
                self.work,
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
            self.work,
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
            self.work,
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
