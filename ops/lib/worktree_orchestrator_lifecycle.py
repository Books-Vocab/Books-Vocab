"""Landing, catchup, repair, and teardown lifecycle for the orchestrator.

This seam owns the history-rewriting and worktree teardown paths.  It binds the shared
runtime namespace after import so the stable CLI and legacy private seams remain intact.
"""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import io
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from lib.exit_codes import EXIT_BLOCK, EXIT_OK, EXIT_TOOL_ERROR, EXIT_USAGE, EXIT_WARN  # noqa: E402

def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted lifecycle functions."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]

def _tool_mutation(argv: list[str], *, cwd: Path | str, label: str) -> tuple[int, str]:
    """Same visible-progress contract as `_git_mutation`, for a repo tool rather than
    git. Routed through the shared runner rather than a silent `capture_output` for
    the reason in `ops/lib/streaming_command.py`: an orchestrator subprocess that can
    take seconds must not be invisible."""
    try:
        proc = run_streamed_command(
            argv,
            cwd=cwd,
            label_key="mutation",
            label=label,
            progress_prefix="[worktree][mutation]",
            heartbeat_interval=20.0,
            capture_limit=64 * 1024,
            merge_stderr=True,
        )
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "")


# The store, and only the store. The generated view left version control (its own
# entry, IMP-20260807-b9526c): it is produced on demand by `backlog.py render` and
# is gitignored, so there is no longer a tracked derived file for the trunk to
# repair, for a rebase to conflict on, or for a separate derived artifact to be scoped to.
LEDGER_PATHS = ("docs/runbook/backlog",)
# A flat backstop, NOT "one per replayed commit" — the loop cannot see how many
# commits are being replayed, and a bound that claims to be derived from something
# it never reads is worse than an admitted constant. Its only job is to stop a loop
# that has stopped making progress; a rebase replaying more than this many
# conflicting commits is a situation for a human either way.
_MAX_REBASE_STEPS = 100


def _rebase_onto(worktree: str | Path, trunk: str, label: str) -> tuple[int, str]:
    """`git rebase <trunk>`. Returns (rc, output); rc != 0 means the caller aborts.

    Deliberately does NOT abort here — the two callers want different things after a
    failure (cutover aborts and refuses; catchup aborts and explains).

    It used to carry a conflict resolver: the rebase would conflict on the 280KB
    GENERATED ledger view (measured on a clone of the real repo, 3 to 6 branches out
    of ten in a single round), and since that file is a pure function of the store,
    "what should it say" had one right answer and no judgement in it — so the helper
    re-ran the generator and continued. That whole apparatus is gone with the file:
    the view is no longer tracked (IMP-20260807-b9526c), so a rebase cannot conflict
    on it. What remains is what should always have been true — a conflict here is a
    real decision, and it goes to a human.
    """
    return _git_mutation(["rebase", trunk], cwd=worktree, label=label)


