"""Gate and cutover command orchestration.

Low-level gate execution lives in worktree_orchestrator_core; this module owns the
CLI-level gate/cutover sequencing and binds shared helpers after runtime import.
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

def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted gate commands."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]

def _interrupted_operation(worktree: str | Path) -> str | None:
    """`"rebase"` / `"merge"` / `"cherry-pick"` when one is in flight here, else None.

    Reads the marker paths git itself uses, via `rev-parse --git-path` so it works in a
    linked worktree (where they live under `.git/worktrees/<name>/`, not the common
    dir). Checking `git status` output instead would make this depend on porcelain
    wording; checking for unmerged paths alone would miss a conflict-free rebase that
    was interrupted, which is equally incoherent to diff against.
    """
    for name, marker in (("rebase", "rebase-merge"), ("rebase", "rebase-apply"),
                         ("merge", "MERGE_HEAD"), ("cherry-pick", "CHERRY_PICK_HEAD")):
        rc, path = _git(["rev-parse", "--git-path", marker], cwd=worktree)
        if rc == 0 and path.strip():
            candidate = Path(path.strip())
            if not candidate.is_absolute():
                candidate = Path(worktree) / candidate
            if candidate.exists():
                return name
    return None


def cmd_gate(args: argparse.Namespace) -> int:
    """Impact-based verification: route changed files to the existing gate tools, run
    them, aggregate a verdict, and record it for cutover."""
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": GATE_SCHEMA, "error": "worktree not found", "worktree": worktree},
              args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    orch = _orchestrator_identity(worktree)
    mismatch = _orchestrator_guard(orch, worktree, "gate", GATE_SCHEMA, args.json)
    if mismatch is not None:
        return mismatch

    interrupted = _interrupted_operation(worktree)
    if interrupted is not None and not args.plan_only:
        # A tree with a rebase/merge in flight has no coherent diff against the trunk,
        # and `git diff` on it reports the PARTIAL state. Measured: mid-rebase with one
        # unmerged path, `_changed_vs_base` returned [] — so `plan_gates` routed nothing,
        # `aggregate_verdict([])` returned "pass", and the run recorded a fresh green
        # verdict bound to that HEAD. A gate that greenlights a conflicted tree is worse
        # than one that fails: cutover's whole freshness contract rests on this verdict.
        #
        # Empty-diff alone is NOT the signal to refuse on — a branch whose work is
        # already contained in the trunk legitimately has nothing to gate. The state of
        # the operation is.
        _emit({"schema": GATE_SCHEMA, "step": "gate",
               "error": f"a {interrupted} is in progress in this worktree — finish or "
                        f"abort it before gating. A tree mid-operation has no coherent "
                        f"diff against the trunk, so the verdict would be recorded over "
                        f"a partial state",
               "worktree": worktree, "interrupted": interrupted}, args.json,
              f"✗ gate refused: a {interrupted} is in progress in {worktree}\n"
              f"  finish it (`git -C {worktree} {interrupted} --continue`) or abandon it "
              f"(`--abort`), then re-run gate")
        return EXIT_BLOCK

    if not args.plan_only:
        # Cheap half of the base binding: refuse before spending a gate run (an iOS gate
        # is tens of minutes) on a tree that cannot land as-gated. `--plan-only` runs
        # nothing and records nothing, so it stays usable as the preview the message
        # below points at.
        trunk = _local_trunk(args.base)
        drift = _base_containment(worktree, trunk)
        if drift is not None:
            msg = (f"{_behind_base_refusal(worktree, trunk, drift)} — gating this tree "
                   f"would bind a verdict to code cutover will not land. `--plan-only` "
                   f"still previews the routing")
            _emit({"schema": GATE_SCHEMA, "step": "gate", "error": msg,
                   "worktree": worktree, "base": args.base, **drift}, args.json,
                  f"✗ gate refused: {msg}")
            return EXIT_BLOCK

    # Snapshot the HEAD BEFORE resolving input scopes. A concurrent commit in this
    # worktree between the diff/fingerprint probe and the record write would otherwise
    # let a reused result acquire the wrong HEAD identity; cutover's later check cannot
    # tell that the fingerprint belonged to the earlier tree.
    head = _head_sha(worktree)
    changed = _changed_vs_base(worktree, args.base)
    no_changed_files = not changed
    # anchor test-existence at the WORKTREE so a test file added in this very diff
    # is seen (the primary checkout may not have it yet)
    full_plan = plan_gates(
        changed,
        ops_test_exists=lambda rel: (Path(worktree) / rel).is_file(),
        base=args.base,
        ops_tests_dir_exists=lambda: (Path(worktree) / "ops/tests").is_dir(),
        path_exists=lambda rel: (Path(worktree) / rel).is_file(),
    )
    try:
        gate_tier = normalize_gate_tier(getattr(args, "gate_tier", None))
    except GateTierError as exc:
        _emit({"schema": GATE_SCHEMA, "step": "gate", "error": str(exc),
               "worktree": worktree}, args.json, f"✗ gate refused: {exc}")
        return EXIT_USAGE
    plan, deferred_plan = select_gate_plan(full_plan, gate_tier)
    required_tier = required_cutover_tier(changed)
    results: list[dict[str, Any]] = []
    rec_path = _gate_record_path(args.state, worktree)
    progress_path = _gate_progress_path(args.state, worktree)
    progress_started = time.monotonic()
    run_id = f"{head[:12]}-{os.getpid()}-{time.monotonic_ns()}"
    print(f"[worktree][gate] phase=plan tier={gate_tier} gates={len(plan)} "
          f"deferred={len(deferred_plan)} progress={progress_path} "
          f"run_id={run_id}", file=sys.stderr, flush=True)
    completed: list[dict[str, str]] = []
    progress_generation: int | None = None

    def publish_progress(*, claim: bool = False, terminal: bool = False) -> None:
        nonlocal progress_generation
        done = len(completed)
        current = None if terminal or done >= len(plan) else plan[done]["name"]
        progress = {
            "schema": GATE_PROGRESS_SCHEMA,
            "run_id": run_id,
            "worktree": worktree,
            "head_sha": head,
            "plan_total": len(plan),
            "done": done,
            "current": current,
            "elapsed": round(time.monotonic() - progress_started, 3),
            "completed": list(completed),
        }
        try:
            with _gate_progress_lock(args.state):
                existing = _read_gate_progress(progress_path)
                if claim:
                    previous_generation = (existing or {}).get("generation", 0)
                    if (not isinstance(previous_generation, int)
                            or isinstance(previous_generation, bool)
                            or previous_generation < 0):
                        previous_generation = 0
                    progress_generation = previous_generation + 1
                elif (progress_generation is None
                      or not existing
                      or existing.get("run_id") != run_id
                      or existing.get("generation") != progress_generation):
                    owner = (existing or {}).get("run_id", "unknown")
                    generation = (existing or {}).get("generation", "unknown")
                    print(f"[worktree][gate] phase=progress progress={progress_path} "
                          f"write=skipped reason=stale-run owner_run_id={owner} "
                          f"owner_generation={generation} run_id={run_id}",
                          file=sys.stderr, flush=True)
                    return
                progress["generation"] = progress_generation
                _write_atomic(progress_path,
                              json.dumps(progress, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            # Progress is observational, not a verdict input. Keep the gate running but
            # name a broken progress surface instead of silently losing the live view.
            print(f"[worktree][gate] phase=progress progress={progress_path} "
                  f"write=failed error={type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)

    if not args.plan_only:
        publish_progress(claim=True)
        previous, previous_error = _read_gate_record(rec_path)
        tracked = _tracked_paths(worktree)
        for spec in plan:
            current_input = _gate_input_scope(spec, worktree, changed, tracked)
            now = _head_sha(worktree)
            if now != head:
                payload = {"schema": GATE_SCHEMA, "step": "gate",
                           "error": (f"worktree HEAD moved while preparing gate inputs "
                                     f"({head[:8]} -> {now[:8]}) — re-run gate"),
                           "worktree": worktree, "initial_head": head, "current_head": now}
                _emit(payload, args.json, f"✗ gate refused: {payload['error']}")
                return EXIT_BLOCK
            reused, reason = _reuse_gate(spec, current_input, previous, previous_error, orch,
                                         args.base)
            if reused is not None:
                result = reused
            else:
                result = _run_gate(spec, worktree, record_path=rec_path, state=args.state)
                result["reused"] = False
                result["reused_from_head"] = None
                result["reuse"] = {
                    "decision": "rerun",
                    "source_head": previous.get("head_sha") if previous else None,
                    "reason": reason,
                }
                result["input"] = current_input
            results.append(result)
            result["tier"] = spec.get("tier", "S2")
            completed.append({"name": result["name"], "status": result["status"]})
            publish_progress()
            print(f"[worktree][gate] phase=gate gate={result['name']} "
                  f"status={result['status']} done={len(completed)}/{len(plan)} "
                  f"elapsed={time.monotonic() - progress_started:.1f}s "
                  f"progress={progress_path}", file=sys.stderr, flush=True)
            if spec.get("preflight") and result.get("status") != "pass":
                # A preflight result must prove the prerequisite, not merely avoid a
                # hard block. Stop on block, warn, or inconclusive so tag races and
                # other typed uncertainty cannot launch expensive gates.
                publish_progress(terminal=True)
                print(f"[worktree][gate] phase=stop reason=preflight-nonpass "
                      f"gate={result['name']} status={result['status']} "
                      f"remaining={len(plan) - len(results)} "
                      f"progress={progress_path}", file=sys.stderr, flush=True)
                break
    verdict = aggregate_verdict(results) if not args.plan_only else "planned"

    now = _head_sha(worktree)
    if not args.plan_only and now != head:
        payload = {"schema": GATE_SCHEMA, "step": "gate",
                   "error": (f"worktree HEAD moved while gates ran "
                             f"({head[:8]} -> {now[:8]}) — discard this run and re-run gate"),
                   "worktree": worktree, "initial_head": head, "current_head": now}
        _emit(payload, args.json, f"✗ gate refused: {payload['error']}")
        return EXIT_BLOCK
    if not args.plan_only:
        # History FIRST, so the never-green check below sees this run too: "never green
        # in N attempts" is only honest if N includes the red being reported.
        history_error = _append_gate_history(args.state, worktree, head, orch, results)
        for r in results:
            if r.get("status") != "block":
                continue
            streak = _never_green(args.state, r["name"].split(":")[0])
            if streak is None:
                continue
            # Said at the moment of blocking, where it can still change what the reader
            # does. Deliberately a HYPOTHESIS, not a verdict: an empty journal is every
            # gate's starting state, so three reds while fixing a genuinely broken build
            # look identical to a structurally-red gate. Asserting "the gate is at fault"
            # would hand the reader a root cause the data cannot support (iron law 3).
            # What the data does support is: nothing here has ever seen this gate pass.
            r["never_green"] = streak
            r["summary"] = (
                f"{r.get('summary', '')} (no green ever recorded for this gate on this "
                f"machine: {streak['attempts']} block attempt(s) across "
                f"{streak['heads']} HEAD(s) / {streak['worktrees']} worktree(s) — worth "
                f"checking whether it can pass at all before treating this as your bug)")

    primary = None
    primary_dirty: list[str] = []
    primary_dirty_error: str | None = None
    if not args.plan_only:
        primary = primary_root()
    if (not args.plan_only and primary is not None
            and Path(primary).resolve() != Path(worktree).resolve()):
        try:
            primary_rc, primary_status = _git(
                ["status", "--porcelain", "--untracked-files=no"], cwd=primary
            )
        except Exception as exc:  # noqa: BLE001 — observation must not fail the gate
            primary_rc, primary_status = 127, str(exc)
        if primary_rc != 0:
            primary_dirty_error = (primary_status[:200]
                                   or f"git status failed with rc={primary_rc}")
        else:
            primary_dirty = _porcelain_paths(primary_status)

    record = {"schema": GATE_SCHEMA, "worktree": worktree, "base": args.base,
              "head_sha": head, "orchestrator": orch, "changed_files": changed,
              "no_changed_files": no_changed_files,
              "gate_tier": gate_tier, "required_tier": required_tier,
              "plan": [{"name": g["name"], "level": g["level"], "category": g["category"],
                        "tier": g.get("tier", "S2"), "cmd": g.get("cmd")} for g in plan],
              "deferred_plan": [{"name": g["name"], "level": g["level"],
                                 "category": g["category"],
                                 "tier": g.get("tier", "S2"),
                                 "note": g.get("note")}
                                for g in deferred_plan],
              "gates": results, "verdict": verdict,
              "gate_reuse": _reuse_summary(results)}
    if not args.plan_only:
        record.update({"primary": str(primary), "primary_dirty": primary_dirty,
                       "primary_dirty_error": primary_dirty_error})
        # Non-blocking, but never silent: a permanently unwritable journal must not be
        # indistinguishable from a machine that simply has no history yet.
        record["history_error"] = history_error
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    # A receipt line the agent PASTES rather than recalls. Structured receipt
    # fields that an agent types from memory are exactly as trustworthy as prose
    # — a fabricated digest is no harder to produce than "tests passed". This
    # line cannot be produced without having run the gate, and the reader can
    # `cat` the record path to check it. Keep one renderer for both output modes;
    # otherwise the two surfaces can silently drift apart.
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    breakdown = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    reuse = record.get("gate_reuse", {})
    no_changes = (" no-changes"
                  if record.get("no_changed_files") and not args.plan_only else "")
    record_ref = (str(_gate_record_path(args.state, worktree))
                  if not args.plan_only else "<not recorded>")
    executed_count = _executed_gate_count(results)
    receipt_line = (f"gate={verdict} tier={gate_tier} required={required_tier} "
                    f"deferred={len(deferred_plan)} record={record_ref} "
                    f"head={head[:8]} orch={_orch_token(record)} gates={len(plan)} "
                    f"executed={executed_count} {breakdown} "
                    f"reused={len(reuse.get('reused', []))} rerun={len(reuse.get('rerun', []))}"
                    f"{no_changes}")
    if getattr(args, "receipt_line", False):
        print(receipt_line)
        return EXIT_OK if args.plan_only or verdict in ("pass", "warn") else EXIT_BLOCK

    lines = [f"# gate {verdict.upper()} tier={gate_tier} required={required_tier} "
             f"({len(changed)} changed file(s), {len(plan)} gate(s), "
             f"{len(deferred_plan)} deferred)  orchestrator={_orch_token(record)}"]
    if not args.plan_only and no_changed_files:
        lines.append(
            f"  ⚠ no changes in this worktree vs {args.base} — no changed files were "
            f"verified. If you have been editing, the edits may have landed in the "
            f"primary checkout instead (cwd drift); check `git -C {worktree} status` "
            "before trusting this gate result."
        )
    if not args.plan_only and primary_dirty_error:
        lines.append(
            f"  ⚠ primary working tree status unavailable: {primary_dirty_error} — "
            "inspect the primary checkout before trusting this gate result."
        )
    elif not args.plan_only and primary_dirty:
        shown = ", ".join(primary_dirty[:5])
        if len(primary_dirty) > 5:
            shown += f" … and {len(primary_dirty) - 5} more"
        lines.append(
            f"  ⚠ primary working tree has {len(primary_dirty)} uncommitted tracked "
            f"file(s): {shown} — if these are your edits, they landed in the primary "
            "checkout rather than this worktree."
        )
    for r in results:
        mark = {"pass": "✓", "warn": "⚠", "block": "✗",
                "inconclusive": "~"}.get(r["status"], "?")
        lines.append(f"  {mark} {r['name']} [{r['status']}] — {r.get('summary','')}")
    if deferred_plan:
        lines.append("  ↷ deferred by tier: " + ", ".join(
            f"{g['name']}[{g.get('tier', 'S2')}]" for g in deferred_plan
        ))
    if not plan:
        lines.append("  (no impact-based gates selected for these changes)")
    if record.get("history_error"):
        lines.append(f"  ! gate history not written ({record['history_error']}) — "
                     f"never-green detection is blind until this is fixed")
    if not args.plan_only:
        lines.append(receipt_line)
    _emit(record, args.json, "\n".join(lines))
    if args.plan_only:
        return EXIT_OK
    return EXIT_OK if verdict in ("pass", "warn") else EXIT_BLOCK


def cmd_cutover(args: argparse.Namespace) -> int:
    """Require a fresh non-block gate verdict, then integrate the worktree into the
    LOCAL trunk: rebase onto local `main` and fast-forward the primary checkout's
    `main` to it — OFFLINE, no push, no deploy. (Publishing to origin, and thereby
    production, is the separate `deploy` step.) A `warn` verdict LANDS ("landed with
    warnings" — its disposition belongs to the driving agent); `block`, a stale/absent
    verdict, and a verdict containing an `inconclusive` gate all refuse."""
    blocked = _freeze_guard(args.state, "cutover", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "cutover", "error": "worktree not found",
               "landed": False}, args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    delegated_records = _delegated_records_for_path(args.state, worktree)
    if delegated_records:
        record = delegated_records[0]
        payload = {
            "schema": SCHEMA, "step": "cutover", "error": (
                "delegated worktree cannot cut over; the integrator must run gate/cutover"
            ), "refusal": "delegated", "delegated": True, "landed": False,
            "worktree": worktree, "branch": record.get("branch"),
        }
        _emit(payload, args.json,
              f"✗ cutover refused: delegated worktree {record.get('branch')} at {worktree}; "
              "the integrator owns landing")
        return EXIT_BLOCK

    orch = _orchestrator_identity(worktree)
    mismatch = _orchestrator_guard(orch, worktree, "cutover", SCHEMA, args.json)
    if mismatch is not None:
        return mismatch

    local = _local_trunk(args.base)
    rec_path = _gate_record_path(args.state, worktree)
    head = _head_sha(worktree)
    refuse: str | None = None
    refuse_extra: dict[str, Any] = {}
    verdict: str | None = None
    gated_head: str | None = None
    warnings: list[str] = []
    gate_reuse: dict[str, Any] = {"reused": [], "rerun": []}
    gate_tier: str | None = None
    required_tier: str | None = None
    if not rec_path.exists():
        refuse = "no gate verdict on record — run `gate` first"
    else:
        rec = json.loads(rec_path.read_text())
        verdict = rec.get("verdict")
        gated_head = rec.get("head_sha")
        try:
            gate_tier = normalize_gate_tier(rec.get("gate_tier"))
            required_tier = normalize_gate_tier(
                rec.get("required_tier") or required_cutover_tier(
                    rec.get("changed_files") or []
                )
            )
        except GateTierError as exc:
            refuse = f"gate record has invalid tier metadata: {exc} — re-run `gate`"
        planned_gates = rec.get("plan")
        recorded_gates = rec.get("gates")
        gate_reuse = rec.get("gate_reuse") or (
            _reuse_summary(recorded_gates)
            if isinstance(recorded_gates, list) else {"reused": [], "rerun": []}
        )
        rec_orch = (rec.get("orchestrator") or {}).get("sha256")
        wt_orch = orch["worktree_copy_sha256"]
        if refuse:
            pass
        elif TIER_RANK[gate_tier] < TIER_RANK[required_tier]:
            refuse = (f"gate tier {gate_tier} is below the required {required_tier} "
                      "for this change set — re-run gate at the required tier")
        elif rec.get("head_sha") != head:
            refuse = ("gate verdict is stale (recorded HEAD "
                      f"{str(rec.get('head_sha'))[:8]} != current {head[:8]}) — re-run `gate`")
        elif wt_orch is not None and rec_orch != wt_orch:
            # Same family as the stale-HEAD refusal: a verdict is usable only if it is
            # bound BOTH to the code it judged and to the judge. head_sha alone cannot
            # see this — the wrong orchestrator run at the SAME HEAD matches on head.
            refuse = ("gate verdict came from a different orchestrator "
                      f"({str(rec_orch)[:8]} != worktree's {wt_orch[:8]}) — re-run `gate` "
                      f"with {worktree}/ops/worktree_orchestrate.py")
        elif verdict == "block":
            refuse = "gate verdict is 'block' — fix the blocking gate(s) and re-run `gate`"
        elif not isinstance(planned_gates, list) or not isinstance(recorded_gates, list):
            refuse = ("gate record is malformed (plan/gates must be lists) — "
                      "re-run `gate` before cutover")
        elif len(recorded_gates) != len(planned_gates):
            # A non-pass preflight intentionally stops before expensive gates. Its
            # aggregate can still be WARN (for example a typed inconclusive result),
            # but a partial plan is never evidence for cutover: warn is landable only
            # after every planned gate has produced a row.
            refuse = (f"gate record is incomplete ({len(recorded_gates)} of "
                      f"{len(planned_gates)} planned gate results) — the preflight "
                      "stopped the run; re-run `gate` before cutover")
        elif verdict not in ("pass", "warn"):
            refuse = f"gate verdict is {verdict!r}, not pass/warn — run `gate` first"
        elif unattributed := [g.get("name") for g in rec.get("gates", [])
                              if g.get("status") == "inconclusive"]:
            # An inconclusive gate folds the VERDICT to warn, and a warn LANDS — so
            # without this the fold quietly turns "this red could not be attributed"
            # into "shipped with a note", which is the disarm direction. It is reachable
            # with no tag surgery at all: every concurrent preflight/catchup/sync/deploy
            # runs `git fetch --prune`, which imports origin's new tags and moves the
            # snapshot under a gate that never reads tags.
            #
            # The gate's own summary already said "re-run this gate"; nothing made that
            # happen. Refusing costs one gate re-run and makes the instruction real.
            refuse = (f"{len(unattributed)} gate(s) came back inconclusive — their red "
                      f"was measured while refs moved underneath, so it is attributable "
                      f"to neither this branch nor the tools: "
                      f"{', '.join(str(n) for n in unattributed[:5])}. Re-run `gate` "
                      f"once the tag surgery is finished")
        elif verdict == "warn":
            # a warn LANDS; surface which gates warned so the record is explicit.
            # `inconclusive` folds INTO this verdict, so it has to be named here too —
            # otherwise the only gate that degraded the run would be the one gate the
            # landing record does not mention.
            warnings = [g.get("name") for g in rec.get("gates", [])
                        if g.get("status") in ("warn", "inconclusive")]
    if not refuse:
        # Ordering is deliberate: the stale-HEAD / wrong-orchestrator / block refusals
        # still win when they apply — they are the more specific diagnosis. This one
        # sits in the SHARED chain, so it is visible in dry-run as well as --commit.
        # The helper's failure key is `containment_error`, not `error`, so **spreading
        # it cannot clobber the refusal prose.
        drift = _base_containment(worktree, local)
        if drift is not None:
            refuse_extra = drift
            refuse = _behind_base_refusal(worktree, local, drift)
    if refuse:
        _emit({"schema": SCHEMA, "step": "cutover", "error": refuse, "landed": False,
               "worktree": worktree, **refuse_extra}, args.json,
              f"✗ cutover refused: {refuse}")
        return EXIT_BLOCK

    primary = primary_root()
    wt_branch = _current_branch(worktree)
    warn_line = (f"\n  landed with warnings: {', '.join(warnings)}" if warnings else "")
    if wt_branch is None:
        _emit({"schema": SCHEMA, "step": "cutover", "error": "worktree is on a detached "
               "HEAD — nothing to integrate", "landed": False, "worktree": worktree},
              args.json, "✗ cutover refused: worktree is on a detached HEAD")
        return EXIT_USAGE

    if not args.commit:
        payload = {"schema": SCHEMA, "step": "cutover", "mode": "dry-run", "landed": False,
                   "branch": wt_branch, "target": local, "verdict": verdict,
                   "warnings": warnings, "gate_reuse": gate_reuse,
                   "gate_tier": gate_tier, "required_tier": required_tier}
        _emit(payload, args.json,
              f"# cutover (dry-run)\n  would rebase {wt_branch} onto {local}, then "
              f"ff local {local} to it (offline — no push, no deploy){warn_line}\n"
              f"  (--commit to land)")
        return EXIT_OK

    # Serialize the trunk advance; rebase onto the CURRENT local trunk INSIDE the lock
    # so a peer cutover that just advanced it is picked up (not raced past).
    with _main_advance_lock(primary):
        guard = _primary_ff_ready(primary, local, branch=wt_branch,
                                  worktree=worktree)
        if guard:
            reason, extra = guard
            _emit({"schema": SCHEMA, "step": "cutover", "error": reason, "landed": False,
                   "primary": str(primary), **extra}, args.json,
                  f"✗ cutover refused: {reason}")
            return EXIT_BLOCK
        # Normally a no-op: the shared refusal chain above already sent a behind
        # branch to `catchup`. It can still move, because that check runs OUTSIDE
        # this lock and a peer cutover may have advanced the trunk since.
        rrc, rout = _rebase_onto(worktree, local, "cutover-rebase")
        if rrc != 0:
            _git_mutation(
                ["rebase", "--abort"], cwd=worktree, label="cutover-rebase-abort",
            )
            _emit({"schema": SCHEMA, "step": "cutover", "error": "rebase failed (aborted)",
                   "detail": rout, "landed": False},
                  args.json,
                  f"✗ rebase onto {local} failed (aborted):\n{rout}")
            return EXIT_BLOCK
        sha = _head_sha(worktree)
        if gated_head is not None and sha != gated_head:
            # Terminal invariant, and the only one a race cannot dodge: the containment
            # check above runs OUTSIDE this lock, so a peer cutover can advance the trunk
            # in between — and the rebase is deliberately taken against the CURRENT trunk.
            # Whatever the cause, a rebase that moved HEAD produced a tree no gate ever
            # judged. Refuse BEFORE the trunk advances; nothing has landed. The worktree
            # is left rebased (that is the remedy anyway) and its verdict is now honestly
            # stale, so the next cutover refuses on head_sha until `gate` is re-run.
            msg = (f"the rebase onto {local} moved HEAD ({gated_head[:8]} -> {sha[:8]}) "
                   f"— the trunk advanced after the verdict was checked, so the tree "
                   f"that would land is not the tree that was gated. The worktree is "
                   f"now rebased: re-run `gate`, then `cutover`")
            _emit({"schema": SCHEMA, "step": "cutover", "error": msg, "landed": False,
                   "worktree": worktree, "gated_sha": gated_head, "rebased_sha": sha,
                   "target": local}, args.json,
                  f"✗ cutover refused: {msg}")
            return EXIT_BLOCK
        # advance the local trunk by a ff-only merge IN the primary (main lives there).
        mrc, mout = _git_mutation(
            ["merge", "--ff-only", wt_branch],
            cwd=primary,
            label="cutover-fast-forward",
        )
        if mrc != 0:
            _emit({"schema": SCHEMA, "step": "cutover", "error": f"ff of {local} failed: "
                   f"{mout[:200]}", "landed": False}, args.json,
                  f"✗ ff of local {local} failed:\n{mout}")
            return EXIT_BLOCK
        vrc, now = _git(["rev-parse", local], cwd=primary)
        if vrc != 0 or now != sha:
            _emit({"schema": SCHEMA, "step": "cutover", "error": "post-ff verification "
                   f"failed: {local} is at {now[:8] if vrc == 0 else '?'}, expected "
                   f"{sha[:8]}", "landed": False}, args.json, "✗ post-ff verification failed")
            return EXIT_BLOCK

        # INSIDE the lock, deliberately. The repair reads and rewrites the same
        # trunk-owned files the ff just moved, so it belongs to the same critical
        # section. Measured outside it, 4 runs out of 4: two concurrent repairs
        # raced in `_write_atomic` and one died with FileNotFoundError, leaving
        # the primary dirty — and a dirty primary is what every later `cutover`
        # refuses on. The lock is also what makes the rollback below safe: nobody
        # else can have dirtied these paths since `_primary_ff_ready` passed.
        repair = _post_landing_repair(primary)
        staged_closures = _stamp_anchor_queue(primary, wt_branch, sha)

    trunk_tip = _head_sha(primary) if repair.get("committed") else sha
    payload = {"schema": SCHEMA, "step": "cutover", "mode": "committed", "landed": True,
               "sha": sha, "trunk_tip": trunk_tip, "target": local, "branch": wt_branch,
               "verdict": verdict, "warnings": warnings, "gate_reuse": gate_reuse,
               "gate_tier": gate_tier, "required_tier": required_tier,
               "repair": repair,
               "staged_closures": staged_closures}
    repair_line = ""
    if repair.get("committed"):
        # Human-readable callers were told nothing at all about the repair, which
        # made a landing that added TWO commits to the trunk print as one.
        repair_line = f"\n  + ledger repair committed ({trunk_tip[:8]})"
    if not repair.get("ok", True):
        repair_line = f"\n  ! ledger repair FAILED: {repair.get('error', '?')}"
    if staged_closures:
        repair_line += (f"\n  staged closures stamped: {', '.join(staged_closures)}"
                        f" — land them with `./ops/backlog.py anchor --commit`")
    _emit(payload, args.json,
          f"✓ cutover: ff local {local} -> {sha[:8]} (offline; run `deploy` to "
          f"publish){warn_line}{repair_line}")
    return EXIT_OK
