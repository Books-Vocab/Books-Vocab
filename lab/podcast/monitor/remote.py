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


def _run_ssh(
    remote_cmd: str,
    *,
    timeout: int | None = None,
    stdin_data: str | None = None,
) -> str:
    """Run a remote command, return stdout. Raise RemoteError on non-zero.

    `remote_cmd` is passed as a single arg to ssh, which then hands it to
    the user's login shell. CALLERS must not template untrusted input —
    use validate_series_id() for series IDs and never interpolate raw user
    strings into shell commands.

    `stdin_data` lets callers pipe a multi-line script (e.g. python -c <stdin)
    instead of cramming everything into a one-liner — vastly cleaner than
    semicolon-chained statements when we need try/except.
    """
    cmd = _ssh_base() + [remote_cmd]
    proc = subprocess.run(
        cmd, input=stdin_data, capture_output=True, text=True,
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


_REBUILD_SCRIPT = r"""
import sys, os, re, json, glob, shutil

pdir = os.path.expanduser(sys.argv[1])
sid = sys.argv[2]

# Defense-in-depth — caller already validated, but assert can be stripped
# with -O so use a real check that survives.
if not re.match(r"^[a-z0-9_]+$", sid):
    print(json.dumps({"error": f"bad series_id: {sid}"}), file=sys.stderr)
    sys.exit(2)

target = os.path.join(pdir, sid)

# Track rm errors so the API can surface partial deletes instead of
# silently lying. shutil.rmtree(onerror=...) lets us collect each failure
# without aborting (we want index rebuild to still happen, but the response
# must mark the series as not-fully-deleted so the dashboard knows.)
rm_errors = []
def _onerr(func, path, exc_info):
    rm_errors.append({"path": path, "err": f"{exc_info[0].__name__}: {exc_info[1]}"})

if os.path.exists(target):
    shutil.rmtree(target, onerror=_onerr)

# Verify the directory actually disappeared. If it didn't (permission, EBUSY,
# something half-removed), report fully deleted=False.
still_exists = os.path.exists(target)

# Rebuild index, skipping any metadata.json we can't parse so one corrupt
# series doesn't take down the entire index.json. Bad files are reported.
idx = []
bad_files = []
for p in sorted(glob.glob(os.path.join(pdir, "*/metadata.json"))):
    try:
        with open(p, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        bad_files.append({"path": p, "err": f"{type(e).__name__}: {e}"})
        continue
    entry = {k: v for k, v in meta.items() if k != "episodes"}
    entry["episodeCount"] = len(meta.get("episodes", []))
    idx.append(entry)

tmp = os.path.join(pdir, "index.json.tmp")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(idx, f, indent=2, ensure_ascii=False)
    f.write("\n")  # match podcast_upload.sh trailing newline expectation
os.replace(tmp, os.path.join(pdir, "index.json"))

print(json.dumps({
    "deleted": sid,
    "fully_deleted": not still_exists,
    "remaining": len(idx),
    "rm_errors": rm_errors,
    "bad_metadata_files": bad_files,
}))
"""


def delete_remote_series(series_id: str) -> dict:
    """rm -rf the series dir, then rebuild index.json (flock-serialized,
    same lock as ops/podcast_upload.sh).

    Returns the parsed JSON from the remote script. Caller MUST check
    `fully_deleted` — if False, `rm_errors` lists which files survived. The
    bad_metadata_files key lists any per-series metadata.json that couldn't
    be parsed (those series are dropped from the rebuilt index, mirroring
    what the user would observe in the API anyway).
    """
    validate_series_id(series_id)
    # Pipe the multi-line python script via stdin so we can have real
    # try/except blocks instead of semicolon-chained one-liners. Series_id
    # still goes through argv with _sh_quote so the user-supplied value is
    # never spliced into the script source itself.
    cmd = (
        f"flock /tmp/podcast_index.lock python3 - "
        f"{_sh_quote(REMOTE_PODCAST_DIR)} "
        f"{_sh_quote(series_id)}"
    )
    out = _run_ssh(cmd, stdin_data=_REBUILD_SCRIPT, timeout=60)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        # Script malformed its own output — surface to caller as a 502 by
        # raising RemoteError instead of pretending it succeeded.
        raise RemoteError(0, f"remote script returned unparseable output: {out!r}", [])


def _sh_quote(s: str) -> str:
    """POSIX shell single-quote — never breaks even on '$', backticks, etc."""
    return "'" + s.replace("'", "'\\''") + "'"
