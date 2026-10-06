"""Locked, atomic persistence for the machine-local ownership ledger."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .records import SCHEMA, normalize_record


@contextlib.contextmanager
def ledger_lock(state_path: Path) -> Iterator[None]:
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as file_handle:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def load_state(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    if not target.exists():
        return {"schema": SCHEMA, "records": []}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"registry state is unreadable: {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"registry state must be an object: {target}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise TypeError(f"registry state records must be a list: {target}")
    clean_records: list[object] = []
    problems: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        record, record_problems = normalize_record(item, index=index)
        problems.extend(record_problems)
        clean_records.append(record if record is not None else item)
    normalized: dict[str, Any] = {"schema": SCHEMA, "records": clean_records}
    if problems:
        normalized["problems"] = problems
    return normalized


def save_state(target: Path, state: dict[str, Any]) -> None:
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "records": list(state.get("records", [])),
    }
    file_descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=str(target.parent)
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, indent=2)
            file_handle.write("\n")
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