def _ticket_is_abandoned(path: Path) -> bool:
    """Is this ticket's owner gone? Answered by the kernel, not by a pid.

    The owner holds an exclusive flock on its OWN ticket file for the whole time
    it is queued, so "abandoned" is simply "the flock is free" — and a flock is
    released by the kernel when the holder dies, which is the entire reason the
    registry uses one. An earlier version asked `os.kill(pid, 0)` instead. That
    was wrong twice over: pids are recycled, so a crashed lane's ticket could be
    kept alive forever by an unrelated process that inherited its number, which
    reintroduces one level down the exact "a file is not a lock" deadlock this
    eviction exists to prevent; and `kill(2)` treats non-positive pids as
    broadcasts (0 = the caller's process group, -1 = every reachable process),
    both of which SUCCEED, so a corrupt ticket carrying 0 read as permanently
    alive. The flock answers both without a special case.

    Failing to open or lock for any other reason returns False — an abandoned
    ticket that we merely could not read must not be evicted out from under a
    live owner. Callers hold `_land_lock`, so no live owner can enqueue mid-probe.
    """
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        wr.fcntl.flock(fd, wr.fcntl.LOCK_EX | wr.fcntl.LOCK_NB)
    except OSError:
        return False            # somebody holds it: the owner is alive
    else:
        wr.fcntl.flock(fd, wr.fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def _land_queue_dir(primary: Path) -> Path:
    return primary / ".cache" / "kg-land-queue"


def _land_lock(primary: Path):
    return wr._ledger_lock(_land_queue_dir(primary) / "seq")


def _land_tickets(qdir: Path) -> list[tuple[int, dict]]:
    """Live tickets, lowest sequence first.

    A ticket whose owner died is DELETED here, not skipped. Skipping would be the
    cheaper read, but the dead ticket would keep its place at the head forever and
    every later lane would wait behind a process that no longer exists — a queue
    that deadlocks on a crash is worse than no queue at all. Callers must hold
    `_land_lock`, since this mutates.
    """
    out: list[tuple[int, dict]] = []
    if not qdir.is_dir():
        return out
    for path in sorted(qdir.glob("*.json")):
        try:
            seq = int(path.stem)
            rec = json.loads(path.read_text())
        except (ValueError, OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        if _ticket_is_abandoned(path):
            path.unlink(missing_ok=True)
            continue
        out.append((seq, rec))
    out.sort(key=lambda t: t[0])
    return out


def _land_enqueue(primary: Path, worktree: str) -> tuple[int, int]:
    """Take a ticket and hold it. Returns (seq, fd).

    The fd is the ticket: the caller must keep it open for as long as it is
    queued, because the flock on it is what proves the lane is still alive. Close
    it — deliberately, or by dying — and the next `_land_tickets` sweep evicts the
    ticket. `pid` is still recorded, but only so a human reading the queue can see
    who is in it; nothing decides liveness from it.
    """
    qdir = _land_queue_dir(primary)
    qdir.mkdir(parents=True, exist_ok=True)
    with _land_lock(primary):
        live = _land_tickets(qdir)
        seq = (live[-1][0] + 1) if live else 1
        path = qdir / f"{seq:012d}.json"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        wr.fcntl.flock(fd, wr.fcntl.LOCK_EX | wr.fcntl.LOCK_NB)
        os.write(fd, json.dumps(
            {"pid": os.getpid(), "worktree": worktree}).encode())
        os.fsync(fd)
    return seq, fd


def _land_position(primary: Path, seq: int) -> tuple[int, dict | None]:
    """(position, ticket-ahead-of-us). 0 means it is our turn; -1 means our own
    ticket is gone, which can only happen if something evicted us."""
    with _land_lock(primary):
        live = _land_tickets(_land_queue_dir(primary))
    seqs = [s for s, _ in live]
    if seq not in seqs:
        return (-1, None)
    pos = seqs.index(seq)
    return (pos, live[0][1] if pos > 0 else None)


def _land_release(primary: Path, seq: int, fd: int | None = None) -> None:
    with _land_lock(primary):
        (_land_queue_dir(primary) / f"{seq:012d}.json").unlink(missing_ok=True)
    if fd is not None:
        try:
            os.close(fd)          # drops the flock; a dead lane gets this for free
        except OSError:
            pass


def _land_step(func, **kw) -> tuple[int, dict]:
    """Run one orchestrator subcommand in-process and capture its payload.

    In-process rather than a subprocess so the gate verdict is produced by exactly
    this orchestrator — `cutover` compares the judge's identity, and re-execing a
    different copy of the file is the failure that check exists to catch. stdout is
    captured because each step emits its own JSON envelope and `land` emits one of
    its own; two JSON documents on one stream is the pollution this repo already
    forbids operators from creating.
    """
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = func(argparse.Namespace(**kw))
    raw = buf.getvalue()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw[-2000:]}
    return rc, payload


def cmd_land(args) -> int:
    """Drive one worktree all the way onto the local trunk, taking a fair turn.

    Measured on a clone of this repo, ten concurrent worktrees each running the
    documented catchup/gate/cutover sequence: TWO landed. The other eight were
    refused with "worktree is behind main" — five at cutover, three before their
    gate would even run — because the trunk is single and the ff is linear, so
    whichever lane lands first makes every other lane stale. The remedy each
    refusal names (catch up, then gate again) races exactly the same way, so the
    recovery convoys instead of converging. At N=3 the same run landed 3 of 3 but
    still spent 6 gate runs to do it.

    Nothing there was unsafe: no ungated tree landed, the primary stayed clean, the
    ledger stayed consistent. The invariant held. What was missing was a verb whose
    meaning is "get me landed", so `land` is that verb.

    It works by widening the critical section. `cutover` serializes only the ff,
    which is enough to keep two lanes from interleaving but not enough to keep a
    lane's verdict fresh: the trunk can move between the gate and the lock. `land`
    holds the turn across catchup -> gate -> cutover, so the tree that is gated is
    the tree that lands, first try. N lanes cost N gate runs.

    Turns are FIFO rather than an flock because an flock is not fair, and the lane
    that loses a repeated race is the one with the slowest gate — in a mixed batch
    that is the iOS lane, i.e. the one that can least afford to run again.
    """
    blocked = _freeze_guard(args.state, "land", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
               "error": f"no such worktree: {worktree}"},
              args.json, f"✗ no such worktree: {worktree}")
        return EXIT_BLOCK
    delegated_records = _delegated_records_for_path(args.state, worktree)
    if delegated_records:
        record = delegated_records[0]
        _emit({
            "schema": SCHEMA, "step": "land", "mode": "refused",
            "error": "delegated worktree cannot land; the integrator owns landing",
            "refusal": "delegated", "delegated": True, "landed": False,
            "worktree": worktree, "branch": record.get("branch"),
        }, args.json,
        f"✗ land refused: delegated worktree {record.get('branch')} at {worktree}; "
        "the integrator owns landing")
        return EXIT_BLOCK
    primary = primary_root()

    if not args.commit:
        with _land_lock(primary):
            live = _land_tickets(_land_queue_dir(primary))
        _emit({"schema": SCHEMA, "step": "land", "mode": "dry-run", "landed": False,
               "worktree": worktree, "queue_depth": len(live),
               "would_run": ["catchup --commit", "gate", "cutover --commit"],
               "note": "takes a FIFO turn first; the whole sequence runs under it"},
              args.json,
              f"[dry-run] land {worktree}: queue depth {len(live)}; would take a turn "
              f"then run catchup --commit -> gate -> cutover --commit")
        return EXIT_OK

    seq, ticket_fd = _land_enqueue(primary, worktree)
    started = time.monotonic()
    common = {"state": args.state, "json": True, "base": args.base,
              "worktree": worktree}
    try:
        waited = 0.0
        last_beat = 0.0
        # The timeout measures LACK OF PROGRESS, not total wait. Total wait is the
        # wrong quantity: `land` holds the turn across the whole gate, so lane N
        # legitimately waits (N-1) x gate. With an iOS gate at "tens of minutes"
        # (cmd_gate's own words) a healthy lane 4 in a ten-lane batch would blow a
        # total-wait budget and be told a "stuck peer" was to blame — the tool
        # diagnosing a working queue as a broken one, in exactly the mixed batch
        # this verb was written for. A queue that keeps moving is healthy however
        # long your turn takes to arrive; a queue whose head has not changed is
        # not.
        last_pos = None
        progressed_at = time.monotonic()
        while True:
            pos, ahead = _land_position(primary, seq)
            if pos == -1:
                _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                       "error": "our queue ticket disappeared — the flock on it was "
                                "seen free, so this lane was judged dead; re-run "
                                "`land`",
                       "landed": False, "worktree": worktree},
                      args.json, "✗ land refused: queue ticket disappeared")
                return EXIT_BLOCK
            if pos == 0:
                break
            now = time.monotonic()
            waited = now - started
            if pos != last_pos:
                last_pos = pos
                progressed_at = now
            stalled = now - progressed_at
            if stalled >= args.queue_timeout:
                _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                       "error": f"the landing queue has not moved for {stalled:.0f}s "
                                f"(still position {pos} after waiting {waited:.0f}s) "
                                f"— the lane holding the turn is not making progress",
                       "landed": False, "position": pos, "ahead": ahead,
                       "stalled_s": round(stalled, 1),
                       "waited_s": round(waited, 1), "worktree": worktree},
                      args.json,
                      f"✗ land refused: queue stalled at position {pos} for "
                      f"{stalled:.0f}s")
                return EXIT_BLOCK
            if waited - last_beat >= 20:
                last_beat = waited
                print(f"[worktree][land] phase=waiting elapsed={waited:.0f}s "
                      f"position={pos} stalled={stalled:.0f}s "
                      f"aheadPid={(ahead or {}).get('pid')} alive=true",
                      file=sys.stderr, flush=True)
            time.sleep(0.4)

        # The CHEAP half of the primary-clean contract, asked before anything
        # expensive has been spent. `cutover` asks the same question again
        # immediately before the ff, and THAT one is the load-bearing check —
        # DO NOT DELETE IT as redundant. The two are at different moments and
        # answer different questions: this one asks "is the primary already dirty
        # right now", cutover's asks "is it still clean now that the gate has
        # finished". Measured 2026-08-08: a primary that was clean at the start was
        # dirtied DURING a 574s gate by the operator's own backlog closures, so an
        # implementation that trusted this answer across the gate would ff over a
        # tenant's uncommitted work.
        #
        # Same helper, not a second copy of the judgement: a duplicated rule is one
        # that drifts, and this one decides whether someone else's working tree gets
        # overwritten.
        # NOT `_current_branch(worktree)`: git discovery walks UP, so a directory
        # that has lost its `.git` answers with the ENCLOSING checkout's branch (i.e.
        # `main`), and cmd_land only checks that the path is a directory. That would
        # post an unattributable "blocked branch: main" notice — the exact thing
        # `_broadcast_cutover_block` calls worse than posting nothing.
        guard = _primary_ff_ready(primary, _local_trunk(args.base),
                                  branch=(_worktree_entry(worktree) or {}).get("branch"),
                                  worktree=worktree)
        if guard is not None:
            reason, extra = guard
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": reason, "landed": False, "worktree": worktree,
                   "primary": str(primary), "refused_before": "gate", **extra},
                  args.json, f"✗ land refused before gate: {reason}")
            return EXIT_BLOCK

        steps: list[dict] = []
        crc, cpay = _land_step(cmd_catchup, commit=True, **common)
        steps.append({"step": "catchup", "rc": crc, "payload": cpay})
        if crc != EXIT_OK:
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": "catchup refused; the branch could not be brought onto "
                            "the trunk", "landed": False, "steps": steps,
                   "worktree": worktree},
                  args.json, "✗ land refused at catchup")
            return EXIT_BLOCK

        grc, gpay = _land_step(cmd_gate, receipt_line=False, plan_only=False, **common)
        steps.append({"step": "gate", "rc": grc, "verdict": gpay.get("verdict"),
                      "payload": gpay})
        if gpay.get("verdict") not in ("pass", "warn"):
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": f"gate verdict is {gpay.get('verdict')!r} — fix the "
                            f"blocking gate(s), then run `land` again",
                   "landed": False, "steps": steps, "worktree": worktree},
                  args.json,
                  f"✗ land refused: gate verdict {gpay.get('verdict')!r}")
            return EXIT_BLOCK

        orc, opay = _land_step(cmd_cutover, commit=True, **common)
        steps.append({"step": "cutover", "rc": orc, "payload": opay})
        landed = bool(opay.get("landed"))
        # Two independent reports of the same fact. They can only disagree if the
        # payload did not parse (`_land_step` degrades it to {"raw": ...}, and a
        # missing "landed" then reads as False) — which would have `land` announce
        # a refusal AFTER the trunk already moved. Say so loudly instead of
        # picking whichever one is more comforting.
        if landed != (orc == EXIT_OK):
            payload_disagrees = (
                f"cutover exit code ({orc}) and its payload (landed={landed!r}) "
                f"disagree — trust neither; inspect local {args.base} before doing "
                f"anything else")
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": payload_disagrees, "landed": None,
                   "cutover_rc": orc, "cutover_payload": opay,
                   "worktree": worktree, "steps": steps},
                  args.json, f"✗ land: {payload_disagrees}")
            return EXIT_BLOCK
        total = time.monotonic() - started
        _emit({"schema": SCHEMA, "step": "land",
               "mode": "committed" if landed else "refused",
               "landed": landed, "worktree": worktree, "queue_seq": seq,
               "waited_for_turn_s": round(waited, 1),
               "elapsed_s": round(total, 1), "gate_runs": 1,
               "verdict": gpay.get("verdict"), "sha": opay.get("sha"),
               "warnings": opay.get("warnings", []), "steps": steps},
              args.json,
              (f"✓ landed {worktree} ({gpay.get('verdict')}) in {total:.0f}s "
               f"after waiting {waited:.0f}s for its turn"
               if landed else
               f"✗ land refused at cutover: {opay.get('error')}"))
        return EXIT_OK if landed else EXIT_BLOCK
    finally:
        _land_release(primary, seq, ticket_fd)


