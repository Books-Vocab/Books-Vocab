"""Acceptance execution and audit seams for the backlog CLI.

This module deliberately has no dependency on ``backlog.py``.  The CLI keeps
small compatibility wrappers around these functions so existing callers and
monkeypatch seams remain stable while acceptance execution has one owner.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from lib.streaming_command import run_streamed_command as _default_runner


ACCEPTANCE_TIMEOUT_SECONDS = 900
STATIC_ACCEPTANCE_TIMEOUT_SECONDS = 60
AUDIT_TIMEOUT_SECONDS = ACCEPTANCE_TIMEOUT_SECONDS // 3
AUDIT_POPULATION = "groomed AND unresolved"

AUDIT_CAVEAT = (
    "green is a CANDIDATE for a human to judge, never a verdict. Some criteria are "
    "green by design (a negative assertion is green until the defect is REintroduced), "
    "and no reading of the command can tell those from a criterion that lies. Declare "
    "the by-design ones with `update <id> --acceptance-green-expected '<why>'` — they "
    "move to `exempt`, where they stay countable. "
    "And `red` is not a clean bill of health: an rc this tool cannot interpret "
    "(grep's 2 for a missing file, or another program-specific code) lands there "
    "too, so a criterion that stopped testing its subject is invisible here whenever "
    "it fails for the wrong reason rather than passing for one. A pytest-shaped "
    "command's rc=5 is reported as `error` / `no-tests-collected`. "
    "For an unexpected rc, the runner executes the criterion a second time under "
    "`bash -x` and records the last traced command as `failing_clause`; this is "
    "diagnostic evidence, not a new verdict, and may repeat side effects."
)

_SHELL_CANNOT_RUN = {127: "command-not-found", 126: "not-executable"}
_AUDIT_UNRUNNABLE = {
    "acceptance-cmd-does-not-parse": "does-not-parse",
    "acceptance-cmd-unparsed": "shell-unavailable",
}


@dataclass(frozen=True)
class AcceptanceDeps:
    """Runtime seams supplied by the CLI façade or isolated tests."""

    root: Path
    run_streamed_command: Callable[..., Any] = _default_runner
    check_acceptance_cmd: Callable[[dict], list[dict]] | None = None
    list_entries: Callable[..., list[dict]] | None = None
    worst_first_key: Callable[[dict], tuple] | None = None
    acceptance_timeout_seconds: float = ACCEPTANCE_TIMEOUT_SECONDS
    static_acceptance_timeout_seconds: float = STATIC_ACCEPTANCE_TIMEOUT_SECONDS
    execute_criterion: Callable[..., tuple[int | None, str, float]] | None = None
    trace_failed_clause: Callable[..., str] | None = None
    run_acceptance: Callable[..., dict] | None = None


def execute_criterion(
    entry_id: str,
    cmd: str,
    timeout_seconds: float,
    progress_prefix: str,
    *,
    deps: AcceptanceDeps,
) -> tuple[int | None, str, float]:
    """Run one stored criterion with the shared heartbeat runner."""
    started = time.monotonic()
    result = deps.run_streamed_command(
        ["bash", "-c", cmd],
        cwd=deps.root,
        label_key="entry",
        label=entry_id,
        progress_prefix=progress_prefix,
        merge_stderr=True,
        timeout_seconds=timeout_seconds,
    )
    elapsed = time.monotonic() - started
    if result.timed_out:
        return None, f"timed out after {timeout_seconds:g}s", elapsed
    return result.returncode, (result.stdout or "").strip()[-400:], elapsed


def trace_failed_clause(
    entry_id: str,
    cmd: str,
    timeout_seconds: float,
    progress_prefix: str,
    *,
    deps: AcceptanceDeps,
) -> str:
    """Re-run a failed criterion under bash tracing for attribution."""
    trace_token = "KG_ACCEPT_TRACE_" + hashlib.sha256(
        f"{entry_id}\0{cmd}".encode("utf-8")
    ).hexdigest()[:16] + ": "
    trace_env = dict(os.environ)
    trace_env["PS4"] = trace_token
    result = deps.run_streamed_command(
        ["bash", "-x", "-c", cmd],
        cwd=deps.root,
        label_key="entry",
        label=entry_id,
        progress_prefix=f"{progress_prefix}-trace",
        merge_stderr=False,
        timeout_seconds=timeout_seconds,
        env=trace_env,
    )
    if getattr(result, "timed_out", False):
        return ""
    lines = []
    for line in (result.stderr or "").splitlines():
        marker = line.find(trace_token)
        if marker >= 0:
            lines.append((marker, line[marker + len(trace_token):].strip()))
    if not lines:
        return ""
    deepest = max(marker for marker, _ in lines)
    return next(command for marker, command in reversed(lines) if marker == deepest)


def run_acceptance(entry_id: str, cmd: str, expect_rc: int, *, deps: AcceptanceDeps) -> dict:
    """Read one criterion through the closing gate."""
    print(
        f"[backlog][acceptance] {entry_id} start: {cmd[:120]}",
        file=sys.stderr,
        flush=True,
    )
    execute = deps.execute_criterion or (
        lambda *args: execute_criterion(*args, deps=deps)
    )
    trace = deps.trace_failed_clause or (
        lambda *args: trace_failed_clause(*args, deps=deps)
    )
    rc, tail, elapsed = execute(
        entry_id,
        cmd,
        deps.acceptance_timeout_seconds,
        "[backlog][acceptance]",
    )
    ok = rc == expect_rc
    print(
        f"[backlog][acceptance] {entry_id} done: rc={rc} expected={expect_rc} "
        f"{'OK' if ok else 'MISMATCH'} elapsed={elapsed:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    failing_clause = (
        ""
        if ok or rc is None
        else trace(entry_id, cmd, deps.acceptance_timeout_seconds, "[backlog][acceptance]")
    )
    return {
        "id": entry_id,
        "cmd": cmd,
        "rc": rc,
        "expect_rc": expect_rc,
        "ok": ok,
        "elapsed_s": round(elapsed, 1),
        "output_tail": tail,
        "failing_clause": failing_clause,
    }


def run_static_acceptance(entry_id: str, cmd: str, *, deps: AcceptanceDeps) -> dict:
    """Run optional worker feedback without changing the store."""
    print(
        f"[backlog][acceptance-static] {entry_id} start: {cmd[:120]}",
        file=sys.stderr,
        flush=True,
    )
    execute = deps.execute_criterion or (
        lambda *args: execute_criterion(*args, deps=deps)
    )
    rc, tail, elapsed = execute(
        entry_id,
        cmd,
        deps.static_acceptance_timeout_seconds,
        "[backlog][acceptance-static]",
    )
    ok = rc == 0
    print(
        f"[backlog][acceptance-static] {entry_id} done: rc={rc} expected=0 "
        f"{'OK' if ok else 'MISMATCH'} elapsed={elapsed:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    return {
        "id": entry_id,
        "cmd": cmd,
        "rc": rc,
        "expect_rc": 0,
        "ok": ok,
        "elapsed_s": round(elapsed, 1),
        "output_tail": tail,
    }


def acceptance_gate(entry: dict, commit: bool, *, deps: AcceptanceDeps) -> dict:
    """The shared precondition for writing ``status: fixed``."""
    entry_id = entry.get("id", "?")
    cmd = str(entry.get("acceptance_cmd") or "").strip()
    if not cmd:
        manual = str(entry.get("acceptance_manual") or "").strip()
        return {"kind": "manual", "id": entry_id, "reason": manual} if manual else {
            "kind": "unproven", "id": entry_id
        }
    expect_rc = int(entry.get("acceptance_expect_rc") or 0)
    if not commit:
        return {
            "kind": "would-run",
            "id": entry_id,
            "cmd": cmd,
            "expect_rc": expect_rc,
        }
    runner = deps.run_acceptance or (
        lambda *args: run_acceptance(*args, deps=deps)
    )
    outcome = runner(entry_id, cmd, expect_rc)
    return {"kind": "ran" if outcome["ok"] else "failed", **outcome}


def acceptance_refusal(result: dict) -> str:
    """Render one stable refusal for a failed acceptance criterion."""
    text = (
        f"acceptance did not hold: `{result['cmd']}` exited {result['rc']}, "
        f"expected {result['expect_rc']}. The closure claims this defect is "
        f"gone; the command the entry nominated to prove that says otherwise."
    )
    if result.get("output_tail"):
        text += f"\n  last output: {result['output_tail']}"
    if result.get("failing_clause"):
        text += f"\n  failing clause: {result['failing_clause']}"
    return text


def looks_like_pytest_command(cmd: str) -> bool:
    """Recognize pytest as the executable, not merely as an argument value."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return False
    for index, token in enumerate(tokens):
        if Path(token).name != "pytest":
            continue
        if index == 0 or tokens[index - 1] in {
            "-m", "run", "env", "command", "&&", ";", "||", "|"
        }:
            return True
        if index >= 2 and tokens[index - 2] == "--with":
            return True
    return False


