"""Thin SSH/rsync wrappers for the Lightsail backend.

Mirrors the constants in ops/podcast_upload.sh so the dashboard and the bash
script speak to the same host. Used by:
  - GET  /api/remote/series      — list what's published
  - GET  /api/remote/disk        — df -h on the data volume
  - DELETE /api/remote/series/{id} — rm -rf on a single series

We deliberately keep these as `subprocess.run` calls (sync, blocking) instead
of going through paramiko — same auth path as the existing bash tooling, no
new dependency, and identical key/known-hosts behavior.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

HOME = Path.home()

SSH_KEY = Path(os.getenv("PODCAST_SSH_KEY", str(HOME / ".ssh" / "lightsail_default.pem")))
SERVER = os.getenv("PODCAST_REMOTE_SERVER", "ubuntu@13.193.212.134")
REMOTE_PODCAST_DIR = os.getenv(
    "PODCAST_REMOTE_DIR", "~/knowledge_graph_api/data/podcasts"
)
SSH_TIMEOUT = int(os.getenv("PODCAST_SSH_TIMEOUT", "20"))

# Series ID validation — MUST mirror backend `_SERIES_ID_RE` in routers/podcast.py.
# Any divergence means the dashboard could try to delete a path the server
# refuses to serve (or worse, escape into a parent dir).
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")


class RemoteError(RuntimeError):
    """SSH command failed. Carries exit code + stderr tail for the API layer."""

    def __init__(self, code: int, stderr: str, cmd: list[str]):
        self.code = code
        self.stderr = stderr
        self.cmd = cmd
        super().__init__(f"ssh exited {code}: {stderr.strip()[:200]}")


def _ssh_base() -> list[str]:
    return [
        "ssh",
        "-T",
        "-i", str(SSH_KEY),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={SSH_TIMEOUT}",
        SERVER,
    ]


def _run_ssh(remote_cmd: str, *, timeout: int | None = None) -> str:
    """Run a remote command, return stdout. Raise RemoteError on non-zero.

    `remote_cmd` is passed as a single arg to ssh, which then hands it to
    the user's login shell. CALLERS must not template untrusted input —
    use validate_series_id() for series IDs and never interpolate raw user
    strings into shell commands.
    """
    cmd = _ssh_base() + [remote_cmd]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout or (SSH_TIMEOUT + 10),
    )
    if proc.returncode != 0:
        raise RemoteError(proc.returncode, proc.stderr, cmd)
    return proc.stdout


def validate_series_id(series_id: str) -> str:
    """Reject anything that doesn't match the backend regex. Returns the id
    unchanged on success (convenience for inline use)."""
    if not _SERIES_ID_RE.match(series_id):
        raise ValueError(
            f"invalid series_id {series_id!r} — must match {_SERIES_ID_RE.pattern}"
        )
    return series_id


# ─── High-level operations ───────────────────────────────────────────────────


def list_remote_series() -> list[dict]:
    """Return the parsed remote index.json + per-series disk size.

    Falls back to scanning metadata.json files if index.json is missing.
    """
    # Single SSH round-trip: cat index.json + du for each series dir.
    # The shell snippet below is fixed (no interpolation) — safe.
    #
    # `printf '\n'` after `cat` is load-bearing: ops/podcast_upload.sh's
    # `json.dump` does not emit a trailing newline, so without it the `]`
    # collapses onto the next `---SIZES---` line and the sentinel parser
    # below fails to split sections. (Caught in Phase 1 smoke test.)
    script = (
        f"cd {REMOTE_PODCAST_DIR} 2>/dev/null || exit 0; "
        "echo '---INDEX---'; "
        "cat index.json 2>/dev/null || echo '[]'; "
        "printf '\\n'; "
        "echo '---SIZES---'; "
        "for d in */; do "
        '  size=$(du -sb "$d" 2>/dev/null | cut -f1); '
        '  echo "${d%/}:$size"; '
        "done"
    )
    out = _run_ssh(script)
    sizes: dict[str, int] = {}
    index: list[dict] = []
    section = None
    for line in out.splitlines():
        if line == "---INDEX---":
            section = "index"
            buf: list[str] = []
            continue
        if line == "---SIZES---":
            section = "sizes"
            if buf:
                try:
                    index = json.loads("\n".join(buf))
                except json.JSONDecodeError:
                    index = []
            continue
        if section == "index":
            buf.append(line)
        elif section == "sizes" and ":" in line:
            sid, sz = line.split(":", 1)
            try:
                sizes[sid] = int(sz)
            except ValueError:
                pass

    # Stitch sizes onto index entries; surface orphan dirs (size present but
    # missing from index) so the user can spot a half-uploaded series.
    indexed_ids = {e.get("id") for e in index if isinstance(e, dict)}
    for entry in index:
        if isinstance(entry, dict) and entry.get("id") in sizes:
            entry["sizeBytes"] = sizes[entry["id"]]
    orphans = [
        {"id": sid, "sizeBytes": sz, "orphan": True}
        for sid, sz in sizes.items()
        if sid not in indexed_ids
    ]
    return list(index) + orphans


def remote_disk_usage() -> dict:
    """`df -h` on the data volume + the podcasts dir size. One byte-level
    number is enough — UI does the formatting."""
    script = (
        f"df -B1 --output=size,used,avail,pcent {REMOTE_PODCAST_DIR} | tail -1; "
        f"du -sb {REMOTE_PODCAST_DIR} 2>/dev/null | cut -f1"
    )
    out = _run_ssh(script).strip().splitlines()
    if len(out) < 2:
        raise RemoteError(0, "df output malformed: " + repr(out), [])
    parts = out[0].split()
    podcast_bytes = int(out[1]) if out[1].isdigit() else 0
    return {
        "total_bytes": int(parts[0]),
        "used_bytes": int(parts[1]),
        "avail_bytes": int(parts[2]),
        "use_percent": parts[3],
        "podcast_bytes": podcast_bytes,
    }


def delete_remote_series(series_id: str) -> dict:
    """rm -rf the series dir, then rebuild index.json (flock-serialized,
    same lock as ops/podcast_upload.sh)."""
    validate_series_id(series_id)
    # Build the rm command separately so series_id is not splat into the
    # shell pipeline as a string fragment. Use python on the remote side
    # to do the deletion + index rebuild in one atomic-ish hop.
    rebuild_py = (
        "import sys, json, os, glob, shutil; "
        "pdir = os.path.expanduser(sys.argv[1]); "
        "sid = sys.argv[2]; "
        "target = os.path.join(pdir, sid); "
        "import re; assert re.match(r'^[a-z0-9_]+$', sid), 'bad sid'; "
        "shutil.rmtree(target, ignore_errors=True); "
        "idx = []; "
        "[idx.append({k:v for k,v in json.load(open(p)).items() if k!='episodes'} "
        "  | {'episodeCount': len(json.load(open(p)).get('episodes', []))}) "
        "  for p in sorted(glob.glob(os.path.join(pdir, '*/metadata.json')))]; "
        "tmp = os.path.join(pdir, 'index.json.tmp'); "
        "json.dump(idx, open(tmp, 'w'), indent=2, ensure_ascii=False); "
        "os.replace(tmp, os.path.join(pdir, 'index.json')); "
        "print(json.dumps({'deleted': sid, 'remaining': len(idx)}))"
    )
    cmd = (
        f"flock /tmp/podcast_index.lock python3 -c "
        f"{_sh_quote(rebuild_py)} "
        f"{_sh_quote(REMOTE_PODCAST_DIR)} "
        f"{_sh_quote(series_id)}"
    )
    out = _run_ssh(cmd, timeout=60)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"deleted": series_id, "remaining": None, "raw": out}


def _sh_quote(s: str) -> str:
    """POSIX shell single-quote — never breaks even on '$', backticks, etc."""
    return "'" + s.replace("'", "'\\''") + "'"
