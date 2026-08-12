#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Session-scoped ownership ledger for repository-launched long tasks.

The ledger is deliberately a small local control plane: one JSON file, one
sidecar flock, and atomic replacement.  Cleanup is fail-closed.  A task can be
signalled only when its named owner, worktree, PID, process-group ID, and
process-start identity all still agree, and only after its heartbeat is stale.
No command argv is retained; only a basename, argument count, and digest are
stored.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

from lib.lock_wait import exclusive_lock


SCHEMA = "kg.task.registry.v1"
STATUS_ACTIVE = "active"
STATUS_FINISHED = "finished"
DEFAULT_STALE_AFTER_SECONDS = 120.0
_UTC = dt.timezone.utc
DEFAULT_SESSION_ID = os.environ.get("KG_TASK_SESSION_ID") or f"session-{uuid.uuid4().hex}"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(_UTC)


def _timestamp(value: dt.datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(_UTC).isoformat()


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC)
    return parsed.astimezone(_UTC)


def _as_datetime(value: str | dt.datetime | None) -> dt.datetime:
    if value is None:
        return _utc_now()
    if isinstance(value, dt.datetime):
        return value.astimezone(_UTC) if value.tzinfo else value.replace(tzinfo=_UTC)
    return _parse_timestamp(value)


def command_identity(command: Sequence[object]) -> dict[str, Any]:
    """Return stable, non-sensitive identity without retaining raw argv."""
    values = [os.fspath(value) if isinstance(value, os.PathLike) else str(value) for value in command]
    digest = hashlib.sha256("\0".join(values).encode("utf-8", errors="surrogatepass")).hexdigest()
    return {
        "basename": Path(values[0]).name if values else "",
        "arg_count": len(values),
        "argv_sha256": digest,
    }


def _proc_stat_start_identity(pid: int) -> str | None:
    path = Path(f"/proc/{pid}/stat")
    try:
        raw = path.read_text()
    except (OSError, UnicodeError):
        return None
    # comm can contain spaces and ')' characters; split only after its final ')'.
    try:
        fields = raw.rsplit(")", 1)[1].split()
        start_ticks = fields[19]  # field 22, with field 3 at index 0
    except (IndexError, ValueError):
        return None
    boot_id = ""
    with contextlib.suppress(OSError):
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return f"proc:{boot_id}:{start_ticks}"


def process_start_identity(pid: int) -> str | None:
    """Read an exact-PID start identity; never search process names/substrings."""
    if pid <= 0:
        return None
    proc_identity = _proc_stat_start_identity(pid)
    if proc_identity is not None:
        return proc_identity
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        return None
    return f"ps:{value}"


