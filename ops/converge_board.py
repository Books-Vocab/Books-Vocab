#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Converge board: classify every branch + worktree into cards for convergence.

Each branch/worktree is a *card* on a *board*; the agent (or user) tags each card
with a *disposition* (white / black / B / freeze / snap) and the converge skill
executes. This tool removes the per-round hand-rolled bash that re-derives every
branch's state; it answers "what is the shape right now, and what would I do".

Architecture (mirrors ops/ui_quality_plane.py, ops/ui_deadcode.py):
  IO layer      read-only git fact gathering (NEVER writes git). fetch-first.
  pure layer    classify(facts) -> State ; suggest_disposition(State, facts) -> Mark
                (unit-tested with synthetic facts dicts; no IO).
  render layer  human table  /  --json (schema kg.converge.board.v1)

Subcommands:
  board               (default) gather facts, classify, render the board
  plan --marks "..."  dry-run: given dispositions, print the git action plan
                      per card (NEVER executes -- a safety preview)
  teardown --branches a,b [--commit]
                      white-mode branch teardown executor: detach holding
                      worktree -> delete local -> delete remote -> verify clean.
                      dry-run default; refuses any branch not landed in base.
  gc [--commit]       prune detached worktrees that are clean AND contained in
                      base; refuses dirty / uncontained ones. dry-run default.
  receipt             given before/after board JSON + round metadata, emit the
                      fixed one-round markdown record (time passed in, not now())

teardown / gc are the only writing subcommands; both are dry-run unless --commit,
and every write is gated by the pure `unsafe_to_drop` predicate.

States (canonical):
  CURRENT     == main (0 unique, clean): identical baseline
  MERGED      patch fully in main but ref still carries old commits (redundant)
  AHEAD       unique committed work, clean, on top of main
  DIRTY       worktree has uncommitted changes (dominates)
  DIVERGED    local rebased, origin tracking ref behind (needs sync push)
  STALE_BASE  behind main, needs rebase
  ORPHAN      detached worktree, no branch

Dispositions (board marks):
  white / W    absorb into main + delete branch (worktree kept unless said)
  black / K    rebase onto latest main + keep (main not advanced); sync origin
  B / promote  land committed work into main + keep branch + rebase + sync
  freeze / F   do nothing (live agent / not ready)
  snap / S     modifier: snapshot-commit dirty work first, then the disposition
  clean        prune an orphan worktree

