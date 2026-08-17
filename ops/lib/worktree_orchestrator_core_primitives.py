"""Git, filesystem, registry, and freeze primitives for the orchestrator."""

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

_OPS_DIR = Path(__file__).resolve().parent.parent
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))

import worktree_registry as wr  # noqa: E402
import backlog as backlog_tool  # noqa: E402
import worktree_campaign as campaign  # noqa: E402
import worktree_gate as gate_logic  # noqa: E402
from lib.provenance import logical_tool_path, sha256_file  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402
from lib import dispatch_preflight  # noqa: E402
from lib.exit_codes import EXIT_BLOCK, EXIT_OK, EXIT_TOOL_ERROR, EXIT_USAGE, EXIT_WARN  # noqa: E402
from lib import worktree_integration_status as integrate_status  # noqa: E402
from lib import worktree_orchestrator_planning as planning  # noqa: E402

SCHEMA = "kg.worktree.orchestrate.v1"
GATE_SCHEMA = "kg.worktree.gate.v1"
GATE_INPUT_SCHEMA = "kg.worktree.gate-input.v1"
GATE_PROGRESS_SCHEMA = "kg.worktree.gate-progress.v1"
FREEZE_SCHEMA = "kg.worktree.freeze.v1"
DELIVERY_SCHEMA = "kg.worktree.delivery.v1"
BASE_DEFAULT = "main"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKTREE_SCRATCH_REL = Path(".cache") / "agent-scratch"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind late-defined façade symbols into extracted function globals.

    Extracted helpers retain their original private-name contracts, while the
    executable façade remains the compatibility owner for provenance and patching.
    """
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]


def _git(args: list[str], cwd: Path | str | None = None) -> tuple[int, str]:
    """Run a bounded, parsed-output git probe expected to finish quickly.

    Potentially long or side-effecting git operations must use ``_git_mutation`` so
    the operator sees start/spawned/heartbeat/done progress on stderr.
    """
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        # cwd can legitimately vanish mid-teardown (resolve removes the worktree the
        # caller stands in); a captured failure beats an unhandled traceback.
        return 127, f"cwd unavailable: {exc}"
    out = proc.stdout.strip()
    if proc.returncode != 0 and proc.stderr.strip():
        out = (out + "\n" + proc.stderr.strip()).strip()
    return proc.returncode, out


def _noninteractive_env() -> dict[str, str]:
    """The parent environment with every door to an interactive prompt shut.

    `git -c core.editor=true` is NOT enough, and the difference is measurable: git
    resolves `GIT_EDITOR` FIRST, so with `GIT_EDITOR=vim` a `rebase --continue`
    launches the editor and blocks on a pipe nobody reads — forever, since these
    runs carry no timeout. On the `cutover` path that happens INSIDE the trunk lock,
    so one operator's editor preference freezes every cutover in the repo. Measured
    with `GIT_EDITOR` pointed at a 25s sleep: `elapsed=25.6s` — the editor really ran.

    This machine happens to have `GIT_EDITOR=true`, which is exactly why the bug was
    invisible here: the tests were green on the environment, not on the code.
    """
    env = dict(os.environ)
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git_mutation(
    args: list[str],
    *,
    cwd: Path | str,
    label: str,
    heartbeat_interval: float = 20.0,
    capture_limit: int = 64 * 1024,
) -> tuple[int, str]:
    """Run a potentially long git operation with machine-output-safe progress.

    ``label`` is a caller-owned semantic identifier. The raw argv is deliberately
    never printed because git remotes and refspecs may contain credentials.
    """
    try:
        proc = run_streamed_command(
            ["git", *args],
            cwd=cwd,
            label_key="mutation",
            label=label,
            progress_prefix="[worktree][mutation]",
            heartbeat_interval=heartbeat_interval,
            capture_limit=capture_limit,
            merge_stderr=False,
            env=_noninteractive_env(),
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        return 127, f"cwd unavailable: {exc}"
    out = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0 and stderr:
        out = (out + "\n" + stderr).strip()
    return proc.returncode, out


def _rmtree_streamed(path: str) -> tuple[int, str]:
    """Remove a directory tree under the same visible-progress contract as every
    other long operation (iron law 5).

    Deliberately NOT `shutil.rmtree`: the tree this removes is a worktree's, and in
    the incident that meant 19 GB of iOS DerivedData taking minutes. An in-process
    rmtree emits nothing for that whole window — exactly the silence the heartbeat
    contract forbids, and the silence that got the original run killed by a caller
    timeout, which is what manufactured the ambiguous state in the first place."""
    try:
        proc = run_streamed_command(
            ["rm", "-rf", "--", path],
            cwd=primary_root(),
            label_key="mutation",
            label="resolve-remove-leftover-directory",
            progress_prefix="[worktree][mutation]",
            heartbeat_interval=20.0,
            capture_limit=64 * 1024,
            merge_stderr=False,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        return 127, f"cwd unavailable: {exc}"
    stderr = (proc.stderr or "").strip()
    return proc.returncode, stderr


def primary_root() -> Path:
    """The MAIN working tree's root (dirname of the git common dir). Stable no matter
    which linked worktree the process stands in — the only safe anchor for open's
    worktree placement and for teardown commands that may remove the caller's own cwd
    (resolve from inside the target worktree)."""
    return wr.common_anchor()


def worktree_scratch_path(worktree: Path | str) -> Path:
    """Return the private, gitignored scratch directory for one worktree."""
    return Path(worktree) / WORKTREE_SCRATCH_REL


def _tag_snapshot(anchor: Path | str) -> str | None:
    """Every tag ref visible from `anchor`, or None when it could not be read.

    A linked worktree shares `refs/` with the primary — measured, not assumed:
    `git rev-parse --path-format=absolute --git-path refs/tags` returns a byte-identical
    path from both (drop that flag and the primary answers relatively while the worktree
    answers absolutely — two strings, one file), so a
    `release.sh` run over there is immediately visible to a child gate running here.
    That is how a gate's colour stops being a property of the branch and becomes a
    property of the machine (IMP-20260805-4ec901, same family as the device-lock case).

    Anchored at the tree being gated rather than at `primary_root()`: identical answer
    for the reason above, one fewer git spawn (`primary_root` shells out to
    `rev-parse --git-common-dir` first), and independent of where this process happens
    to stand.

    None means UNMEASURED and the caller must read it as "cannot tell", never as
    "changed": a probe that fails must not manufacture inconclusives out of real reds.
    """
    try:
        rc, out = _git(["for-each-ref", "--format=%(objectname) %(refname)", "refs/tags"],
                       cwd=anchor)
    except Exception:  # noqa: BLE001 — this is instrumentation; it may not fail a gate
        return None
    return out if rc == 0 else None


def _tag_delta(before: str | None, after: str | None) -> int:
    """How many tag refs appeared or disappeared between two snapshots. 0 when either
    side is unmeasured (see `_tag_snapshot`) — a retagged name counts as 2, which is
    literally what happened: one removed, one added."""
    if before is None or after is None:
        return 0
    return len(set(before.splitlines()) ^ set(after.splitlines()))


def _norm(p: str) -> str:
    return os.path.realpath(os.path.abspath(p))


def _fetch(quiet: bool = True) -> tuple[int, str]:
    return _git_mutation(
        ["fetch", "origin", "--prune"], cwd=primary_root(), label="fetch-origin",
    )


def _main_advance_lock(primary: Path):
    """Serialize local-`main` fast-forwards so two concurrent cutovers cannot race:
    without it both would rebase onto main@X and the second's ff-only would fail (or
    worse, interleave). Reuses the registry's reviewed flock primitive on a sidecar
    beside the ledger (`.cache/`, gitignored, one per repo)."""
    return wr._ledger_lock(primary / ".cache" / "kg-main-advance")


def _delivery_loop_lock(primary: Path):
    """Serialize each Delivery Team's final primary+remote closure.

    Child worktrees and integration rounds remain parallel. The final sequence is
    one critical section because its Gate must be based on the current primary,
    its cutover advances primary/main, and its sync mirrors that exact resulting
    tip. A Delivery Team waits on this lock; it does not need another team to
    coordinate manually.
    """
    return wr._ledger_lock(primary / ".cache" / "kg-delivery-loop")


_C_ESCAPES = {"n": 0x0A, "t": 0x09, "r": 0x0D, "a": 0x07, "b": 0x08,
              "f": 0x0C, "v": 0x0B, "\\": 0x5C, '"': 0x22}


def _c_unquote(p: str) -> str:
    """Undo git's C-style path quoting (core.quotePath): a path with spaces or
    non-ASCII bytes arrives as `"..."` with `\\`-escapes and 3-digit octal UTF-8
    byte sequences. Unwrapped paths pass through untouched."""
    if not (len(p) >= 2 and p.startswith('"') and p.endswith('"')):
        return p
    body, out, i = p[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            if body[i + 1] in "01234567":
                j = i + 2
                while j < min(i + 4, len(body)) and body[j] in "01234567":
                    j += 1
                out.append(int(body[i + 1:j], 8) & 0xFF)
                i = j
                continue
            out.append(_C_ESCAPES.get(body[i + 1], ord(body[i + 1])))
            i += 2
            continue
        out.extend(c.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def _porcelain_paths(out: str) -> list[str]:
    """Pathnames from `git status --porcelain` output (renames report the new side),
    C-unquoted to real paths. No fixed-offset slicing: `_git` strips its output,
    which can eat the first line's leading status column — split the 1-2 char XY
    field off instead."""
    paths: list[str] = []
    for ln in out.splitlines():
        ln = ln.lstrip()
        if not ln or " " not in ln:
            continue
        p = ln.split(" ", 1)[1].lstrip()
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.append(_c_unquote(p))
    return paths


COORDINATION_BROADCAST_REL = ".cache/coordination/broadcast.md"


def _broadcast_cutover_block(primary: Path, branch: str | None,
                             files: list[str],
                             worktree: str | None = None) -> str | None:
    """Post a dirty-primary refusal to the repo's shared mailbox. Returns the path it
    wrote to, or None if it could not (or should not) write.

    The refusal message was already good — it lists the files, gives options and points
    at session-mgmt. What it did not do is any of the coordination it describes, so the
    whole cost landed on the blocked session: find the running sessions, work out whose
    files those are, go write in the mailbox. That was done BY HAND three times
    (2026-08-05 twice, 2026-08-06 once, the last blocking a batch of eleven).

    BEST-EFFORT BY CONSTRUCTION. `.cache/` is gitignored scratch, never a source of
    truth, so every failure here is swallowed and the caller's refusal reason stands
    untouched. Substituting a courtesy for the diagnosis would be strictly worse than
    never sending it.

    IDEMPOTENT per (day, branch, dirty set). The refusal tells the operator to re-run
    once the primary is clean, so polling is the expected usage — an append per attempt
    would flood the mailbox humans read with the one participant that is a program. A
    different dirty set is genuinely new information and does get posted.

    The DAY is in the key because nobody deletes these. The record asks the reader to
    remove it when handled; the real mailbox is 694 lines going back to 2026-08-05 with
    not one entry removed. Without a day the marker never expires, so the same branch
    blocked by the same file a week later — entirely plausible, slugs repeat and the
    recurring dirty file is the same `ops/release.sh` — would post nothing at all.

    The key hashes EVERY file, not the ten that get shown, and joins on NUL: `_c_unquote`
    hands back real filenames, which may contain newlines, so a newline separator would
    collide `["a\\nb"]` with `["a", "b"]`.
    """
    shown = files[:10]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    key = hashlib.sha256(
        "\0".join([ts[:10], branch or "?", *files]).encode()).hexdigest()[:16]
    marker = f"<!-- kg-cutover-block {key} -->"
    # Backtick-quoted, newlines escaped: these are real paths going into markdown, and
    # `test_cutover_dirty_refusal_unquotes_special_paths` proves this path really does
    # receive things like `中文檔.txt`. A `#` or a leading `-` would otherwise render as
    # a heading or a list item, and a newline would break the record's line structure.
    listed = ", ".join("`" + p.replace("\n", "\\n") + "`" for p in shown) + (
        f" … and {len(files) - 10} more" if len(files) > 10 else "")
    try:
        path = primary / COORDINATION_BROADCAST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and marker in path.read_text(encoding="utf-8", errors="replace"):
            return str(path)
        entry = (
            f"\n---\n## {ts}Z — cutover 被擋:primary 有未提交的 tracked 改動\n\n"
            f"被擋的分支:`{branch or '(unknown)'}`"
            + (f" (worktree `{worktree.replace(chr(10), chr(92) + 'n')}`)"
               if worktree else "") + "\n\n"
            f"dirty: {listed}\n\n"
            f"**這則是 `ops/worktree_orchestrate.py` 自動貼的(IMP-20260806-42d183),"
            f"不是人寫的。** 若這些檔是你的:把它們 commit,或撤到一條 worktree。**然後"
            f"被擋的那條要再跑一次 `cutover` 才會過——它不會自動重試。** 它的 gate 判決"
            f"綁在自己的 HEAD 上、仍然有效,所以不必重跑 gate。處理完請自行刪除本則。\n"
            f"{marker}\n")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
        return str(path)
    except OSError:
        return None


def _primary_ff_ready(primary: Path, local: str, branch: str | None = None,
                      worktree: str | None = None,
                      allow_dirty: bool = False) -> tuple[str, dict[str, Any]] | None:
    """Refusal `(reason, extra-json-fields)` (or None) for advancing the primary
    checkout's local `main` by a fast-forward. `main` is checked out in the primary,
    so a ff updates its working tree — it must be on `local`, tracked-clean, with no
    merge/rebase in flight. Same guard family as sync-main, in the local-integration
    direction. Every reason names its next step: with multiple sessions sharing the
    repo a refusal is a coordination event, not a dead end."""
    cur = _current_branch(str(primary))
    if cur != local:
        where = "a detached HEAD" if cur is None else f"{cur!r}"
        return (f"primary checkout is on {where}, not {local!r} — cutover advances "
                f"the local trunk under its own checkout; put the primary back on "
                f"{local!r} (its tenant may be mid-task — coordinate, don't force), "
                f"then re-run cutover", {})
    rc, _ = _git(["rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=primary)
    if rc == 0:
        return ("a merge is in progress in the primary checkout — let its tenant "
                "conclude it (commit or `git merge --abort`), then re-run cutover", {})
    for probe in ("rebase-merge", "rebase-apply"):
        rc, p = _git(["rev-parse", "--path-format=absolute", "--git-path", probe],
                     cwd=primary)
        if rc == 0 and p and Path(p).exists():
            return ("a rebase is in progress in the primary checkout — let its tenant "
                    "conclude it (`git rebase --continue`/`--abort`), then re-run "
                    "cutover", {})
    rc, out = _git(["status", "--porcelain", "--untracked-files=no"], cwd=primary)
    if rc != 0:
        return (f"cannot read primary status: {out[:200]} — inspect the primary "
                f"checkout by hand, then re-run cutover", {})
    if out.strip():
        files = _porcelain_paths(out)
        if allow_dirty:
            return None
        shown = ", ".join(files[:10])
        if len(files) > 10:
            shown += f" … and {len(files) - 10} more"
        # A refusal is a coordination event, so make the tool do the coordinating.
        # This runs BEFORE the return and its result cannot change it: the reason
        # below is the diagnosis, the notice is a courtesy.
        posted = _broadcast_cutover_block(primary, branch, files, worktree)
        reason = (
            "primary working tree is dirty (tracked changes) — a ff updates the "
            f"checked-out files\n  dirty: {shown}\n"
            "  likely another session is working in the primary. Options: (a) use "
            "the session-mgmt MCP — list_sessions to find running sessions on this "
            "repo, send_message to ask the tenant to commit; (b) if the leftovers "
            "are yours, commit them or evacuate them to a worktree. The gate verdict "
            "is bound to the worktree HEAD and stays valid — once the primary is "
            "clean, just re-run cutover")
        if posted:
            reason += (f"\n  this block was posted for you to {posted} "
                       f"— no need to write it by hand")
        return (reason, {"dirty_files": files, "broadcast": posted})
    return None


def _changed_vs_base(worktree: str, base: str) -> list[str]:
    """Files changed against base, plus current tracked/untracked worktree paths.

    The committed diff is the PATCH a cutover would land. The status union is needed
    for omission checks: a newly created file that was never staged is absent from the
    patch but is still an input the gate must inspect (IMP-20260808-88c404).
    """
    rc, out = _git(["diff", "--name-only", f"{base}...HEAD"], cwd=worktree)
    if rc != 0:
        # base unresolved (e.g. no origin/main locally) — fall back to two-dot.
        rc, out = _git(["diff", "--name-only", f"{base}..HEAD"], cwd=worktree)
    changed = {ln for ln in out.splitlines() if ln}
    status_rc, status = _git(
        ["status", "--porcelain", "--untracked-files=all"], cwd=worktree
    )
    if status_rc == 0:
        # Only the omission-sensitive official-deck specs belong in this status
        # union. Treating every untracked helper (for example the synthetic
        # orchestrator copy used by provenance tests) as a committed Python diff
        # would spuriously arm unrelated source gates that cannot run in a fixture
        # tree. The fixed official-decks gate still runs independently of this list.
        changed.update(
            path for path in _porcelain_paths(status)
            if path.startswith("ops/official_decks/") and path.endswith(".json")
        )
    return sorted(changed)


def _local_trunk(base: str) -> str:
    """The LOCAL branch a cutover rebases onto. `--base` may be spelled `origin/main`,
    but the ref a cutover actually integrates against is always the local trunk. gate
    and cutover must measure containment against the SAME ref, or the check drifts
    away from the thing it protects."""
    return base.split("/", 1)[1] if "/" in base else base


def _delivery_operation_base(
    base: str | None,
    *,
    manifest: dict[str, Any] | None = None,
) -> str:
    """Resolve a close-wave operation target without confusing identity for a ref.

    Completed manifests retain exact commit identities so recovery can prove which
    tree was gated or anchored.  An exact SHA is not an operational branch, though:
    cutover, anchor, and resolve must continue to act on this checkout's local
    ``main``.  Symbolic ``origin/main`` remains normalized by ``_local_trunk``.
    """
    requested = str(base or "main")
    identities = [requested]
    if isinstance(manifest, dict):
        identities.extend([
            manifest.get("base"),
            manifest.get("base_sha"),
            (manifest.get("close_wave") or {}).get("anchor_base_sha")
            if isinstance(manifest.get("close_wave"), dict) else None,
        ])
    if any(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-fA-F]{7,64}", value)
        for value in identities
    ):
        return "main"
    return _local_trunk(requested)


def _base_containment(worktree: str, base: str) -> dict[str, Any] | None:
    """None when `base`'s tip is already an ancestor of the worktree HEAD — i.e. the
    tree that was gated IS the tree a cutover lands, because the rebase is then a
    no-op. Otherwise the drift, MEASURED: how many commits, and which files base
    gained since the fork point.

    The missing half of iron law 2's machine enforcement (IMP-20260806-945e01).
    `head_sha` binds a verdict to the code the gate READ; nothing bound it to the code
    it lands ALONGSIDE. A branch behind base passes the stale-HEAD check BY
    CONSTRUCTION — the HEAD did not move, only the base did — and cutover then rebases
    onto a tree the gate never saw."""
    rc, _ = _git(["merge-base", "--is-ancestor", base, "HEAD"], cwd=worktree)
    if rc == 0:
        return None
    _, tip = _git(["rev-parse", base], cwd=worktree)
    if rc != 1:
        # 128 = unresolvable ref / unreadable repo. NOT the same as "behind": report
        # the inability to verify rather than inventing a count, and still refuse —
        # "cannot check" must never render as "checked and fine".
        return {"base_ref": base, "base_sha": tip, "behind_commits": None,
                "base_changed_files": [], "containment_error": f"git rc={rc}"}
    _, n = _git(["rev-list", "--count", f"HEAD..{base}"], cwd=worktree)
    _, files = _git(["diff", "--name-only", f"HEAD...{base}"], cwd=worktree)
    return {"base_ref": base, "base_sha": tip,
            "behind_commits": int(n) if n.isdigit() else None,
            "base_changed_files": [ln for ln in files.splitlines() if ln]}


def _behind_base_refusal(worktree: str, trunk: str, drift: dict[str, Any]) -> str:
    if drift.get("containment_error"):
        return (f"cannot verify that {trunk} is contained in the worktree HEAD "
                f"({drift['containment_error']}) — refusing rather than binding a "
                f"verdict to a tree that may not be the one that lands")
    return (f"worktree is behind {trunk} ({drift['behind_commits']} commit(s), "
            f"{len(drift['base_changed_files'])} file(s) changed on {trunk} since the "
            f"fork) — cutover rebases onto {trunk} first, so the gated tree is NOT the "
            f"tree that lands. Run `{worktree}/ops/worktree_orchestrate.py catchup "
            f"--worktree {worktree} --commit`, then re-run `gate`")


def _head_sha(worktree: str) -> str:
    _, out = _git(["rev-parse", "HEAD"], cwd=worktree)
    return out


def _current_branch(worktree: str) -> str | None:
    rc, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree)
    return out if rc == 0 and out != "HEAD" else None


def _worktree_entry(worktree: str) -> dict[str, Any] | None:
    """This path's `git worktree list --porcelain` record, or None if git does not
    list it as a worktree at all.

    This is the ONLY admissible path→branch answer for teardown. `_current_branch`
    is not: git's repository discovery WALKS UP from its cwd, so a directory whose
    `.git` has been removed — an interrupted `worktree remove`, whose first act is
    to unlink that file — answers with the ENCLOSING checkout's branch. Worktrees
    live at <repo>/.claude/worktrees/<slug>, so the enclosing checkout is the
    primary and the answer is `main`. The worktree list has no such fallback: it
    still names the real branch and flags the entry `prunable`."""
    target = _norm(worktree)
    for w in wr._worktrees():
        if _norm(w["path"]) == target:
            return w
    return None


def _remote_branch_exists(name: str) -> bool:
    rc, out = _git_mutation(
        ["ls-remote", "--heads", "origin", name],
        cwd=primary_root(),
        label="remote-branch-probe",
    )
    return rc == 0 and bool(out.strip())


# ---- registry (P2) in-process, JSON captured ------------------------------
def _registry(argv: list[str]) -> tuple[int, dict[str, Any] | None]:
    """Call worktree_registry.main in-process; capture its --json stdout if present."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = wr.main(argv)
    text = buf.getvalue().strip()
    payload: dict[str, Any] | None = None
    if "--json" in argv and text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    return rc, payload


