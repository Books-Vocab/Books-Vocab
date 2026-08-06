#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Worktree registry: a birth→resolution ledger + orphan sentinel for git worktrees.

Every convergence/feature worktree is *born* (register), lives while an agent works
it, and is *resolved* (cutover=merged, or dropped=abandoned). The registry is the
書面登記閉環 the P3 orchestrator drives; `sweep` is the crash-recovery sentinel that
reconciles the ledger against on-disk git reality and proposes what to reclaim —
never destroying unlanded or unsaved work.

Architecture (mirrors the retired ops/converge_board.py, ops/ui_deadcode.py — three layers):
  IO layer      read-only git fact gathering (NEVER mutates git except the explicit
                `sweep --commit` clearance actions). fetch-first. Owns the ONE piece
                of real judgement here: `landed_in_base` computed by TREE-DIFF.
  pure layer    consumed from ops/lib/worktree_state.py (P1): classify(facts)->State
                and unsafe_to_drop(facts)->reason|None. This module NEVER re-implements
                a verdict — it gathers facts and defers every judgement to P1.
  render layer  human table / --json (schema kg.worktree.registry.v1)

⚠ TREE-DIFF CONTAINMENT (the whole point). `landed_in_base` answers "is this ref's
net change already present in base?" It is computed by comparing trees, NOT by
`git cherry` / patch-id. The retired converge_board._cherry_unmerged used `git cherry`, which
went WRONG after a rebase/squash (patch-ids drift) — reporting landed work as
unlanded or vice versa. This tool deliberately uses tree containment so a
squash-merged branch (commit sha differs, content already in base) is correctly
seen as landed. See `landed_in_base`.

Registry state file (per-machine, NEVER committed):
  anchored at  <dirname(git-common-dir)>/.cache/worktree_registry.json
  so every linked worktree shares ONE ledger (like the shared DerivedData anchor).
  schema kg.worktree.registry.v1:
    {"schema": ..., "records": [{path, branch, intent, base, created_at,
                                 status(active|merged|abandoned), resolved_at}]}
  Timestamps are taken in the CLI adapter (--at overrides for tests); the IO/pure
  layers read no clock.

Subcommands (register/resolve/sweep are the P3 orchestrator API, not just human):
  register   birth: record a new active worktree     (--path --branch --intent --base)
  list       ledger + live classify of each record   (table / --json)
  resolve    death: strike a worktree active record  (--branch|--path --status)
  sweep      orphan sentinel: fetch → gather every worktree/branch fact → P1
             classify + unsafe_to_drop → propose a CONSERVATIVE disposition. dry-run
             default; --commit executes clearance (remote branch → worktree remove →
             local branch), gated per-card by unsafe_to_drop.

             Absolute protection (the retired converge convention "main first, never teardown"): the base
             branch (--base, default origin/main, incl. its local branch) and the
             PRIMARY worktree (the main working tree / repo root) are NEVER CLEAR and
             never receive a `branch -D` / `worktree remove` — hard-excluded before any
             classify reasoning (see sweep_guards + _step_touches_protected).

             CLEAR is confined to three shapes; everything else is KEEP:
               (a) dangling landed branch — a branch, no worktree, landed+clean;
               (b) orphan detached worktree — detached, contained-in-base, clean;
               (c) registry-resolved subject — a record already merged/abandoned.
             A landed branch that STILL has a checked-out worktree is KEPT (reclaimable,
             awaiting resolve), never auto-cleared. On --commit, an ACTIVE record whose
             subject was cleared resolves to *merged* (not abandoned); a record whose
             worktree merely vanished is struck abandoned.

Exit codes: 0 ok | 64 usage error | 1 partial failure (sweep --commit).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Consume the P1 pure judgement layer — never re-implement a verdict here.
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import worktree_state as ws  # noqa: E402  (ops/lib shared pure module)

SCHEMA = "kg.worktree.registry.v1"
EXIT_OK = 0
EXIT_USAGE = 64
EXIT_PARTIAL = 1

STATUS_ACTIVE = "active"
RESOLVE_STATUS = ("merged", "abandoned")  # terminal states a resolve can set


# ============================================================================
# IO layer — read-only git. The ONLY writes live in `sweep --commit` clearance.
# ============================================================================
def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.stdout.strip()


