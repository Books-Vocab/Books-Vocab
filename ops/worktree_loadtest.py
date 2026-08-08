#!/usr/bin/env -S uv run --script
"""Load-test the worktree flow at N-way concurrency, inside a throwaway clone.

Why this exists as a tool rather than a one-off script: the plan is 10 -> 15 -> 20
worktrees per batch, and every step up has to be MEASURED rather than argued. A
script that lives in someone's scratchpad gets re-derived; this one gets re-run.

Why a clone: both modes end in `cutover`, which fast-forwards the LOCAL trunk.
Run against the real repo they would land N junk commits on the user's main. A
`git clone --no-hardlinks` gives the orchestrator a complete, isolated repo — its
own worktrees, its own ledger, its own trunk — so the test can be destructive
without being dangerous. `sync` and `deploy` are never invoked.

TWO MODES, because the repo has two different workflows that both look like
"several worktrees at once" and whose correct handling is OPPOSITE:

  --mode concurrent   Independent sessions, each landing its own work. This is
                      what `land`'s FIFO queue is for. Measured 2026-08-08:
                      manual catchup/gate/cutover gets 2/10 at N=10; `land` gets
                      10/10 with exactly N gate runs.

  --mode batch        One fan-out batch: N delegates stop at commit, and a single
                      INTEGRATOR cherry-picks them into one tree, resolves each
                      conflict once, gates once, cuts over once. This is the path
                      `.claude/skills/worktree-flow/SKILL.md` "批次交回狀態"
                      mandates, and it is the one the backlog dogfood uses.

The distinction matters because the first mode's numbers say nothing about the
second. `land` presumes N landers; a fan-out batch has exactly one by contract.

WHAT `--conflict shared` IS FOR. The first version of this harness gave every
lane its own file, so no two lanes ever touched the same bytes — the harness
could not observe the failure mode it was built to find. Real tickets collide:
`docs/reference/tech_index.md`, `docs/registry.yml`, the backlog store. With
`--conflict shared` every lane also inserts a row into one shared table at the
same anchor, which makes every cherry-pick after the first conflict by
construction. The integrator resolves each one by keeping BOTH rows — the
mechanical analogue of a human merging table rows — and the run then asserts the
thing that actually matters:

    every row that went in comes out.

That assertion is the point of the whole exercise. This repo has already lost
three ledger entries to exactly this shape (IMP-20260806-e06150): a rebase
conflict on a generated table, resolved by regenerating, rc=0, empty stderr,
plausible row count, all gates green — and the loss was noticed only because a
commit count went from 5 to 4.

Output is a JSON report on stdout; progress goes to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REAL_REPO = Path(__file__).resolve().parents[1]
MAX_CUTOVER_ATTEMPTS = 12
SHARED_TABLE = "ops/loadtest_fixtures/SHARED.md"
SHARED_ANCHOR = "<!-- rows below -->"


def log(msg: str) -> None:
    print(f"[loadtest {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def run(argv, cwd, label, timeout=1800):
    t0 = time.monotonic()
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          timeout=timeout)
    return {"label": label, "rc": proc.returncode,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "stdout": proc.stdout, "stderr_tail": proc.stderr[-1500:]}


def as_json(step):
    try:
        return json.loads(step["stdout"])
    except Exception:
        return None


def build_clone(dest: Path, branch: str | None) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"cloning {REAL_REPO} -> {dest}")
    r = run(["git", "clone", "--no-hardlinks", str(REAL_REPO), str(dest)],
            cwd=REAL_REPO.parent, label="clone", timeout=900)
    if r["rc"] != 0:
        raise SystemExit(f"clone failed: {r['stderr_tail']}")
    for k, v in (("user.name", "loadtest"), ("user.email", "loadtest@example.invalid")):
        run(["git", "config", k, v], cwd=dest, label=f"config {k}")
    if branch:
        # The clone's trunk must BE the branch under test: the tool being measured
        # lives on it, and every lane forks from the clone's main.
        r = run(["git", "checkout", "-B", "main", f"origin/{branch}"], cwd=dest,
                label="checkout")
        if r["rc"] != 0:
            raise SystemExit(f"checkout {branch} failed: {r['stderr_tail']}")
        log(f"clone trunk set to {branch}")
    return dest


def seed_shared_table(clone: Path) -> None:
    """One table on trunk that every lane will insert into at the same anchor."""
    path = clone / SHARED_TABLE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# load-test shared table\n\n"
        "Every lane inserts one row directly under the anchor, so every "
        "cherry-pick after the first conflicts.\n\n"
        "| lane | note |\n|---|---|\n"
        f"{SHARED_ANCHOR}\n", encoding="utf-8")
    run(["git", "add", SHARED_TABLE], cwd=clone, label="seed-add")
    run(["git", "commit", "-qm", "ops: seed load-test shared table"], cwd=clone,
        label="seed-commit")


def lane_row(i: int) -> str:
    return f"| lt-{i:02d} | row written by lane {i} |"


def make_lane_commit(wt: Path, i: int, conflict: str) -> list[dict]:
    """The change one lane makes. Routes to a real gate; optionally collides."""
    steps = []
    # `ops/**.sh` -> ops-shell-syntax (bash -n, block) + ops-shell-untested (warn).
    # The warn also exercises the "landed with warnings" path.
    fixture = wt / "ops" / "loadtest_fixtures" / f"lt_{i:02d}.sh"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        "#!/usr/bin/env bash\n"
        f"# synthetic load-test fixture; lane {i}\n"
        "set -euo pipefail\n"
        f"loadtest_lane_{i}() {{ printf '%s\\n' 'lane {i}'; }}\n", encoding="utf-8")
    paths = [str(fixture)]
    if conflict == "shared":
        table = wt / SHARED_TABLE
        text = table.read_text(encoding="utf-8")
        table.write_text(text.replace(SHARED_ANCHOR, f"{SHARED_ANCHOR}\n{lane_row(i)}"),
                         encoding="utf-8")
        paths.append(str(table))
    steps.append(run(["git", "add", *paths], cwd=wt, label="add"))
    steps.append(run(["git", "commit", "-m",
                      f"ops: load-test lane {i}\n\nReviewed-by: loadtest"],
                     cwd=wt, label="commit"))
    return steps


# ---------------------------------------------------------------------------
# mode: concurrent — every lane lands its own work
# ---------------------------------------------------------------------------

def concurrent_lane(clone: Path, i: int, verb: str, conflict: str, report: dict,
                    slow_seconds: float) -> None:
    slug = f"lt-{i:02d}"
    orch = clone / "ops" / "worktree_orchestrate.py"
    st = run([str(orch), "open", "--intent", f"load test lane {i}", "--slug", slug,
              "--json"], cwd=clone, label="open")
    steps = [st]
    payload = as_json(st)
    if st["rc"] != 0 or not payload or not payload.get("path"):
        report[slug] = {"steps": steps, "landed": False, "why": "open failed"}
        return
    wt = Path(payload["path"])
    wt_orch = wt / "ops" / "worktree_orchestrate.py"
    steps += make_lane_commit(wt, i, conflict)

    if verb == "land":
        if slow_seconds:
            time.sleep(slow_seconds)
        l = run([str(wt_orch), "land", "--worktree", str(wt), "--commit", "--json"],
                cwd=wt, label="land", timeout=5400)
        steps.append(l)
        lp = as_json(l) or {}
        landed = bool(lp.get("landed"))
        steps.append(run([str(orch), "resolve", "--worktree", str(wt), "--commit",
                          "--json"], cwd=clone, label="resolve"))
        report[slug] = {"steps": steps, "landed": landed, "attempts": 1,
                        "gate_runs": lp.get("gate_runs", 1),
                        "waited_for_turn_s": lp.get("waited_for_turn_s"),
                        "verdict": lp.get("verdict"),
                        "why": None if landed else lp.get("error", l["stderr_tail"][-300:])}
        return

    attempts, landed = 0, False
    while attempts < MAX_CUTOVER_ATTEMPTS and not landed:
        attempts += 1
        g = run([str(wt_orch), "gate", "--worktree", str(wt), "--json"], cwd=wt,
                label=f"gate#{attempts}")
        steps.append(g)
        verdict = (as_json(g) or {}).get("verdict")
        if verdict not in ("pass", "warn"):
            report[slug] = {"steps": steps, "landed": False, "attempts": attempts,
                            "why": f"gate verdict {verdict!r}"}
            return
        if slow_seconds:
            time.sleep(slow_seconds)
        c = run([str(wt_orch), "cutover", "--worktree", str(wt), "--commit", "--json"],
                cwd=wt, label=f"cutover#{attempts}")
        steps.append(c)
        cp = as_json(c) or {}
        if c["rc"] == 0 and cp.get("landed"):
            landed = True
            break
        err = cp.get("error", "")
        if "moved HEAD" not in err and "stale" not in err and "behind" not in err:
            report[slug] = {"steps": steps, "landed": False, "attempts": attempts,
                            "why": f"cutover refused: {err[:200]}"}
            return
    steps.append(run([str(clone / "ops" / "worktree_orchestrate.py"), "resolve",
                      "--worktree", str(wt), "--commit", "--json"], cwd=clone,
                     label="resolve"))
    report[slug] = {"steps": steps, "landed": landed, "attempts": attempts,
                    "gate_runs": sum(1 for s in steps if s["label"].startswith("gate"))}


# ---------------------------------------------------------------------------
# mode: batch — delegates stop at commit, ONE integrator lands
# ---------------------------------------------------------------------------

def resolve_keep_both(path: Path) -> bool:
    """Union-resolve one conflicted file: keep both sides, drop the markers.

    Deliberately mechanical and deliberately LOSSLESS. A human merging two table
    rows keeps both; a resolver that picks a side is how rows disappear. The run
    asserts row count afterwards, so a resolver that silently dropped one would
    turn the whole measurement green while destroying the thing it measures.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if "<<<<<<<" not in text:
        return False
    out, keep = [], []
    state = "plain"
    for line in text.splitlines():
        if line.startswith("<<<<<<<"):
            state, keep = "ours", []
            continue
        if line.startswith("=======") and state == "ours":
            state = "theirs"
            continue
        if line.startswith(">>>>>>>") and state == "theirs":
            state = "plain"
            continue
        if state == "plain":
            out.append(line)
        else:
            # Both halves, in order, de-duplicated: the anchor line appears on both
            # sides of every one of these conflicts and must not be doubled.
            if line not in keep:
                keep.append(line)
                out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True


