"""Read-only Codex thread metadata for the delivery board.

The worktree registry stores only the stable ``codex_thread_id``.  A thread
title is mutable presentation metadata, so the board receives it from this
mirror instead of copying it into a worktree record.  The collector uses
``thread/read`` only: it never resumes a thread, subscribes to events, changes
its name, or starts a turn.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "kg.codex.thread-mirror.v1"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _status(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("type")
    return _text(value)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(raw: dict[str, Any], *, index: int, errors: list[str]) -> dict[str, Any] | None:
    thread_id = _text(raw.get("thread_id") if "thread_id" in raw else raw.get("id"))
    if not thread_id:
        errors.append(f"thread {index} has no id")
        return None
    row: dict[str, Any] = {"thread_id": thread_id}
    aliases = {
        "title": ("title", "name"),
        "parent_thread_id": ("parent_thread_id", "parentThreadId", "forkedFromId"),
        "session_id": ("session_id", "sessionId"),
        "nickname": ("nickname", "agentNickname"),
        "role": ("role", "agentRole"),
        "source_kind": ("source_kind", "sourceKind"),
        "cwd": ("cwd",),
    }
    for field, names in aliases.items():
        value = next((raw[name] for name in names if name in raw), None)
        if value is not None and not isinstance(value, str):
            errors.append(f"thread {thread_id} {field} is not a string")
            continue
        text = _text(value)
        if text is not None:
            row[field] = text
    if "status" in raw:
        status = _status(raw["status"])
        if status is None:
            errors.append(f"thread {thread_id} status is malformed")
        else:
            row["status"] = status
    else:
        row["status"] = "unknown"
    if "error" in raw:
        error = _text(raw["error"])
        if error is not None:
            row["error"] = error
    return row


def normalise_thread_mirror(payload: Any) -> dict[str, Any]:
    """Return a bounded, stable thread mirror; malformed input fails closed."""
    if not isinstance(payload, dict):
        return {
            "schema": SCHEMA, "at": None, "host": None, "complete": False,
            "error": "thread mirror is not an object", "threads": [],
        }
    errors: list[str] = []
    raw_threads = payload.get("threads")
    if not isinstance(raw_threads, (list, tuple)):
        errors.append("threads is not a list")
        raw_threads = []
    threads = [row for index, raw in enumerate(raw_threads)
               if isinstance(raw, dict)
               for row in [_row(raw, index=index, errors=errors)] if row is not None]
    errors.extend("thread record is not an object" for raw in raw_threads if not isinstance(raw, dict))
    return {
        "schema": SCHEMA,
        "at": _text(payload.get("at")),
        "host": _text(payload.get("host")),
        "complete": payload.get("complete") is True and not errors,
        "error": "; ".join(errors) or _text(payload.get("error")),
        "threads": threads,
    }


def _read_line(stream, selector: selectors.BaseSelector, timeout: float) -> dict[str, Any] | None:
    events = selector.select(timeout)
    if not events:
        raise TimeoutError("codex app-server response timed out")
    line = stream.readline()
    if not line:
        raise EOFError("codex app-server closed stdout")
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _send(stream, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stream.flush()


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()
        proc.wait(timeout=2)


def collect_thread_mirror(
    thread_ids: list[str], *, codex_bin: str = "codex", timeout: float = 8.0,
) -> dict[str, Any]:
    """Query exact active owner ids through a short-lived read-only app-server."""
    ids = sorted({item.strip() for item in thread_ids if isinstance(item, str) and item.strip()})
    base = {"schema": SCHEMA, "at": _timestamp(), "host": socket.gethostname(),
            "complete": False, "error": None, "threads": []}
    if not ids:
        base["complete"] = True
        return base
    try:
        proc = subprocess.Popen(
            [codex_bin, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, start_new_session=True,
        )
    except OSError as exc:
        base["error"] = f"codex app-server unavailable: {type(exc).__name__}: {exc}"
        return base
    assert proc.stdin is not None and proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    rows: list[dict[str, Any]] = []
    try:
        _send(proc.stdin, {
            "method": "initialize", "id": 1,
            "params": {"clientInfo": {
                "name": "kg_delivery_board",
                "title": "KG Delivery Board",
                "version": "1.0.0",
            }},
        })
        _send(proc.stdin, {"method": "initialized", "params": {}})
        initialized = False
        while not initialized:
            response = _read_line(proc.stdout, selector, timeout)
            if response is None:
                continue
            if response.get("id") == 1:
                if "error" in response:
                    base["error"] = f"app-server initialize failed: {response['error']}"
                    return base
                initialized = True
        next_id = 2
        for thread_id in ids:
            request_id = next_id
            next_id += 1
            _send(proc.stdin, {
                "method": "thread/read", "id": request_id,
                "params": {"threadId": thread_id, "includeTurns": False},
            })
            response = None
            while response is None or response.get("id") != request_id:
                response = _read_line(proc.stdout, selector, timeout)
            if "error" in response:
                rows.append({"thread_id": thread_id, "title": None,
                             "status": "unavailable", "error": str(response["error"])})
                continue
            thread = response.get("result", {}).get("thread")
            if not isinstance(thread, dict):
                rows.append({"thread_id": thread_id, "title": None,
                             "status": "unavailable", "error": "thread/read returned no thread"})
                continue
            raw = dict(thread)
            raw["thread_id"] = thread_id
            rows.append(raw)
        result = dict(base)
        result["complete"] = True
        result["threads"] = normalise_thread_mirror({"complete": True, "threads": rows})["threads"]
        return result
    except (EOFError, OSError, TimeoutError, ValueError) as exc:
        base["error"] = f"thread mirror collection failed: {type(exc).__name__}: {exc}"
        base["threads"] = normalise_thread_mirror({"complete": True, "threads": rows})["threads"]
        return base
    finally:
        selector.close()
        _terminate(proc)


def _load_thread_ids(path: Path) -> list[str]:
    state = json.loads(path.read_text(encoding="utf-8"))
    return [str(record["codex_thread_id"]) for record in state.get("records", [])
            if record.get("status") == "active" and record.get("codex_thread_id")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thread_mirror.py")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        ids = _load_thread_ids(Path(args.ledger))
        payload = collect_thread_mirror(ids, codex_bin=args.codex_bin, timeout=args.timeout)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        payload = {
            "schema": SCHEMA, "at": _timestamp(), "host": socket.gethostname(),
            "complete": False, "error": f"ledger unreadable: {exc}", "threads": [],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