Exit codes: 0 ok | 64 usage error | 1 partial failure (teardown/gc --commit).
"""

from __future__ import annotations

import argparse
import enum
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "kg.converge.board.v1"
EXIT_OK = 0
EXIT_USAGE = 64


# ----------------------------------------------------------------------------
# canonical enums
# ----------------------------------------------------------------------------
class State(enum.Enum):
    CURRENT = "CURRENT"
    MERGED = "MERGED"
    AHEAD = "AHEAD"
    DIRTY = "DIRTY"
    DIVERGED = "DIVERGED"
    STALE_BASE = "STALE_BASE"
    ORPHAN = "ORPHAN"


class Mark(enum.Enum):
    WHITE = "white"      # absorb into main + delete branch
    BLACK = "black"      # rebase + keep, main not advanced
    PROMOTE = "B"        # land committed work + keep + rebase + sync
    FREEZE = "freeze"    # do nothing
    SNAP = "snap"        # snapshot dirty first (modifier; standalone = snap+resolve)
    CLEAN = "clean"      # prune orphan worktree


# Aliases accepted on the `plan --marks` CLI (and in user shorthand).
MARK_ALIASES = {
    "w": Mark.WHITE, "white": Mark.WHITE, "白": Mark.WHITE, "W": Mark.WHITE,
    "k": Mark.BLACK, "black": Mark.BLACK, "黑": Mark.BLACK, "K": Mark.BLACK,
    "b": Mark.PROMOTE, "promote": Mark.PROMOTE, "B": Mark.PROMOTE,
    "f": Mark.FREEZE, "freeze": Mark.FREEZE, "凍": Mark.FREEZE, "F": Mark.FREEZE,
    "s": Mark.SNAP, "snap": Mark.SNAP, "存": Mark.SNAP, "S": Mark.SNAP,
    "clean": Mark.CLEAN, "清": Mark.CLEAN,
}


def parse_mark(token: str) -> Mark:
    t = token.strip()
    if t in MARK_ALIASES:
        return MARK_ALIASES[t]
    lo = t.lower()
    if lo in MARK_ALIASES:
        return MARK_ALIASES[lo]
    raise KeyError(token)


# ----------------------------------------------------------------------------
# pure layer (unit-tested) — no IO
# ----------------------------------------------------------------------------
def classify(facts: dict[str, Any]) -> State:
    """Map gathered facts to a canonical state. Pure; precedence matters.

    Precedence (most-specific first):
      ORPHAN     detached worktree (no branch to act on) — dominates dirty
      DIRTY      uncommitted worktree changes — dominates committed-state buckets
      then by committed shape:
        CURRENT     no unique work, not behind   (== main)
        MERGED      ref ahead but cherry says patch already in main (redundant)
        STALE_BASE  behind main (needs rebase before it can land cleanly)
        DIVERGED    origin tracking ref diverged from local (needs sync push)
        AHEAD       unique committed work on top of main
    """
    if facts.get("detached"):
        return State.ORPHAN
    if facts.get("dirty"):
        return State.DIRTY

    ahead = int(facts.get("ahead", 0))
    behind = int(facts.get("behind", 0))
    unmerged = int(facts.get("unmerged", 0))

    # No unique patch left relative to main.
    if unmerged == 0:
        # A remote-only ref (different name living on origin, no local branch) with
        # no unique patch is a redundant remote ref to delete — never CURRENT,
        # which means "this ref IS main".
        if facts.get("remote_only"):
            return State.MERGED
        # If the ref still carries commits (ahead>0) those patches already
        # landed in main under different hashes -> redundant ref = MERGED.
        # Otherwise it is literally at/under main = CURRENT.
        if ahead > 0:
            return State.MERGED
        return State.CURRENT

    # There is unique committed work (unmerged > 0).
    if behind > 0:
        return State.STALE_BASE

    # local has committed work the origin tracking ref lacks -> needs sync push.
    if facts.get("has_origin") and int(facts.get("origin_ahead", 0)) > 0:
        return State.DIVERGED

    return State.AHEAD


def _is_live(facts: dict[str, Any]) -> bool:
    """Heuristic: unique committed work whose HEAD is a recent commit is probably
    an active agent — flag it, suggest FREEZE. Covers both a local worktree
    (live local agent) and a freshly pushed remote-only ref (live cloud session)."""
    return bool(
        (facts.get("worktree") or facts.get("remote_only"))
        and int(facts.get("unmerged", 0)) > 0
        and facts.get("head_recent")
    )


def suggest_disposition(state: State, facts: dict[str, Any]) -> Mark:
    """Recommend a board mark for a state. Pure; every State has an answer."""
    if state is State.ORPHAN:
        return Mark.CLEAN
    if state is State.DIRTY:
        return Mark.SNAP
    if state is State.MERGED:
        return Mark.WHITE          # redundant ref: absorb (already in main) + delete
    if state is State.CURRENT:
        return Mark.BLACK          # keep synced (rebase no-op) / leave alone
    if state in (State.STALE_BASE, State.DIVERGED):
        return Mark.BLACK          # needs rebase / origin sync, no main advance implied
    if state is State.AHEAD:
        if _is_live(facts):
            return Mark.FREEZE     # don't touch a live agent
        return Mark.PROMOTE        # has landable committed work
    return Mark.FREEZE             # unreachable; defensive


def unsafe_to_drop(facts: dict[str, Any]) -> str | None:
    """Guard for *destructive* dispositions (teardown a branch / gc a worktree):
    return a human reason when dropping the card would LOSE work, else None.

    Pure. Three ways a drop loses work, in precedence:
      dirty            uncommitted changes (would vanish; snapshot first, never stash)
      branch unmerged  committed work not yet in base (cherry '+' > 0)
      detached !contained  detached HEAD is not an ancestor of base (orphans commits)

    A clean branch with unmerged==0 (all patches landed in main, even rebased
    under new hashes) is safe to delete. A clean detached worktree whose HEAD is
    contained in base is safe to prune. Everything else is refused — this is the
    predicate that turns the advisory plan into a tool that cannot destroy work.
    """
    if facts.get("dirty"):
        return "dirty: uncommitted changes (snapshot first; never stash)"
    if facts.get("detached"):
        if not facts.get("contained", False):
            return "detached HEAD not contained in base (carries commits not in main)"
        return None
    unmerged = int(facts.get("unmerged", 0))
    if unmerged > 0:
        return f"{unmerged} commit(s) not yet in base (not landed — would be lost)"
    return None


# ----------------------------------------------------------------------------
# IO layer — read-only git. NEVER mutates.
# ----------------------------------------------------------------------------
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
    return proc.returncode, proc.stdout.strip()


def repo_root() -> Path:
    return Path(_git(["rev-parse", "--show-toplevel"]))


def fetch_origin() -> None:
    """fetch-first: main moves under us; refresh origin refs before gathering.
    Best-effort — offline / no-remote is tolerated (board still classifies local)."""
    subprocess.run(
        ["git", "fetch", "origin", "--prune"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _rev_list_count(rev_a: str, rev_b: str) -> tuple[int, int]:
    """Return (behind, ahead) = (commits in a not b, commits in b not a) for
    `git rev-list --left-right --count a...b`."""
    rc, out = _git_ok(["rev-list", "--left-right", "--count", f"{rev_a}...{rev_b}"])
    if rc != 0 or not out:
        return (0, 0)
    parts = out.split()
    if len(parts) != 2:
        return (0, 0)
    return (int(parts[0]), int(parts[1]))


def _cherry_unmerged(base: str, branch: str) -> int:
    """`git cherry base branch` '+' lines = patches not yet in base."""
    rc, out = _git_ok(["cherry", base, branch])
    if rc != 0:
        return 0
    return sum(1 for ln in out.splitlines() if ln.startswith("+"))


def _is_ancestor(rev: str, base: str) -> bool:
    """True if `rev` is an ancestor of `base` (i.e. fully contained in base).
    Used to decide a detached worktree carries no commits absent from base."""
    if not rev:
        return False
    rc, _ = _git_ok(["merge-base", "--is-ancestor", rev, base])
    return rc == 0


def _remote_branch_exists(name: str, remote: str = "origin") -> bool:
    """Read-only: True if `<remote>` still carries a branch named `name`."""
    rc, out = _git_ok(["ls-remote", "--heads", remote, name])
    return rc == 0 and bool(out.strip())


def _worktree_map() -> dict[str, dict[str, Any]]:
    """Parse `git worktree list --porcelain` into {ref_or_HEAD: {...}}.
    Keyed by branch short-name when on a branch; detached entries collected
    separately under synthetic keys."""
    out = _git(["worktree", "list", "--porcelain"])
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
            ref = line[len("branch "):]
            cur["branch"] = ref.replace("refs/heads/", "")
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line == "locked" or line.startswith("locked "):
            cur["locked"] = True
    if cur:
        worktrees.append(cur)
    return {"_list": worktrees}  # type: ignore[dict-item]


def _is_dirty(worktree_path: str) -> bool:
    rc, out = _git_ok(["status", "--porcelain"], cwd=Path(worktree_path))
    return rc == 0 and bool(out.strip())


def _head_recent(worktree_path: str, within_seconds: int) -> bool:
    """True if the worktree HEAD commit is younger than `within_seconds`."""
    return _rev_recent("HEAD", within_seconds, cwd=Path(worktree_path))


def _rev_recent(rev: str, within_seconds: int, cwd: Path | None = None) -> bool:
    """True if `rev`'s commit time is younger than `within_seconds`. Works for a
    worktree HEAD or any ref (e.g. a remote-only origin/<branch> tip)."""
    rc, out = _git_ok(["log", "-1", "--format=%ct", rev], cwd=cwd)
    if rc != 0 or not out:
        return False
    try:
        committed_at = int(out)
    except ValueError:
        return False
    # System time is read only here in the IO layer, never in the pure classifier.
    import time

    return (int(time.time()) - committed_at) < within_seconds


def gather_facts(
    base: str = "main",
    live_window_seconds: int = 7200,
) -> list[dict[str, Any]]:
    """Read-only: produce one facts dict per card (branch and detached worktree).

    Cards = every local branch except the base + every detached worktree.
    """
    wt = _worktree_map()["_list"]
    # path -> worktree record, and branch -> path
    branch_to_wt: dict[str, dict[str, Any]] = {}
    detached: list[dict[str, Any]] = []
    for rec in wt:
        if rec.get("detached"):
            detached.append(rec)
        elif rec.get("branch"):
            branch_to_wt[rec["branch"]] = rec

    cards: list[dict[str, Any]] = []

    # local branches
    branches = [
        b for b in _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"]).splitlines()
        if b
    ]
    local_names = set(branches)
    tracked_upstreams: set[str] = set()  # origin refs already owned by a local branch
    for b in branches:
        is_main = b == base
        behind, ahead = _rev_list_count(base, b)
        unmerged = 0 if is_main else _cherry_unmerged(base, b)
        wtrec = branch_to_wt.get(b)
        wt_path = wtrec["path"] if wtrec else None
        dirty = _is_dirty(wt_path) if wt_path else False

        has_origin = False
        origin_behind = origin_ahead = 0
        upstream = _git(["for-each-ref", "--format=%(upstream:short)", f"refs/heads/{b}"])
        if upstream:
            has_origin = True
            tracked_upstreams.add(upstream)
            # local-perspective: origin_ahead = local commits origin lacks (needs
            # push); origin_behind = origin commits local lacks (needs pull).
            origin_ahead, origin_behind = _rev_list_count(b, upstream)

        head_recent = bool(wt_path) and _head_recent(wt_path, live_window_seconds)

        cards.append({
            "name": b,
            "is_main": is_main,
            "detached": False,
            "remote_only": False,
            "ahead": ahead,
            "behind": behind,
            "unmerged": unmerged,
            "dirty": dirty,
            "has_origin": has_origin,
            "origin_ahead": origin_ahead,
            "origin_behind": origin_behind,
            "worktree": wt_path,
            "head_recent": head_recent,
            # branch "landed in base" == cherry says no unique patch remains.
            "contained": unmerged == 0,
        })

    # remote-only branches: refs/remotes/origin/* that no local branch owns. These
    # are pushed by cloud sessions / other machines and have NO local ref and NO
    # worktree; scanning only refs/heads above made the board blind to them, so a
    # freshly pushed unmerged cloud branch read as fully converged. We surface each
    # as a card the same way — classify on (ahead/behind/unmerged) vs base.
    remote_refs = [
        r for r in _git(
            ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]
        ).splitlines() if r
    ]
    for ref in remote_refs:
        if ref == "origin" or ref.endswith("/HEAD"):
            continue  # origin/HEAD symbolic pointer, not a branch
        name = ref[len("origin/"):] if ref.startswith("origin/") else ref
        if name == base or name in local_names or ref in tracked_upstreams:
            continue  # the base itself, or already represented by a local branch
        behind, ahead = _rev_list_count(base, ref)
        unmerged = _cherry_unmerged(base, ref)
        head_recent = _rev_recent(ref, live_window_seconds)
        cards.append({
            "name": name,
            "is_main": False,
            "detached": False,
            "remote_only": True,
            "ahead": ahead,
            "behind": behind,
            "unmerged": unmerged,
            "dirty": False,            # no worktree -> never dirty
            "has_origin": True,        # it lives on origin by definition
            "origin_ahead": 0,
            "origin_behind": 0,
            "worktree": None,
            "head_recent": head_recent,
            "contained": unmerged == 0,
        })

    # detached worktrees (orphans)
    for rec in detached:
        wt_path = rec["path"]
        head_full = rec.get("head", "")
        cards.append({
            "name": None,
            "is_main": False,
            "detached": True,
            "ahead": 0,
            "behind": 0,
            "unmerged": 0,
            "dirty": _is_dirty(wt_path),
            "has_origin": False,
            "origin_ahead": 0,
            "origin_behind": 0,
            "worktree": wt_path,
            "head": head_full[:8],
            "head_recent": _head_recent(wt_path, live_window_seconds),
            # detached "contained" == HEAD is an ancestor of base; a detached
            # worktree carrying commits absent from base must NOT be pruned blindly.
            "contained": _is_ancestor(head_full, base),
        })

    return cards


# ----------------------------------------------------------------------------
# card assembly (facts -> classified card)
# ----------------------------------------------------------------------------
def build_card(facts: dict[str, Any]) -> dict[str, Any]:
    state = classify(facts)
    mark = suggest_disposition(state, facts)
    live = _is_live(facts)
    return {
        "name": facts.get("name") or ("(detached " + str(facts.get("head", "")) + ")"),
        "state": state.value,
        "suggest": mark.value,
        "ahead": facts.get("ahead", 0),
        "behind": facts.get("behind", 0),
        "unique": facts.get("unmerged", 0),
        "dirty": bool(facts.get("dirty")),
        "origin": (
            "none" if not facts.get("has_origin")
            else f"+{facts.get('origin_ahead', 0)}/-{facts.get('origin_behind', 0)}"
        ),
        "worktree": facts.get("worktree"),
        "live": live,
        "is_main": bool(facts.get("is_main")),
        "remote_only": bool(facts.get("remote_only")),
    }


# ----------------------------------------------------------------------------
# plan layer (dry-run action preview) — pure given (cards, marks)
# ----------------------------------------------------------------------------
def plan_actions(card: dict[str, Any], mark: Mark) -> list[str]:
    """Return the ordered git action steps a disposition implies. Never executes."""
    name = card["name"]
    wt = card.get("worktree")
    dirty = card.get("dirty")
    steps: list[str] = []

    # An ORPHAN has no branch to absorb/rebase/keep: the only coherent action is
    # pruning its worktree, regardless of any bulk mark applied to it.
    if card.get("state") == State.ORPHAN.value:
        steps.append(f"git worktree remove {wt}" if wt else "git worktree prune --verbose")
        if mark not in (Mark.CLEAN, Mark.FREEZE):
            steps.append(f"# note: '{mark.value}' is a no-op on a detached worktree; pruned instead")
        return steps

    # A remote-only card has NO local branch and NO worktree: never `git branch -D`
    # and never a worktree rebase. Absorption merges the origin ref; teardown is a
    # pure remote-ref delete.
    if card.get("remote_only"):
        if mark is Mark.FREEZE:
            steps.append(f"# FREEZE {name}: no action (live cloud session / not ready)")
        elif mark is Mark.CLEAN:
            steps.append(f"# CLEAN is a no-op on remote-only {name} (no worktree to prune)")
        elif mark is Mark.WHITE:
            steps.append(f"# assemble origin/{name} into the single candidate (git merge origin/{name})")
            steps.append("#   -> end-of-round: ONE build-gate of the candidate commit, then push main")
            steps.append(f"git push origin --delete {name}      # delete remote ref (no local branch / worktree)")
        elif mark in (Mark.PROMOTE, Mark.SNAP):
            steps.append(f"# assemble committed work of origin/{name} into the single candidate")
            steps.append(f"# remote-only: origin/{name} KEPT (no local checkout to rebase)")
        elif mark is Mark.BLACK:
            steps.append("# remote-only: no local worktree to rebase. To rebase + sync:")
            steps.append(f"#   git fetch origin {name} && git checkout -b {name} FETCH_HEAD && "
                         f"git rebase origin/main && git push origin {name} --force-with-lease")
            steps.append("# or leave the remote ref untouched (main NOT advanced)")
        return steps

    snap = mark is Mark.SNAP
    # SNAP standalone = snapshot the dirty work, then land it. Once snapshotted the
    # card carries committed work, so the natural follow-through is PROMOTE.
    effective = mark
    if snap:
        if dirty and wt:
            steps.append(f"git -C {wt} add -A && git -C {wt} commit -m 'ops: snapshot — <desc> (converge pre-op)'")
        effective = Mark.PROMOTE
    elif dirty and wt:
        # any non-snap disposition on a dirty card MUST snapshot first (never stash)
        steps.append(f"git -C {wt} add -A && git -C {wt} commit -m 'ops: snapshot — <desc> (converge pre-op)'  # dirty: never stash")

    if effective is Mark.FREEZE:
        steps.append(f"# FREEZE {name}: no action (live agent / not ready)")
        return steps

    if effective is Mark.CLEAN:
        steps.append(f"git worktree remove {wt}" if wt else "git worktree prune --verbose")
        return steps

    if effective is Mark.WHITE:
        steps.append(f"# assemble {name} into the single candidate (merge into integration HEAD)")
        steps.append("#   -> end-of-round: ONE build-gate of the candidate commit, then push main")
        steps.append(f"git branch -D {name}                 # delete local branch")
        steps.append(f"git push origin --delete {name}      # delete remote (skip if absent)")
        steps.append(f"# worktree {wt} KEPT (white deletes branch, not worktree)" if wt else "# (no worktree)")
        return steps

    if effective is Mark.PROMOTE:
        steps.append(f"# assemble committed work of {name} into the single candidate")
        steps.append("#   -> end-of-round: ONE build-gate of the candidate commit, then push main")
        if wt:
            steps.append(f"git -C {wt} fetch origin main && git -C {wt} rebase origin/main")
            if card.get("origin") != "none":
                steps.append(f"git -C {wt} push origin HEAD --force-with-lease   # sync origin")
        steps.append(f"# branch {name} KEPT")
        return steps

    if effective is Mark.BLACK:
        if wt:
            steps.append(f"git -C {wt} fetch origin main && git -C {wt} rebase origin/main")
            if card.get("origin") != "none":
                steps.append(f"git -C {wt} push origin HEAD --force-with-lease   # sync origin")
        else:
            steps.append(f"# branch {name} has no worktree: rebase via temp checkout or skip")
        steps.append("# main NOT advanced; branch KEPT")
        return steps

    return steps


# ----------------------------------------------------------------------------
# render layer
# ----------------------------------------------------------------------------
def render_board_table(cards: list[dict[str, Any]]) -> str:
    headers = ["card", "state", "tip(a/b)", "unique", "dirty", "origin", "worktree", "suggest"]
    rows = []
    for c in cards:
        wt = c.get("worktree") or "-"
        wt_short = wt
        if wt != "-":
            wt_short = "…/" + "/".join(Path(wt).parts[-2:])
        elif c.get("remote_only"):
            wt_short = "(remote-only)"
        live = " ⚡live" if c.get("live") else ""
        rows.append([
            c["name"] + (" *main" if c.get("is_main") else ""),
            c["state"],
            f"{c.get('ahead', 0)}/{c.get('behind', 0)}",
            str(c.get("unique", 0)),
            "yes" if c.get("dirty") else "-",
            c.get("origin", "none"),
            wt_short,
            c["suggest"] + live,
        ])
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


def board_json(cards: list[dict[str, Any]], base: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "base": base, "cards": cards}


# ----------------------------------------------------------------------------
# receipt layer (round record). Time passed in — NEVER datetime.now().
# ----------------------------------------------------------------------------
def render_receipt(
    round_at: str,
    before: dict[str, Any],
    after: dict[str, Any],
    marks: dict[str, str],
    candidate_sha: str,
    gate_verdict: str,
    main_before: str,
    main_after: str,
    pushed: list[str],
    deleted: list[str],
    kept: list[str],
) -> str:
    def card_state_map(board: dict[str, Any]) -> dict[str, str]:
        return {c["name"]: c["state"] for c in board.get("cards", [])}

    bstates = card_state_map(before)
    astates = card_state_map(after)
    names = sorted(set(bstates) | set(astates) | set(marks))

    lines = [
        f"## Converge round — {round_at}",
        "",
        f"**candidate:** `{candidate_sha}`  **gate:** {gate_verdict}",
        f"**main:** `{main_before}` → `{main_after}`",
        "",
        "| card | before | disposition | after |",
        "|------|--------|-------------|-------|",
    ]
    for n in names:
        lines.append(
            f"| {n} | {bstates.get(n, '-')} | {marks.get(n, '-')} | {astates.get(n, '-')} |"
        )
    lines += [
        "",
        f"**pushed:** {', '.join(pushed) if pushed else '—'}",
        f"**deleted:** {', '.join(deleted) if deleted else '—'}",
        f"**kept:** {', '.join(kept) if kept else '—'}",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def cmd_board(args: argparse.Namespace) -> int:
    if not args.no_fetch:
        fetch_origin()
    facts = gather_facts(base=args.base, live_window_seconds=args.live_window)
    cards = [build_card(f) for f in facts]
    # stable ordering: main first, then by state severity, then name
    severity = {
        State.DIRTY.value: 0, State.ORPHAN.value: 1, State.STALE_BASE.value: 2,
        State.DIVERGED.value: 3, State.AHEAD.value: 4, State.MERGED.value: 5,
        State.CURRENT.value: 6,
    }
    cards.sort(key=lambda c: (not c["is_main"], severity.get(c["state"], 9), c["name"]))
    if args.json:
        print(json.dumps(board_json(cards, args.base), indent=2, ensure_ascii=False))
    else:
        print(render_board_table(cards))
    return EXIT_OK


def cmd_plan(args: argparse.Namespace) -> int:
    if not args.no_fetch:
        fetch_origin()
    facts = gather_facts(base=args.base, live_window_seconds=args.live_window)
    cards = {c["name"]: c for c in (build_card(f) for f in facts)}

    # parse --marks "card=mark,card=mark" ; "all=mark" applies to every card
    marks: dict[str, Mark] = {}
    spec = args.marks or ""
    bulk: Mark | None = None
    for token in [t for t in spec.split(",") if t.strip()]:
        if "=" not in token:
            print(f"✗ bad mark spec (need card=mark): {token!r}", file=sys.stderr)
            return EXIT_USAGE
        card_name, mark_str = (s.strip() for s in token.split("=", 1))
        try:
            mark = parse_mark(mark_str)
        except KeyError:
            print(f"✗ unknown mark: {mark_str!r}", file=sys.stderr)
            return EXIT_USAGE
        if card_name in ("all", "全"):
            bulk = mark
        else:
            marks[card_name] = mark

    print(f"# converge plan (dry-run, base={args.base}) — NO git is executed\n")
    for name, card in cards.items():
        if card.get("is_main"):
            continue
        mark = marks.get(name, bulk)
        if mark is None:
            mark = MARK_ALIASES_BY_VALUE(card["suggest"])
            origin = "suggested"
        else:
            origin = "requested"
        print(f"## {name}  [{card['state']}]  ->  {mark.value}  ({origin})")
        for step in plan_actions(card, mark):
            print(f"   {step}")
        print()
    return EXIT_OK


def MARK_ALIASES_BY_VALUE(value: str) -> Mark:
    for m in Mark:
        if m.value == value:
            return m
    return Mark.FREEZE


# ----------------------------------------------------------------------------
# mutation layer — the ONLY git WRITES in this module, reached solely through
# `teardown` / `gc`. Both are dry-run by default; `--commit` executes. Every
# write is gated by the pure `unsafe_to_drop` predicate, so the tool cannot
# delete a branch / prune a worktree that still holds unlanded or dirty work.
# ----------------------------------------------------------------------------
def _exec_step(label: str, gargs: list[str], cwd: Path | None, commit: bool) -> bool:
    """Print (dry-run) or run (commit) one git step. Returns True on success."""
    shown = "git " + " ".join(gargs) + (f"   (in {cwd})" if cwd else "")
    if not commit:
        print(f"   {shown}   # {label}")
        return True
    rc, out = _git_ok(gargs, cwd=cwd)
    print(f"   {'✓' if rc == 0 else '✗'} {shown}   # {label}")
    if rc != 0 and out:
        print(f"      {out}")
    return rc == 0


def cmd_teardown(args: argparse.Namespace) -> int:
    """White-mode branch teardown: detach holding worktree -> delete local ->
    delete remote -> verify remote clean. Refuses any branch not fully landed in
    base (this is the step that, hand-rolled, silently dropped the remote delete)."""
    if not args.no_fetch:
        fetch_origin()
    base = args.base
    root = repo_root()
    facts = gather_facts(base=base, live_window_seconds=args.live_window)
    by_name = {f["name"]: f for f in facts if f.get("name")}
    targets = [t.strip() for t in (args.branches or "").split(",") if t.strip()]
    if not targets:
        print("✗ teardown needs --branches a,b", file=sys.stderr)
        return EXIT_USAGE

    refused: list[tuple[str, str]] = []
    safe: list[dict[str, Any]] = []
    for name in targets:
        f = by_name.get(name)
        if f is None:
            refused.append((name, "no such local branch"))
        elif f.get("is_main"):
            refused.append((name, "refusing to tear down the base branch"))
        elif (reason := unsafe_to_drop(f)) is not None:
            refused.append((name, reason))
        else:
            safe.append(f)

    mode = "EXECUTE" if args.commit else "dry-run"
    print(f"# converge teardown ({mode}, base={base})\n")
    for name, why in refused:
        print(f"✗ REFUSE {name}: {why}")
    if refused and not args.force:
        print(
            f"\n✗ {len(refused)} card(s) refused; nothing executed. Land/snapshot "
            "them, or pass --force to tear down only the safe ones.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    failures = 0
    for f in safe:
        name = f["name"]
        wt = f.get("worktree")
        remote_only = bool(f.get("remote_only"))
        print(f"\n## teardown {name}  [{classify(f).value}]")
        # remote-only card: no holding worktree, no local branch — go straight to
        # the remote ref delete (the local steps below would fail on a missing ref).
        if not remote_only:
            if wt and not _exec_step("detach worktree HEAD (keep worktree)",
                                     ["switch", "--detach"], Path(wt), args.commit):
                failures += 1
            if not _exec_step("delete local branch", ["branch", "-D", name], root, args.commit):
                failures += 1
        # remote delete is idempotent: only act when origin still carries it.
        if args.commit:
            if _remote_branch_exists(name):
                if not _exec_step("delete remote branch",
                                  ["push", "origin", "--delete", name], root, True):
                    failures += 1
            else:
                print("   (remote branch absent — skip remote delete)")
        else:
            _exec_step("delete remote branch IF present on origin",
                       ["push", "origin", "--delete", name], root, False)

    if args.commit and safe:
        still = [f["name"] for f in safe if _remote_branch_exists(f["name"])]
        if still:
            failures += 1
            print(f"\n✗ remote still carries: {', '.join(still)}")
        else:
            print(f"\n✓ remote verified clean for: {', '.join(f['name'] for f in safe)}")
    if not args.commit:
        print("\n# dry-run only — re-run with --commit to execute.")
    return EXIT_OK if failures == 0 else 1


def cmd_gc(args: argparse.Namespace) -> int:
    """Prune detached worktrees that are clean AND contained in base. Refuses
    (keeps + reports) any detached worktree that is dirty or carries commits not
    in base. Branch worktrees are never auto-pruned — that is teardown's job."""
    if not args.no_fetch:
        fetch_origin()
    base = args.base
    facts = gather_facts(base=base, live_window_seconds=args.live_window)
    orphans = [f for f in facts if f.get("detached") and f.get("worktree")]
    mode = "EXECUTE" if args.commit else "dry-run"
    print(f"# converge gc ({mode}, base={base}) — prune contained+clean detached worktrees only\n")
    if not orphans:
        print("(no detached worktrees)")
        return EXIT_OK

    failures = pruned = kept = 0
    for f in orphans:
        wt = f["worktree"]
        label = f"{f.get('head', '')}  {wt}"
        if (reason := unsafe_to_drop(f)) is not None:
            kept += 1
            print(f"  KEEP   {label}\n         ↳ {reason}")
            continue
        if not args.commit:
            pruned += 1
            print(f"  PRUNE  {label}   (git worktree remove {wt})")
            continue
        rc, out = _git_ok(["worktree", "remove", wt])
        if rc == 0:
            pruned += 1
            print(f"  ✓ PRUNED {label}")
        else:
            failures += 1
            print(f"  ✗ FAIL   {label}\n         {out}")
    if args.commit:
        _git_ok(["worktree", "prune"])
    tail = "" if args.commit else " (dry-run; --commit to execute)"
    print(f"\n# {pruned} prunable, {kept} kept{tail}")
    return EXIT_OK if failures == 0 else 1


