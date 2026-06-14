"""Disk-derived workspace status primitives — the pure, FastAPI-free core.

Extracted from ``server.py`` so headless tooling (``ops/podcast_ops.py``) can
reuse the EXACT same artifact-derivation logic the dashboard renders, without
importing FastAPI / mounting StaticFiles / triggering the upload-staging side
effects that ``import server`` incurs. ``server.py`` re-imports every name from
here, so there is a single source of truth and the existing monitor test suite
(which imports ``server``) keeps exercising this code unchanged.

Everything here is stdlib-only and reads from on-disk artifacts — never from the
in-memory job tracker (a runtime concern that only exists while the dashboard is
live). The one runtime-aware field, "running" status, is layered on top by the
caller via ``disk_status(..., active_job=...)``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

# Workspace name regex — same constraint as backend _SERIES_ID_RE plus a
# safety guard against `..` / absolute paths sneaking in via FastAPI path params.
_WS_NAME_RE = re.compile(r"\A[a-z0-9_]+\Z")

# Pipeline stage order (mirror of pipeline.py STAGES) — used for the
# marker-based resume point. Keep in sync with pipeline.py.
_STAGES_ORDERED = (
    "prep", "analyst", "architect", "plan-review",
    "enricher-gap", "enricher", "scriptwrite",
    "series-polish", "script-review",
    "tts-prep", "synthesize", "audio-qa", "subtitle", "cover", "publish",
)
_STAGE_NAMES = set(_STAGES_ORDERED)
_STAGE_COUNT = len(_STAGES_ORDERED)
# Final stage — when its done-marker exists, the whole workspace is "done".
_FINAL_STAGE = "publish"

_MILESTONE_KEYS = ("plan", "script", "audio", "subtitle")
logger = logging.getLogger(__name__)

# Per-episode artifact gate regexes (durable, disk-derived). Leading-zero
# tolerant so ep_04 and ep_4 collapse to the same episode number.
_EP_PLAN_RE = re.compile(r"ep_0*(\d+)\.md$")
_EP_SCRIPT_RE = re.compile(r"ep_0*(\d+)_script\.md$")
_EP_AUDIO_RE = re.compile(r"ep_0*(\d+)_(pro|flash)\.(mp3|m4a)$")
_EP_SRT_RE = re.compile(r"ep_0*(\d+)_(pro|flash)\.srt$")


def _stages_done(ws: Path) -> set[str]:
    """Stage names whose done-marker (`.stage_<name>_done`) exists in *ws*."""
    return {
        m.name.replace(".stage_", "").replace("_done", "")
        for m in ws.glob(".stage_*_done")
    }


def _read_tail(plog: Path, nbytes: int = 65536) -> str | None:
    """Last *nbytes* of the log decoded as utf-8, or None if absent/unreadable.
    A stage_end/error is one line; even a verbose run rarely emits >64KB after
    the latest failure, so the tail is sufficient for failure/last-activity reads."""
    if not plog.exists():
        return None
    try:
        size = plog.stat().st_size
        with plog.open("rb") as f:
            f.seek(max(0, size - nbytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError as exc:
        __import__("logging").getLogger(__name__).warning(
            "failed to read tail from pipeline log=%s: %s",
            plog,
            exc,
        )
        logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return None


def _iter_log(tail: str):
    """Yield (line_index, parsed_obj) for each well-formed JSON line in *tail*."""
    for i, line in enumerate(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            yield i, json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed JSON line in workspace log tail (line=%s)", i)
            continue


def failure_detail(plog: Path, stages_done: set[str]) -> dict | None:
    """Rich detail for the most-recent UNRESOLVED stage failure, or None.

    Returns ``{"stage", "at", "error"}`` where *stage* is the failing stage,
    *at* is that failing stage_end's ``ts`` (or None), and *error* is the nearest
    preceding ``error`` event's msg (the WHY — pipeline logs the error then
    returns False then the loop writes stage_end(success=False), so the error
    line sits just before the failing stage_end). One tail scan feeds both the
    status cascade and the human-facing reason, so there is no second scan.

    "Unresolved" = the stage's latest stage_end was success=false AND it has no
    done-marker (a rerun that succeeded would have written one). When several
    stages are unresolved, the MOST RECENT in the log wins — the one an operator
    should look at first.
    """
    tail = _read_tail(plog)
    if tail is None:
        return None

    latest: dict[str, bool] = {}      # stage -> latest stage_end success flag
    order: dict[str, int] = {}        # stage -> latest stage_end line index
    at: dict[str, str | None] = {}    # stage -> latest stage_end ts
    errors: list[tuple[int, str]] = []  # (line index, msg) for every error event
    for i, obj in _iter_log(tail):
        ev = obj.get("event")
        if ev == "stage_end":
            stage = obj.get("stage")
            if stage:
                latest[stage] = bool(obj.get("success", True))
                order[stage] = i
                at[stage] = obj.get("ts")
        elif ev == "error":
            errors.append((i, str(obj.get("msg", ""))))

    unresolved = [
        (order[stage], stage)
        for stage, success in latest.items()
        if success is False and stage not in stages_done
    ]
    if not unresolved:
        return None
    idx, stage = max(unresolved)
    # Nearest error event AT or BEFORE the failing stage_end (greatest index ≤ idx).
    prior = [(i, msg) for i, msg in errors if i <= idx]
    error = max(prior)[1] if prior else None
    return {"stage": stage, "at": at.get(stage), "error": error}


def unresolved_failed_stage(plog: Path, stages_done: set[str]) -> str | None:
    """The stage of the most-recent unresolved failure, or None. Thin accessor
    over failure_detail so the cascade, the reason and the detail share one scan."""
    d = failure_detail(plog, stages_done)
    return d["stage"] if d else None


def _scan_pipeline_log_status(plog: Path, stages_done: set[str]) -> bool:
    """True iff an unresolved stage failure exists (single source of truth)."""
    return failure_detail(plog, stages_done) is not None


def next_incomplete_stage(stages_done: set[str]) -> str | None:
    """First pipeline stage (in order) without a done-marker — the resume point,
    mirroring pipeline.py detect_resume_point but keyed by name. None if every
    stage is marked done."""
    for stage in _STAGES_ORDERED:
        if stage not in stages_done:
            return stage
    return None


def last_activity(ws: Path) -> str | None:
    """ts of the most recent pipeline_log line (any event), or None if no log.
    The disk-derived 'how long since anything happened here' signal."""
    tail = _read_tail(ws / "pipeline_log.jsonl")
    if tail is None:
        return None
    ts = None
    for _i, obj in _iter_log(tail):
        if obj.get("ts"):
            ts = obj["ts"]
    return ts


def _milestones(ws: Path) -> tuple[list[dict], float]:
    """Derive the four production gates from on-disk artifacts.

    Returns (milestones, overall_progress) where milestones is a list of
    {key,label,done,total,ratio} (one per gate, in pipeline order) and
    overall_progress is the 0..1 bar fill = mean of the four ratios.

    Target episode count = max(planned episodes, scripts, audio, subtitle) so
    a gate ratio never exceeds 1.0 even when, say, audio was synthesized for
    more episodes than the plan dir currently lists.
    """
    scripts = ws / "scripts"
    plan_eps = ws / "plan" / "episodes"

    n_plan_eps = len(list(plan_eps.glob("ep_*.md"))) if plan_eps.is_dir() else 0
    if scripts.is_dir():
        n_script = sum(1 for _ in scripts.glob("ep_*_script.md"))
        n_audio = sum(
            1 for f in [*scripts.glob("ep_*.mp3"), *scripts.glob("ep_*.m4a")]
            if re.match(r"ep_\d+_(pro|flash)\.(mp3|m4a)$", f.name)
        )
        n_srt = sum(
            1 for f in scripts.glob("ep_*.srt")
            if re.match(r"ep_\d+_(pro|flash)\.srt$", f.name)
        )
    else:
        n_script = n_audio = n_srt = 0

    target = max(n_plan_eps, n_script, n_audio, n_srt)
    has_plan = (ws / "plan" / "overview.md").exists()

    # PLAN gate is binary on overview.md (the architect's deliverable); the
    # other three scale with episode artifacts against `target`.
    def ratio(done: int) -> float:
        return min(1.0, done / target) if target else 0.0

    milestones = [
        {"key": "plan", "label": "PLAN",
         "done": 1 if has_plan else 0, "total": 1,
         "ratio": 1.0 if has_plan else 0.0},
        {"key": "script", "label": "SCRIPT",
         "done": n_script, "total": target, "ratio": ratio(n_script)},
        {"key": "audio", "label": "AUDIO",
         "done": n_audio, "total": target, "ratio": ratio(n_audio)},
        {"key": "subtitle", "label": "SUBTITLE",
         "done": n_srt, "total": target, "ratio": ratio(n_srt)},
    ]
    overall = sum(m["ratio"] for m in milestones) / len(milestones)
    return milestones, overall


def _episode_status(ws: Path) -> list[dict]:
    """Per-episode gate status from on-disk artifacts.

    Returns a list (sorted by episode number) of
    {ep, plan, script, audio, subtitle, variant, audio_bytes}. `variant` /
    `audio_bytes` describe the chosen mp3 (pro preferred over flash) or are
    None when no audio exists. Decoy files (ep_N_review.md,
    ep_N_voice_preview.mp3) are excluded by the strict regexes.
    """
    plan_eps = ws / "plan" / "episodes"
    scripts = ws / "scripts"

    eps: set[int] = set()
    plan_set: set[int] = set()
    if plan_eps.is_dir():
        for f in plan_eps.glob("ep_*.md"):
            m = _EP_PLAN_RE.match(f.name)
            if m:
                n = int(m.group(1))
                eps.add(n)
                plan_set.add(n)

    script_set: set[int] = set()
    srt_set: set[int] = set()
    audio: dict[int, dict] = {}  # ep -> {variant, bytes}; pro wins over flash
    if scripts.is_dir():
        for f in scripts.glob("ep_*_script.md"):
            m = _EP_SCRIPT_RE.match(f.name)
            if m:
                n = int(m.group(1))
                eps.add(n)
                script_set.add(n)
        for f in [*scripts.glob("ep_*.mp3"), *scripts.glob("ep_*.m4a")]:
            m = _EP_AUDIO_RE.match(f.name)
            if not m:
                continue  # skip ep_N_voice_preview.mp3 etc.
            n = int(m.group(1))
            variant = m.group(2)
            eps.add(n)
            cur = audio.get(n)
            if cur is None or (cur["variant"] == "flash" and variant == "pro"):
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                audio[n] = {"variant": variant, "bytes": size}
        for f in scripts.glob("ep_*.srt"):
            m = _EP_SRT_RE.match(f.name)
            if m:
                n = int(m.group(1))
                eps.add(n)
                srt_set.add(n)

    out: list[dict] = []
    for n in sorted(eps):
        a = audio.get(n)
        out.append({
            "ep": n,
            "plan": n in plan_set,
            "script": n in script_set,
            "audio": a is not None,
            "subtitle": n in srt_set,
            "variant": a["variant"] if a else None,
            "audio_bytes": a["bytes"] if a else None,
        })
    return out


def _gate_states(
    ws: Path, *, has_plan: bool, n_script: int, n_audio: int, target: int,
) -> list[dict]:
    """Tri-state for the two approval gates: passed / awaiting / pending.

    gate1 (plan→script):
      passed   — n_script>0 OR .plan_approved exists (de-facto or explicit)
      awaiting — plan complete, no scripts yet, not approved
      pending  — plan not complete
    gate2 (script→audio):
      passed   — n_audio>0 OR .script_approved exists
      awaiting — scripts complete (n_script==target>0), no audio, not approved
      pending  — scripts not complete
    """
    if n_script > 0 or (ws / ".plan_approved").exists():
        g1 = "passed"
    elif has_plan:
        g1 = "awaiting"
    else:
        g1 = "pending"

    scripts_complete = target > 0 and n_script >= target
    if n_audio > 0 or (ws / ".script_approved").exists():
        g2 = "passed"
    elif scripts_complete:
        g2 = "awaiting"
    else:
        g2 = "pending"

    return [{"key": "plan", "state": g1}, {"key": "script", "state": g2}]


def _ensure_created(ws: Path) -> float:
    """Return the workspace 'added' timestamp (epoch seconds), backfilling it.

    Ground truth is a `.created` sidecar holding an epoch float. If absent
    (every pre-existing workspace), seed it from the directory's real birth
    time — st_birthtime on APFS/macOS, falling back to st_mtime on filesystems
    that don't track it (Linux ext4). Persisting it to `.created` shields the
    value from later rsync/restore operations that would otherwise reset the
    inode's birth time.
    """
    marker = ws / ".created"
    try:
        raw = marker.read_text().strip()
        return float(raw)
    except (OSError, ValueError):
        __import__("logging").getLogger(__name__).info(
            "workspace=%s .created marker missing/unreadable; falling back to filesystem time",
            ws.name,
            exc_info=True,
        )
    # No (or unreadable) sidecar — derive from inode birth time. Guard the
    # stat() too: the dir can vanish in the TOCTOU window between the route's
    # directory listing and this call. Returning 0.0 keeps the contract that
    # one bad workspace never breaks the whole sidebar list.
    try:
        st = ws.stat()
    except OSError as exc:
        __import__("logging").getLogger(__name__).warning(
            "workspace=%s marker read failed, fallback derived age value",
            ws,
            exc_info=True,
        )
        logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return 0.0
    bt = getattr(st, "st_birthtime", None)
    created = bt if bt is not None else st.st_mtime  # 0.0 birthtime is valid, don't `or`
    try:
        marker.write_text(f"{created}\n")
    except OSError:
        __import__("logging").getLogger(__name__).info(
            "workspace=%s .created marker write skipped (read-only mount?)",
            ws.name,
            exc_info=True,
        )  # read-only mount etc. — still return the derived value
    return created


def _workspace_has_audio(ws: Path) -> bool:
    """A workspace counts as 'synthesized' once it holds an audio artifact that
    ops/podcast_upload.sh would actually publish. MUST mirror upload.sh's stage
    glob (ep_*_{pro,flash}.{m4a,mp3}, :64-67) — matching a looser ep_*.mp3 would
    flag a workspace holding only intermediate audio (e.g. ep_1_raw.mp3) as
    synthesized, stranding it as permanently 'drifted' since upload.sh would
    stage nothing for it."""
    scripts = ws / "scripts"
    if not scripts.is_dir():
        return False
    return any(
        any(scripts.glob(f"ep_*_{variant}.{ext}"))
        for variant in ("pro", "flash")
        for ext in ("m4a", "mp3")
    )


def reconcile_workspaces(workspaces_dir: Path, published_ids: set[str]) -> list[dict]:
    """Drift report: workspaces that have synthesized audio but whose series id
    is absent from the S3 catalog — i.e. publish never succeeded. This is the
    forward-looking net that catches a silently-failed auto-upload, distinct
    from the served-disk↔S3 reconcile (ops/podcast_backfill_disk.py --check)
    which covers the legacy instance-disk series."""
    if not workspaces_dir.exists():
        return []
    drifted = []
    for ws in sorted(p for p in workspaces_dir.iterdir() if p.is_dir()):
        if _workspace_has_audio(ws) and ws.name not in published_ids:
            drifted.append({"workspace": ws.name, "reason": "synthesized_not_published"})
    return drifted


# Synthesized-episode regex. Intentionally NOT leading-zero tolerant (no `0*`):
# this mirrors the dashboard's historical episode_count glob exactly so the
# count is byte-for-byte identical whether read via the server or headlessly.
_AUDIO_EP_RE = re.compile(r"ep_(\d+)_(pro|flash)\.(mp3|m4a)$")


def audio_episode_numbers(ws: Path) -> set[int]:
    """Set of episode numbers that have a synthesized audio artifact (pro/flash,
    mp3/m4a). Deduped across variants — an episode with both pro and flash audio
    counts once, which is why this returns a set rather than a file count."""
    scripts = ws / "scripts"
    eps: set[int] = set()
    if scripts.is_dir():
        for f in [*scripts.glob("ep_*.mp3"), *scripts.glob("ep_*.m4a")]:
            m = _AUDIO_EP_RE.match(f.name)
            if m:
                eps.add(int(m.group(1)))
    return eps


def disk_status(
    ws: Path,
    *,
    stages_done: set[str],
    has_episodes: bool,
    gate_state: dict[str, str],
    active_job: dict | None = None,
) -> str:
    """The status cascade (running > done > failed > awaiting > idle > fresh).

    Single source of truth for both the dashboard sidebar (passes a live
    ``active_job``) and headless tooling (passes ``None`` — there is no in-memory
    job tracker outside the running server, so "running" is never inferred from
    disk). Every input is precomputed by the caller so neither path double-scans.

    - running  — a live job is bound to this workspace (dashboard only)
    - done     — the final stage's done-marker exists
    - failed   — an unresolved stage_end failure in pipeline_log.jsonl
    - awaiting — paused at an approval gate (plan or script gate == awaiting)
    - fresh    — no markers AND no audio artifacts (truly untouched)
    - idle     — has artifacts but none of the above
    """
    if active_job:
        return "running"
    if _FINAL_STAGE in stages_done:
        return "done"
    if _scan_pipeline_log_status(ws / "pipeline_log.jsonl", stages_done):
        return "failed"
    if "awaiting" in (gate_state.get("plan"), gate_state.get("script")):
        return "awaiting"
    if not stages_done and not has_episodes:
        return "fresh"
    return "idle"


def headless_summary(ws: Path, active_job: dict | None = None) -> dict:
    """Disk-derived workspace summary for headless callers (ops/podcast_ops.py).

    A FastAPI-free subset of the dashboard's ``_workspace_summary``: status +
    progress + the four production gates + episode count, all from artifacts.
    Deliberately omits the runtime/cost/saga fields (active_job tracker, cost
    aggregation, series.md parsing) — the CLI layers cost on top via cost.py and
    has no live job tracker, so "running" is only reported if a caller injects an
    ``active_job`` (the CLI never does).
    """
    stages_done = _stages_done(ws)
    milestones, progress = _milestones(ws)
    _ms = {m["key"]: m for m in milestones}
    has_plan = bool(_ms.get("plan", {}).get("done"))
    n_script = int(_ms.get("script", {}).get("done", 0))
    n_audio = int(_ms.get("audio", {}).get("done", 0))
    target = int(_ms.get("script", {}).get("total", 0))
    gates = _gate_states(
        ws, has_plan=has_plan, n_script=n_script, n_audio=n_audio, target=target,
    )
    gate_state = {g["key"]: g["state"] for g in gates}
    episodes = audio_episode_numbers(ws)
    status = disk_status(
        ws, stages_done=stages_done, has_episodes=bool(episodes),
        gate_state=gate_state, active_job=active_job,
    )
    out = {
        "name": ws.name,
        "status": status,
        "episode_count": len(episodes),
        "progress": round(progress, 4),
        "milestones": milestones,
        "gates": gates,
        # Disk-derived recency so callers can age a stuck workspace (None = the
        # pipeline never logged anything here).
        "last_activity": last_activity(ws),
        # The resume point — first stage without a done-marker. Lets idle/failed
        # rows render a copy-pasteable `pipeline.py --skip-to <stage>` next step.
        "resume_stage": next_incomplete_stage(stages_done),
    }
    # Surface WHY/WHEN a failure happened. This re-reads the tail (a second small
    # ≤64KB scan after disk_status's cascade scan) — cheap, and only on the
    # failed path; we reuse the already-computed stages_done so the verdict can't
    # disagree with the cascade.
    if status == "failed":
        d = failure_detail(ws / "pipeline_log.jsonl", stages_done) or {}
        out["failed_stage"] = d.get("stage")
        out["failed_at"] = d.get("at")
        out["error"] = d.get("error")
    # Name the gate the producer must approve (which of plan/script is awaiting).
    if status == "awaiting":
        out["awaiting_gate"] = (
            "plan" if gate_state.get("plan") == "awaiting" else "script")
    return out
