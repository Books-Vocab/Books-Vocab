"""Shared wave-queue primitives and stage/unstage command orchestration."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from lib.lock_wait import LockUnavailable, exclusive_lock


@dataclass(frozen=True)
class WaveDeps:
    """Callbacks for queue storage and the stage/unstage lifecycle doors."""

    root: Path = Path(".")
    error_type: type[Exception] = ValueError
    git: Callable[..., Any] | None = None
    current_branch: Callable[[], str] | None = None
    queue_anchor: Callable[[], Path] | None = None
    queue_path: Callable[[Path | None], Path] | None = None
    queue_lock: Callable[[Path], Any] | None = None
    read_queue: Callable[[Path], list[dict]] | None = None
    write_queue: Callable[[Path, list[dict]], None] | None = None
    entry_path: Callable[[Path, str], Path] | None = None
    entry_lock: Callable[[Path], Any] | None = None
    load_entry: Callable[[Path, str], dict] | None = None
    closure_changes: Callable[..., dict] | None = None
    merged_and_validated: Callable[..., dict] | None = None
    write_atomic: Callable[[Path, str], None] | None = None
    staged_status: str = "fixed"


def current_branch(*, deps: WaveDeps) -> str:
    if deps.git is None:
        raise RuntimeError("wave queue requires a git dependency")
    proc = deps.git("rev-parse", "--abbrev-ref", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def queue_anchor(*, deps: WaveDeps) -> Path:
    if deps.git is None:
        raise RuntimeError("wave queue requires a git dependency")
    proc = deps.git("rev-parse", "--path-format=absolute", "--git-common-dir")
    common = proc.stdout.strip() if proc.returncode == 0 else ""
    if not common:
        proc = deps.git("rev-parse", "--git-common-dir")
        common = proc.stdout.strip() if proc.returncode == 0 else ""
    if not common:
        return deps.root
    return (
        Path(common)
        if Path(common).is_absolute()
        else (Path.cwd() / common)
    ).resolve().parent


def held_tickets(anchor: Path | None = None, *, deps: WaveDeps) -> dict[str, dict]:
    """Read the per-machine worktree claims, failing soft when unavailable."""
    anchor_fn = deps.queue_anchor or (lambda: queue_anchor(deps=deps))
    path = (anchor or anchor_fn()) / ".cache" / "worktree_registry.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        records = state["records"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    held: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "active":
            continue
        for ticket in record.get("backlog") or []:
            held[str(ticket)] = {
                "branch": record.get("branch"),
                "path": record.get("path"),
                "claimed_at": record.get("claimed_at"),
            }
    return held


def queue_path(explicit: Path | None = None, *, deps: WaveDeps) -> Path:
    if explicit is not None:
        return Path(explicit)
    anchor = deps.queue_anchor or (lambda: queue_anchor(deps=deps))
    return anchor() / ".cache" / "backlog_anchor_queue.jsonl"


@contextlib.contextmanager
def queue_lock(queue: Path, *, deps: WaveDeps):
    lock_path = Path(queue).with_name(Path(queue).name + ".lock")
    try:
        with exclusive_lock(lock_path, label=f"backlog-queue:{queue.name}"):
            yield
    except LockUnavailable as exc:
        raise deps.error_type(
            f"queue lock unavailable ({exc}); refusing to stage rather than append "
            f"unserialized — an unlocked append loses rows silently. Lock: {lock_path}"
        ) from exc


def read_queue(path: Path, *, deps: WaveDeps) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise deps.error_type(
                f"{path}:{lineno} is not valid JSON ({exc.msg}). The wave queue is "
                "per-machine scratch: delete the bad line, or delete the file to "
                "drop every staged closure that has not been anchored yet."
            ) from exc
    return rows


def write_queue(path: Path, rows: list[dict], *, deps: WaveDeps) -> None:
    if deps.write_atomic is None:
        raise RuntimeError("wave queue requires a write_atomic dependency")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deps.write_atomic(
        path,
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )


def pending_queue_summary(queue: Path | None = None, *, deps: WaveDeps) -> dict:
    path_fn = deps.queue_path or (lambda explicit: queue_path(explicit, deps=deps))
    reader = deps.read_queue or (lambda path: read_queue(path, deps=deps))
    path = path_fn(queue)
    try:
        rows = reader(path)
    except deps.error_type as exc:
        return {"queue": str(path), "error": str(exc)}
    return {
        "queue": str(path),
        "total": len(rows),
        "staged_adds": sum(1 for row in rows if row.get("kind") == "add"),
        "staged_closures": sum(1 for row in rows if row.get("kind") != "add"),
        "unstamped": sum(1 for row in rows if not row.get("landed_sha")),
    }


def stage_add(args, entry: dict, *, deps: WaveDeps) -> tuple[dict, Path]:
    """Park a newly composed entry on the shared wave queue."""
    if any(
        callback is None
        for callback in (
            deps.current_branch,
            deps.queue_path,
            deps.queue_lock,
            deps.read_queue,
            deps.write_queue,
            deps.entry_path,
            deps.entry_lock,
        )
    ):
        raise RuntimeError("stage add requires complete queue and entry dependencies")
    queue = deps.queue_path(args.queue)
    row = {
        "kind": "add",
        "id": entry["id"],
        "entry": entry,
        "branch": deps.current_branch(),
        "landed_sha": None,
    }
    path = deps.entry_path(args.store, entry["id"])
    with deps.queue_lock(queue):
        with deps.entry_lock(path):
            if path.exists():
                raise deps.error_type(
                    f"{entry['id']} already exists in the store; staged add would "
                    "collide with an existing entry"
                )
            rows = deps.read_queue(queue)
            clash = next((row for row in rows if row.get("id") == entry["id"]), None)
            if clash is not None:
                raise deps.error_type(
                    f"{entry['id']} is already staged on branch "
                    f"{clash.get('branch') or '<unknown>'}. Two staged adds for one "
                    "id would make anchor choose an arbitrary payload; resolve the "
                    "collision before retrying."
                )
            rows.append(row)
            deps.write_queue(queue, rows)
    return row, queue


def cmd_stage(args, *, deps: WaveDeps) -> int:
    """Park a validated closure on the queue instead of writing the store."""
    if any(
        callback is None
        for callback in (
            deps.closure_changes,
            deps.load_entry,
            deps.merged_and_validated,
            deps.current_branch,
            deps.queue_path,
            deps.queue_lock,
            deps.read_queue,
            deps.write_queue,
        )
    ):
        raise RuntimeError("stage requires complete mutation and queue dependencies")
    changes = deps.closure_changes(
        verdict=args.verdict,
        by=args.by,
        evidence=args.evidence,
        at=args.at,
        status=deps.staged_status,
        fixed_by=None,
    )
    current = deps.load_entry(args.store, args.id)
    deps.merged_and_validated(
        current, changes, args.id, check_traceability=False
    )
    row = {
        "id": args.id,
        "verdict": args.verdict,
        "by": args.by,
        "evidence": args.evidence,
        "status": deps.staged_status,
        "at": changes["verified_at"],
        "branch": deps.current_branch(),
        "landed_sha": None,
    }
    queue = deps.queue_path(args.queue)
    with deps.queue_lock(queue):
        rows = deps.read_queue(queue)
        clash = [r for r in rows if r.get("id") == args.id]
        if clash and not args.replace:
            raise deps.error_type(
                f"{args.id} is already staged on branch "
                f"{clash[0].get('branch') or '<unknown>'} by "
                f"{clash[0].get('by') or '<unknown>'}. Two closures for one entry "
                "means two people fixed it or one of you has the wrong id — decide "
                "which, then `unstage {args.id}` or re-run with --replace."
            )
        rows = [item for item in rows if item.get("id") != args.id]
        rows.append(row)
        deps.write_queue(queue, rows)
    if args.json:
        print(
            json.dumps(
                {
                    "schema": "kg.backlog.stage.v1",
                    "staged": row,
                    "queue": str(queue),
                    "replaced": bool(clash),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(
            f"[staged] {args.id} {args.verdict} by {args.by}"
            f"{' (replaced a previous row)' if clash else ''}\n"
            f"  queued in {queue} — lands in the store when the wave runs "
            "`./ops/backlog.py anchor --commit`"
        )
    return 0


def cmd_unstage(args, *, deps: WaveDeps) -> int:
    """Remove one queued row, optionally committing the removal."""
    path_fn = deps.queue_path or (lambda explicit: queue_path(explicit, deps=deps))
    lock_fn = deps.queue_lock or (lambda path: queue_lock(path, deps=deps))
    reader = deps.read_queue or (lambda path: read_queue(path, deps=deps))
    writer = deps.write_queue or (lambda path, rows: write_queue(path, rows, deps=deps))
    queue = path_fn(args.queue)
    with lock_fn(queue):
        rows = reader(queue)
        keep = [row for row in rows if row.get("id") != args.id]
        dropped = [row for row in rows if row.get("id") == args.id]
        if not dropped:
            raise deps.error_type(f"{args.id} is not on the queue ({queue})")
        if args.commit:
            writer(queue, keep)
    payload = {
        "schema": "kg.backlog.unstage.v1",
        "id": args.id,
        "mode": "committed" if args.commit else "dry-run",
        "dropped": dropped,
        "remaining": len(keep),
        "queue": str(queue),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        verb = "dropped" if args.commit else "would drop"
        for row in dropped:
            print(
                f"[{verb}] {row.get('id')} {row.get('verdict')} by {row.get('by')}"
                f" (branch {row.get('branch') or '<unknown>'},"
                f" landed_sha {row.get('landed_sha') or '—'})"
            )
        print(
            f"  {len(keep)} row(s) remain in {queue}"
            + ("" if args.commit else "  [dry-run: --commit to apply]")
        )
    return 0