def _git_ok(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out = proc.stdout.strip()
    if proc.returncode != 0 and proc.stderr.strip():
        out = (out + "\n" + proc.stderr.strip()).strip()
    return proc.returncode, out


def repo_root() -> Path:
    return Path(_git(["rev-parse", "--show-toplevel"]))


def common_anchor() -> Path:
    """dirname of the git common dir — the main working tree's root, shared by every
    linked worktree. The registry lives under here so all worktrees see one ledger."""
    cd = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if not cd:
        cd = _git(["rev-parse", "--git-common-dir"])
    return Path(cd).resolve().parent


def default_state_path() -> Path:
    return common_anchor() / ".cache" / "worktree_registry.json"


def fetch_origin() -> None:
    """fetch-first: base (main) moves under us. Best-effort — offline tolerated."""
    subprocess.run(
        ["git", "fetch", "origin", "--prune"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---- tree-diff containment (the anti-`git cherry` core) ---------------------
def _merge_base(a: str, b: str) -> str | None:
    rc, out = _git_ok(["merge-base", a, b])
    if rc != 0 or not out:
        return None
    return out.strip()


def _diff_names(a: str, b: str) -> tuple[bool, set[str]]:
    """(ok, changed_paths) for `git diff --name-only a b`. ok=False on git error
    (without --exit-code the rc is 0 whether or not there is a diff, so a non-zero
    rc means a genuine failure → the caller must fail safe)."""
    rc, out = _git_ok(["diff", "--name-only", a, b])
    if rc != 0:
        return (False, set())
    return (True, {ln for ln in out.splitlines() if ln})


def landed_in_base(base: str, ref: str) -> bool:
    """TREE-DIFF containment: is `ref`'s net change already present in `base`?

    NOT computed via `git cherry` / patch-id — those drift after a rebase/squash and
    are the exact bug (the retired converge_board._cherry_unmerged) this tool must not repeat.

    Method (fork-relative tree comparison):
      mb      = merge-base(base, ref)                      # the fork point
      changed = paths ref changed since mb  (diff mb..ref) # ref's contribution
      differ  = paths where ref and base trees differ now  (diff ref..base)
    ref is landed ⟺ NONE of ref's changed paths differ between ref and base, i.e.
    base already holds ref's version of everything ref touched (adds/mods/deletes):
        changed.isdisjoint(differ)

    This is correct for a squash-merge (ref's commit sha absent from base, yet its
    content present): `changed` = the touched paths, `differ` = ∅ ⇒ landed. A branch
    ancestor of base: `changed` = ∅ ⇒ landed. A branch with unique work: its path is
    in both sets ⇒ not landed. Fails safe (not landed) on unrelated histories or any
    git error so a bad read never green-lights dropping work."""
    mb = _merge_base(base, ref)
    if mb is None:
        return False  # unrelated histories / error → fail safe
    ok, changed = _diff_names(mb, ref)
    if not ok:
        return False
    if not changed:
        return True  # ref net-changed nothing vs the fork point → fully in base
    ok2, differ = _diff_names(ref, base)
    if not ok2:
        return False
    return changed.isdisjoint(differ)


# ---- topology / worktree facts ---------------------------------------------
def _rev_list_count(base: str, ref: str) -> tuple[int, int]:
    """(behind, ahead) = (commits in base not ref, commits in ref not base)."""
    rc, out = _git_ok(["rev-list", "--left-right", "--count", f"{base}...{ref}"])
    if rc != 0 or not out:
        return (0, 0)
    parts = out.split()
    if len(parts) != 2:
        return (0, 0)
    return (int(parts[0]), int(parts[1]))


def _head_epoch(ref: str, cwd: Path | None = None) -> int | None:
    """Commit time (unix seconds) of `ref`'s tip, or None if unresolved."""
    rc, out = _git_ok(["log", "-1", "--format=%ct", ref], cwd=cwd)
    if rc != 0 or not out:
        return None
    try:
        return int(out.splitlines()[0])
    except (ValueError, IndexError):
        return None


def _is_dirty(worktree_path: str) -> bool:
    rc, out = _git_ok(["status", "--porcelain"], cwd=Path(worktree_path))
    return rc == 0 and bool(out.strip())


def _upstream(branch: str) -> str | None:
    up = _git(["for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch}"])
    return up or None


def _local_branches() -> list[str]:
    return [
        b for b in _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"]).splitlines()
        if b
    ]


def _remote_branch_exists(name: str, remote: str = "origin") -> bool:
    rc, out = _git_ok(["ls-remote", "--heads", remote, name])
    return rc == 0 and bool(out.strip())


def parse_worktree_porcelain(out: str) -> list[dict[str, Any]]:
    """Pure parser for `git worktree list --porcelain` — split out so the record
    shape can be asserted on a string literal instead of a real repo."""
    worktrees: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    for line in out.splitlines():
        if not line:
            if cur:
                worktrees.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line == "prunable" or line.startswith("prunable "):
            cur["prunable"] = line[len("prunable "):] or "prunable"
        elif line == "locked" or line.startswith("locked "):
            # a locked worktree is exempt from `git worktree prune` even when broken,
            # so "broken" and "reapable" are not the same question
            cur["locked"] = line[len("locked "):] or "locked"
    if cur:
        worktrees.append(cur)
    return worktrees


def _worktrees() -> list[dict[str, Any]]:
    """Parse `git worktree list --porcelain` into records with keys
    path / head / branch (short) / detached / bare / prunable.

    `prunable` carries git's own reason string (e.g. "gitdir file points to
    non-existent location") and is the signal that a worktree's administrative link
    is broken while its directory survives — an interrupted teardown. It is recorded
    because git's answer here stays truthful when `rev-parse` no longer is: repository
    discovery walks UP out of a `.git`-less directory and reports the ENCLOSING
    checkout instead (see worktree_orchestrate._worktree_entry)."""
    return parse_worktree_porcelain(_git(["worktree", "list", "--porcelain"]))


# ---- sweep guards: base branch + primary worktree are NEVER swept ----------
def sweep_guards(base: str) -> tuple[str | None, set[str]]:
    """(primary_worktree_path_normalized, protected_branch_names) — the two things a
    sweep must NEVER tear down (the retired converge convention: "main first, never teardown").

      * primary worktree = the MAIN working tree (the repo root), always the first
        entry of `git worktree list`. Removing it destroys the repository; a running
        session lives there. Never a CLEAR candidate, never `worktree remove`-d.
      * base branch = the `--base` ref (and, since --base defaults to origin/main, the
        LOCAL branch it tracks). Deleting it (`branch -D main`) is catastrophic. We
        also protect whatever branch the primary worktree currently has checked out.

    This is a hard, absolute exclusion applied BEFORE any classify/CLEAR reasoning."""
    wts = _worktrees()
    primary = _norm(wts[0]["path"]) if wts else None
    protected: set[str] = set()
    if base:
        protected.add(base)
        if "/" in base:               # origin/main -> also protect the local branch 'main'
            protected.add(base.split("/", 1)[1])
    if wts and wts[0].get("branch"):  # whatever the main working tree has checked out
        protected.add(wts[0]["branch"])
    return primary, protected


def _step_touches_protected(
    gargs: list[str], primary_path: str | None, protected_branches: set[str]
) -> bool:
    """Safety net: True if this git clearance step would delete the base branch or
    remove the primary worktree. CLEAR never contains protected subjects, so this
    should never fire — belt-and-suspenders so a bug upstream can never emit a
    repository-destroying `branch -D main` / `worktree remove <repo>`.

    The subject is located by skipping option tokens rather than by index. Reading a
    fixed `gargs[2]` made this silently blind to `worktree remove --force <primary>`
    — it inspected the string `--force` — which is precisely the argv shape the
    orchestrator's resolve emits, so the one caller most in need of the net was the
    one it did not cover."""
    def _subject(argv: list[str], start: int) -> str | None:
        for tok in argv[start:]:
            if not tok.startswith("-"):
                return tok
        return None

    if gargs[:2] == ["branch", "-D"]:
        subject = _subject(gargs, 2)
        if subject is not None and subject in protected_branches:
            return True
    if gargs[:2] == ["worktree", "remove"]:
        subject = _subject(gargs, 2)
        if subject is not None and primary_path and _norm(subject) == primary_path:
            return True
    if gargs[:1] == ["push"] and "--delete" in gargs and gargs[-1] in protected_branches:
        return True
    return False


# ============================================================================
# facts assembly — gather read-only facts, defer EVERY verdict to P1.
# ============================================================================
def build_facts(
    base: str,
    *,
    name: str | None,
    detached: bool,
    worktree_path: str | None,
    head_sha: str | None,
    now_epoch: int,
    live_window: int,
    registered_active: bool,
) -> dict[str, Any]:
    """Produce ONE P1 `facts` dict (see worktree_state.py contract). The ref to
    inspect is the branch (when on a branch) or the detached HEAD sha."""
    ref = name if (name and not detached) else (head_sha or "HEAD")
    landed = landed_in_base(base, ref)
    behind, ahead = _rev_list_count(base, ref)
    dirty = _is_dirty(worktree_path) if worktree_path else False
    head_epoch = _head_epoch(ref, cwd=Path(worktree_path) if worktree_path else None)
    head_age = (now_epoch - head_epoch) if head_epoch is not None else None
    has_origin = bool(name) and _upstream(name) is not None

    # unique_commits (P1 REQUIRED): landed → 0. Not landed → the topological ahead
    # count, but at least 1 so P1.classify never mis-files uncontained work as MERGED
    # (P1's own belt-and-suspenders would still refuse the drop, but this keeps
    # classify honest: uncontained work reads ACTIVE/DIVERGED, not MERGED).
    if landed:
        unique = 0
    else:
        unique = ahead if ahead > 0 else 1

    return {
        "name": name,
        "detached": detached,
        "dirty": dirty,
        "ahead": ahead,               # advisory
        "behind": behind,
        "unique_commits": unique,     # REQUIRED
        "landed_in_base": landed,     # REQUIRED (tree-diff)
        "head_age_s": head_age,
        "live_window_s": live_window,
        "has_worktree": worktree_path is not None,
        "has_origin": has_origin,     # advisory
        "registered_active": registered_active,
    }


def _norm(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _subject(
    facts: dict[str, Any],
    *,
    kind: str,
    worktree_path: str | None,
    head_sha: str | None,
    tracked: bool,
    registry_status: str | None,
    protected: bool,
    protected_reason: str | None,
    excluded: bool = False,
) -> dict[str, Any]:
    """Classify + safety-gate ONE subject via P1, attach a CONSERVATIVE disposition.

    Safety floors (any forces KEEP, in this precedence):
      protected            base branch / primary worktree — NEVER swept (hard rule).
      excluded             the worktree the sweep was invoked FROM (--exclude-current):
                           an orchestrator running a preflight sweep from inside a live
                           worktree must never propose clearing itself. Highest KEEP
                           floor after `protected` — applies even to an otherwise-CLEAR
                           detached orphan whose root == the caller's cwd.
      unsafe_to_drop != None  live / dirty / unlanded / uncontained — dropping loses
                           work (P1 verdict; classify alone can orphan commits, so the
                           unsafe gate is mandatory).

    Given a safe (unsafe is None), non-protected subject, CLEAR is confined to three
    shapes; EVERYTHING else is KEEP:
      (a) dangling landed branch   — a branch, no worktree, landed+clean.
      (b) orphan detached worktree — detached, contained-in-base, clean.
      (c) registry-resolved        — a record already resolved (merged/abandoned);
                                     honoured even with an open worktree.
    In particular a landed branch that STILL has a checked-out worktree is KEPT
    (reclaimable, awaiting resolve) — never auto-cleared, lest an agent's live
    worktree be removed out from under it."""
    state = ws.classify(facts)
    unsafe = ws.unsafe_to_drop(facts)
    name = facts.get("name")
    has_wt = bool(facts.get("has_worktree"))
    detached = bool(facts.get("detached"))
    landed = bool(facts.get("landed_in_base"))

    keep_reason: str | None = None
    if protected:
        disposition = "KEEP"
        keep_reason = protected_reason or "base branch / primary worktree — never teardown"
    elif excluded:
        disposition = "KEEP"
        keep_reason = "excluded: sweep invoked from this worktree (--exclude-current) — never self-clear"
    elif unsafe is not None:
        disposition = "KEEP"
        keep_reason = unsafe
    elif registry_status in RESOLVE_STATUS:
        disposition = "CLEAR"                                   # (c) operator resolved it
    elif detached and has_wt and landed:
        disposition = "CLEAR"                                   # (b) contained detached orphan
    elif (not has_wt) and landed and name is not None:
        disposition = "CLEAR"                                   # (a) dangling landed branch
    else:
        disposition = "KEEP"
        if landed and has_wt and name is not None:
            keep_reason = "landed, reclaimable — resolve to clear (open worktree)"
        else:
            keep_reason = "not eligible for clearance (kept by default)"

    label = name
    if label is None:
        label = f"(detached {(head_sha or '')[:8]})"
    return {
        "kind": kind,
        "name": name,
        "label": label,
        "path": worktree_path,
        "state": state.value,
        "landed": landed,
        "dirty": bool(facts.get("dirty")),
        "detached": detached,
        "ahead": facts.get("ahead", 0),
        "behind": facts.get("behind", 0),
        "unique": facts.get("unique_commits", 0),
        "has_origin": bool(facts.get("has_origin")),
        "tracked": tracked,
        "untracked": not tracked,
        "registry_status": registry_status,
        "protected": bool(protected),
        "excluded": bool(excluded),
        "unsafe": unsafe,
        "keep_reason": keep_reason,
        "disposition": disposition,
    }


def gather_sweep(
    base: str,
    now_epoch: int,
    live_window: int,
    records: list[dict[str, Any]],
    *,
    exclude_path: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconcile the on-disk git reality against the active ledger.

    Returns (subjects, stale_entries):
      subjects       one card per worktree (branch or detached) + per worktree-less
                     local branch, each with a CLEAR/KEEP disposition. The base branch
                     and primary worktree are always present but forced KEEP+protected.
      stale_entries  active records whose worktree path no longer exists on disk AND
                     whose branch is NOT itself being cleared (a cleared dangling-landed
                     branch resolves to merged via nit1, not abandoned).

    exclude_path   normalized path of the worktree the sweep was invoked FROM
                   (--exclude-current). Its worktree subject is force-KEPT (excluded=True)
                   so an orchestrator's preflight sweep never proposes clearing itself.
    """
    active = [r for r in records if r.get("status") == STATUS_ACTIVE]
    reg_paths = {_norm(r["path"]) for r in active if r.get("path")}
    reg_branches = {r["branch"] for r in active if r.get("branch")}

    # resolved (merged/abandoned) records → registry_status for CLEAR shape (c).
    resolved_by_branch: dict[str, str] = {}
    resolved_by_path: dict[str, str] = {}
    for r in records:
        st = r.get("status")
        if st in RESOLVE_STATUS:
            if r.get("branch"):
                resolved_by_branch[r["branch"]] = st
            if r.get("path"):
                resolved_by_path[_norm(r["path"])] = st

    def _registry_status(name: str | None, path: str | None) -> str | None:
        # an active record wins; else the branch/path's last resolved status, if any.
        if (name is not None and name in reg_branches) or (path is not None and _norm(path) in reg_paths):
            return STATUS_ACTIVE
        if name is not None and name in resolved_by_branch:
            return resolved_by_branch[name]
        if path is not None and _norm(path) in resolved_by_path:
            return resolved_by_path[_norm(path)]
        return None

    primary_path, protected_branches = sweep_guards(base)

    def _protection(is_primary: bool, branch: str | None) -> tuple[bool, str | None]:
        bits = []
        if is_primary:
            bits.append("primary worktree (main working tree)")
        if branch is not None and branch in protected_branches:
            bits.append(f"base branch {branch!r}")
        if not bits:
            return False, None
        return True, " / ".join(bits) + " — never teardown (main-first invariant)"

    subjects: list[dict[str, Any]] = []
    seen_branches: set[str] = set()
    seen_paths: set[str] = set()

    # 1. worktree-carried subjects (branch or detached)
    for wt in _worktrees():
        if wt.get("bare"):
            continue
        path = wt["path"]
        npath = _norm(path)
        seen_paths.add(npath)
        branch = wt.get("branch")
        detached = bool(wt.get("detached"))
        if branch:
            seen_branches.add(branch)
        is_primary = primary_path is not None and npath == primary_path
        protected, protected_reason = _protection(is_primary, branch)
        excluded = exclude_path is not None and npath == exclude_path
        registered = npath in reg_paths or (branch is not None and branch in reg_branches)
        facts = build_facts(
            base, name=branch, detached=detached, worktree_path=path,
            head_sha=wt.get("head"), now_epoch=now_epoch, live_window=live_window,
            registered_active=registered,
        )
        subjects.append(_subject(
            facts, kind="worktree", worktree_path=path, head_sha=wt.get("head"),
            tracked=registered, registry_status=_registry_status(branch, path),
            protected=protected, protected_reason=protected_reason, excluded=excluded,
        ))

    # 2. local branches with no worktree
    for b in _local_branches():
        if b in seen_branches:
            continue
        protected, protected_reason = _protection(False, b)
        registered = b in reg_branches
        facts = build_facts(
            base, name=b, detached=False, worktree_path=None, head_sha=None,
            now_epoch=now_epoch, live_window=live_window, registered_active=registered,
        )
        subjects.append(_subject(
            facts, kind="branch", worktree_path=None, head_sha=None, tracked=registered,
            registry_status=_registry_status(b, None),
            protected=protected, protected_reason=protected_reason,
        ))

    # 3. stale registry entries — active record whose worktree path vanished AND whose
    #    branch is NOT being cleared (nit1: a cleared dangling-landed branch is resolved
    #    to merged, so it must not be double-counted here and struck as abandoned).
    cleared_branches = {s["name"] for s in subjects if s["disposition"] == "CLEAR" and s.get("name")}
    stale: list[dict[str, Any]] = []
    for r in active:
        p = r.get("path")
        if not p or _norm(p) in seen_paths:
            continue
        if r.get("branch") in cleared_branches:
            continue
        if not Path(p).exists():
            stale.append(r)

    return subjects, stale


# ============================================================================
# registry state IO (local JSON ledger — NOT git-tracked)
# ============================================================================
def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "records": []}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError(f"malformed registry state at {path}")
    data.setdefault("schema", SCHEMA)
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    # atomic: write a sibling temp then os.replace, so a reader (or a crash mid-write)
    # never sees a half-written ledger — the swap is a single rename syscall.
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body)
        os.replace(tmp, path)
    finally:
        # a raise between write and replace would otherwise strand the temp; the
        # replace consumes it on success, so this only fires on the failure path.
        tmp.unlink(missing_ok=True)


@contextmanager
def _ledger_lock(state_path: Path):
    """Exclusive lock over one ledger's whole read-modify-write, so concurrent
    register / resolve / sweep from parallel hands-off sessions cannot lose each
    other's updates (the ledger is a shared JSON file; unlocked RMW is last-writer-
    wins). An advisory flock on a sidecar `<ledger>.lock` — the kernel drops it when
    the fd closes, so a crashed holder never leaves a stale lock (unlike an O_EXCL
    marker file). Blocking acquire with no timeout is safe: every writer's critical
    section terminates (register/resolve are a small-JSON load+mutate+save; sweep also
    runs git under the lock, so it can hold for seconds — still bounded), and a dead
    holder auto-releases, so no deadlock can form. Advisory only — every WRITER must
    take it; load_state stays lock-free for read-only callers, which the atomic
    save_state protects from torn reads."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _try_acquire_ledger_lock_nb(state_path: Path) -> bool:
    """True if the ledger lock is currently free (non-blocking acquire+release),
    False if another open file description holds it. Inspection/tests only — never a
    substitute for holding `_ledger_lock` across a real read-modify-write."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


# ============================================================================
# CLI adapter — the ONLY place a clock is read (or --at overrides it).
# ============================================================================
def _parse_at(at: str) -> datetime:
    at = at.strip()
    if at.isdigit():
        return datetime.fromtimestamp(int(at), tz=timezone.utc)
    dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_now(at: str | None) -> tuple[int, str]:
    """(epoch_seconds, iso8601) for 'now'. --at overrides the clock for tests."""
    if at:
        dt = _parse_at(at)
        return int(dt.timestamp()), dt.isoformat()
    now = datetime.now(timezone.utc)
    return int(now.timestamp()), now.isoformat()


def _state_path(args: argparse.Namespace) -> Path:
    return Path(args.state).resolve() if args.state else default_state_path()


# ============================================================================
# render layer
# ============================================================================
def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    sep = "  "
    out = [sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append(sep.join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        out.append(sep.join(cell.ljust(widths[i]) for i, cell in enumerate(r)))
    return "\n".join(out)


def _short_path(p: str | None) -> str:
    if not p:
        return "-"
    parts = Path(p).parts
    return "…/" + "/".join(parts[-2:]) if len(parts) >= 2 else p


# ============================================================================
# subcommands
# ============================================================================
def cmd_register(args: argparse.Namespace) -> int:
    _, now_iso = resolve_now(args.at)
    path = os.path.abspath(args.path)
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]

    # upsert-by-branch/path among ACTIVE records (idempotent for the orchestrator):
    # a re-register of a live worktree refreshes its intent/base/path in place.
    #
    # A branch-match and a DISTINCT path-match can BOTH be active (branch B_old lives
    # at this path; branch B was checked out elsewhere). Updating only the first would
    # leave two active records sharing one path. So collapse ALL matches: keep the
    # first as the survivor, and terminally close the rest (displaced by a re-checkout
    # — not merged, hence "abandoned"). This holds the invariant INDUCTIVELY: register
    # is the sole creator of active records, so if it never lets the incoming branch
    # OR path collide with a surviving active peer, then "at most one active record
    # per branch AND per path" holds across the whole ledger. It only reconciles
    # matches to THIS branch/path — an unrelated pre-existing collision is cleared when
    # register next touches it, or by sweep.
    matches = [
        r for r in records
        if r.get("status") == STATUS_ACTIVE
        and (r.get("branch") == args.branch
             or (r.get("path") and _norm(r["path"]) == _norm(path)))
    ]
    if matches:
        # the branch is the ledger's identity key, so the branch-match record is the
        # survivor (this branch moved worktrees); whatever else held the target path
        # is the displaced one. Falls back to the sole path-match when no branch-match.
        rec = next((r for r in matches if r.get("branch") == args.branch), matches[0])
        displaced = [r for r in matches if r is not rec]
        rec.update({
            "path": path, "branch": args.branch,
            "intent": args.intent, "base": args.base,
        })
        for d in displaced:
            d["status"] = "abandoned"
            d["resolved_at"] = now_iso
            d["note"] = f"superseded by re-register of {args.branch} at {path}"
        verb = "updated"
    else:
        rec = {
            "path": path, "branch": args.branch, "intent": args.intent,
            "base": args.base, "created_at": now_iso,
            "status": STATUS_ACTIVE, "resolved_at": None,
        }
        records.append(rec)
        verb = "registered"

    save_state(state_path, state)
    if args.json:
        print(json.dumps({"schema": SCHEMA, "action": verb, "record": rec},
                         indent=2, ensure_ascii=False))
    else:
        print(f"✓ {verb} [{args.branch}] intent={args.intent!r} base={args.base}")
        print(f"  path: {path}")
        print(f"  ledger: {state_path}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]

    enriched: list[dict[str, Any]] = []
    for r in records:
        view = dict(r)
        if r.get("status") == STATUS_ACTIVE and r.get("branch"):
            now_epoch, _ = resolve_now(args.at)
            facts = build_facts(
                r.get("base") or "main", name=r["branch"], detached=False,
                worktree_path=(r["path"] if r.get("path") and Path(r["path"]).exists() else None),
                head_sha=None, now_epoch=now_epoch, live_window=args.live_window,
                registered_active=True,
            )
            view["live_state"] = ws.classify(facts).value
            view["landed"] = bool(facts["landed_in_base"])
            view["worktree_present"] = bool(r.get("path") and Path(r["path"]).exists())
        enriched.append(view)

    if args.json:
        print(json.dumps({"schema": SCHEMA, "ledger": str(state_path), "records": enriched},
                         indent=2, ensure_ascii=False))
        return EXIT_OK

    if not records:
        print(f"(empty ledger: {state_path})")
        return EXIT_OK
    headers = ["branch", "intent", "base", "status", "live", "wt", "created", "resolved"]
    rows = []
    for v in enriched:
        rows.append([
            str(v.get("branch") or "-"),
            str(v.get("intent") or "-"),
            str(v.get("base") or "-"),
            str(v.get("status") or "-"),
            str(v.get("live_state") or "-"),
            ("yes" if v.get("worktree_present") else "-") if v.get("status") == STATUS_ACTIVE else "-",
            str(v.get("created_at") or "-")[:19],
            str(v.get("resolved_at") or "-")[:19],
        ])
    print(f"# ledger: {state_path}\n")
    print(_table(headers, rows))
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    _, now_iso = resolve_now(args.at)
    if args.status not in RESOLVE_STATUS:
        print(f"✗ --status must be one of {RESOLVE_STATUS}", file=sys.stderr)
        return EXIT_USAGE
    if not args.branch and not args.path:
        print("✗ resolve needs --branch or --path", file=sys.stderr)
        return EXIT_USAGE

    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]
    target_path = _norm(args.path) if args.path else None

    matches = [
        r for r in records
        if r.get("status") == STATUS_ACTIVE
        and (
            (args.branch and r.get("branch") == args.branch)
            or (target_path and r.get("path") and _norm(r["path"]) == target_path)
        )
    ]
    if not matches:
        sel = f"branch={args.branch}" if args.branch else f"path={args.path}"
        print(f"✗ no active registry record for {sel}", file=sys.stderr)
        return EXIT_USAGE

    for r in matches:
        r["status"] = args.status
        r["resolved_at"] = now_iso
    save_state(state_path, state)

    if args.json:
        print(json.dumps({"schema": SCHEMA, "action": "resolve", "status": args.status,
                          "records": matches}, indent=2, ensure_ascii=False))
    else:
        for r in matches:
            print(f"✓ resolved [{r.get('branch') or r.get('path')}] -> {args.status} @ {now_iso}")
    return EXIT_OK


def _clear_steps(subject: dict[str, Any], root: Path) -> list[tuple[str, list[str], Path]]:
    """Ordered clearance steps for a CLEAR subject: remote branch → worktree remove
    → local branch. (worktree remove BEFORE branch delete: a branch checked out in a
    worktree cannot be deleted.) Only emits steps that apply to this subject shape."""
    steps: list[tuple[str, list[str], Path]] = []
    name = subject.get("name")
    path = subject.get("path")
    if name and _remote_branch_exists(name):
        steps.append(("delete remote branch", ["push", "origin", "--delete", name], root))
    if path:
        steps.append(("remove worktree", ["worktree", "remove", path], root))
    if name:
        steps.append(("delete local branch", ["branch", "-D", name], root))
    return steps


def _exec_step(label: str, gargs: list[str], cwd: Path, commit: bool, quiet: bool = False) -> bool:
    """Preview (dry-run) or run (commit) one clearance git step. `quiet` suppresses
    stdout (JSON mode) while still executing under --commit. Returns True on success."""
    shown = "git " + " ".join(gargs)
    if not commit:
        if not quiet:
            print(f"     {shown}   # {label}")
        return True
    rc, out = _git_ok(gargs, cwd=cwd)
    if not quiet:
        print(f"     {'✓' if rc == 0 else '✗'} {shown}   # {label}")
        if rc != 0 and out:
            print(f"        {out}")
    return rc == 0


def cmd_sweep(args: argparse.Namespace) -> int:
    if not args.no_fetch:
        fetch_origin()
    now_epoch, now_iso = resolve_now(args.at)
    root = repo_root()
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]

    # --exclude-current: never propose clearing the worktree the sweep runs FROM.
    # The invoking worktree's root is `git rev-parse --show-toplevel` at cwd (= root
    # here, since cmd_sweep uses cwd's git context throughout).
    exclude_path = _norm(str(root)) if args.exclude_current else None

    subjects, stale = gather_sweep(
        args.base, now_epoch, args.live_window, records, exclude_path=exclude_path
    )
    clears = [s for s in subjects if s["disposition"] == "CLEAR"]
    keeps = [s for s in subjects if s["disposition"] == "KEEP"]
    mode = "committed" if args.commit else "dry-run"

    # Build the clearance plan up front. clears already excludes base/primary; this
    # filter is a hard safety net so a repository-destroying step can never be emitted.
    primary_path, protected_branches = sweep_guards(args.base)
    plans: list[tuple[dict[str, Any], list[tuple[str, list[str], Path]]]] = []
    for s in clears:
        safe_steps = [
            step for step in _clear_steps(s, root)
            if not _step_touches_protected(step[1], primary_path, protected_branches)
        ]
        plans.append((s, safe_steps))

    # ---- human tables first (printed before execution, non-json) ----------
    if not args.json:
        print(f"# worktree sweep ({mode}, base={args.base}) — orphan sentinel\n")
        if keeps:
            print("── KEEP (protected / live / dirty / unlanded / open-worktree) ──")
            headers = ["subject", "state", "landed", "prot", "untracked", "reason"]
            rows = [[
                s["label"], s["state"], "yes" if s["landed"] else "-",
                "PROT" if s.get("protected") else "-",
                "UNTRACKED" if s["untracked"] else "-",
                s.get("keep_reason") or s.get("unsafe") or "-",
            ] for s in keeps]
            print(_table(headers, rows))
            print()
        if clears:
            print("── CLEAR (dangling-landed / detached-orphan / resolved) ──")
            headers = ["subject", "state", "untracked", "worktree"]
            rows = [[
                s["label"], s["state"],
                "UNTRACKED" if s["untracked"] else "-",
                _short_path(s["path"]),
            ] for s in clears]
            print(_table(headers, rows))
            print()
        if stale:
            print("── STALE-ENTRY (registered but worktree gone → strike ledger) ──")
            for r in stale:
                print(f"  {r.get('branch') or '-'}   {r.get('path')}")
            print()
        if not (keeps or clears or stale):
            print("(nothing to sweep)")

    # ---- execute / preview clearance -------------------------------------
    failures = 0
    executed: list[dict[str, Any]] = []
    for s, safe_steps in plans:
        if not args.json:
            print(f"## clear {s['label']}  [{s['state']}]"
                  + ("  (UNTRACKED)" if s["untracked"] else ""))
        step_results = []
        for label, gargs, cwd in safe_steps:
            ok = _exec_step(label, gargs, cwd, args.commit, quiet=args.json)
            step_results.append({"label": label, "cmd": "git " + " ".join(gargs), "ok": ok})
            if not ok:
                failures += 1
        executed.append({"label": s["label"], "name": s.get("name"), "steps": step_results})

    # ---- ledger reconciliation (only on --commit) -------------------------
    # nit1: an ACTIVE record whose subject was CLEARed resolves to *merged* — a
    # successful landing/clearance. It must NOT later be struck as abandoned by the
    # stale path just because its worktree is now gone.
    cleared_branches = {s["name"] for s in clears if s.get("name")}
    cleared_paths = {_norm(s["path"]) for s in clears if s.get("path")}
    resolved_merged = 0
    struck = 0
    if args.commit:
        for r in records:
            if r.get("status") != STATUS_ACTIVE:
                continue
            if r.get("branch") in cleared_branches or (r.get("path") and _norm(r["path"]) in cleared_paths):
                r["status"] = "merged"
                r["resolved_at"] = now_iso
                resolved_merged += 1
        for r in stale:
            if r.get("status") != STATUS_ACTIVE:   # skip any just flipped to merged
                continue
            r["status"] = "abandoned"
            r["resolved_at"] = now_iso
            struck += 1
        if resolved_merged or struck:
            save_state(state_path, state)

    if not args.json:
        if struck:
            print(f"\n✓ struck {struck} stale ledger entry(ies) -> abandoned")
        elif stale:
            print(f"\n# {len(stale)} stale ledger entry(ies) would be struck (--commit to write)")
        if resolved_merged:
            print(f"✓ resolved {resolved_merged} cleared record(s) -> merged")
        if not args.commit:
            print("\n# dry-run only — re-run with --commit to execute clearance.")

    # ---- json (printed AFTER execution so committed mode reflects results) -
    if args.json:
        payload: dict[str, Any] = {
            "schema": SCHEMA, "mode": mode, "base": args.base,
            "clear": clears, "keep": keeps,
            "stale_entries": [
                {"branch": r.get("branch"), "path": r.get("path"), "intent": r.get("intent")}
                for r in stale
            ],
            "plan": [
                {"label": s["label"], "name": s.get("name"), "path": s.get("path"),
                 "cmds": ["git " + " ".join(gargs) for (_lbl, gargs, _cwd) in safe_steps]}
                for (s, safe_steps) in plans
            ],
        }
        if args.commit:
            payload["executed"] = executed
            payload["failures"] = failures
            payload["resolved_merged"] = resolved_merged
            payload["struck_stale"] = struck
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return EXIT_OK if failures == 0 else EXIT_PARTIAL


# ============================================================================
# argparse
# ============================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="worktree_registry.py",
        description=(
            "Worktree registry — birth→resolution ledger + orphan sentinel. "
            "Judgement (classify / unsafe_to_drop) is deferred to the P1 pure layer "
            "ops/lib/worktree_state.py; containment uses TREE-DIFF, never git cherry. "
            "See module docstring for the state file schema and layer contract."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def add_state(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--state", default=None,
                        help="registry state file (default: <git-common-dir dirname>/.cache/worktree_registry.json)")
        sp.add_argument("--at", default=None,
                        help="override 'now' (ISO8601 or epoch seconds) — for tests/determinism")

    def add_base(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--base", default="origin/main",
            help="baseline ref for containment (default: origin/main — the LOCAL base "
                 "may lag origin, which would hide already-landed work; compare against "
                 "the remote so a merged branch reads as landed)",
        )
        sp.add_argument("--live-window", type=int, default=ws.LIVE_WINDOW_DEFAULT_S,
                        help=f"seconds; HEAD younger than this = live agent (default {ws.LIVE_WINDOW_DEFAULT_S})")

    reg = sub.add_parser("register", help="birth: record a new active worktree")
    add_state(reg)
    reg.add_argument("--path", required=True, help="worktree path")
    reg.add_argument("--branch", required=True, help="branch name checked out in it")
    reg.add_argument("--intent", required=True, help="why this worktree exists (short)")
    reg.add_argument("--base", default="main", help="baseline ref it forks from (default: main)")
    reg.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    reg.set_defaults(func=cmd_register)

    ls = sub.add_parser("list", help="ledger + live classify of each record")
    add_state(ls)
    ls.add_argument("--live-window", type=int, default=ws.LIVE_WINDOW_DEFAULT_S,
                    help="seconds; live-agent window for the live classify column")
    ls.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    ls.set_defaults(func=cmd_list)

    rs = sub.add_parser("resolve", help="death: strike a worktree's active record")
    add_state(rs)
    rs.add_argument("--branch", default=None, help="branch of the record to resolve")
    rs.add_argument("--path", default=None, help="path of the record to resolve")
    rs.add_argument("--status", required=True, choices=list(RESOLVE_STATUS),
                    help="merged (cutover) | abandoned (dropped)")
    rs.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    rs.set_defaults(func=cmd_resolve)

    sw = sub.add_parser(
        "sweep",
        help="orphan sentinel: fetch → classify every worktree/branch → propose "
             "clearance (dry-run default; --commit executes; unsafe work refused)",
    )
    add_state(sw)
    add_base(sw)
    sw.add_argument("--no-fetch", action="store_true", help="skip git fetch (offline / tests)")
    sw.add_argument("--exclude-current", action="store_true",
                    help="never propose clearing the worktree the sweep is invoked FROM "
                         "(self-exclusion; lets the P3 orchestrator preflight from any worktree)")
    sw.add_argument("--commit", action="store_true", help="execute clearance (default: dry-run)")
    sw.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    sw.set_defaults(func=cmd_sweep)

    return p


def main(argv: list[str] | None = None) -> int:
    tokens = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(tokens)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    # Serialize the WRITERS over the shared ledger so parallel hands-off sessions
    # cannot lose each other's updates (each mutator is a load→mutate→save RMW on one
    # JSON file). Read-only commands (list) run lock-free — the atomic save_state
    # keeps their reads from tearing. The lock spans the whole mutator, so its
    # internal load_state/save_state are one indivisible critical section.
    if args.func in (cmd_register, cmd_resolve, cmd_sweep):
        with _ledger_lock(_state_path(args)):
            return args.func(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