# ============================================================================
# integrate — N branches, ONE gate
# ============================================================================
def cmd_catchup(args) -> int:
    """Bring a worktree onto the current local trunk — the step `gate` and `cutover`
    both send you to when the trunk moved under the branch.

    It existed as a sentence before it existed as a command: both refusals used to
    say "run `git -C <path> rebase main`". Handing an agent raw git there is fine
    right up until the rebase conflicts — and what the agent then does is unbounded,
    which is why the remedy belongs to a verb the flow controls rather than to a
    sentence in an error message. The original argument was narrower (the rebase kept
    conflicting on a 280KB GENERATED ledger view, 3 to 6 branches out of ten in a
    single round, and that file had one right answer), and it no longer applies: the
    view left version control in IMP-20260807-b9526c and the resolver went with it.
    `_rebase_onto` is the authority on the behaviour; this is now a clean rebase and
    every conflict is a real decision that goes to a human.
    """
    # `freeze` is a stop-the-world lock for repo surgery — history rewrite, gc,
    # shared hooks. `catchup` REWRITES HISTORY (that is what a rebase is), so it
    # belongs on the blocked side with open/adopt/cutover/sync/deploy, not on the
    # draining side with resolve/sweep/gate. It was missed simply because it is the
    # newest primitive; a lock that a new verb can walk past is not a lock.
    blocked = _freeze_guard(args.state, "catchup", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    trunk = _local_trunk(args.base)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "refused",
               "error": f"no such worktree: {worktree}"},
              args.json, f"✗ no such worktree: {worktree}")
        return EXIT_BLOCK
    drift = _base_containment(worktree, trunk)
    if drift is None:
        # `mode` on every branch, including this one: it is the most common outcome
        # (agents run `catchup` speculatively), so a machine caller reading
        # payload["mode"] would KeyError precisely where nothing went wrong.
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "noop", "worktree": worktree,
               "trunk": trunk, "behind": False, "rebased": False,
               "sha": _head_sha(worktree)}, args.json,
              f"✓ already on top of {trunk} — nothing to catch up to")
        return EXIT_OK
    if drift.get("containment_error"):
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "refused",
               "error": _behind_base_refusal(worktree, trunk, drift), **drift},
              args.json, f"✗ catchup refused: {_behind_base_refusal(worktree, trunk, drift)}")
        return EXIT_BLOCK
    if not args.commit:
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "dry-run", "rebased": False,
               "worktree": worktree, "trunk": trunk, "behind": True, **drift}, args.json,
              f"# catchup (dry-run)\n  {worktree} is {drift['behind_commits']} commit(s) "
              f"behind {trunk}; {len(drift['base_changed_files'])} file(s) changed there\n"
              f"  would rebase onto {trunk} (--commit); a conflict aborts and comes "
              f"back to you\n  then re-run `gate`")
        return EXIT_OK

    before = _head_sha(worktree)
    rc, out = _rebase_onto(worktree, trunk, "catchup-rebase")
    if rc != 0:
        _git_mutation(["rebase", "--abort"], cwd=worktree, label="catchup-rebase-abort")
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "committed",
               "error": "rebase failed (aborted)", "detail": out, "rebased": False,
               "worktree": worktree, "trunk": trunk}, args.json,
              f"✗ rebase onto {trunk} failed (aborted):\n{out}")
        return EXIT_BLOCK
    sha = _head_sha(worktree)
    _emit({"schema": SCHEMA, "step": "catchup", "mode": "committed", "rebased": True,
           "worktree": worktree, "trunk": trunk,
           "sha": sha, "previous_sha": before}, args.json,
          f"✓ catchup: {worktree} rebased onto {trunk} ({before[:8]} -> {sha[:8]})"
          f"\n  HEAD moved, so any gate verdict is now stale — re-run `gate`")
    return EXIT_OK

_REPAIR_MESSAGE = (
    "ops: cutover 落地後重新推導 ledger 錨點\n\n"
    "rebase 在 gate 之後改寫了分支的 sha,所以 entry 的 fixed_by 在落地那一刻\n"
    "才指得到正確的 commit。這顆 commit 由 cutover 自己產生,內容全部是\n"
    "`backlog.py reanchor --docs --commit` 從既有資料重新推導的。"
)


def _ledger_dirty(primary: Path, paths: tuple[str, ...] = LEDGER_PATHS) -> tuple[int, str]:
    """Tracked-only dirtiness of the ledger paths.

    `--untracked-files=no` on purpose, matching `_primary_ff_ready`: an untracked
    entry JSON in the primary is a LEGAL and common state (an agent filed one and
    has not committed it), and it does not block anybody's cutover. Counting it as
    dirt is what led the repair to sweep other people's unfinished work into a
    commit that claimed every changed path was tool-derived.
    """
    return _git(["status", "--porcelain", "--untracked-files=no", "--", *paths],
                cwd=primary)


def _repair_restore(
    primary: Path, out: dict[str, Any], paths: tuple[str, ...] = LEDGER_PATHS,
) -> None:
    """Put the repair's tracked paths back to HEAD after failure, and VERIFY it.

    The one thing a failed repair must not do is leave the primary dirty: that is
    the exact condition `_primary_ff_ready` refuses on, so an abandoned repair does
    not fail one cutover, it fails EVERY later one — and it does so with a message
    pointing the next agent at "another session is working in the primary", which is
    not what happened. Measured before this existed: `render --commit` returned its
    own designed refusal (exit 2, entry-loss guard), the already-written `reanchor`
    edit was left behind, and the next cutover was blocked.

    `restored` is set from a RE-READ of git's status, not from the exit code of the
    restore command. The first version reported success from `checkout`'s rc while
    the tree was still dirty — `checkout HEAD -- <dir>` is a silent no-op for a path
    that is staged-new and absent from HEAD. Asserting the property instead of the
    command is the only version that cannot drift away from what it claims.

    `reset` then `checkout HEAD --` is belt AND braces, and measurably redundant
    today: with the reset first, the plain `checkout --` form restores from an index
    that already matches HEAD, so the two are equivalent — a mutation swapping them
    survives every test, correctly. The pair is kept because each covers the other's
    failure mode if a staging step ever returns to this function, and because the
    re-read below is what actually decides the verdict either way.

    Untracked files under these paths are deliberately NOT touched: they are someone
    else's unfinished work, and this function's job is to undo its own edits.  The
    default set is the ledger; a successful/failed docs reanchor extends it with the
    exact markdown paths reported by the child command.
    """
    _git(["reset", "-q", "--", *paths], cwd=primary)
    _git(["checkout", "HEAD", "--", *paths], cwd=primary)
    rc, dirty = _ledger_dirty(primary, paths)
    out["restored"] = rc == 0 and not dirty.strip()
    if not out["restored"]:
        out["error"] = (f"{out.get('error', '?')} | AND the primary could not be "
                        f"restored ({dirty.strip()[:200]}) — it is dirty and the next "
                        f"cutover will refuse until you clean docs/runbook by hand")


ANCHOR_QUEUE = ".cache/backlog_anchor_queue.jsonl"


def _anchor_queue(primary: Path) -> Path:
    return Path(primary) / ANCHOR_QUEUE


def _read_anchor_queue(primary: Path) -> list[dict[str, Any]]:
    path = _anchor_queue(primary)
    if not path.exists():
        return []
    try:
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except (OSError, json.JSONDecodeError):
        # Never fatal HERE: a landing that already happened must not be reported as
        # failed because this per-machine sidecar was unreadable.
        #
        # But be honest about what that costs. `backlog.py anchor` is the other
        # reader and it fails LOUD on the same file (BacklogError naming the line),
        # so an unreadable queue is silent through cutover and resolve and only
        # surfaces at wave end. The rows do not "stay unstamped and get reported" —
        # from here they are invisible, so nothing reports them at all. That is the
        # right direction for a step that has already moved the trunk and the wrong
        # one for a step that has not, which is why the two policies differ.
        return []


