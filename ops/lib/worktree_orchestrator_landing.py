"""Landing and catchup history-rewriting lifecycle commands."""

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
    refusal = operator_refusal(
        command="land", operator=getattr(args, "operator", "manager"),
        commit=args.commit, manager_only=True,
    )
    if refusal:
        _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
               "landed": False, **refusal}, args.json,
              "✗ land refused: only Manager may land primary main")
        return EXIT_BLOCK
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
            "error": "delegated worktree cannot land; Manager owns landing admission",
            "refusal": "delegated", "delegated": True, "landed": False,
            "worktree": worktree, "branch": record.get("branch"),
        }, args.json,
        f"✗ land refused: delegated worktree {record.get('branch')} at {worktree}; "
        "Manager owns landing admission")
        return EXIT_BLOCK
    primary = primary_root()
    requested_gate_tier = getattr(args, "gate_tier", "S2")
    requested_deferrals = list(getattr(args, "defer_gate", []) or [])

    if not args.commit:
        with _land_lock(primary):
            live = _land_tickets(_land_queue_dir(primary))
        _emit({"schema": SCHEMA, "step": "land", "mode": "dry-run", "landed": False,
               "worktree": worktree, "queue_depth": len(live),
               "would_run": ["catchup --commit",
                             f"gate --gate-tier {requested_gate_tier}",
                             "cutover --commit"],
               "gate_tier": requested_gate_tier,
               "defer_gates": requested_deferrals,
               "note": "takes a FIFO turn first; the whole sequence runs under it"},
              args.json,
              f"[dry-run] land {worktree}: queue depth {len(live)}; would take a turn "
              f"then run catchup --commit -> gate({requested_gate_tier}) -> "
              "cutover --commit")
        return EXIT_OK

    seq, ticket_fd = _land_enqueue(primary, worktree)
    started = time.monotonic()
    common = {"state": args.state, "json": True, "base": args.base,
              "worktree": worktree, "gate_tier": requested_gate_tier,
              "defer_gate": requested_deferrals}
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
               "gate_tier": requested_gate_tier,
               "defer_gates": requested_deferrals,
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