def _registry_mutation(
    argv: list[str],
    *,
    cwd: Path | str,
    label: str,
    heartbeat_interval: float = 20.0,
) -> tuple[int, dict[str, Any] | None]:
    """Run a registry action whose commit path may perform long git teardown.

    stdout remains the registry's single JSON document; progress and registry
    diagnostics are captured separately so the orchestrator's own JSON is pure.
    """
    proc = run_streamed_command(
        [sys.executable, str(Path(__file__).resolve().with_name("worktree_registry.py")),
         *argv],
        cwd=cwd,
        label_key="mutation",
        label=label,
        progress_prefix="[worktree][mutation]",
        heartbeat_interval=heartbeat_interval,
        capture_limit=64 * 1024,
        merge_stderr=False,
    )
    text = (proc.stdout or "").strip()
    payload: dict[str, Any] | None = None
    if "--json" in argv and text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    diagnostic = (proc.stderr or "").strip()
    if proc.returncode != 0:
        # Preserve the old route's visible failure evidence without writing it to
        # parent stdout. The child argv is never echoed, and the bounded runner has
        # already capped this stream; keep a smaller tail in the structured result.
        safe_tail = diagnostic[-2000:]
        if payload is None:
            payload = {"error": "registry mutation failed"}
        if safe_tail:
            payload["detail"] = safe_tail
    return proc.returncode, payload