def criterion_unrunnable_reason(cmd: str, rc: int) -> str | None:
    """Classify shell/tool failures that are not criterion evidence."""
    if rc in _SHELL_CANNOT_RUN:
        return _SHELL_CANNOT_RUN[rc]
    if rc == 5 and looks_like_pytest_command(cmd):
        return "no-tests-collected"
    return None


def audit_population(store: Path, *, deps: AcceptanceDeps) -> list[dict]:
    if deps.list_entries is None or deps.worst_first_key is None:
        raise ValueError("audit population dependencies are not configured")
    hits = [p for p in deps.list_entries(store, groomed=True)
            if p.get("status") not in ("fixed", "wont-fix")]
    return sorted(hits, key=deps.worst_first_key)


def audit_row(entry: dict, **extra) -> dict:
    return {
        "id": entry.get("id"),
        "severity": entry.get("severity"),
        "detail": str(entry.get("detail") or "")[:120],
        **extra,
    }


def audit_unrunnable(entry: dict, *, deps: AcceptanceDeps) -> str | None:
    if deps.check_acceptance_cmd is None:
        raise ValueError("acceptance command checker is not configured")
    unrunnable = [
        _AUDIT_UNRUNNABLE[p["kind"]]
        for p in deps.check_acceptance_cmd(entry)
        if p["kind"] in _AUDIT_UNRUNNABLE
    ]
    return unrunnable[0] if unrunnable else None