def _write_atomic(path: Path, body: str) -> None:
    """Same shape as `worktree_registry.save_state`: sibling temp then `os.replace`,
    so a crash mid-write cannot leave a half-line. Local rather than imported because
    that one also serializes the ledger's dict; this writes jsonl text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _stamp_anchor_queue(primary: Path, branch: str, sha: str) -> list[str]:
    """Record which commit actually reached the trunk, for this branch's rows.

    A hunter stages its closure BEFORE the branch is rebased, so it cannot know
    which commit will carry the fix — writing the pre-rebase sha is precisely the
    orphaned `fixed_by` the reanchor repair exists to clean up afterwards. This is
    the first moment the answer exists.

    Called AFTER every post-ff refusal. `make_commit_state` accepts a sha reachable
    from HEAD *or* main, so a sha written by a cutover that was then refused would
    still validate when anchored from a worktree that has not been torn down — the
    entry would close against a commit on no trunk, and nothing downstream would
    complain. Placing this earlier looks harmless for exactly that reason.

    Under the queue lock, and the loss it prevents is worse here than at `stage`.
    Measured with the window widened (the method this repo's `_view_lock` docstring
    already uses), in BOTH orders — a concurrent `stage` straddling this write drops
    the stamp back to null, while cutover still reports `staged_closures: [IMP-…]`
    and prints it. By then the branch is in the trunk and `resolve` has torn the
    worktree down; this function only ever runs during that branch's cutover, so
    the sha is never re-derived. `anchor` then files the row under "its branch has
    not landed", which is false, and the only copy of the answer was in a payload
    nobody kept. So: same lock as `stage`, and `_write_atomic` rather than
    `write_text`, whose partial write would leave a truncated line that
    `_read_anchor_queue` swallows and `anchor` chokes on.
    """
    queue = _anchor_queue(primary)
    with wr._ledger_lock(queue):
        rows = _read_anchor_queue(primary)
        stamped = []
        for row in rows:
            if row.get("branch") == branch and not row.get("landed_sha"):
                row["landed_sha"] = sha
                stamped.append(row.get("id"))
        if stamped:
            try:
                _write_atomic(
                    queue,
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            except OSError:
                return []
        return stamped


def _post_landing_repair(primary: Path) -> dict[str, Any]:
    """Re-derive what the rebase invalidated, in the checkout that now holds it.

    `cutover` rebases the branch onto the current trunk and then fast-forwards. That
    rebase runs AFTER the gate — the last thing to check the tree runs before the last
    thing to change it — so `fixed_by` shas written on the branch are rewritten by the
    rebase and become `fixed-by-orphaned` (measured: validate 0 problems -> 1).
    `reanchor` maps them back by `git patch-id --stable`, and refuses to guess when it
    cannot. That is not repairable from the branch: the correct sha does not exist
    until the landing has happened.

    The repair now also covers document `verified_against` anchors. The generated
    markdown view is no longer tracked, so there is no second render step; only
    the ledger files and the exact documents reported by `reanchor --docs` enter
    the repair commit.

    Committed, not left in the tree: an uncommitted repair merely relocates the
    failure to the next `cutover`, which refuses on a dirty primary. And if any step
    fails, the tree is put BACK — see `_repair_restore`.

    It never fails the cutover. The landing already happened; reporting a repair
    problem loudly is honest, rolling back a completed ff is not.
    """
    tool = Path(primary) / "ops" / "backlog.py"
    out: dict[str, Any] = {"ran": False, "committed": False, "steps": [], "ok": True}
    if not tool.exists():
        out["reason"] = "no ledger tool in this checkout"
        return out
    out["ran"] = True
    # `reanchor` is the single repair primitive. The rebase inside cutover rewrites
    # the branch's commit shas, which can orphan both `fixed_by` and
    # `verified_against` anchors. Ask for JSON so the exact document paths it
    # rewrote can join the same tracked path set as the backlog ledger.
    repair_paths = list(LEDGER_PATHS)
    for sub, label in (("reanchor", "ledger-reanchor"),):
        argv = [sys.executable, str(tool), sub, "--docs", "--commit", "--json"]
        rc, text = _tool_mutation(argv,
                                  cwd=primary, label=label)
        payload = {}
        for line in reversed((text or "").splitlines()):
            try:
                candidate = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        # A successful reanchor reports `doc_landed`; a failed transactional
        # reanchor reports the complete planned set as `doc_paths` after it has
        # rolled back.  Keep both paths in the restore set: the latter is the
        # only machine-readable way to recover an arbitrary document when the
        # child command exits before its success payload.
        doc_paths = payload.get("doc_landed") or payload.get("doc_paths") or []
        if not doc_paths:
            doc_paths = [item.get("path") for item in payload.get("doc_plan", [])
                         if isinstance(item, dict) and item.get("path")]
        for path in doc_paths:
            if isinstance(path, str) and path not in repair_paths:
                repair_paths.append(path)
        out["repair_paths"] = repair_paths
        out["steps"].append({"step": sub, "rc": rc})
        if rc != 0:
            out["ok"] = False
            out["error"] = f"{sub} exited {rc}: {text.strip()[:300]}"
            _repair_restore(primary, out, tuple(repair_paths))
            return out
    rc, dirty = _ledger_dirty(primary, tuple(repair_paths))
    if rc != 0:
        out["ok"] = False
        out["error"] = "could not read the primary's status after the repair"
        return out
    if not dirty.strip():
        return out
    # NO `git add`, and a pathspec on the commit. Both matter, and the reason is the
    # same: `git commit -- <paths>` takes the working-tree content of the TRACKED
    # files under those paths and nothing else. A `git add -- docs/runbook/backlog`
    # also stages untracked entry JSONs, which is precisely how a co-tenant's
    # uncommitted filing got swept into a commit whose message claimed "everything here
    # was re-derived by a tool" even though it also contained that filing.
    # Measured: the repair commit contained COTENANT.json; without the add, it
    # contains only the file `reanchor` actually rewrote.
    crc, ctext = _git_mutation(["commit", "-m", _REPAIR_MESSAGE, "--", *repair_paths],
                               cwd=primary, label="ledger-repair-commit")
    if crc != 0:
        out["ok"] = False
        out["error"] = f"repair commit failed: {ctext.strip()[:300]}"
        _repair_restore(primary, out, tuple(repair_paths))
        return out
    out["committed"] = True
    # The repair rewrote ledger data on the trunk and no gate has looked at the
    # result — the gate ran on the branch, before the rebase that made the repair
    # necessary. So the repair checks its own work; a mis-anchored `fixed_by` landing
    # silently would be handed to whichever branch cuts over next.
    vrc, vtext = _tool_mutation(
        [sys.executable, str(tool), "validate", "--baseline-check"],
        cwd=primary, label="ledger-validate")
    out["steps"].append({"step": "validate", "rc": vrc})
    if vrc != 0:
        out["ok"] = False
        out["error"] = ("the repair landed but `validate --baseline-check` is red on "
                        f"the result: {vtext.strip()[:300]}")
    return out


def _active_ledger_records(state: str | None, branch: str) -> list[dict[str, Any]]:
    """Active ledger records naming this BRANCH. Read-only — the write is still the
    registry's own `resolve`.

    Deliberately not "…or this path", unlike the registry's own resolve selector: the
    question a teardown asks is "does an authority vouch for deleting THIS BRANCH",
    and a record that merely proves the path is registered answers a different one.
    Matching on path lets a worktree's own registration vouch for deleting an
    unrelated branch named on the command line."""
    path = Path(state).resolve() if state else wr.default_state_path()
    try:
        data = wr.load_state(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return [r for r in data.get("records", [])
            if r.get("status") == wr.STATUS_ACTIVE and r.get("branch") == branch]


def _ledger_branches_for_path(state: str | None, worktree: str) -> list[str]:
    """Every branch the ledger has ever recorded at this path, any status.

    Status-blind on purpose: this is a DERIVATION source of last resort, not an
    authorisation. It covers the states where git's admin entry is gone but the
    path is still real — `worktree remove` erroring partway drops the entry anyway,
    and any `git worktree prune` in the repo (including one issued for an unrelated
    worktree) removes it. Without this the operator's only recourse would be to
    hand-type --branch, which is the guess this change exists to eliminate."""
    path = Path(state).resolve() if state else wr.default_state_path()
    try:
        data = wr.load_state(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    target = _norm(worktree)
    seen: list[str] = []
    for r in data.get("records", []):
        if r.get("path") and _norm(r["path"]) == target and r.get("branch"):
            if r["branch"] not in seen:
                seen.append(r["branch"])
    return seen


def _delegated_records_for_path(state: str | None, worktree: str) -> list[dict[str, Any]]:
    """Return active delegated records for a normalized worktree path.

    Ledger read failures are treated as no delegation marker: this helper is an
    authority lookup, not a second registry parser, and cutover's other guards still
    fail closed on stale or untrusted worktree state.
    """
    path = Path(state).resolve() if state else wr.default_state_path()
    try:
        data = wr.load_state(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    target = _norm(worktree)
    return [
        r for r in data.get("records", [])
        if r.get("status") == wr.STATUS_ACTIVE
        and r.get("delegated") is True
        and r.get("path")
        and _norm(r["path"]) == target
    ]


def _protected_branches(base: str, target: str | None) -> tuple[str | None, set[str]]:
    """The registry's protected set, widened by terms that do NOT depend on `--base`.

    `wr.sweep_guards` derives everything from `--base` plus the primary's current
    checkout, so `--base origin/prod` while the primary sits on some other branch
    leaves `main` unprotected — and a resolve then deletes local `main` outright.
    Measured, not hypothesised. A floor that a caller-supplied flag can lower is not
    a floor, so three base-independent terms are added:

      * the local trunk (`BASE_DEFAULT`) — in this repo's local-main-centric topology
        deleting it is never a legitimate outcome, whatever `--base` says;
      * the remote's default branch, read from `origin/HEAD`;
      * every branch checked out in any OTHER worktree — which internalises a refusal
        we were previously outsourcing to git ("cannot delete branch used by worktree
        at …"). The target's own branch is excluded because removing its worktree
        first is exactly how a legitimate teardown frees it."""
    primary_path, protected = wr.sweep_guards(base)
    protected.add(BASE_DEFAULT)
    rc, ref = _git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
                   cwd=primary_root())
    if rc == 0 and ref:
        protected.add(ref.rsplit("/", 1)[-1])
    norm_target = _norm(target) if target else None
    for w in wr._worktrees():
        if w.get("branch") and _norm(w["path"]) != norm_target:
            protected.add(w["branch"])
    return primary_path, protected


def _rm_target_vetted(worktree: str, state: str | None) -> bool:
    """Whether this path may be handed to a recursive delete.

    `git worktree remove` validates before deleting — that validation is why the
    incident's re-run got rc=128 instead of destroying anything. A raw recursive
    delete has none, and git will list an ADOPTED worktree at an arbitrary path
    anywhere on the filesystem. So the target must either live under this repo's
    worktree root, or be a path the ledger itself recorded."""
    root = _norm(str(primary_root() / ".claude" / "worktrees"))
    if _norm(worktree).startswith(root + os.sep):
        return True
    return bool(_ledger_branches_for_path(state, worktree))


# Refusal codes, and the exit status each carries. Misuse ("you pointed me at the
# wrong thing") stays EXIT_USAGE; a safety refusal ("what you asked for is not a
# legitimate outcome") is EXIT_BLOCK. Emitted as `reason_code` beside the prose so a
# caller can switch on the decision instead of grepping a sentence that will be
# reworded.
RESOLVE_REFUSALS = {
    "not-a-worktree": EXIT_USAGE,
    "detached-head": EXIT_USAGE,
    "ambiguous-ledger": EXIT_USAGE,
    "protected-branch": EXIT_BLOCK,
    "primary-worktree": EXIT_BLOCK,
    "branch-contradicts-git": EXIT_BLOCK,
    "uncorroborated-branch": EXIT_BLOCK,
    "integration-ref-unresolvable": EXIT_BLOCK,
    "integration-ref-not-landed": EXIT_BLOCK,
    "integration-sources-active": EXIT_BLOCK,
    "rm-target-unvetted": EXIT_BLOCK,
    "unsafe-step": EXIT_BLOCK,
}


def _resolve_target(worktree: str, explicit: str | None, base: str, state: str | None
                    ) -> tuple[str | None, dict[str, Any] | None, str | None, str | None]:
    """(branch, git worktree entry, refusal code, reason) — the single chokepoint
    every teardown target passes through. NEVER falls back to the invoking cwd's HEAD.

    The protected set comes from the registry's own `sweep_guards`, which already
    owns the invariant "the base branch and the primary worktree are never torn
    down". Sweep consulted it; resolve did not, which is how a mis-derived branch
    reached `branch -D main` and `push origin --delete main` with nothing but git's
    external refusals in the way (IMP-20260806-1359bd)."""
    entry = _worktree_entry(worktree)
    # git CONTRADICTING the caller is categorically worse than git having nothing to
    # say, and the two must not collapse into one condition. When they do, a ledger
    # record belonging to a DIFFERENT worktree can vouch for the branch named here:
    # `resolve --worktree <alpha> --branch <bravo's branch>` then tears down alpha
    # and deletes bravo's remote branch, with only git's "cannot delete branch used
    # by worktree at …" standing in the way of the local half. No ledger record from
    # elsewhere may override git's direct statement about THIS path.
    if entry is not None and explicit and entry.get("branch") \
            and entry["branch"] != explicit:
        return None, entry, "branch-contradicts-git", (
            f"git says {worktree} is on {entry['branch']!r}, not {explicit!r} — "
            "refusing to tear down one worktree while deleting another's branch. "
            "Drop --branch to target what git names.")
    branch = explicit
    if not branch:
        if entry is not None:
            if entry.get("detached") or not entry.get("branch"):
                return None, entry, "detached-head", (
                    f"{worktree} has a detached HEAD — there is no branch to resolve; "
                    "pass --branch to name one explicitly")
            branch = entry["branch"]
        else:
            # git no longer lists the path; fall back to what the ledger recorded FOR
            # THIS PATH. Never to `rev-parse`, whose answer here is the enclosing
            # checkout's branch.
            candidates = _ledger_branches_for_path(state, worktree)
            if len(candidates) == 1:
                branch = candidates[0]
            elif len(candidates) > 1:
                return None, None, "ambiguous-ledger", (
                    f"the ledger records more than one branch at {worktree} "
                    f"({', '.join(candidates)}) — pass --branch to disambiguate")
            else:
                return None, None, "not-a-worktree", (
                    f"{worktree} is not a git worktree and the ledger has never "
                    "recorded one there — refusing to guess its branch, because "
                    "asking a directory for its HEAD answers with the ENCLOSING "
                    "checkout's branch (the primary's, for anything under the repo). "
                    "Pass --branch to name the target explicitly.")

    primary_path, protected = _protected_branches(base, worktree)
    if primary_path is None:
        # A real repo always lists at least the primary worktree. An empty list means
        # the probe failed, and `sweep_guards` cannot distinguish that from "nothing
        # is protected" — so treat it as unknown and fail closed rather than tear
        # down against an empty protected set.
        return None, entry, "not-a-worktree", (
            "cannot enumerate this repository's worktrees — refusing to tear anything "
            "down while the protected set is unknown")
    if branch in protected:
        return None, entry, "protected-branch", (
            f"branch {branch!r} is protected — it is the base branch or the primary "
            "worktree's checked-out branch, and deleting it is never a resolve "
            "outcome (registry sweep_guards)")
    if _norm(worktree) == primary_path:
        return None, entry, "primary-worktree", (
            f"{worktree} is the PRIMARY worktree — removing it destroys the repository")
    return branch, entry, None, None


def _entry_is_closed(root: Path, entry_id: str) -> bool:
    """Is this ticket already resolved in the store? Plain file read, fail-open.

    The queue is NOT sufficient on its own, and this function is here because the
    guard it feeds false-positived on its first real teardown. The documented order
    is stage -> cutover -> resolve -> (wave end) anchor, and under that order the
    row is still queued when `resolve` looks. But anchoring BEFORE resolving is
    equally legitimate — and `anchor --commit` DRAINS the queue, so the row that
    proved the closure is gone by the time the guard runs. Measured: the very
    teardown that landed this guard reported its own correctly-closed ticket.

    A warning that fires on a normal path is a warning that gets switched off, and
    it would have taken the real signal with it.

    Read directly rather than through `backlog.py`: this module is deliberately
    dependency-free (the bootstrap paradox — it has to run in a checkout too old to
    have the rest of the toolchain), and it already treats the store as paths under
    `LEDGER_PATHS`. Fail-OPEN — an unreadable entry yields False, i.e. "still open",
    so the guard speaks up rather than going quiet on a file it could not check.
    """
    path = Path(root) / "docs" / "runbook" / "backlog" / f"{entry_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status") in (
            "fixed", "wont-fix")
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def _claimed_tickets(state: str | None, branch: str) -> list[str]:
    """Tickets the ACTIVE ledger record for `branch` claims. Read-only, fail-soft.

    Goes through the registry's own `list --json` rather than reaching into the
    state file: the ledger's location is derived (git-common-dir anchored) and its
    schema belongs to that module. A second hand-rolled reader here is how the two
    drift — this repo has already paid for a hand-copied lock path that watched the
    wrong file and reported FREE unconditionally.
    """
    rc, out = _registry(["list", *_state_arg(state), "--json"])
    if rc != 0 or not isinstance(out, dict):
        return []
    for rec in out.get("records", []):
        if isinstance(rec, dict) and rec.get("branch") == branch \
                and rec.get("status") == "active":
            return [str(t) for t in (rec.get("backlog") or [])]
    return []


def _close_registry_for_teardown(
    state: str | None, branch: str,
) -> tuple[list[str], list[str], int, dict[str, Any]]:
    """Atomically recheck integration dependencies and close the target record.

    The earlier read-only guard makes dry-run useful, but it cannot authorize a
    destructive commit: a source reservation can appear after that read. This is
    the linearization point shared with `claim_integration_sources`. Once this
    returns success, the integration record is terminal, and new source claims
    reject it as an owner before any git path is removed.
    """
    state_path = Path(state).resolve() if state else wr.default_state_path()
    with wr._ledger_lock(state_path):
        ledger = wr.load_state(state_path)
        active = [r for r in ledger.get("records") or []
                  if r.get("status") == wr.STATUS_ACTIVE]
        owned = sorted(
            str(r.get("branch")) for r in active
            if (r.get("integration_owner") or {}).get("branch") == branch
        )
        if owned:
            return owned, [], EXIT_BLOCK, {"reason": "integration sources active"}
        targets = [r for r in active if r.get("branch") == branch]
        claimed = sorted({str(ticket) for r in targets
                          for ticket in (r.get("backlog") or [])})
        if not targets:
            # Idempotent retry after ledger closure but before git teardown finished.
            return [], claimed, EXIT_OK, {"action": "already-closed"}
        ns = argparse.Namespace(
            state=str(state_path), at=None, branch=branch, path=None,
            status="merged", json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wr.cmd_resolve(ns)
        try:
            payload = json.loads(buf.getvalue())
        except json.JSONDecodeError:
            payload = {"reason": "registry returned unreadable resolve output"}
        return [], claimed, rc, payload


AUDIT_SEARCH_DEPTH = 2000


def _patch_id_index(ref: str, depth: int) -> dict[str, str]:
    """patch-id -> commit sha, for the last `depth` commits reachable from `ref`.

    One `git log -p | git patch-id` pass rather than two processes per commit:
    at depth 2000 the per-commit form takes minutes, and a check nobody is willing
    to wait for is a check that gets skipped.
    """
    proc = subprocess.run(
        f"git log -p --no-color --max-count={int(depth)} {shlex.quote(ref)} "
        f"| git patch-id --stable",
        shell=True, cwd=str(primary_root()), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    index: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            index.setdefault(parts[0], parts[1])
    return index


def _subject_file_index(ref: str, depth: int) -> dict[str, list[tuple[str, frozenset]]]:
    """subject -> [(sha, files)], the weaker match's raw material."""
    rc, out = _git(["log", f"--max-count={int(depth)}", "--name-only",
                    "--format=%x01%H%x00%s", ref])
    index: dict[str, list[tuple[str, frozenset]]] = {}
    if rc != 0:
        return index
    for block in out.split("\x01"):
        if not block.strip():
            continue
        head, _, body = block.partition("\n")
        sha, _, subject = head.partition("\x00")
        files = frozenset(ln for ln in body.splitlines() if ln.strip())
        index.setdefault(subject, []).append((sha, files))
    return index


def _commit_patch_id(sha: str) -> str | None:
    proc = subprocess.run(
        f"git show {shlex.quote(sha)} | git patch-id --stable", shell=True,
        cwd=str(primary_root()), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    parts = proc.stdout.split()
    return parts[0] if parts else None


def _audit_integrated(branch: str, base: str,
                      depth: int = AUDIT_SEARCH_DEPTH) -> dict:
    """Did every commit unique to `branch` reach `base`, and on what evidence?

    This is the three-step audit `.claude/skills/worktree-flow/SKILL.md` prescribes
    for a batch-integrated branch, executed by the tool instead of by a person.

    Why it is needed: `resolve`'s landed-floor asks "is this branch's net change in
    base", by tree-diff. After a batch integration the answer is legitimately NO —
    conflict resolution left base holding a NEWER version than the branch — and that
    is byte-for-byte indistinguishable from "this work never landed". Measured with
    `ops/worktree_loadtest.py --mode batch -n 10 --conflict shared`: **10 of 10**
    source branches refuse teardown. Every one of them needs the same audit, and all
    three of its steps are mechanical.

    Why not simply loosen the floor: a rule permissive enough to pass this case also
    passes work that never landed at all, and that refusal has already caught one
    commit dropped during an integration. So this is a SECOND door, and it reports
    which comparison opened it — a branch that got through on the weaker match is
    visible as such, rather than being indistinguishable from a strong one.

    Two comparisons, strongest first:

      patch-id      the same change under a different sha (a clean cherry-pick)
      subject+files the same message AND exactly the same set of paths — the case
                    where integration edited the content while merging. Subject
                    alone is NOT accepted: two commits can share a message and touch
                    unrelated files, which is the shape that would wave through a
                    branch nobody integrated.
    """
    rc, out = _git(["rev-list", "--reverse", f"{base}..{branch}"])
    if rc != 0:
        return {"ok": False, "error": f"cannot list {base}..{branch}", "commits": []}
    shas = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not shas:
        # Nothing unique to the branch: it is an ancestor of base. The floor would
        # not have refused, so getting here means the caller asked anyway.
        return {"ok": True, "commits": [], "base": base, "searched": 0}

    by_patch = _patch_id_index(base, depth)
    by_subject = _subject_file_index(base, depth)

    results = []
    for sha in shas:
        _, subject = _git(["log", "-1", "--format=%s", sha])
        subject = subject.strip()
        _, names = _git(["show", "--name-only", "--format=", sha])
        files = frozenset(ln.strip() for ln in names.splitlines() if ln.strip())
        match, matched = None, None
        pid = _commit_patch_id(sha)
        if pid and pid in by_patch:
            match, matched = "patch-id", by_patch[pid]
        else:
            for cand_sha, cand_files in by_subject.get(subject, []):
                if cand_files == files and files:
                    match, matched = "subject+files", cand_sha
                    break
        results.append({"sha": sha[:9], "subject": subject, "match": match,
                        "matched_sha": (matched or "")[:9] or None,
                        "files": sorted(files)[:8]})
    return {"ok": all(r["match"] for r in results), "commits": results,
            "base": base, "searched": min(depth, len(by_patch))}


def cmd_resolve(args: argparse.Namespace) -> int:
    """Landed-floor guard, then registry resolve merged → worktree remove + branch -D
    (local + remote) + drop the gate-record cache."""
    worktree = _norm(args.worktree)

    def _refuse(code: str, reason: str, **extra: Any) -> int:
        _emit({"schema": SCHEMA, "step": "resolve", "error": "refused",
               "reason_code": code, "reason": reason, "branch": extra.pop("branch", None),
               "worktree": worktree, **extra},
              args.json, f"✗ resolve refused [{code}]: {reason}")
        return RESOLVE_REFUSALS[code]

    branch, entry, code, reason = _resolve_target(worktree, args.branch, args.base,
                                                  args.state)
    if code:
        return _refuse(code, reason, branch=args.branch)

    # CORROBORATION: the target must be vouched for by at least one authority — git's
    # worktree list, or an active ledger record. In the incident neither named it:
    # the list did not map that path to `main`, and the ledger said "no active record
    # for branch=main" — which the tool PRINTED and then ignored. Requiring only ONE
    # of the two is deliberate: after an interrupted teardown the ledger is already
    # closed (it is struck before the git steps), so a ledger-AND rule would strand
    # every re-run, and the whole point of that re-run is to finish the job.
    #
    # Note this refusal deliberately does NOT tell the operator to run `adopt`: adopt
    # resolves its target through `--show-toplevel`, which for a .git-less directory
    # answers with the primary and makes adopt refuse. It is a dead end for exactly
    # the degraded worktrees that reach this line.
    corroborated_by_git = bool(entry and entry.get("branch") == branch)
    corroborated_by_ledger = bool(_active_ledger_records(args.state, branch)) or \
        branch in _ledger_branches_for_path(args.state, worktree)
    if not corroborated_by_git and not corroborated_by_ledger:
        return _refuse("uncorroborated-branch",
                       f"no authority vouches for branch {branch!r} at {worktree} — git "
                       "does not map that path to that branch and the ledger has never "
                       "recorded it there. Point --worktree at the real path, or drop "
                       "--branch and let git's worktree list name the target.",
                       branch=branch)

    registry_state = (Path(args.state).resolve() if args.state
                      else wr.default_state_path())
    owned_sources = wr.integration_sources_owned_by(registry_state, branch)
    if owned_sources:
        return _refuse(
            "integration-sources-active",
            f"integration branch {branch!r} still owns {len(owned_sources)} active "
            "source branch(es). Resolve those sources after the final integration "
            "has landed in the trunk, or abort the integration to release them; "
            "deleting this tree first would erase the only durable ownership edge.",
            branch=branch, source_branches=owned_sources,
        )

    # nit2 LANDED FLOOR: resolve is a force-discard (worktree remove --force + branch -D).
    # Called out of order (before cutover) it would vaporize unlanded work. Refuse a
    # branch whose net change is NOT already in base — using the registry's tree-diff
    # containment (never git cherry; same authority the sweep trusts). --force overrides.
    root = primary_root()
    audit = None
    integrated_closures: list[str] = []
    if not args.force:
        _fetch()  # base may have advanced; compare against the fresh tip
        if not wr.landed_in_base(args.base, branch):
            # SECOND EVIDENCE PATH, not a looser floor. After a batch integration
            # the tree-diff answer is legitimately "no" — conflict resolution left
            # base holding a NEWER version than the branch — and that is
            # indistinguishable from "never landed". Measured with
            # `ops/worktree_loadtest.py --mode batch -n 10 --conflict shared`:
            # 10 of 10 source branches land here. `--via-integration <ref>` runs
            # the audit the SKILL prescribes, mechanically, and reports what each
            # commit was matched on.
            if args.via_integration:
                landed_rc, _ = _git(
                    ["merge-base", "--is-ancestor", args.via_integration, args.base],
                    cwd=root,
                )
                if landed_rc != EXIT_OK:
                    return _refuse(
                        "integration-ref-not-landed",
                        f"integration ref {args.via_integration!r} is not an ancestor "
                        f"of {args.base!r}. It may contain matching patches without "
                        "having landed them in the trunk, so it cannot authorize "
                        "source teardown. Land the final integration first, then use "
                        f"`--via-integration {args.base}`.",
                        branch=branch, integration_ref=args.via_integration,
                        base=args.base,
                    )
                audit = _audit_integrated(branch, args.via_integration)
                if not audit["ok"]:
                    missing = [c for c in audit["commits"] if not c["match"]]
                    reason = (
                        f"branch {branch!r} is not landed in {args.base} (tree-diff), "
                        f"and the integration audit against {args.via_integration!r} "
                        f"could not account for {len(missing)} of "
                        f"{len(audit['commits'])} commit(s): "
                        + "; ".join(f"{c['sha']} {c['subject']!r}" for c in missing[:5])
                        + ". Either they never landed, or the ref you named is not "
                        "the one that carried them.")
                    _emit({"schema": SCHEMA, "step": "resolve", "error": "refused",
                           "reason": reason, "branch": branch, "landed": False,
                           "audit": audit}, args.json,
                          f"✗ resolve refused: {reason}")
                    return EXIT_BLOCK
                weak = [c["sha"] for c in audit["commits"]
                        if c["match"] == "subject+files"]
                print(f"[worktree][audit] {branch}: "
                      f"{len(audit['commits'])} commit(s) accounted for in "
                      f"{args.via_integration}"
                      + (f"; {len(weak)} on the WEAKER subject+files match "
                         f"({', '.join(weak[:5])})" if weak else ""),
                      file=sys.stderr, flush=True)
            else:
                reason = (f"branch {branch!r} is not landed in {args.base} (tree-diff) "
                          "— resolve would force-discard unlanded work. If it was "
                          "batch-integrated (conflict resolution leaves base holding a "
                          "NEWER version, which reads identically to 'never landed'), "
                          f"prove it with `--via-integration {args.base}` and the tool "
                          "will audit every commit and say what it matched on. "
                          "Otherwise run `cutover` first, or pass --force.")
                _emit({"schema": SCHEMA, "step": "resolve", "error": "refused",
                       "reason": reason, "branch": branch, "landed": False}, args.json,
                      f"✗ resolve refused: {reason}")
                return EXIT_BLOCK

    # An explicit integration REF is the batch model's equivalent of cutover: it
    # proves this source branch reached the named integration/trunk ref after
    # cherry-pick or conflict resolution. Preserve the hunter's staged evidence
    # before teardown, using that ref's actual tip just as ordinary cutover stamps
    # its landed trunk tip. This must also run when the source is already an
    # ancestor of the base (the normal no-diff path), because resolve otherwise
    # deletes the only branch identity that can connect the queue row to the
    # landed work and anchor leaves it unstamped forever (IMP-20260808-b6f69d).
    if args.commit and args.via_integration:
        landed_ref_rc, _ = _git(
            ["merge-base", "--is-ancestor", args.via_integration, args.base],
            cwd=root,
        )
        if landed_ref_rc != EXIT_OK:
            return _refuse(
                "integration-ref-not-landed",
                f"integration ref {args.via_integration!r} is not an ancestor "
                f"of {args.base!r}; refusing to stamp staged closures before "
                "the batch identity is on the target trunk",
                branch=branch, integration_ref=args.via_integration,
                base=args.base,
            )
        rc, integrated_sha = _git(["rev-parse", f"{args.via_integration}^{{commit}}"],
                                  cwd=root)
        if rc != 0 or not integrated_sha.strip():
            return _refuse(
                "integration-ref-unresolvable",
                f"integration audit passed but {args.via_integration!r} no longer "
                "resolves to a commit; refusing teardown before losing the staged "
                "closure's branch identity",
                branch=branch,
            )
        # A source resolver is invoked with the integration branch as its
        # corroborating REF by close-wave.  The staged row belongs to that
        # integration branch, not to the source branch being torn down.  Keep
        # stamping the source identity for the direct/legacy path, and stamp
        # the explicit integration identity as well; dedupe so a resolver of
        # the integration branch itself remains idempotent.
        stamp_branches = [branch]
        if args.via_integration != args.base:
            stamp_branches.append(args.via_integration)
        for stamp_branch in dict.fromkeys(stamp_branches):
            integrated_closures.extend(
                _stamp_anchor_queue(root, stamp_branch, integrated_sha.strip())
            )

    # teardown MUST run from the primary root: step 1 removes the target worktree,
    # which may be the very directory this process was invoked from. For the same
    # reason the gate-cache path is resolved NOW — its default-state branch derives
    # the ledger anchor from the process cwd, which teardown may be about to remove.
    gate_cache = _gate_record_path(args.state, worktree)
    gate_progress = _gate_progress_path(args.state, worktree)
    steps: list[dict[str, Any]] = []

    def _plan(label: str, gargs: list[str], cwd: Path, *, critical: bool = False) -> None:
        steps.append({"label": label, "cmd": "git " + " ".join(gargs),
                      "progress_label": "resolve-" + label.replace(" ", "-"),
                      "gargs": gargs, "cwd": str(cwd), "critical": critical})

    # Teardown shape depends on whether git's administrative link is intact.
    #
    # A `prunable` entry is the fossil of an interrupted `worktree remove --force`:
    # that command unlinks the worktree's `.git` FIRST and only then rm's the tree,
    # so a caller timeout during a slow removal (19 GB of DerivedData, in the
    # incident) leaves the directory standing with a broken link. `worktree remove`
    # answers rc=128 on such an entry — but MEASURED: once the directory itself is
    # gone it succeeds again, rc=0, and removes only that one entry.
    #
    # That measurement is why there is no `git worktree prune` here. Prune has no
    # path filter: in a repo with two independently broken worktrees, one prune
    # reaps BOTH. Since concurrent sessions are this repo's normal mode, a routine
    # resolve would silently destroy a sibling session's only remaining path->branch
    # record — the very information whose loss caused this incident. `worktree
    # remove` addresses exactly one path, so the healthy and the degraded paths end
    # up on the same targeted command.
    #
    # ORDER IS THE RESILIENCE: the slow, resumable step (rm -rf) runs while the
    # admin entry still holds the path->branch mapping, and the cheap administrative
    # strike runs last. Reversed, an interruption in between would leave a directory
    # nothing can attribute to a branch.
    def _plan_rm() -> None:
        steps.append({"label": "remove leftover worktree directory",
                      "cmd": f"rm -rf {worktree}",
                      "progress_label": "resolve-remove-leftover-directory",
                      "rmtree": worktree, "critical": True})

    if entry is not None:
        if entry.get("prunable") and Path(worktree).is_dir():
            _plan_rm()
        _plan("remove worktree", ["worktree", "remove", "--force", worktree], root,
              critical=True)
    elif Path(worktree).is_dir():
        # git no longer lists the path — an errored `worktree remove` drops the admin
        # entry anyway, and any prune in the repo removes it — but the directory is
        # still on disk. `worktree remove` has nothing left to act on, so without this
        # branch resolve reported `failures: 0` and exited 0 while leaving the whole
        # tree behind: a silent false success, and 19 GB of it in the incident's shape.
        _plan_rm()

    if any(s.get("rmtree") for s in steps) and not _rm_target_vetted(worktree, args.state):
        return _refuse("rm-target-unvetted",
                       f"{worktree} is neither under this repo's worktree root nor a "
                       "path the ledger recorded — refusing to delete it recursively",
                       branch=branch)

    _plan("delete local branch", ["branch", "-D", branch], root)
    if _remote_branch_exists(branch):
        _plan("delete remote branch", ["push", "origin", "--delete", branch], root)

    # Belt-and-suspenders, same net the registry's sweep clearance runs: no planned
    # step may delete a protected branch or remove the primary worktree. _resolve_target
    # already makes that unrepresentable; this catches a future bug upstream of it.
    primary_path, protected = _protected_branches(args.base, worktree)
    unsafe = [s["cmd"] for s in steps if s.get("gargs")
              and wr._step_touches_protected(s["gargs"], primary_path, protected)]
    # the recursive delete carries no argv, so the registry predicate cannot see it
    unsafe += [s["cmd"] for s in steps if s.get("rmtree")
               and primary_path and _norm(s["rmtree"]) == primary_path]
    if unsafe:
        return _refuse("unsafe-step",
                       "planned a repository-destroying step — refusing: "
                       + "; ".join(unsafe), branch=branch, unsafe=unsafe)

    if not args.commit:
        payload = {"schema": SCHEMA, "step": "resolve", "mode": "dry-run", "branch": branch,
                   # what let this teardown through, when it was not the
                   # plain tree-diff floor. Absent means the floor passed.
                   **({"audit": audit} if audit else {}),
                   "plan": [{"label": s["label"], "cmd": s["cmd"]} for s in steps]}
        human = ("# resolve (dry-run) — ledger -> merged, then:\n"
                 + "\n".join(f"  {s['cmd']}   # {s['label']}" for s in steps)
                 + "\n  (--commit to execute)")
        _emit(payload, args.json, human)
        return EXIT_OK

    # ledger closure first (idempotent even if the git teardown partially failed before).
    # BEFORE the registry is struck. `resolve` closes the record ahead of the git
    # steps, and a closed record is exactly what `held_tickets`-style readers filter
    # out — so reading the claim afterwards would always answer "nothing was
    # claimed", i.e. a check that can only ever pass.
    newly_owned, claimed_at_teardown, registry_rc, registry_payload = \
        _close_registry_for_teardown(args.state, branch)
    if newly_owned:
        return _refuse(
            "integration-sources-active",
            f"integration branch {branch!r} gained {len(newly_owned)} active "
            "source branch(es) while resolve was preparing. Nothing was deleted; "
            "resolve those sources after the final integration lands, then retry.",
            branch=branch, source_branches=newly_owned,
        )
    if registry_rc != EXIT_OK:
        return _refuse(
            "unsafe-step",
            f"registry refused to close {branch!r} before git teardown: "
            f"{registry_payload.get('reason', registry_payload)}",
            branch=branch, registry=registry_payload,
        )
    # FAIL-FAST on the steps later ones depend on. Half of the incident lived here:
    # `worktree remove --force` returned 128 and the loop went on to run `branch -D`
    # and `push origin --delete` anyway. Correct targeting makes those two harmless;
    # it does not make "keep going after a destructive step failed" correct. It also
    # matters for the new rm: if the directory removal fails, continuing would strike
    # the admin entry and leave a directory nothing can attribute to a branch — the
    # unrecoverable version of the state this whole change exists to make recoverable.
    results = []
    failures = 0
    aborted_after = None
    for s in steps:
        if s.get("rmtree"):
            rc, out = _rmtree_streamed(s["rmtree"])
        else:
            rc, out = _git_mutation(
                s["gargs"], cwd=Path(s["cwd"]), label=s["progress_label"],
            )
        ok = rc == 0
        results.append({"label": s["label"], "cmd": s["cmd"], "ok": ok,
                        "detail": out[:200] if not ok else ""})
        if not ok:
            failures += 1
            if s.get("critical"):
                aborted_after = s["label"]
                skipped = [t["label"] for t in steps[steps.index(s) + 1:]]
                results.append({"label": "aborted", "cmd": "", "ok": False,
                                "detail": f"skipped after a failed critical step: "
                                          f"{', '.join(skipped)}" if skipped else
                                          "no remaining steps"})
                break

    # nit3 ZERO RESIDUE: also drop this worktree's gate-record cache (the per-machine
    # verdict file gate wrote beside the ledger). Otherwise a stale verdict lingers
    # after the worktree it described is gone. (Path was resolved pre-teardown.)
    gate_cache_removed = False
    if gate_cache.exists():
        try:
            gate_cache.unlink()
            gate_cache_removed = True
        except OSError:
            pass
    # ...and the failed-gate output logs sitting beside it (IMP-20260808-c47253).
    # Same residue rule as the verdict: a log describing a gate run on a worktree
    # that no longer exists can only mislead. The filename carries this worktree's
    # key, so the glob cannot reach a sibling session's logs.
    gate_logs_removed = 0
    for stale_log in sorted(gate_cache.parent.glob(f"{gate_cache.stem}.*.log")):
        try:
            stale_log.unlink()
            gate_logs_removed += 1
        except OSError:
            pass

    # The live progress sidecar follows the verdict's lifecycle. Use the same short
    # lock as publishers so a concurrent gate cannot interleave its atomic replace
    # with this cleanup.
    gate_progress_removed = False
    try:
        with _gate_progress_lock(args.state):
            if gate_progress.exists():
                gate_progress.unlink()
                gate_progress_removed = True
    except OSError:
        pass

    # Said out loud, and deliberately NOT blocking. The anchor queue is gitignored
    # and per-machine, so nothing downstream of this teardown can notice a closure
    # that landed but was never written into the store: not the gate, not docs lint,
    # and not any reader of the ledger — `backlog.py list`, `show` and the generated
    # view all read the STORE, where a staged-and-never-anchored entry simply looks
    # open, with no trace of the work that closed it. (No claim here about the
    # planned bounty board: it does not exist yet. The one board this repo ever had,
    # `converge_board.py`, is retired — see worktree_registry.py's header.)
    # Refusing would be worse: the closure HAS landed, the entry is merely not
    # closed yet, and a teardown that refuses strands the worktree instead of
    # fixing anything.
    # Stamped-but-not-yet-anchored is the NORMAL state here: the documented order is
    # stage -> cutover -> resolve per worktree, with one `anchor` at wave end. So this
    # is a handoff note, not a warning — the first draft printed `⚠ never anchored` on
    # every successful hunter, and `make_commit_state`'s own docstring is the argument
    # against that: "a gate that reds on the normal path is one that gets switched
    # off." What makes it worth printing at all is that this is the last moment the
    # worktree exists to say it: after teardown the row's only remaining trace is an
    # id in a gitignored file.
    pending_anchor = sorted({r.get("id") for r in _read_anchor_queue(root)
                             if r.get("branch") == branch and r.get("landed_sha")})

    # CLAIMED but never staged — a different question from `pending_anchor`, and the
    # one that actually loses tickets. `pending_anchor` asks "did someone who
    # remembered to close it finish the job"; this asks "did anyone remember at all".
    # Both report an empty list on the happy path, which is exactly why the second
    # one has to exist separately: an unclosed claim and a clean teardown were
    # indistinguishable.
    #
    # Measured, on this tool's own flagship task: `open --backlog IMP-20260807-b9526c`
    # claimed it, the work landed, `resolve` printed `pending_anchor: []`, the
    # worktree vanished, and the entry is still `open`. Five other tickets in the
    # same session closed correctly — every one of them FILED mid-work. The claim is
    # taken at the start and the closure happens at the end, and nothing carried the
    # obligation across those hours; teardown is the last moment anyone knows the
    # claim existed.
    #
    # WARN, not block, and the reason is that all three of these are legitimate:
    # investigating and deciding it needs no fix, splitting the work across branches,
    # and abandoning a claim on purpose. A block would make the honest cases fight
    # the tool, and `make_commit_state`'s docstring already paid for that lesson.
    staged_here = {r.get("id") for r in _read_anchor_queue(root)
                   if r.get("branch") == branch}
    claimed_open = sorted(t for t in claimed_at_teardown
                          if t not in staged_here and not _entry_is_closed(root, t))

    payload = {"schema": SCHEMA, "step": "resolve", "mode": "committed", "branch": branch,
                   # what let this teardown through, when it was not the
                   # plain tree-diff floor. Absent means the floor passed.
                   **({"audit": audit} if audit else {}),
               "resolved": "merged", "executed": results, "failures": failures,
               "aborted_after": aborted_after,
               "gate_cache_removed": gate_cache_removed,
               "gate_progress_removed": gate_progress_removed,
               "gate_logs_removed": gate_logs_removed,
               "staged_closures": integrated_closures,
               "pending_anchor": pending_anchor,
               "claimed_without_closure": claimed_open}
    human = ["# resolve (committed): ledger -> merged"]
    for r in results:
        human.append(f"  {'✓' if r['ok'] else '✗'} {r['cmd']}   # {r['label']}")
    if gate_cache_removed:
        human.append("  ✓ dropped gate-record cache")
    if gate_progress_removed:
        human.append("  ✓ dropped gate-progress sidecar")
    if gate_logs_removed:
        human.append(f"  ✓ dropped {gate_logs_removed} failed-gate output log(s)")
    if pending_anchor:
        human.append(f"  · {len(pending_anchor)} closure(s) landed and awaiting the "
                     f"wave's anchor: {', '.join(pending_anchor)}")
        human.append("    run `./ops/backlog.py anchor --commit` once the wave is done")
    if claimed_open:
        # Louder than pending_anchor on purpose: that one is a reminder about work
        # already recorded, this one is the last chance to notice work that was
        # never recorded at all.
        human.append(f"  ⚠ {len(claimed_open)} claimed ticket(s) with NO staged "
                     f"closure: {', '.join(claimed_open)}")
        human.append("    if the work landed, it is still open — `./ops/backlog.py "
                     "stage <id> ...` before the branch is gone, or say why it stays "
                     "open with `update <id> --resolution ...`")
        human.append("    run: ./ops/backlog.py anchor --commit")
    _emit(payload, args.json, "\n".join(human))
    return EXIT_OK if failures == 0 else EXIT_BLOCK