def _state_arg(state: str | None) -> list[str]:
    return ["--state", state] if state else []


def _delegated_arg(value: bool | None) -> list[str]:
    """Forward an explicit delegated tri-state without clearing omitted metadata."""
    if value is True:
        return ["--delegated"]
    if value is False:
        return ["--not-delegated"]
    return []


def _freeze_path(state: str | None) -> Path:
    """The stop-the-world surgery lock, beside the ledger (same anchoring as the
    gate-record cache) so every worktree sees the one lock."""
    base_dir = Path(state).resolve().parent if state else wr.default_state_path().parent
    return base_dir / "worktree_freeze.json"


def _frozen(state: str | None) -> dict[str, Any] | None:
    """The freeze payload if the flow is frozen, else None. An unreadable lock file
    still counts as frozen — fail closed during surgery."""
    p = _freeze_path(state)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {"reason": f"unreadable freeze file at {p}", "frozen_at": None}
    if not isinstance(data, dict):  # valid JSON but not ours — still fail closed
        return {"reason": f"malformed freeze file at {p}", "frozen_at": None}
    return data


def _freeze_guard(state: str | None, step: str, as_json: bool) -> int | None:
    """EXIT_BLOCK if frozen (birth/landing steps only — draining steps like resolve
    and sweep stay allowed so quiescing for surgery is possible), else None."""
    frz = _frozen(state)
    if frz is None:
        return None
    _emit({"schema": SCHEMA, "step": step, "error": "frozen",
           "reason": frz.get("reason"), "frozen_at": frz.get("frozen_at")}, as_json,
          f"✗ {step} refused: worktree flow is FROZEN — {frz.get('reason')} "
          f"(since {frz.get('frozen_at')}); run `freeze off` to resume")
    return EXIT_BLOCK