def audit_one(entry: dict, timeout_seconds: float, *, deps: AcceptanceDeps) -> tuple[str, dict]:
    cmd = str(entry.get("acceptance_cmd") or "").strip()
    expect_rc = int(entry.get("acceptance_expect_rc") or 0)
    execute = deps.execute_criterion or (
        lambda *args: execute_criterion(*args, deps=deps)
    )
    trace = deps.trace_failed_clause or (
        lambda *args: trace_failed_clause(*args, deps=deps)
    )
    rc, tail, elapsed = execute(
        entry["id"], cmd, timeout_seconds, "[backlog][audit]"
    )
    row = audit_row(
        entry,
        cmd=cmd,
        expect_rc=expect_rc,
        rc=rc,
        elapsed_s=round(elapsed, 1),
        output_tail=tail,
    )
    if rc is None:
        return "timeout", {**row, "timeout_seconds": timeout_seconds}
    unrunnable_reason = criterion_unrunnable_reason(cmd, rc)
    if unrunnable_reason:
        return "error", {
            **row,
            "reason": unrunnable_reason,
            "failing_clause": "",
        }
    if rc != expect_rc:
        row["failing_clause"] = trace(
            entry["id"], cmd, timeout_seconds, "[backlog][audit]"
        )
    return ("green" if rc == expect_rc else "red"), row