def batch_mode(clone: Path, n: int, conflict: str, report: dict) -> dict:
    orch = clone / "ops" / "worktree_orchestrate.py"
    lanes: list[dict] = []

    # --- N delegates: each opens a worktree, commits, and STOPS. No gate, no
    #     cutover — that is the contract this mode exists to model.
    def delegate(i: int) -> None:
        slug = f"lt-{i:02d}"
        st = run([str(orch), "open", "--intent", f"batch lane {i}", "--slug", slug,
                  "--json"], cwd=clone, label="open")
        payload = as_json(st)
        if st["rc"] != 0 or not payload:
            report[slug] = {"stopped_at_commit": False, "why": "open failed",
                            "stderr": st["stderr_tail"][-300:]}
            return
        wt = Path(payload["path"])
        steps = make_lane_commit(wt, i, conflict)
        sha = run(["git", "rev-parse", "HEAD"], cwd=wt, label="sha")["stdout"].strip()
        rec = {"slug": slug, "branch": payload["branch"], "path": str(wt), "sha": sha,
               "stopped_at_commit": all(s["rc"] == 0 for s in steps)}
        lanes.append(rec)
        report[slug] = rec

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(delegate, range(n)))
    lanes.sort(key=lambda r: r["slug"])
    log(f"{len(lanes)}/{n} delegates stopped at commit; opening integration worktree")

    # --- ONE integrator.
    st = run([str(orch), "open", "--intent", "integrate the batch", "--slug",
              "integrate", "--json"], cwd=clone, label="open-integrator")
    ip = as_json(st)
    if st["rc"] != 0 or not ip:
        return {"error": "integration worktree failed", "stderr": st["stderr_tail"]}
    integ = Path(ip["path"])

    picks = []
    for rec in lanes:
        c = run(["git", "cherry-pick", rec["sha"]], cwd=integ, label=f"pick:{rec['slug']}")
        conflicted, resolved = [], []
        if c["rc"] != 0:
            status = run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=integ,
                         label="conflicts")["stdout"].split()
            conflicted = status
            for rel in status:
                if resolve_keep_both(integ / rel):
                    resolved.append(rel)
                    run(["git", "add", rel], cwd=integ, label="add-resolved")
            cont = run(["git", "-c", "core.editor=true", "cherry-pick", "--continue"],
                       cwd=integ, label="continue")
            if cont["rc"] != 0:
                run(["git", "cherry-pick", "--abort"], cwd=integ, label="abort")
                picks.append({"slug": rec["slug"], "ok": False,
                              "conflicted": conflicted, "resolved": resolved,
                              "why": cont["stderr_tail"][-200:]})
                continue
        picks.append({"slug": rec["slug"], "ok": True, "conflicted": conflicted,
                      "resolved": resolved})

    # --- the assertion this whole mode exists for: nothing silently dropped.
    rows_present, rows_missing = [], []
    if conflict == "shared":
        table = (integ / SHARED_TABLE).read_text(encoding="utf-8")
        for rec in lanes:
            i = int(rec["slug"].split("-")[1])
            (rows_present if lane_row(i) in table else rows_missing).append(rec["slug"])
    files_present = [rec["slug"] for rec in lanes
                     if (integ / "ops" / "loadtest_fixtures"
                         / f"lt_{int(rec['slug'].split('-')[1]):02d}.sh").exists()]

    g = run([str(integ / "ops" / "worktree_orchestrate.py"), "gate", "--worktree",
             str(integ), "--json"], cwd=integ, label="gate", timeout=5400)
    gate = as_json(g) or {}
    c = run([str(integ / "ops" / "worktree_orchestrate.py"), "cutover", "--worktree",
             str(integ), "--commit", "--json"], cwd=integ, label="cutover", timeout=3600)
    cut = as_json(c) or {}

    # --- teardown: the KNOWN trap. `resolve` judges "did this branch land" by
    #     tree-diff, and a cherry-picked branch whose files were later touched by
    #     conflict resolution can read as "not landed".
    teardown = []
    for rec in lanes:
        # Two attempts, and BOTH are recorded. The plain form is expected to refuse
        # (measured 10/10 before `--via-integration` existed) — keeping it in the
        # run is what stops the report from quietly becoming "teardown is fine now"
        # if the audit path is ever removed.
        plain = run([str(orch), "resolve", "--worktree", rec["path"], "--commit",
                     "--json"], cwd=clone, label=f"resolve:{rec['slug']}")
        vouched = None
        if plain["rc"] != 0:
            vouched = run([str(orch), "resolve", "--worktree", rec["path"],
                           "--via-integration", "main", "--commit", "--json"],
                          cwd=clone, label=f"resolve-vouched:{rec['slug']}")
        payload = as_json(vouched or plain) or {}
        matches = [c.get("match") for c in (payload.get("audit") or {}).get("commits", [])]
        teardown.append({
            "slug": rec["slug"],
            "floor_refused": plain["rc"] != 0,
            "vouched_rc": None if vouched is None else vouched["rc"],
            "torn_down": (vouched or plain)["rc"] == 0,
            "audit_matches": matches,
            "why": payload.get("error", "")[:160] if (vouched or plain)["rc"] else ""})
    r = run([str(orch), "resolve", "--worktree", str(integ), "--commit", "--json"],
            cwd=clone, label="resolve:integrate")
    teardown.append({"slug": "integrate", "floor_refused": r["rc"] != 0,
                     "vouched_rc": None, "torn_down": r["rc"] == 0,
                     "audit_matches": []})

    return {
        "delegates_stopped_at_commit": sum(1 for r in lanes if r["stopped_at_commit"]),
        "cherry_picks_ok": sum(1 for p in picks if p["ok"]),
        "cherry_picks_conflicted": sum(1 for p in picks if p["conflicted"]),
        "picks": picks,
        "shared_rows_present": len(rows_present),
        "shared_rows_missing": rows_missing,
        "lane_files_present": len(files_present),
        "gate_verdict": gate.get("verdict"),
        "gate_blocks": [x["name"] for x in gate.get("gates", [])
                        if x.get("status") == "block"],
        "cutover_landed": bool(cut.get("landed")),
        "cutover_error": cut.get("error"),
        "floor_refused": sum(1 for t in teardown if t["floor_refused"]),
        "torn_down_by_audit": sum(1 for t in teardown
                                  if t["floor_refused"] and t["torn_down"]),
        "still_stuck": [t["slug"] for t in teardown if not t["torn_down"]],
        "audit_match_kinds": sorted({m for t in teardown for m in t["audit_matches"]}),
        "teardown": teardown,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("concurrent", "batch"), default="batch",
                    help="'batch' = one integrator lands N delegates (the fan-out "
                         "contract, and what the backlog dogfood uses); "
                         "'concurrent' = independent sessions each landing their own")
    ap.add_argument("-n", type=int, default=10, help="lanes (default 10)")
    ap.add_argument("--conflict", choices=("shared", "none"), default="shared",
                    help="'shared' makes every lane touch one table at the same "
                         "anchor, so collisions are guaranteed. 'none' is the "
                         "disjoint-files case, which measures queueing only")
    ap.add_argument("--verb", choices=("manual", "land"), default="land",
                    help="concurrent mode only: 'land' uses the FIFO queue, "
                         "'manual' replays the documented gate/cutover sequence")
    ap.add_argument("--slow-lanes", type=int, default=0)
    ap.add_argument("--slow-seconds", type=float, default=20.0)
    ap.add_argument("--branch", default=None,
                    help="check this branch out as the clone's trunk first")
    ap.add_argument("--clone", default=None, help="where to put the throwaway clone")
    ap.add_argument("--keep", action="store_true", help="keep the clone for inspection")
    args = ap.parse_args()

    scratch = Path(os.environ.get("LOADTEST_SCRATCH", "/tmp")) / "kg-loadtest"
    clone = Path(args.clone) if args.clone else scratch / "clone"

    t0 = time.monotonic()
    build_clone(clone, args.branch)
    if args.conflict == "shared":
        seed_shared_table(clone)
    base = run(["git", "rev-parse", "HEAD"], cwd=clone, label="base")["stdout"].strip()
    log(f"base={base[:12]} mode={args.mode} n={args.n} conflict={args.conflict}")

    report: dict = {}
    if args.mode == "batch":
        result = batch_mode(clone, args.n, args.conflict, report)
    else:
        slow = set(range(args.slow_lanes))
        with ThreadPoolExecutor(max_workers=args.n) as pool:
            list(pool.map(
                lambda i: concurrent_lane(
                    clone, i, args.verb, args.conflict, report,
                    args.slow_seconds if i in slow else 0.0),
                range(args.n)))
        landed = [k for k, v in report.items() if v.get("landed")]
        result = {"landed": len(landed),
                  "not_landed": [k for k in report if k not in landed],
                  "total_gate_runs": sum(v.get("gate_runs", 0) for v in report.values()),
                  "gate_runs_over_ideal":
                      sum(v.get("gate_runs", 0) for v in report.values()) - args.n,
                  "waits_s": [report[k].get("waited_for_turn_s")
                              for k in sorted(report)]}

    post = {
        "trunk_commits_added": run(["git", "rev-list", "--count", f"{base}..HEAD"],
                                   cwd=clone, label="count")["stdout"].strip(),
        "primary_dirty": run(["git", "status", "--porcelain"], cwd=clone,
                             label="status")["stdout"].strip(),
        "worktrees_left": len([l for l in run(["git", "worktree", "list"], cwd=clone,
                                              label="wt")["stdout"].splitlines()
                               if l.strip()]) - 1,
        "validate_rc": run([str(clone / "ops" / "backlog.py"), "validate", "--json"],
                           cwd=clone, label="validate")["rc"],
    }
    summary = {"schema": "kg.loadtest.worktree.v2", "mode": args.mode, "n": args.n,
               "conflict": args.conflict,
               "verb": args.verb if args.mode == "concurrent" else None,
               "base": base, "wall_seconds": round(time.monotonic() - t0, 1),
               **result, "post": post}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    detail = clone.parent / "loadtest-detail.json"
    detail.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    log(f"per-lane detail -> {detail}")
    if not args.keep:
        log("clone kept for inspection")

    ok = (post["validate_rc"] == 0 and not post["primary_dirty"]
          and post["worktrees_left"] == 0)
    if args.mode == "batch":
        ok = (ok and result.get("cutover_landed")
              and not result.get("shared_rows_missing")
              and not result.get("still_stuck"))
    else:
        ok = ok and result.get("landed") == args.n
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
