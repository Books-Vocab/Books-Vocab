"""Post-landing ledger repair and teardown safety support."""

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


# The store, and only the store. The generated view left version control (its own
# entry, IMP-20260807-b9526c): it is produced on demand by `backlog.py render` and
# is gitignored, so there is no longer a tracked derived file for the trunk to
# repair, for a rebase to conflict on, or for a separate derived artifact to be scoped to.
LEDGER_PATHS = ("docs/runbook/backlog",)

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
