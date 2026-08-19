"""Persistent staged-to-GC lifecycle with active-job protection."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar


class LifecycleError(ValueError):
    """Invalid transition or lifecycle state."""


_ALLOWED = {
    "staged": {"running"},
    "running": {"terminal", "failed"},
    "terminal": {"fetched", "failed"},
    "fetched": {"acked"},
    "acked": set(),
    "failed": set(),
}

_Result = TypeVar("_Result")


class JobLifecycle:
    def __init__(self, path: Path | str, *, ttl_seconds: int):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, dict[str, Any]] = self._read()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _mutate(self, mutation: Callable[[dict[str, dict[str, Any]]], _Result]) -> _Result:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                jobs = self._read()
                result = mutation(jobs)
                fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(jobs, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self._jobs = jobs
                return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def stage(self, job_id: str) -> None:
        def add_job(jobs: dict[str, dict[str, Any]]) -> None:
            if job_id in jobs:
                raise LifecycleError("duplicate")
            jobs[job_id] = {"state": "staged", "created_at": int(time.time())}

        self._mutate(add_job)

    def get(self, job_id: str) -> dict[str, Any]:
        try:
            return dict(self._jobs[job_id])
        except KeyError as exc:
            raise LifecycleError("unknown") from exc

    def transition(self, job_id: str, state: str) -> None:
        def change_state(jobs: dict[str, dict[str, Any]]) -> None:
            try:
                record = dict(jobs[job_id])
            except KeyError as exc:
                raise LifecycleError("unknown") from exc
            if state not in _ALLOWED.get(record["state"], set()):
                raise LifecycleError("order")
            record["state"] = state
            jobs[job_id] = record

        self._mutate(change_state)

    def reap(self, *, now: int) -> list[str]:
        removed: list[str] = []

        def remove_expired(jobs: dict[str, dict[str, Any]]) -> list[str]:
            for job_id, record in list(jobs.items()):
                if record["state"] in {"terminal", "failed", "acked"} and now - record.get("created_at", 0) >= self.ttl_seconds:
                    removed.append(job_id)
                    del jobs[job_id]
            return removed

        return self._mutate(remove_expired)