def cmd_receipt(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())
    marks: dict[str, str] = {}
    for token in [t for t in (args.marks or "").split(",") if t.strip()]:
        if "=" in token:
            k, v = token.split("=", 1)
            marks[k.strip()] = v.strip()
    out = render_receipt(
        round_at=args.round_at,
        before=before,
        after=after,
        marks=marks,
        candidate_sha=args.candidate_sha,
        gate_verdict=args.gate_verdict,
        main_before=args.main_before,
        main_after=args.main_after,
        pushed=[s for s in (args.pushed or "").split(",") if s.strip()],
        deleted=[s for s in (args.deleted or "").split(",") if s.strip()],
        kept=[s for s in (args.kept or "").split(",") if s.strip()],
    )
    print(out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="converge_board.py",
        description=(
            "Classify branches + worktrees into converge cards (state + suggested "
            "disposition). Read-only git; fetch-first. See module docstring for the "
            "state taxonomy and disposition vocabulary."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--base", default="main", help="baseline ref (default: main)")
        sp.add_argument("--no-fetch", action="store_true",
                        help="skip `git fetch origin` (offline / tests)")
        sp.add_argument("--live-window", type=int, default=7200,
                        help="seconds; HEAD younger than this flags a live agent (default 7200)")

    b = sub.add_parser("board", help="gather + classify + render the board (default)")
    add_common(b)
    b.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    b.set_defaults(func=cmd_board)

    pl = sub.add_parser(
        "plan", help="dry-run: given dispositions, print the git action plan (no exec)"
    )
    add_common(pl)
    pl.add_argument(
        "--marks", default="",
        help='dispositions e.g. "all=black" or "feat-x=B,docs-y=white" '
             "(white/W/白, black/K/黑, B/promote, freeze/F/凍, snap/S/存, clean/清)",
    )
    pl.set_defaults(func=cmd_plan)

    td = sub.add_parser(
        "teardown",
        help="white-mode branch teardown: detach worktree -> del local -> del "
             "remote -> verify (refuses any branch not landed in base)",
    )
    add_common(td)
    td.add_argument("--branches", required=True,
                    help="comma list of local branches to tear down (already landed in base)")
    td.add_argument("--commit", action="store_true",
                    help="execute (default: dry-run preview)")
    td.add_argument("--force", action="store_true",
                    help="tear down the safe branches even if some targets are refused")
    td.set_defaults(func=cmd_teardown)

    gc = sub.add_parser(
        "gc",
        help="prune detached worktrees that are clean AND contained in base "
             "(refuses dirty / uncontained ones)",
    )
    add_common(gc)
    gc.add_argument("--commit", action="store_true",
                    help="execute (default: dry-run preview)")
    gc.set_defaults(func=cmd_gc)

    r = sub.add_parser("receipt", help="emit the one-round markdown record (time passed in)")
    r.add_argument("--round-at", required=True, help="round timestamp (passed in, NOT now())")
    r.add_argument("--before", required=True, help="path to board-before JSON")
    r.add_argument("--after", required=True, help="path to board-after JSON")
    r.add_argument("--marks", default="", help='applied dispositions "card=mark,..."')
    r.add_argument("--candidate-sha", default="-", help="assembled candidate sha")
    r.add_argument("--gate-verdict", default="-", help="build gate verdict pass/fail")
    r.add_argument("--main-before", default="-", help="main sha before cutover")
    r.add_argument("--main-after", default="-", help="main sha after cutover")
    r.add_argument("--pushed", default="", help="comma list of pushed refs")
    r.add_argument("--deleted", default="", help="comma list of deleted refs")
    r.add_argument("--kept", default="", help="comma list of kept refs")
    r.set_defaults(func=cmd_receipt)

    return p


def main(argv: list[str] | None = None) -> int:
    tokens = list(argv) if argv is not None else sys.argv[1:]
    # `board` is the default subcommand. argparse can't express a default
    # subparser, so route bare and flag-first invocations (e.g. `--json`,
    # `--base main`) to board explicitly — otherwise a leading flag is parsed
    # against the top-level parser and errors out. A leading -h/--help still
    # shows the top-level help (the subcommand list).
    if not tokens or (tokens[0].startswith("-") and tokens[0] not in ("-h", "--help")):
        tokens = ["board", *tokens]
    parser = build_parser()
    args = parser.parse_args(tokens)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