def process_group_id(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (OSError, ValueError):
        return None


def _process_is_alive(pid: int) -> bool:
    """Check one exact PID, treating a reaped/zombie process as not alive."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text().rsplit(")", 1)[1].split()
        return not fields[0].startswith("Z")
    except (OSError, IndexError):
        pass
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return True
    state = completed.stdout.strip()
    return completed.returncode == 0 and bool(state) and not state.startswith("Z")


def _default_state_path(cwd: Path) -> Path:
    configured = os.environ.get("KG_TASK_REGISTRY_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--git-common-dir"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            common = Path(completed.stdout.strip())
            if not common.is_absolute():
                common = (cwd / common).resolve()
            return common.resolve().parent / ".cache" / "task_registry.json"
    except OSError:
        pass
    return cwd.resolve() / ".cache" / "task_registry.json"


def _atomic_save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "records": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(
        data.get("records"), list
    ):
        raise ValueError(f"malformed task registry state at {path}")
    return data


def _record_or_error(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    for record in state["records"]:
        if record.get("task_id") == task_id:
            return record
    raise KeyError(task_id)


class TaskRegistry:
    """Atomic JSON ledger with process ownership and lifecycle operations."""

    def __init__(
        self,
        state_path: Path | str | None = None,
        *,
        session_id: str | None = None,
        campaign: str | None = None,
        worktree: Path | str | None = None,
    ) -> None:
        resolved_worktree = Path(worktree or os.getcwd()).expanduser().resolve()
        self.state_path = (
            Path(state_path).expanduser().resolve()
            if state_path is not None
            else _default_state_path(resolved_worktree)
        )
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self.session_id = session_id or DEFAULT_SESSION_ID
        self.campaign = campaign if campaign is not None else os.environ.get("KG_TASK_CAMPAIGN", "")
        self.worktree = resolved_worktree

    @staticmethod
    def load(path: Path | str) -> dict[str, Any]:
        return _load(Path(path).expanduser().resolve())

    def _update(self, callback: Callable[[dict[str, Any]], Any]) -> Any:
        with exclusive_lock(self.lock_path, label=f"task-registry:{self.state_path.name}"):
            state = _load(self.state_path)
            result = callback(state)
            _atomic_save(self.state_path, state)
            return result

    def start(
        self,
        *,
        command: Sequence[object],
        log_path: Path | str | None = None,
        at: str | dt.datetime | None = None,
    ) -> dict[str, Any]:
        task_id = f"task-{uuid.uuid4().hex}"
        started_at = _timestamp(_as_datetime(at))
        resolved_log = (
            Path(log_path).expanduser().resolve()
            if log_path is not None
            else self.state_path.parent / "task_logs" / f"{task_id}.log"
        )
        resolved_log.parent.mkdir(parents=True, exist_ok=True)
        resolved_log.touch(exist_ok=True)
        record = {
            "task_id": task_id,
            "session_id": self.session_id,
            "campaign": self.campaign,
            "worktree": str(self.worktree),
            "pid": None,
            "pgid": None,
            "start_identity": None,
            "phase": "starting",
            "status": STATUS_ACTIVE,
            "started_at": started_at,
            "heartbeat_at": started_at,
            "finished_at": None,
            "log_path": str(resolved_log),
            "command_identity": command_identity(command),
            "terminal_outcome": None,
            "returncode": None,
            "cleanup": None,
        }

        def append(state: dict[str, Any]) -> dict[str, Any]:
            state["records"].append(record)
            return dict(record)

        return self._update(append)

    def bind_process(
        self,
        task_id: str,
        *,
        pid: int,
        pgid: int,
        start_identity: str,
        at: str | dt.datetime | None = None,
    ) -> dict[str, Any]:
        def bind(state: dict[str, Any]) -> dict[str, Any]:
            record = _record_or_error(state, task_id)
            if record["status"] != STATUS_ACTIVE:
                raise ValueError(f"task is not active: {task_id}")
            record.update(
                {
                    "pid": int(pid),
                    "pgid": int(pgid),
                    "start_identity": str(start_identity),
                    "phase": "running",
                    "heartbeat_at": _timestamp(_as_datetime(at)),
                }
            )
            return dict(record)

        return self._update(bind)

    def heartbeat(
        self,
        task_id: str,
        *,
        phase: str = "heartbeat",
        at: str | dt.datetime | None = None,
    ) -> dict[str, Any]:
        def pulse(state: dict[str, Any]) -> dict[str, Any]:
            record = _record_or_error(state, task_id)
            if record["status"] != STATUS_ACTIVE:
                raise ValueError(f"task is not active: {task_id}")
            record["phase"] = phase
            record["heartbeat_at"] = _timestamp(_as_datetime(at))
            return dict(record)

        return self._update(pulse)

    def finish(
        self,
        task_id: str,
        *,
        returncode: int | None = None,
        terminal_outcome: str | None = None,
        timed_out: bool = False,
        at: str | dt.datetime | None = None,
    ) -> dict[str, Any]:
        def close(state: dict[str, Any]) -> dict[str, Any]:
            record = _record_or_error(state, task_id)
            if record["status"] == STATUS_FINISHED:
                return dict(record)
            outcome = terminal_outcome
            if outcome is None:
                outcome = "timeout" if timed_out else f"exit:{returncode}"
            record.update(
                {
                    "phase": "finished",
                    "status": STATUS_FINISHED,
                    "finished_at": _timestamp(_as_datetime(at)),
                    "terminal_outcome": outcome,
                    "returncode": returncode,
                }
            )
            return dict(record)

        return self._update(close)

    def cleanup(
        self,
        task_id: str,
        *,
        owner_session: str,
        owner_worktree: Path | str,
        expected_pid: int,
        expected_pgid: int,
        expected_start_identity: str,
        stale_after: float = DEFAULT_STALE_AFTER_SECONDS,
        dry_run: bool = True,
        now: str | dt.datetime | None = None,
        term_timeout: float = 5.0,
    ) -> dict[str, Any]:
        if not math.isfinite(stale_after) or not math.isfinite(term_timeout):
            raise ValueError("stale_after and term_timeout must be finite")
        if stale_after < 0 or term_timeout < 0:
            raise ValueError("stale_after and term_timeout must be non-negative")
        current_time = _as_datetime(now)
        resolved_owner_worktree = str(Path(owner_worktree).expanduser().resolve())

        def inspect_and_cleanup(state: dict[str, Any]) -> dict[str, Any]:
            try:
                record = _record_or_error(state, task_id)
            except KeyError:
                return {"task_id": task_id, "allowed": False, "reason": "unknown-task", "signals": []}
            if record.get("status") != STATUS_ACTIVE:
                return {"task_id": task_id, "allowed": False, "reason": "finished-task", "signals": []}
            if record.get("session_id") != owner_session:
                return {"task_id": task_id, "allowed": False, "reason": "different-session", "signals": []}
            if record.get("worktree") != resolved_owner_worktree:
                return {"task_id": task_id, "allowed": False, "reason": "different-worktree", "signals": []}
            heartbeat_at = record.get("heartbeat_at")
            if not heartbeat_at:
                return {"task_id": task_id, "allowed": False, "reason": "missing-heartbeat", "signals": []}
            if (current_time - _parse_timestamp(heartbeat_at)).total_seconds() <= stale_after:
                return {"task_id": task_id, "allowed": False, "reason": "live-heartbeat", "signals": []}
            if record.get("pid") != expected_pid:
                return {"task_id": task_id, "allowed": False, "reason": "pid-mismatch", "signals": []}
            if record.get("pgid") != expected_pgid:
                return {"task_id": task_id, "allowed": False, "reason": "pgid-mismatch", "signals": []}
            if record.get("start_identity") != expected_start_identity:
                return {"task_id": task_id, "allowed": False, "reason": "pid-reuse", "signals": []}

            current_identity = process_start_identity(expected_pid)
            if current_identity is None or current_identity != record.get("start_identity"):
                return {"task_id": task_id, "allowed": False, "reason": "pid-reuse", "signals": []}
            current_pgid = process_group_id(expected_pid)
            if current_pgid is None or current_pgid != record.get("pgid"):
                return {"task_id": task_id, "allowed": False, "reason": "pgid-mismatch", "signals": []}

            plan = {
                "task_id": task_id,
                "allowed": True,
                "dry_run": dry_run,
                "pid": expected_pid,
                "pgid": expected_pgid,
                "signals": [],
            }
            if dry_run:
                return plan

            signals_sent: list[str] = []
            try:
                os.killpg(expected_pgid, signal.SIGTERM)
                signals_sent.append("TERM")
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + term_timeout
            while _process_is_alive(expected_pid) and time.monotonic() < deadline:
                time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
            if _process_is_alive(expected_pid):
                try:
                    os.killpg(expected_pgid, signal.SIGKILL)
                    signals_sent.append("KILL")
                except ProcessLookupError:
                    pass

            outcome = "stale-cleanup:" + (signals_sent[-1] if signals_sent else "already-exited")
            finished_at = _timestamp(current_time)
            record.update(
                {
                    "phase": "finished",
                    "status": STATUS_FINISHED,
                    "finished_at": finished_at,
                    "terminal_outcome": outcome,
                    "returncode": None,
                    "cleanup": {
                        "owner_session": owner_session,
                        "worktree": resolved_owner_worktree,
                        "pid": expected_pid,
                        "pgid": expected_pgid,
                        "start_identity": expected_start_identity,
                        "signals": list(signals_sent),
                    },
                }
            )
            plan["signals"] = signals_sent
            plan["terminal_outcome"] = outcome
            return plan

        return self._update(inspect_and_cleanup)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="inspect and safely clean long-task ownership")
    parser.add_argument("--state-path")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("task_id")
    status_parser.add_argument("--json", action="store_true")
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("task_id")
    cleanup.add_argument("--session", required=True)
    cleanup.add_argument("--worktree", required=True)
    cleanup.add_argument("--pid", type=int, required=True)
    cleanup.add_argument("--pgid", type=int, required=True)
    cleanup.add_argument("--start-identity", required=True)
    cleanup.add_argument("--stale-after", type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    cleanup.add_argument("--term-timeout", type=float, default=5.0)
    cleanup.add_argument("--commit", action="store_true")
    cleanup.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    registry = TaskRegistry(args.state_path) if args.state_path else TaskRegistry()
    if args.subcommand == "list":
        payload: object = TaskRegistry.load(registry.state_path)
    elif args.subcommand == "status":
        try:
            payload = _record_or_error(TaskRegistry.load(registry.state_path), args.task_id)
        except KeyError:
            payload = {"task_id": args.task_id, "error": "unknown-task"}
    else:
        payload = registry.cleanup(
            args.task_id,
            owner_session=args.session,
            owner_worktree=args.worktree,
            expected_pid=args.pid,
            expected_pgid=args.pgid,
            expected_start_identity=args.start_identity,
            stale_after=args.stale_after,
            dry_run=not args.commit,
            term_timeout=args.term_timeout,
        )
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if isinstance(payload, dict) and payload.get("error"):
        return 1
    if isinstance(payload, dict) and payload.get("allowed") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
