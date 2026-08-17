"""Git, filesystem, registry, and gate-execution support for the orchestrator.

The command façade owns lifecycle sequencing; this module owns the reusable operational
seams.  Runtime symbols are rebound after import so legacy private monkeypatch seams
and the stable executable path remain compatible.
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


def _gate_record_path(state: str | None, worktree: str) -> Path:
    """Where a gate verdict is recorded so cutover can read it — a per-machine cache
    beside the registry ledger, keyed by the worktree's normalized path."""
    if state:
        base_dir = Path(state).resolve().parent
    else:
        base_dir = wr.default_state_path().parent
    key = hashlib.sha256(_norm(worktree).encode()).hexdigest()[:16]
    return base_dir / "worktree_gates" / f"{key}.json"


def _gate_progress_path(state: str | None, worktree: str) -> Path:
    """Where the live progress sidecar is recorded, separate from the verdict."""
    record_path = _gate_record_path(state, worktree)
    return record_path.with_name(f"{record_path.stem}.progress.json")


def _gate_progress_lock(state: str | None):
    """Serialize progress ownership without adding a second lock-file family."""
    state_path = Path(state).resolve() if state else wr.default_state_path()
    return wr._ledger_lock(state_path)


def _read_gate_progress(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _tracked_paths(worktree: str) -> list[str] | None:
    """Return tracked paths from the tree being gated, or None when it cannot be read.

    Reuse is an optimisation, so an unreadable path inventory is not a reason to make
    a claim about unchanged inputs.  The caller treats None as an unknown scope and
    runs the gate.
    """
    rc, out = _git(["ls-files", "-z"], cwd=worktree)
    if rc != 0:
        return None
    return sorted(p for p in out.split("\0") if p)


def _input_file_digest(worktree: str, paths: list[str]) -> str | None:
    """Hash the exact worktree bytes and modes for a bounded input file set."""
    h = hashlib.sha256()
    try:
        for rel in paths:
            fp = Path(worktree) / rel
            h.update(rel.encode("utf-8", "surrogateescape"))
            h.update(b"\0")
            if fp.is_symlink():
                h.update(b"symlink\0")
                h.update(os.readlink(fp).encode("utf-8", "surrogateescape"))
            elif fp.is_file():
                h.update(b"file\0")
                h.update(fp.read_bytes())
            else:
                h.update(b"missing\0")
            try:
                h.update(str(fp.stat().st_mode & 0o7777).encode("ascii"))
            except OSError:
                h.update(b"stat-missing")
            h.update(b"\0")
    except (OSError, UnicodeError):
        return None
    return h.hexdigest()


_IOS_OPS_COMMON_INPUTS = frozenset({
    "ops/ios_ops.sh",
    # ios_ops.sh sources every ios_ops_* module before dispatch.  The catalog
    # module also sources these three transitively, so a parse/load failure in
    # any of them affects both build and test commands.
    "ops/lib/ios_cache_evict.sh",
    "ops/lib/fixture_dataset_env.sh",
    "ops/lib/userland_compat.sh",
})
_IOS_BUILD_INPUTS = frozenset({
    "ops/ios_build.sh",
    "ops/ios_diagnostics.py",
    "ops/lib/ios_build_progress.sh",
    "ops/lib/ios_install_provenance.sh",
    "ops/lib/ios_lock_wait.sh",
    "ops/lib/ios_run_metrics.sh",
    "ops/lib/ios_run_verdict.sh",
})
_IOS_TEST_INPUTS = frozenset({
    "ops/ios_test.sh",
    "ops/ios_coverage.py",
    "ops/ios_diagnostics.py",
    "ops/ios_device_files.sh",
    "ops/p9_review_calendar_evidence.py",
    "ops/ui_world_manifest.py",
    "ops/uitest_contact_sheet.py",
    "ops/lib/ios_test_discovery.sh",
    "ops/lib/ios_test_failure_verdict.sh",
    "ops/lib/ios_test_cache_root.sh",
    "ops/lib/ios_test_failure_verdict.sh",
    "ops/lib/ios_xctestrun_cache.sh",
    "ops/lib/ios_build_progress.sh",
    "ops/lib/ios_lock_wait.sh",
    "ops/lib/ios_test_video_archive.sh",
    "ops/lib/ios_run_metrics.sh",
    "ops/lib/ios_run_verdict.sh",
    "ops/lib/signal_traps.sh",
})


def _ios_executable_input_files(name: str, tracked: list[str]) -> tuple[str, list[str]] | None:
    """Return a conservative command-specific iOS input surface.

    All iOS commands read the project tree and the common ios_ops dispatcher.  Build
    and test then delegate to different top-level scripts.  Keeping those delegates
    separate is what lets a retry reuse an already-green build after repairing only
    the test runner; shared wrapper/libs still invalidate both, and an unknown iOS
    gate deliberately falls back to the broader category scope below.
    """
    if name in {"ios-build", "ios-build-catalyst"}:
        kind = "tracked-ios-build-surface"
        explicit = _IOS_OPS_COMMON_INPUTS | _IOS_BUILD_INPUTS
    elif name == "ios-test-unit" or name.startswith("ios-test-ui:") or \
            name == "ios-live-demo-uitest-compile":
        kind = "tracked-ios-test-surface"
        explicit = _IOS_OPS_COMMON_INPUTS | _IOS_TEST_INPUTS
    else:
        return None
    files = [p for p in tracked if p.startswith("ios/") or p in explicit or
             p.startswith("ops/lib/ios_ops_") or
             (kind == "tracked-ios-test-surface" and (
                 p.startswith("ops/fixtures/ui_worlds/") or
                 p.startswith("ops/uitest_review_") or
                 p.startswith("ops/catalog_")
             ))]
    return kind, files


def _gate_input_scope(spec: dict[str, Any], worktree: str,
                      changed_files: list[str], tracked: list[str] | None) -> dict[str, Any]:
    """Resolve a conservative, auditable input scope for one gate.

    This is intentionally narrower than the whole repository for expensive gates, but
    broader than the changed paths: the tool being reused may scan a whole subsystem.
    A gate without a defensible scope is explicitly non-reusable rather than silently
    guessed.  The returned descriptor is persisted with the verdict.
    """
    name = str(spec.get("name", ""))
    kind = "unknown"
    files: list[str] = []
    if tracked is not None:
        if name == "coverage":
            kind = "changed-files"
            files = sorted(changed_files)
        elif name == "backlog-validate":
            kind = "tracked-subsystem"
            files = [p for p in tracked if p == "ops/backlog.py" or
                     (p.startswith(BACKLOG_STORE_DIR) and
                      "/" not in p[len(BACKLOG_STORE_DIR):] and p.endswith(".json"))]
        elif name == "data-plane:ops/docs_lint.sh":
            kind = "tracked-control-plane"
            files = [p for p in tracked if p == "docs/registry.yml" or
                     p.startswith("ops/docs") and p.endswith((".py", ".sh"))]
        elif name in {"docs-lint", "docs-conflict-markers"}:
            kind = "tracked-docs"
            files = [p for p in tracked if p.startswith("docs/") and
                     (p.endswith(".md") or p == "docs/registry.yml")]
            files.extend(p for p in tracked if p.startswith("ops/docs") and
                         p.endswith((".py", ".sh")))
        elif name == "docs-verified-against":
            # Reachability is a property of the repository's commit graph, not only
            # the bytes of the named documents.  Keep this cheap gate honest until a
            # graph fingerprint exists.
            kind = "unknown"
        elif name == "ops-pytest":
            kind = "tracked-subsystem"
            files = [p for p in tracked if p.startswith("ops/") or
                     p.startswith(".github/workflows/")]
        elif name == "ops-python-scan":
            # The scanner reads every tracked Python source, so make that exact
            # repository-wide surface reusable when unrelated files change.
            kind = "tracked-python-source"
            files = [p for p in tracked if p.endswith(".py")]
        elif name.startswith("ops-shell"):
            kind = "tracked-shell-tree"
            files = [p for p in tracked if p.endswith(".sh")]
        elif spec.get("category") == "ios":
            executable = _ios_executable_input_files(name, tracked)
            if executable is not None:
                kind, files = executable
            else:
                # Quality/advisory/unknown iOS gates keep the broad fail-safe scope.
                # A new gate must earn a narrower dependency declaration explicitly.
                kind = "tracked-ios-surface"
                files = [p for p in tracked if p.startswith("ios/") or
                         p.startswith("ops/ios") or p.startswith("ops/lib/ios") or
                         p.startswith("ops/tests/test_ios") or p.startswith("ops/test_ios") or
                         p.startswith("ops/ui_quality") or
                         p.startswith("ops/tests/test_ui_quality")]
        elif spec.get("category") == "backend":
            kind = "tracked-backend-surface"
            files = [p for p in tracked if p.startswith("backend/") or
                     p in {"pyproject.toml", "uv.lock"}]
        elif spec.get("category") == "design-system":
            kind = "tracked-design-system"
            files = [p for p in tracked if p.startswith("design-system/") or
                     p.startswith("ops/verify_design_system") or p.startswith("ops/token") or
                     p.startswith("ops/gen_") or p.startswith("ios/BooksAndVocab/Models/") or
                     p.startswith("ios/BooksAndVocab/UIComponents/") or
                     p in {"backend/static/kg-tokens.css", "backend/static/kg-components.css",
                           "package.json", "package-lock.json"}]

    clean = not bool(_git(["status", "--porcelain", "--untracked-files=all"],
                          cwd=worktree)[1])
    definition = {
        "name": spec.get("name"), "category": spec.get("category"),
        "kind": spec.get("kind"), "level": spec.get("level"),
        "cmd": spec.get("cmd"), "cwd": spec.get("cwd"),
        "files": spec.get("files"),
    }
    descriptor: dict[str, Any] = {
        "schema": GATE_INPUT_SCHEMA, "kind": kind, "files": sorted(files),
        "worktree_clean": clean,
        "definition_fingerprint": hashlib.sha256(
            json.dumps(definition, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")).hexdigest(),
    }
    descriptor["fingerprint"] = (
        _input_file_digest(worktree, descriptor["files"])
        if kind not in {"unknown", "history"} else None
    )
    descriptor["reusable"] = bool(
        kind not in {"unknown", "history", "changed-files"}
        and descriptor["fingerprint"] is not None and clean
    )
    return descriptor


def _read_gate_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read the previous live-worktree record without making reuse fail open."""
    if not path.exists():
        return None, "no_prior_record"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "prior_record_unreadable"
    return (payload, None) if isinstance(payload, dict) else (None, "prior_record_invalid")


def _reuse_gate(spec: dict[str, Any], current_input: dict[str, Any],
                previous: dict[str, Any] | None, previous_error: str | None,
                orchestrator: dict[str, Any], base: str = BASE_DEFAULT
                ) -> tuple[dict[str, Any] | None, str]:
    """Return a copied prior result only when every reuse proof is present."""
    if previous is None:
        return None, previous_error or "no_prior_record"
    if not current_input.get("reusable"):
        return None, "input_scope_not_reusable"
    if current_input.get("schema") != GATE_INPUT_SCHEMA:
        return None, "current_input_schema_unknown"
    if previous.get("schema") != GATE_SCHEMA:
        return None, "source_record_schema_unknown"
    if previous.get("base") != base:
        return None, "base_changed"
    old_orchestrator = previous.get("orchestrator")
    if not isinstance(old_orchestrator, dict):
        return None, "source_record_orchestrator_invalid"
    old_orch = old_orchestrator.get("sha256")
    if old_orch != orchestrator.get("sha256"):
        return None, "orchestrator_changed"
    previous_gates = previous.get("gates")
    if not isinstance(previous_gates, list) or any(
            not isinstance(gate, dict) for gate in previous_gates):
        return None, "source_record_gates_invalid"
    prior = next((gate for gate in previous_gates
                  if gate.get("name") == spec.get("name")), None)
    if not isinstance(prior, dict):
        return None, "no_prior_gate"
    if prior.get("status") not in {"pass", "warn"}:
        return None, f"source_status_{prior.get('status', 'missing')}"
    old_input = prior.get("input")
    if not isinstance(old_input, dict):
        return None, "source_record_has_no_input_fingerprint"
    if old_input.get("schema") != GATE_INPUT_SCHEMA:
        return None, "source_input_schema_unknown"
    if old_input.get("kind") != current_input.get("kind"):
        return None, "input_scope_changed"
    if old_input.get("files") != current_input.get("files"):
        return None, "input_file_set_changed"
    if old_input.get("definition_fingerprint") != current_input.get("definition_fingerprint"):
        return None, "gate_definition_changed"
    if old_input.get("fingerprint") != current_input.get("fingerprint"):
        return None, "input_content_changed"
    if old_input.get("worktree_clean") is not True or current_input.get("worktree_clean") is not True:
        return None, "worktree_not_clean"
    copied = dict(prior)
    reuse_metadata = prior.get("reuse")
    if reuse_metadata is not None and not isinstance(reuse_metadata, dict):
        return None, "source_gate_reuse_metadata_invalid"
    source_head = (reuse_metadata or {}).get("source_head") or previous.get("head_sha")
    copied["reused"] = True
    copied["reused_from_head"] = source_head
    copied["reuse"] = {"decision": "reused", "source_head": source_head,
                       "reason": "input_unchanged"}
    copied["input"] = current_input
    copied["summary"] = f"reused from {str(source_head)[:8]}: {prior.get('summary', '')}"
    return copied, "input_unchanged"


def _reuse_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Small, human-readable audit projection for gate and cutover payloads."""
    reused = [{"name": r.get("name"),
               "source_head": r.get("reused_from_head") or r.get("reuse", {}).get("source_head"),
               "reason": r.get("reuse", {}).get("reason")} for r in results
              if r.get("reuse", {}).get("decision") == "reused"]
    rerun = [{"name": r.get("name"), "reason": r.get("reuse", {}).get("reason")}
             for r in results if r.get("reuse", {}).get("decision") != "reused"]
    return {"reused": reused, "rerun": rerun}


def _executed_gate_count(results: list[dict[str, Any]]) -> int:
    """Count gates run by this invocation, excluding reuse and spawn failures."""
    return sum(
        1 for result in results
        if result.get("reuse", {}).get("decision") != "reused"
        and result.get("executed", True) is not False
    )


def _gate_log_path(record_path: Path, gate_name: str) -> Path:
    """Where a FAILED gate's captured output is kept — beside its verdict record.

    One file per (worktree, gate), named off the record so the pair is obvious on
    disk and `resolve` can strike both with one glob. Gate names carry `:` and `/`
    (`ops-shell:test_devops.sh`, `data-plane:ops/tests/test_lint_baselines.sh`), so
    anything outside a conservative set folds to `_`: this is a filename, not an
    identifier, and the record next to it holds the exact name.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", gate_name)
    return record_path.parent / f"{record_path.stem}.{slug}.log"


# Lines worth lifting out of a failed gate's output. Deliberately broad: these gates
# are a zoo — shell harnesses printing `✗`, pytest, TAP producers, bash's own
# `error:` — and a marker set narrow enough to look tidy is one that goes silent for
# whichever tool nobody had in mind. A false positive costs one line of noise; a miss
# costs the re-run this whole mechanism exists to remove.
# Two of these were added on 2026-08-09 after the set went silent on the two gates
# whose silence cost the most (IMP-20260808-8b4690):
#   `✘` U+2718 — Swift Testing's marker, one codepoint away from the `✗` U+2717
#     already here and visually near-identical, so no by-eye review of this tuple
#     was ever going to catch it. Measured on a real ios-test-unit log: 4 lines
#     carried U+2718, 1 carried U+2717.
# The zero-match branch in `_failed_gate_summary` changes how the tail is labelled,
# so a gate whose output uses an unfamiliar failure vocabulary cannot masquerade as a
# named failure.
GATE_FAILURE_MARKERS = ("✗", "✘", "FAIL", "AssertionError", "not ok", "error:")
GATE_MAX_FAILURE_LINES = 20

# The log is now the artefact an operator opens, so the capture has to be able to
# hold a whole harness run rather than just enough to describe one. Still bounded:
# `run_streamed_command` keeps the LAST N bytes per stream, and an unbounded capture
# would make a chatty gate a memory incident.
GATE_CAPTURE_LIMIT = 1024 * 1024

# These are the gates for which another iOS toolchain process can change what the
# child observes without changing the branch. Keep this list explicit: a warning on
# every red gate becomes boilerplate, while silently treating an iOS contention red as
# a code defect trains operators to distrust the whole gate layer (IMP-20260808-f0c1bb).
CONTENTION_SENSITIVE_GATES = frozenset({
    "ios-test-unit",
    "ops-shell:test_ios_test_discovery.sh",
    "ops-ci-coverage",
    "ops-shell:ops-ci-coverage",
    "ops-shell:test_ops_ci_coverage.sh",
})


def _gate_failure_lines(output: str) -> list[str]:
    """The lines of a failed gate's output that name what failed."""
    hits = [ln.rstrip() for ln in output.splitlines()
            if any(m in ln for m in GATE_FAILURE_MARKERS)]
    return hits[:GATE_MAX_FAILURE_LINES]


def _machine_state(state: str | None = None) -> dict[str, Any]:
    """Take a bounded, secret-free snapshot of state relevant to iOS gate contention.

    This is attribution evidence, never a verdict.  It records process identity only
    as ``pid`` plus a coarse kind; raw command lines can contain paths, tokens, or
    fixture data and are not useful to the operator.  Probe failures remain visible in
    ``probe_errors`` instead of becoming the misleading value "nothing is running".
    """
    errors: list[str] = []
    load_average: list[float] | None = None
    try:
        load_average = [float(v) for v in os.getloadavg()]
    except (AttributeError, OSError, ValueError) as exc:
        errors.append(f"load_average: {type(exc).__name__}: {exc}")

    processes: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode != 0:
            errors.append(f"ps: rc={proc.returncode}: {(proc.stderr or '').strip()[:160]}")
        else:
            seen: set[tuple[int, str]] = set()
            for line in (proc.stdout or "").splitlines():
                fields = line.strip().split(None, 1)
                if len(fields) != 2:
                    continue
                try:
                    pid = int(fields[0])
                except ValueError:
                    continue
                command = fields[1]
                kind = None
                if re.search(r"(?<![A-Za-z0-9_])xcodebuild(?![A-Za-z0-9_])", command):
                    kind = "xcodebuild"
                elif re.search(r"(?<![A-Za-z0-9_])ios_test\.sh(?![A-Za-z0-9_])", command):
                    kind = "ios_test.sh"
                if kind is None:
                    continue
                identity = (pid, kind)
                if identity not in seen:
                    processes.append({"pid": pid, "kind": kind})
                    seen.add(identity)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        errors.append(f"ps: {type(exc).__name__}: {exc}")

    active_worktrees: int | None = None
    try:
        state_path = Path(state).resolve() if state else wr.default_state_path()
        registry = wr.load_state(state_path)
        records = registry.get("records", [])
        active_worktrees = sum(1 for row in records
                               if isinstance(row, dict) and row.get("status") == "active")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"registry: {type(exc).__name__}: {exc}")

    return {
        "load_average": load_average,
        "active_ios_process_count": len(processes),
        "active_ios_processes": processes,
        "active_worktrees": active_worktrees,
        "probe_errors": errors,
    }


def _machine_state_record(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Merge before/after probes without claiming a process caused the red."""
    processes: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for snapshot in (before, after):
        for process in snapshot.get("active_ios_processes", []):
            identity = (process.get("pid"), process.get("kind"))
            if identity in seen:
                continue
            seen.add(identity)
            processes.append({"pid": process.get("pid"), "kind": process.get("kind")})
    errors = list(before.get("probe_errors", [])) + list(after.get("probe_errors", []))
    return {
        "before": before,
        "after": after,
        "contention": bool(processes),
        "contention_processes": processes,
        "probe_errors": errors,
    }


def _contention_warning(spec: dict[str, Any], cwd: Path,
                        machine: dict[str, Any]) -> str | None:
    """Render an actionable warning only for a sensitive gate with observed contention."""
    if spec["name"] not in CONTENTION_SENSITIVE_GATES or not machine.get("contention"):
        return None
    processes = machine.get("contention_processes", [])
    labels = ", ".join(f"{p.get('kind')} pid={p.get('pid')}" for p in processes)
    rerun = f"cd {shlex.quote(str(cwd))} && {shlex.join(spec['cmd'])}"
    return (
        f"machine contention detected: {len(processes)} concurrent iOS tool process(es) "
        f"({labels}); this {spec['name']} result may be non-reproducible. "
        f"It remains red; no automatic retry. Re-run when quiet: {rerun}"
    )


def _gate_history_path(state: str | None) -> Path:
    """Append-only behavioural log of gate outcomes, beside the per-worktree verdicts.

    The verdict file is one file per LIVE worktree, overwritten each run and struck on
    resolve — by design, and correct for its job (cutover needs the current verdict, not
    a museum). But it means nothing in the system can answer "has this gate EVER gone
    green", which is the only question that separates a broken check from a broken
    change. `ios-build-catalyst` could not go green on this machine for two months and
    blocked every iOS cutover; each individual red looked like an ordinary failure.
    """
    return _gate_record_path(state, "").parent / "history.jsonl"


def _append_gate_history(state: str | None, worktree: str, head: str,
                         orch: dict[str, Any],
                         results: list[dict[str, Any]]) -> str | None:
    """One compact JSONL line per gate result. NEVER fails the caller — a gate that
    refused because its own bookkeeping broke would be a fresh way to turn a green
    change red. (Same hard rule as ops/lib/ios_run_metrics.sh.)

    Returns the error string instead, so the caller can SAY that journaling is broken: a
    permanently unwritable journal and a fresh clone otherwise look identical (both
    "no history"), and a detector that can die with zero signal is the very disease
    this journal exists to catch.
    """
    try:
        path = _gate_history_path(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex
        wt_key = hashlib.sha256(_norm(worktree).encode()).hexdigest()[:16]
        with path.open("a", encoding="utf-8") as fh:
            for idx, r in enumerate(results):
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                row = {
                    "ts": ts,
                    "run_id": run_id,
                    "idx": idx,
                    "gate": r["name"],
                    # colon-suffixed gates (ios-test-ui:<Class>) are per-diff instances
                    # of ONE check; capability lives at the base name.
                    "base_name": r["name"].split(":")[0],
                    "status": r.get("status"),
                    "rc": r.get("rc"),
                    "level": r.get("level"),
                    "dur_s": r.get("dur_s"),
                    "lock_wait_ms": r.get("lock_wait_ms", 0),
                    "work_dur_s": r.get("work_dur_s", r.get("dur_s")),
                    "timing_status": r.get("timing_status", "legacy"),
                    # False only for gates that never started (spawn failure). A row
                    # for a check that did not run must not be usable as evidence
                    # about whether that check can pass.
                    "executed": r.get("executed", True),
                    "head8": head[:8],
                    "orch8": orch["sha256"][:8],
                    "wt": wt_key,
                    "reused": r.get("reuse", {}).get("decision") == "reused",
                    "reuse_source_head8": str(
                        r.get("reuse", {}).get("source_head") or "")[:8] or None,
                    "reuse_reason": r.get("reuse", {}).get("reason"),
                    "input_fingerprint": (r.get("input") or {}).get("fingerprint"),
                    "machine_state": r.get("machine_state"),
                }
                # Preserve the explicit producer provenance bit only when a producer
                # supplied it; old rows and ordinary checks retain their legacy shape,
                # while an all-skipped/deleted run remains visibly unestablished.
                if "established" in r:
                    row["established"] = r["established"]
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — bookkeeping is never load-bearing
        return f"{type(exc).__name__}: {exc}"
    return None


def gate_history_rows(state: str | None) -> list[dict[str, Any]]:
    """Every parseable row of the journal.

    A malformed line skips ITSELF, never the whole file. The journal is append-only and
    never rotated, so one truncated write (disk full, SIGKILL mid-flush) would otherwise
    disable every reader of it permanently and silently — the exact failure shape the
    journal exists to find.
    """
    path = _gate_history_path(state)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def gate_history_verdicts(state: str | None, base_names: list[str],
                          min_attempts: int = 3,
                          min_heads: int = 2) -> dict[str, dict[str, Any]]:
    """Per capability: `proven` (recorded green at least once), `never-green` (tried
    enough times, never once green) or `unproven` (too little history to say).

    THE reader. `ops/tests/test_gate_can_fail.sh` calls this instead of parsing the
    journal itself: two readers of one file are two chances to disagree, and they did
    exactly that — the shell copy counted rows for gates that never started, which the
    python side skips, so the same row could read "never green" in one place and "no
    data" in the other.

    "Never green, ever" rather than "not green lately" on purpose: someone iterating on
    a genuinely broken build reds the same gate repeatedly, and a recency rule would cry
    wolf at them.

    Only `level == "block"` rows count. The level is what makes a red consequential; a
    gate promoted from advisory to block would otherwise inherit the whole streak it
    accumulated while nobody was obliged to act on it, and trip on its first real block.
    """
    rows = gate_history_rows(state)
    out: dict[str, dict[str, Any]] = {}
    for name in base_names:
        mine = [r for r in rows
                if r.get("base_name") == name
                and r.get("level") == "block"
                # `executed is False` = the gate never started (spawn failure): not
                # evidence in either direction. An ABSENT key is a row written before
                # the field existed, i.e. a real run.
                and r.get("executed") is not False
                # `established is False` = the producer ran but checked nothing
                # (all files skipped or deleted). A colour without a check is not
                # evidence that this gate can pass or fail.
                and r.get("established") is not False
                # Same reasoning one step further out: an `inconclusive` row DID run,
                # but its colour was contaminated by refs moving under it, so it says
                # nothing about whether the gate can pass. Without this it would count
                # as an attempt and never as a green — inflating the streak until the
                # next genuine red arrived carrying "no green ever recorded", which is
                # the wrong hypothesis to hand someone (IMP-20260805-4ec901).
                and r.get("status") != "inconclusive"]
        greens = [r for r in mine if r.get("status") == "pass"]
        heads = {r.get("head8") for r in mine}
        if greens:
            verdict = "proven"
        elif len(mine) >= min_attempts and len(heads) >= min_heads:
            verdict = "never-green"
        else:
            verdict = "unproven"
        out[name] = {"verdict": verdict, "attempts": len(mine), "heads": len(heads),
                     "worktrees": len({r.get("wt") for r in mine}),
                     "last_green": greens[-1].get("ts") if greens else None}
    return out


def _never_green(state: str | None, base_name: str,
                 min_attempts: int = 3, min_heads: int = 2) -> dict[str, int] | None:
    """{attempts, heads, worktrees} when this gate has never been recorded green and has
    been tried enough times to mean something; None otherwise. Bookkeeping, so it
    swallows its own failures — a broken journal must not turn a green change red."""
    try:
        v = gate_history_verdicts(state, [base_name], min_attempts, min_heads)[base_name]
    except Exception:  # noqa: BLE001
        return None
    if v["verdict"] != "never-green":
        return None
    return {"attempts": v["attempts"], "heads": v["heads"], "worktrees": v["worktrees"]}


def _orchestrator_identity(worktree: str) -> dict[str, Any]:
    """WHO produced this verdict.

    `_run_gate` executes every shell gate with the worktree as cwd, so the TOOLS being
    routed to come from the worktree. `plan_gates` — the routing itself — comes from
    whichever copy of this file the shell resolved from the caller's cwd. Those two can
    be different commits: running `gate` from the primary checkout against a branch that
    changed the routing silently plans the OLD rule set and records it in a shape
    indistinguishable from the new one.

    A content hash, not a git commit: a commit id would attribute an uncommitted edit to
    the committed version, and an uncommitted edit is precisely when this matters.

    Three states, deliberately distinct — collapsing any two reopens the bypass:
      * no ops/ tree at all (synthetic fixtures, any non-kg checkout) -> None, "cannot
        compare". This must NOT masquerade as a mismatch or every such caller is refused
        for a question that was never asked.
      * present and readable -> True/False on the digests.
      * present but UNREADABLE -> False, fail closed. Reporting it as None would let the
        guard wave it through, which is the same silent bypass with a new trigger.
    """
    running = Path(__file__).resolve()
    wt_copy = Path(worktree) / "ops" / "worktree_orchestrate.py"
    wt_sha: str | None = None
    wt_error: str | None = None
    if wt_copy.is_file():
        try:
            wt_sha = sha256_file(wt_copy)
        except OSError as exc:
            wt_error = f"{type(exc).__name__}: {exc}"
    running_sha = sha256_file(running)
    if wt_error is not None:
        matches: bool | None = False
        source = "unreadable"
    elif wt_sha is None:
        matches = None
        source = "invoked"
    else:
        matches = wt_sha == running_sha
        source = "worktree" if matches else "invoked"
    return {
        "path": logical_tool_path(running),
        "resolved": str(running),
        "sha256": running_sha,
        "source": source,
        "worktree_copy_sha256": wt_sha,
        "worktree_copy_error": wt_error,
        "matches_worktree_copy": matches,
    }


def _orch_token(record: dict[str, Any]) -> str:
    """The one rendering of orchestrator identity, read back OUT of the record so the
    human report and the receipt line cannot drift from the JSON that cutover reads.
    Carries the source, not just the digest: a bare digest looks identical whether the
    worktree agreed, had nothing to compare, or could not be read."""
    o = record["orchestrator"]
    return f"{o['sha256'][:8]} ({o['source']})"


def _orchestrator_guard(orch: dict[str, Any], worktree: str, step: str, schema: str,
                        as_json: bool) -> int | None:
    """EXIT_USAGE when the running orchestrator is NOT the worktree's own copy.

    Narrow by construction: `matches_worktree_copy` is False only when the branch
    actually modified this tool. A byte-identical copy plans an identical set of gates,
    so refusing there would be friction with no safety gain — and friction is what
    teaches people to route around a gate. `None` (no ops/ tree to compare against)
    is "cannot compare", never "mismatch".
    """
    if orch["matches_worktree_copy"] is not False:
        return None
    remedy = f"{worktree}/ops/worktree_orchestrate.py"
    if orch.get("worktree_copy_error"):
        what = (f"the worktree's own orchestrator at {remedy} could not be read "
                f"({orch['worktree_copy_error']}), so this plan cannot be shown to come "
                f"from the tree that is landing")
    else:
        what = (f"this orchestrator ({orch['sha256'][:8]}, {orch['resolved']}) is not the "
                f"one in the worktree ({orch['worktree_copy_sha256'][:8]}, {remedy})")
    reason = (
        f"{what}. The gate TOOLS run from the worktree, so the routing must come from "
        f"there too — otherwise the plan is a different generation from the tools it "
        f"plans. Re-run as: {remedy}"
    )
    _emit({"schema": schema, "step": step, "error": "orchestrator mismatch",
           "reason": reason, "orchestrator": orch}, as_json,
          f"✗ {step} refused: {reason}")
    return EXIT_USAGE


# ---- internal gate runners -------------------------------------------------
def _run_conflict_markers(worktree: str, files: list[str]) -> dict[str, Any]:
    hits = []
    for rel in files:
        fp = Path(worktree) / rel
        if not fp.exists():
            continue
        try:
            for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                if line.startswith("<<<<<<<") or line.startswith(">>>>>>>") \
                        or line.rstrip() == "=======":
                    hits.append(f"{rel}:{i}")
        except OSError:
            continue
    if hits:
        return {"status": "block", "rc": 1,
                "summary": f"conflict markers in {len(hits)} location(s): {', '.join(hits[:5])}"}
    return {"status": "pass", "rc": 0, "summary": "no conflict markers"}


_SYNTAX_CHECKABLE_SHELLS = ("bash", "sh", "zsh")

# Indirection so a test can patch THIS name instead of `shutil.which` itself: the
# stdlib module object is process-global, and a monkeypatch on it outlives the test
# that set it for every other test sharing the interpreter.
_which = shutil.which


def _shell_syntax_interpreter(fp: Path) -> str | None:
    """The interpreter to run `-n` under, or None when it is not one we can check.

    No shebang means bash. That default is load-bearing, not a fallback: six tracked
    `ops/lib/*.sh` are sourced rather than executed and carry no shebang, and treating
    "unknown" as "skip" would silently demote them from having a syntax floor to having
    none — a widening of the gate that reads like a hardening of it.
    """
    try:
        with fp.open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        return "bash"  # unreadable here means bash reports it, not that we look away
    if not first.startswith("#!"):
        return "bash"
    # `#!/usr/bin/env bash`, `#!/bin/bash`, `#!/bin/bash -e` — the interpreter is the
    # last token that is not a flag.
    words = [w for w in first[2:].split() if not w.startswith("-")]
    if not words:
        return "bash"
    name = words[-1].rsplit("/", 1)[-1]
    if name not in _SYNTAX_CHECKABLE_SHELLS:
        return None
    # Recognised is not the same as available: the name is resolved through PATH, and
    # `zsh` is absent from GitHub's ubuntu runner by default. Letting it fall through
    # would raise inside `subprocess.run` and land in `bad` — a BLOCK about the SCRIPT
    # stating a fact about the MACHINE, the very substitution this function exists to
    # refuse. Absent interpreter is UNCHECKABLE, which is the `skipped` list's meaning.
    return name if _which(name) else None


def _run_shell_syntax(worktree: str, files: list[str]) -> dict[str, Any]:
    """A syntax floor on every changed shell script. The floor exists because it is the
    only check that applies to ALL of them: roughly a third of ops/*.sh has no test of
    its own, and before IMP-0051 a shell change selected no gate whatsoever.

    The interpreter comes from the shebang. `bash -n` on a script that is not bash is a
    false red — indistinguishable from a real one at the gate — so a shebang we do not
    recognise is SKIPPED and NAMED in the summary rather than guessed at: an enumerated
    hole beats an anonymous one. Today every tracked `*.sh` is bash or shebang-less, so
    this changes no verdict; it is the guard for the first one that is not."""
    bad: list[str] = []
    skipped: list[str] = []
    # Counted, never inferred from `len(files)`. That list also holds the ones deleted
    # in this same diff, so the old summary reported "3 shell script(s) parse" for a run
    # that invoked bash zero times — a green whose number was simply untrue.
    checked = 0
    for rel in files:
        fp = Path(worktree) / rel
        if not fp.is_file():
            continue  # deleted in this diff; routing to it would be a red for no reason
        interpreter = _shell_syntax_interpreter(fp)
        if interpreter is None:
            skipped.append(rel)
            continue
        try:
            proc = subprocess.run([interpreter, "-n", str(fp)], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            bad.append(f"{rel}: {type(exc).__name__}")
            continue
        checked += 1
        if proc.returncode != 0:
            first = next((ln for ln in proc.stderr.splitlines() if ln.strip()), "")
            bad.append(f"{rel}: {first.strip()}")
    if bad:
        result = {"status": "block", "rc": 1,
                  "summary": f"{len(bad)} shell script(s) do not parse: " + "; ".join(bad[:3])}
        if checked == 0:
            result["established"] = False
        return result
    if skipped:
        # warn, not pass, when NOTHING was actually checked: this is a block gate, so
        # its colour is a claim, and a run that invoked bash zero times established
        # nothing. Not block either — a machine missing an interpreter is not the
        # branch's fault, the same judgement `inconclusive` encodes for gates.
        result = {"status": "pass" if checked else "warn", "rc": 0,
                  "summary": (f"{checked} shell script(s) parse; "
                              f"{len(skipped)} skipped (interpreter not available or not "
                              f"recognised): " + ", ".join(skipped))}
        if checked == 0:
            result["established"] = False
        return result
    result = {"status": "pass", "rc": 0, "summary": f"{checked} shell script(s) parse"}
    if checked == 0:
        # A diff containing only deleted files produced a green result without
        # invoking a parser; keep the colour for compatibility but mark its proof
        # provenance explicitly so history readers cannot count it as evidence.
        result["established"] = False
    return result

_VA_RE = re.compile(r"^\s*verified_against:\s*([0-9a-fA-F]{7,40})\s*$", re.MULTILINE)


def _run_verified_against(worktree: str, files: list[str]) -> dict[str, Any]:
    bad = []
    checked = 0
    for rel in files:
        fp = Path(worktree) / rel
        if not fp.exists():
            continue
        m = _VA_RE.search(fp.read_text(errors="replace"))
        if not m:
            continue
        checked += 1
        sha = m.group(1)
        rc, _ = _git(["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], cwd=worktree)
        if rc != 0:
            bad.append(f"{rel} -> {sha} (absent)")
            continue
        rc, _ = _git(["merge-base", "--is-ancestor", sha, "HEAD"], cwd=worktree)
        if rc != 0:
            bad.append(f"{rel} -> {sha} (orphan)")
    if bad:
        return {"status": "warn", "rc": 1,
                "summary": f"verified_against unreachable for {len(bad)} doc(s): {', '.join(bad[:5])}"}
    return {"status": "pass", "rc": 0, "summary": f"verified_against reachable ({checked} checked)"}


def _run_streamed_command(
    command: list[str],
    *,
    cwd: Path | str,
    gate_name: str,
    heartbeat_interval: float = 20.0,
    capture_limit: int = 64 * 1024,
) -> tuple[int, str, float]:
    completed = run_streamed_command(
        command,
        cwd=cwd,
        label_key="gate",
        label=gate_name,
        progress_prefix="[worktree][gate]",
        heartbeat_interval=heartbeat_interval,
        capture_limit=capture_limit,
        merge_stderr=True,
    )
    return completed.returncode, completed.stdout, completed.elapsed_s


_LOCK_WAIT_PATTERNS = {
    "lockWaitMs": re.compile(
        r"(?<![A-Za-z0-9_])lockWaitMs(?:=|:)\s*(\d+(?:\.\d+)?)\b"
    ),
    "deviceRunLockWaitMs": re.compile(
        r"(?<![A-Za-z0-9_])deviceRunLockWaitMs(?:=|:)\s*(\d+(?:\.\d+)?)\b"
    ),
}


def _required_lock_wait_fields(spec: dict[str, Any]) -> tuple[str, ...]:
    """Return producer timing fields that must survive a gate's bounded output.

    ``ios_test.sh`` prints ``lockWaitMs`` before its final
    ``deviceRunLockWaitMs`` line, so either field being absent from the captured
    tail makes the split measurement unavailable. ``--prepare-cache`` exits after
    build-for-testing and only promises the process lock field. Other iOS gates do
    not promise these metrics.
    """
    if spec.get("category") != "ios":
        return ()
    command = [str(arg) for arg in (spec.get("cmd") or [])]
    names = {Path(arg).name for arg in command}
    is_test = "ios_test.sh" in names or (
        command and Path(command[0]).name == "ios_ops.sh" and
        len(command) > 1 and command[1] == "test"
    )
    if is_test:
        if "--prepare-cache" in command:
            return ("lockWaitMs",)
        return tuple(_LOCK_WAIT_PATTERNS)
    if "ios_build.sh" in names or (
        command and Path(command[0]).name == "ios_ops.sh" and
        len(command) > 1 and command[1] == "build"
    ):
        return ("lockWaitMs",)
    return ()


def _duration_fields(
    elapsed_s: float,
    output: str = "",
    *,
    required_lock_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Keep runner wall time and known iOS lock time as separate measurements.

    ``dur_s`` is the monotonic wall time measured by ``run_streamed_command``. The
    iOS wrappers expose lock waits as ``lockWaitMs`` and
    ``deviceRunLockWaitMs``; use the last value for each field because wrappers may
    print an acquisition line and a final timing line. Non-iOS gates omit both
    fields, so their work duration remains the full elapsed time.  A producer-backed
    gate whose required field is absent from the bounded capture is marked
    ``timing_status=unknown`` rather than silently treating the wait as zero.
    """
    elapsed = max(float(elapsed_s), 0.0)
    observed: dict[str, float] = {}
    for field, pattern in _LOCK_WAIT_PATTERNS.items():
        matches = pattern.findall(output)
        if matches:
            observed[field] = float(matches[-1])
    missing = [field for field in required_lock_fields if field not in observed]
    if missing:
        # A bounded tail can lose a producer's early metric.  ``0`` would falsely
        # claim that no lock was waited on, and subtracting only the surviving field
        # would inflate work time; keep wall time but make the split explicitly
        # unavailable.
        return {
            "dur_s": round(elapsed, 6),
            "lock_wait_ms": None,
            "work_dur_s": None,
            "timing_status": "unknown",
        }
    lock_wait_ms = round(sum(observed.values()), 3)
    work_dur_s = max(elapsed - lock_wait_ms / 1000.0, 0.0)
    return {
        "dur_s": round(elapsed, 6),
        "lock_wait_ms": lock_wait_ms,
        "work_dur_s": round(work_dur_s, 6),
        "timing_status": "known" if observed else "not-applicable",
    }


def _failed_gate_summary(returncode: int, output: str, tail: str,
                         log_path: Path | None) -> str:
    """What a blocked operator actually reads: named failures, then the tail, then
    where the rest of it is.

    The tail alone WAS the entire summary until 2026-08-08, and it is kept — for many
    gates the tail is the failure. What it could not do is carry a name that had
    scrolled past it, and three lines is exactly what a shell harness's closing
    frame costs, so the name was always the thing that got dropped.
    """
    lines = [f"exit {returncode}"]
    hits = _gate_failure_lines(output)
    if hits:
        lines.append(f"  failure-marked lines ({len(hits)} shown):")
        lines.extend(f"    {h}" for h in hits)
    else:
        # Said out loud rather than quietly degrading to the old shape. "This summary
        # looks thin" and "this gate prints no marker the scanner knows" are different
        # problems with different fixes, and only the second one is the tool's.
        lines.append("  no failure-marked lines found (scanned for "
                     f"{', '.join(GATE_FAILURE_MARKERS)})")
    if tail:
        # The heading is CONDITIONAL, and that is the whole repair. Both branches used
        # to print a bare `tail:`, so the slot an operator reads as "the evidence" was
        # byte-identical whether the scanner had found the failure or found nothing at
        # Conditional rather than always-on: a warning that fires on every ordinary
        # red is one people stop reading, which is this same defect one level up.
        lines.append("  tail:" if hits else
                     "  tail (NOT failure lines — the scanner matched nothing, so "
                     "these are merely the last lines and may show passes):")
        lines.extend(f"    {ln}" for ln in tail.splitlines())
    if log_path is not None:
        lines.append(f"  full output: {log_path}")
    return "\n".join(lines)


def _write_gate_log(log_path: Path, spec: dict[str, Any], cwd: Path,
                    returncode: int, output: str) -> str | None:
    """Persist a failed gate's captured output. Returns an error string, never raises.

    Bookkeeping is never load-bearing: a gate that reddened because its own log could
    not be written would be a fresh way to turn a green change red (same hard rule as
    `_append_gate_history`). The header exists so the file explains itself to whoever
    opens it hours later without the summary in front of them.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# gate: {spec['name']}\n"
            f"# cmd: {' '.join(spec.get('cmd') or [])}\n"
            f"# cwd: {cwd}\n"
            f"# rc: {returncode}\n"
            f"# capture: merged stdout+stderr, last {GATE_CAPTURE_LIMIT} bytes\n"
            f"# ---\n" + output,
            encoding="utf-8")
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _run_gate(spec: dict[str, Any], worktree: str, *,
              record_path: Path | None = None,
              state: str | None = None) -> dict[str, Any]:
    """Execute ONE planned gate against the worktree and return a result record.

    `record_path` is this worktree's verdict-record path; a failed gate's captured
    output is written beside it and pointed at from the summary. Optional because the
    log is an enhancement and not a precondition — without it the gate still runs and
    still reports, it just has nowhere to put the long form.
    """
    name, level = spec["name"], spec["level"]
    required_lock_fields = _required_lock_wait_fields(spec)
    result = {"name": name, "category": spec["category"], "level": level}
    machine_before = _machine_state(state)
    if spec["kind"] == "internal":
        started = time.monotonic()
        if name == "docs-conflict-markers":
            result.update(_run_conflict_markers(worktree, spec["files"]))
        elif name == "coverage":
            # Bookkeeping, not policing: pass when every changed file is routed
            # or declared, warn (never block) when something is unrouted. A
            # permanently-warn gate would desensitise the warn signal, and a
            # blocking one would force an exemption list — which is itself the
            # next thing to rot.
            unc = spec.get("uncovered") or []
            result.update({
                "status": "warn" if unc else "pass", "rc": 0,
                "summary": (f"{len(unc)} changed file(s) covered by no gate: "
                            + ", ".join(unc[:5]))
                           if unc else
                           (f"{len(spec.get('covered') or [])} covered, "
                            f"{len(spec.get('neutral') or [])} neutral, 0 uncovered"),
            })
        elif name == "ops-shell-syntax":
            result.update(_run_shell_syntax(worktree, spec["files"]))
        elif name == "docs-verified-against":
            result.update(_run_verified_against(worktree, spec["files"]))
        else:  # advisory-only gate (e.g. backend-tests-advisory)
            result.update({"status": "warn", "rc": 0, "summary": spec.get("note", "advisory")})
        result.update(_duration_fields(time.monotonic() - started))
        result["machine_state"] = _machine_state_record(machine_before, _machine_state(state))
        return result

    # shell gate — run the real tool. cwd is the worktree (or a subdir like backend).
    cwd = Path(worktree) / spec["cwd"] if spec.get("cwd") else Path(worktree)
    log_path = _gate_log_path(record_path, name) if record_path is not None else None
    # Struck BEFORE the run, not after: a log left by an earlier red describes a
    # failure that may already be fixed, and nothing on disk marks it stale. Doing it
    # here rather than on success means every exit from this function — including the
    # spawn-failure return below — leaves no log that this run did not write.
    if log_path is not None and log_path.exists():
        try:
            log_path.unlink()
        except OSError:
            pass
    # Bracket the run with a refs probe. Some ops tests read repo-global tag state, and
    # `refs/` is SHARED with the primary — so a `release.sh` running over there while
    # this gate runs can turn it red for a reason that has nothing to do with the
    # branch. Measured 2026-08-05: `ops/test_ios_ops.sh` at 371 passed / 1 failed inside
    # a batch gate, 371 green and exit 0 when rerun alone.
    tags_before = _tag_snapshot(worktree)
    started = time.monotonic()
    # TaskRegistry records the runner before spawning the child. Its default state/log
    # paths are rooted in `cwd`, so letting it see a missing directory first would create
    # that directory and make Popen accuse the command instead. Diagnose the requested
    # working directory at the gate boundary, before any runner bookkeeping can mutate it.
    try:
        cwd.stat()
    except FileNotFoundError:
        result.update(_duration_fields(
            time.monotonic() - started,
            required_lock_fields=required_lock_fields,
        ))
        result.update({
            "status": "block" if level == "block" else "warn",
            "rc": 127,
            "executed": False,
            "summary": (f"gate tool not runnable: cmd={spec['cmd'][0]} cwd={cwd} — "
                        f"FileNotFoundError on {cwd}"),
            "machine_state": _machine_state_record(
                machine_before, _machine_state(state)),
        })
        return result
    try:
        returncode, output, dur_s = _run_streamed_command(
            spec["cmd"], cwd=cwd, gate_name=name, capture_limit=GATE_CAPTURE_LIMIT,
        )
        result.update(_duration_fields(
            dur_s, output, required_lock_fields=required_lock_fields,
        ))
    except OSError as exc:
        # The router and the tools it routes to can be different generations
        # (IMP-0045): a branch that deleted a script leaves a stale router still
        # pointing at it. Letting this escape aborts the WHOLE run — every other
        # gate's result is discarded and the operator gets a traceback naming
        # subprocess.py rather than a gate.
        #
        # But OSError covers two very different stories and only one of them is
        # about the tool. ENOENT/EACCES/ENOTDIR mean this really cannot be run —
        # and `exc.filename` says WHICH path, because with spec["cwd"] set it is
        # the missing directory, not the command. Everything else (EMFILE, ENOMEM,
        # EAGAIN: a machine that cannot fork right now) says nothing about the tool
        # at all, and claiming it does is iron law 3 inverted — an operator told
        # "gate tool not runnable: ops/ios_ops.sh" goes hunting a stale router
        # while the real problem is fd exhaustion in a sibling worktree.
        if exc.errno in (errno.ENOENT, errno.EACCES, errno.ENOTDIR):
            summary = (f"gate tool not runnable: cmd={spec['cmd'][0]} cwd={cwd} — "
                       f"{type(exc).__name__} on {exc.filename or 'unknown path'}")
        else:
            summary = (f"gate could not be spawned (errno {exc.errno}): "
                       f"cmd={spec['cmd'][0]} — {type(exc).__name__}: {exc}")
        # `executed: False` is not cosmetic. Without it these rows enter the journal
        # as ordinary block attempts, and `_never_green` — which reads level and
        # status, never rc — counts three of them as evidence that the gate can
        # never pass. The next genuine red then arrives carrying "no green ever
        # recorded", steering the reader away from their own bug. rc alone cannot
        # carry this: a tool that RAN and exited 127 is a real red.
        result.update(_duration_fields(
            time.monotonic() - started,
            required_lock_fields=required_lock_fields,
        ))
        result.update({"status": "block" if level == "block" else "warn", "rc": 127,
                       "executed": False, "summary": summary,
                       "machine_state": _machine_state_record(
                           machine_before, _machine_state(state))})
        return result
    tail = "\n".join(output.splitlines()[-3:]) if output else ""
    if returncode == 0:
        # Green needs no attribution, so the second probe is not taken at all on this
        # path. Refs moving under a gate that PASSED changes nothing anyone would act
        # on, and calling it inconclusive would degrade the verdict of a run that
        # produced exactly the answer it was asked for. It also keeps the common case
        # at one `git for-each-ref` (~140ms here) instead of two.
        result.update({"status": "pass", "rc": returncode,
                       "summary": f"exit {returncode}" + (f": {tail}" if tail else ""),
                       "machine_state": _machine_state_record(
                           machine_before, _machine_state(state))})
        return result
    tags_after = _tag_snapshot(worktree)

    # Preserve the public producer contract at the consumer boundary.  A WARN
    # (rc=3) is advisory even when the routed gate is normally block-level;
    # otherwise docs_lint's warning-only origin-anchor check becomes a false
    # product BLOCK.  A typed BLOCK (rc=2) remains a block regardless of the
    # route's default level.  Untyped/tool failures keep the historical level
    # fallback so advisory tools do not become hard gates accidentally.
    if returncode == EXIT_WARN:
        status = "warn"
    elif returncode == EXIT_BLOCK:
        status = "block"
    elif returncode in (EXIT_TOOL_ERROR, EXIT_USAGE):
        status = "block" if level == "block" else "warn"
    else:
        status = "block" if level == "block" else "warn"
    log_error = None
    if log_path is not None:
        log_error = _write_gate_log(log_path, spec, cwd, returncode, output)
    summary = _failed_gate_summary(returncode, output, tail,
                                   None if log_error else log_path)
    if log_error:
        # Never silent: an unwritable log and a gate that simply had nothing to say
        # otherwise look identical, and the reader would go looking for a file that
        # was never there.
        summary += f"\n  ! output log not written ({log_error})"
    refs_changed = _tag_delta(tags_before, tags_after)
    infrastructure_unavailable = returncode == 75
    if tags_before is None or tags_after is None:
        # Fail-safe, but never silent. The red stands — an unreadable probe is no reason
        # to downgrade anything — yet "could not measure" must not look identical to
        # "measured, nothing moved", which is the same rule `history_error`,
        # `log_error` and `executed: False` each exist to enforce. A probe that goes
        # permanently blind on some machine would otherwise reinstate this whole bug
        # with zero signal.
        result["refs_probe"] = "unmeasured"
        summary += ("\n  ! refs probe unmeasured — cannot tell whether concurrent tag "
                    "surgery contaminated this result")
    if infrastructure_unavailable:
        # rc=75 is a typed machine-state result (for example an iOS shlock
        # timeout), not evidence that this branch is broken. Keep the summary
        # stable for machine consumers; the captured output/log still carries
        # holder and selector diagnostics when the producer emitted them.
        status = "inconclusive"
        result["infrastructure_unavailable"] = True
        if log_path is not None:
            if log_error:
                result["output_log_error"] = log_error
            else:
                result["output_log"] = str(log_path)
        summary = "infrastructure unavailable (rc=75), not a verdict on this branch"
    elif refs_changed:
        # Not `block`: the measurement was taken while someone else moved refs under
        # it, so charging this red to the branch kills work over a machine-state
        # artefact. Not `pass` either — nothing here established the gate would have
        # been green. The rc is kept verbatim; the point is attribution, not amnesia.
        status = "inconclusive"
        result["refs_changed"] = True
        summary = (f"refs changed during this gate ({refs_changed} tag(s) "
                   f"added/removed); rc={returncode} is not attributable to the "
                   f"branch — re-run this gate once the tag surgery is done\n{summary}")
    machine = _machine_state_record(machine_before, _machine_state(state))
    result["machine_state"] = machine
    warning = _contention_warning(spec, Path(cwd), machine) if status == "block" else None
    if warning:
        result["contention_warning"] = True
        summary = f"{warning}\n{summary}"
    result.update({"status": status, "rc": returncode, "summary": summary})
    return result
