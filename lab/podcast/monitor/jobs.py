"""In-memory background job tracker for dashboard-triggered subprocess actions.

Jobs are ephemeral (server restart drops them). Each job streams stdout+stderr
to a temp log file the client can tail. Used by /api/workspace/<n>/upload,
/api/workspace/<n>/rerun, /api/pipeline/start, /api/remote/series DELETE, etc.

Design notes:
  - Threading, not asyncio — subprocess.Popen + a reader thread is simpler and
    sufficient here; FastAPI handlers are async but we don't need fanout.
  - One log file per job under monitor/.jobs/<id>.log — survives crashes for
    post-mortem.
  - Status transitions: pending → running → (succeeded | failed | killed).
  - Active job count is bounded (default 4) to keep the 2GB VPS sane if the
    user clicks "rerun" on 12 episodes at once.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
JOBS_DIR = ROOT / "monitor" / ".jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

MAX_ACTIVE = int(os.getenv("PODCAST_MAX_ACTIVE_JOBS", "4"))
MAX_HISTORY = int(os.getenv("PODCAST_JOB_HISTORY", "100"))


@dataclass
class Job:
    id: str
    label: str               # human-readable: "upload:atomic_habits_..."
    kind: str                # "upload" | "rerun" | "pipeline" | "remote-delete" | ...
    cmd: list[str]
    cwd: str
    status: str              # pending | running | succeeded | failed | killed
    started_ts: float        # epoch seconds
    ended_ts: Optional[float] = None
    exit_code: Optional[int] = None
    log_path: str = ""
    pid: Optional[int] = None
    metadata: dict = field(default_factory=dict)  # caller-supplied context

    def to_dict(self) -> dict:
        d = asdict(self)
        # Hide internal cwd noise from API response; client doesn't need it.
        d.pop("cwd", None)
        d["duration_s"] = (
            round((self.ended_ts or time.time()) - self.started_ts, 1)
            if self.started_ts else None
        )
        return d


class JobTracker:
    """Thread-safe job registry. Single global instance used by server.py."""

    def __init__(self):
        self._lock = threading.Lock()
        # OrderedDict for O(1) reverse-chronological iteration when pruning.
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._procs: dict[str, subprocess.Popen] = {}

    # ─── Public API ────────────────────────────────────────────────────────

    def spawn(
        self,
        cmd: list[str],
        *,
        label: str,
        kind: str,
        cwd: Path | str = ROOT,
        env: dict | None = None,
        metadata: dict | None = None,
    ) -> Job:
        """Start a subprocess, write its output to a per-job log file,
        return the Job record immediately (non-blocking)."""
        active = sum(1 for j in self._jobs.values() if j.status == "running")
        if active >= MAX_ACTIVE:
            raise RuntimeError(
                f"Job limit reached ({active}/{MAX_ACTIVE} running) — "
                f"wait for current jobs to finish or raise PODCAST_MAX_ACTIVE_JOBS."
            )

        job_id = uuid.uuid4().hex[:12]
        log_path = JOBS_DIR / f"{job_id}.log"
        job = Job(
            id=job_id,
            label=label,
            kind=kind,
            cmd=list(cmd),
            cwd=str(cwd),
            status="pending",
            started_ts=time.time(),
            log_path=str(log_path),
            metadata=dict(metadata or {}),
        )

        # Write a header to the log so post-mortem readers know what ran.
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# job {job_id} · {label}\n")
            f.write(f"# kind={kind} cwd={cwd}\n")
            f.write(f"# cmd: {shlex.join(cmd)}\n")
            f.write(f"# started: {time.strftime('%F %T', time.localtime(job.started_ts))}\n")
            f.write("# ─── output below ─────────────────────────────────\n")
            f.flush()

        try:
            # Inherit env so PATH / SSH_AUTH_SOCK / dotfiles work; layer caller overrides on top.
            full_env = {**os.environ, **(env or {})}
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=open(log_path, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                env=full_env,
                # New process group so we can SIGTERM the whole tree (e.g. uv run → python).
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            # spawn failure — record and surface, don't pretend it ran
            job.status = "failed"
            job.ended_ts = time.time()
            job.exit_code = -1
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[spawn failed] {type(exc).__name__}: {exc}\n")
            with self._lock:
                self._jobs[job_id] = job
                self._prune_locked()
            return job

        job.pid = proc.pid
        job.status = "running"
        with self._lock:
            self._jobs[job_id] = job
            self._procs[job_id] = proc
            self._prune_locked()

        # Reaper thread: blocks on proc.wait() and updates the job record.
        threading.Thread(target=self._reap, args=(job_id,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())[-limit:][::-1]  # newest first

    def kill(self, job_id: str) -> bool:
        with self._lock:
            proc = self._procs.get(job_id)
            job = self._jobs.get(job_id)
        if not proc or not job or job.status != "running":
            return False
        try:
            # SIGTERM the entire group (handles `uv run python pipeline.py` properly).
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return False
        # The reaper thread will flip status to "killed" once wait() returns.
        return True

    def tail_log(self, job_id: str, max_bytes: int = 32_768) -> str:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return ""
        p = Path(job.log_path)
        if not p.exists():
            return ""
        try:
            size = p.stat().st_size
            with p.open("rb") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                    # Drop the partial first line so a tail starts on a boundary.
                    f.readline()
                data = f.read()
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""

    # ─── Internals ─────────────────────────────────────────────────────────

    def _reap(self, job_id: str) -> None:
        with self._lock:
            proc = self._procs.get(job_id)
            job = self._jobs.get(job_id)
        if not proc or not job:
            return
        try:
            rc = proc.wait()
        except Exception as exc:  # noqa: BLE001 — anything from wait() ends the job
            rc = -1
            with open(job.log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[reaper exception] {type(exc).__name__}: {exc}\n")

        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.ended_ts = time.time()
            j.exit_code = rc
            if j.status == "running":
                j.status = "succeeded" if rc == 0 else ("killed" if rc < 0 else "failed")
            self._procs.pop(job_id, None)

    def _prune_locked(self) -> None:
        """Drop oldest finished jobs once history exceeds MAX_HISTORY."""
        if len(self._jobs) <= MAX_HISTORY:
            return
        excess = len(self._jobs) - MAX_HISTORY
        for jid, j in list(self._jobs.items()):
            if excess <= 0:
                break
            if j.status not in {"running", "pending"}:
                # Best-effort cleanup of the log file too.
                try:
                    Path(j.log_path).unlink(missing_ok=True)
                except OSError:
                    pass
                self._jobs.pop(jid, None)
                excess -= 1


# Global singleton — server.py imports this.
tracker = JobTracker()
