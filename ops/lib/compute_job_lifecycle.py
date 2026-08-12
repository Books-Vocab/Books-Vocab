"""Persistent staged-to-GC lifecycle with active-job protection."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


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


class JobLifecycle:
    def __init__(self, path: Path | str, *, ttl_seconds: int):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, dict[str, Any]] = self._read()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(self._jobs, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def stage(self, job_id: str) -> None:
        if job_id in self._jobs:
            raise LifecycleError("duplicate")
        self._jobs[job_id] = {"state": "staged", "created_at": int(time.time())}
        self._write()

    def get(self, job_id: str) -> dict[str, Any]:
        try:
            return dict(self._jobs[job_id])
        except KeyError as exc:
            raise LifecycleError("unknown") from exc

    def transition(self, job_id: str, state: str) -> None:
        record = self.get(job_id)
        if state not in _ALLOWED.get(record["state"], set()):
            raise LifecycleError("order")
        record["state"] = state
        self._jobs[job_id] = record
        self._write()

    def reap(self, *, now: int) -> list[str]:
        removed: list[str] = []
        for job_id, record in list(self._jobs.items()):
            if record["state"] in {"terminal", "failed", "acked"} and now - record.get("created_at", 0) >= self.ttl_seconds:
                removed.append(job_id)
                del self._jobs[job_id]
        if removed:
            self._write()
        return removed
