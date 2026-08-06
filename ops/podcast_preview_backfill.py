#!/usr/bin/env -S uv run --python 3.13 --with boto3 python
"""Backfill free-tier **preview** clips for podcast series already in S3.

Why this exists separately from ``ops/podcast_upload.sh``:
``podcast_upload.sh`` generates ``ep_01/preview.<fmt>`` for *new* publishes from
the lab workspace. Series published before the tiered-access change have no
preview object, so a free-tier caller would 404 on episode 1. This tool walks
the **bucket itself** (no local workspace needed — the source of truth for an
already-published series is S3) and, for each series:

  1. download ``<sid>/ep_01/audio.<fmt>``               — the full episode 1.
  2. stream-copy the first ``PREVIEW_SECONDS`` (``ffmpeg -t N -c copy``) into a
     ``preview.<fmt>`` — same container/codec, no re-encode, near-instant,
     lossless. A byte-truncated copy of a progressive MP4 cannot be played
     cleanly (its single ``moov`` advertises the full duration), so the preview
     MUST be a self-contained re-muxed file — exactly what ``-c copy`` produces.
  3. PUT ``<sid>/ep_01/preview.<fmt>``                  — a *new* key; nothing
     points at it until step 4, so no client-visible side effect yet.
  4. read-modify-write ``<sid>/metadata.json`` setting episode 1's
     ``previewAvailable=true`` + ``previewDurationSec`` **and bumping
     ``updatedAt``** — a single-object atomic PUT.
  5. patch that same ``updatedAt`` into this series' entry in ``index.json``.

Why 4 bumps ``updatedAt`` and 5 exists at all (changed 2026-08-06). Both used to
be deliberately skipped, on the reasoning that preview fields live *inside* the
episode list — which the series-list index strips — so the catalog view was
unaffected. That reasoning stopped holding the day the iOS client started
**caching on the catalog fingerprint**: it now skips the per-series detail fetch
when nothing in ``index.json`` changed. A content mutation with no visible
signal is therefore invisible *forever* — the backfilled preview would never
reach an already-installed device, which is the entire population this tool
exists to serve.

Idempotency is preserved, just moved: ``backfill_series`` returns ``already``
and writes nothing when the preview object and the metadata flag are both
present, so a re-run still touches zero bytes. Only a run that genuinely
publishes something bumps the stamp.

``index.json`` is **patched, not rebuilt**: step 5 rewrites only this series'
entry, leaving every other entry byte-identical. Touching only
``<sid>/ep_01/preview.*`` + ``<sid>/metadata.json`` + one index entry means this
tool still can never drop or disturb another series (mirrors the audio-decoupled
discipline of ``podcast_cover_publish.py``, which rebuilds the whole index).

Atomicity = ordering: step 3 (preview object) before step 4 (the metadata flag
that makes it authoritative) makes every interruption a safe state — re-run
drives toward the published terminal state (re-entrant + idempotent).

Usage:
    # every series in the bucket missing a preview
    ops/podcast_preview_backfill.py --all [--execute]
    # specific series
    ops/podcast_preview_backfill.py --series the_let_them_theory [--execute]
    # read-only drift report (preview ⟷ metadata consistency), exit≠0 on drift
    ops/podcast_preview_backfill.py --all --check

Default is dry-run; ``--execute`` required to write. Credentials/bucket come from
the env (``PODCAST_BUCKET`` / ``AWS_PROFILE`` etc.), same model as upload.sh —
source ``lab/podcast/.env`` before running outside the monitor. Requires
``ffmpeg``/``ffprobe`` on PATH.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Must match backend podcast_access.FREE_PREVIEW_EP_NUM + PREVIEW_SECONDS in
# ops/podcast_upload.sh. Kept in sync by hand (3 call sites, all referenced in
# docs/reference/feature_boundary/podcast.md §metadata.json contract).
PREVIEW_SECONDS = 180
PREVIEW_EP_NUM = 1
# \A..\Z (not ^..$): mirror backend _SERIES_ID_RE byte-for-byte (Python's $ also
# matches before a trailing newline).
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")
_JSON_CT = "application/json; charset=utf-8"
_AUDIO_CT = {"m4a": "audio/mp4", "mp3": "audio/mpeg"}
_LOGGER = logging.getLogger(__name__)


def _is_not_found(exc: Exception, s3) -> bool:
    """True iff exc is a 404 / NoSuchKey. Any other fault (perms / throttle /
    network) must surface — mistaking AccessDenied for 'absent' would skip a
    real backfill or false-clear drift (KG 鐵律 1)."""
    nsk = getattr(getattr(s3, "exceptions", None), "NoSuchKey", ())
    if nsk and isinstance(exc, nsk):
        return True
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return code in ("NoSuchKey", "NoSuchBucket", "404")


def _get_json(s3, bucket: str, key: str):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc, s3):
            _LOGGER.debug(
                "preview metadata missing: bucket=%s key=%s; treating as absent",
                bucket,
                key,
                exc_info=True,
            )
            return None
        raise
    return json.loads(obj["Body"].read())


def _get_bytes(s3, bucket: str, key: str) -> bytes | None:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc, s3):
            _LOGGER.debug(
                "preview audio bytes missing: bucket=%s key=%s; treating as absent",
                bucket,
                key,
                exc_info=True,
            )
            return None
        raise
    return obj["Body"].read()


def _key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc, s3):
            _LOGGER.debug(
                "preview key missing: bucket=%s key=%s; treating as absent",
                bucket,
                key,
                exc_info=True,
            )
            return False
        raise


def _put(s3, bucket: str, key: str, body: bytes, content_type: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] PUT s3://{bucket}/{key}  ({len(body)} B, {content_type})")
        return
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    print(f"  PUT s3://{bucket}/{key}  ({len(body)} B)")


def resolve_audio_format(s3, bucket: str, series_id: str, meta: dict | None) -> str:
    """Series' audio extension, mirroring the backend: trust metadata.audioFormat,
    else probe ep_01 in m4a → mp3 order. Raises if neither resolves (a series
    with no ep_01 audio cannot be backfilled — loud-fail, don't guess)."""
    raw = meta.get("audioFormat") if isinstance(meta, dict) else None
    if isinstance(raw, str) and raw in ("m4a", "mp3"):
        return raw
    for cand in ("m4a", "mp3"):
        if _key_exists(s3, bucket, f"{series_id}/ep_{PREVIEW_EP_NUM:02d}/audio.{cand}"):
            return cand
    raise ValueError(f"{series_id}: no ep_{PREVIEW_EP_NUM:02d}/audio.{{m4a,mp3}} in bucket")


def make_preview_bytes(audio_body: bytes, fmt: str) -> tuple[bytes, int]:
    """Stream-copy the first PREVIEW_SECONDS of ``audio_body`` → (preview_bytes,
    duration_sec). ffmpeg/ffprobe operate on temp files: mp4 muxing with
    ``+faststart`` needs a seekable output, and ffprobe needs a real path.
    Raises on ffmpeg failure (a publish without a playable preview must fail
    loud — never PUT a broken object)."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"audio.{fmt}"
        dst = Path(td) / f"preview.{fmt}"
        src.write_bytes(audio_body)
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
               "-t", str(PREVIEW_SECONDS), "-c", "copy"]
        if fmt == "m4a":
            cmd += ["-movflags", "+faststart"]  # mp4-only
        cmd.append(str(dst))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not dst.is_file():
            raise RuntimeError(f"ffmpeg preview generation failed: {proc.stderr.strip()}")
        body = dst.read_bytes()
        duration = _probe_duration(dst)
    return body, duration


def _probe_duration(path: Path) -> int:
    try:
        pr = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if pr.returncode == 0 and pr.stdout.strip():
            return int(float(pr.stdout.strip()))
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[podcast_preview_backfill] ffprobe duration failed for {path}: {exc}", file=sys.stderr)
    return 0


def utc_stamp() -> str:
    """``updatedAt`` in the same shape the publisher writes (ISO8601, UTC)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def patch_preview_meta(meta: dict, *, duration_sec: int, stamp: str) -> dict:
    """Return a copy of metadata with episode PREVIEW_EP_NUM's preview fields set
    and ``updatedAt`` bumped to ``stamp``.

    All other fields (createdAt, episode list order, other episodes) are
    preserved verbatim. The stamp bump is what makes the change visible to a
    client that caches on the catalog fingerprint — see the module docstring.
    Idempotency lives in ``backfill_series``' ``already`` short-circuit, not in
    byte-identical rewrites.
    """
    out = dict(meta)
    episodes = [dict(e) for e in out.get("episodes", [])]
    found = False
    for ep in episodes:
        if ep.get("episodeNumber") == PREVIEW_EP_NUM:
            ep["previewAvailable"] = True
            ep["previewDurationSec"] = duration_sec
            found = True
            break
    if not found:
        raise ValueError(f"metadata has no episode {PREVIEW_EP_NUM} to mark previewable")
    out["episodes"] = episodes
    out["updatedAt"] = stamp
    return out


def patch_index_stamp(index: list, *, series_id: str, stamp: str) -> tuple[list, bool]:
    """Return (index, changed) with only ``series_id``'s ``updatedAt`` rewritten.

    Patches rather than rebuilds: every other entry stays byte-identical, so this
    tool keeps its "can never disturb another series" property. Returns
    ``changed=False`` when the series has no index entry — that is a real
    inconsistency (published metadata, absent from the catalog) and the caller
    warns rather than inventing an entry from partial data.
    """
    out = [dict(e) if isinstance(e, dict) else e for e in index]
    for entry in out:
        if isinstance(entry, dict) and entry.get("id") == series_id:
            entry["updatedAt"] = stamp
            return out, True
    return out, False


def backfill_series(s3, *, bucket: str, series_id: str, dry_run: bool = True) -> str:
    """Generate + publish the preview for one series. Returns a state string:
    ``published`` / ``already`` (skipped — preview present + metadata flagged).
    Aborts (raises) on malformed id, missing metadata, or missing ep1 audio."""
    if not _SERIES_ID_RE.match(series_id):
        raise ValueError(f"invalid series_id '{series_id}' — must match ^[a-z0-9_]+$")

    meta = _get_json(s3, bucket, f"{series_id}/metadata.json")
    if not isinstance(meta, dict):
        raise ValueError(f"{series_id}: no/invalid metadata.json — series not published")

    fmt = resolve_audio_format(s3, bucket, series_id, meta)
    preview_key = f"{series_id}/ep_{PREVIEW_EP_NUM:02d}/preview.{fmt}"

    ep1 = next((e for e in meta.get("episodes", []) if e.get("episodeNumber") == PREVIEW_EP_NUM), None)
    meta_flagged = bool(ep1 and ep1.get("previewAvailable"))
    if _key_exists(s3, bucket, preview_key) and meta_flagged:
        print("  already published (preview + metadata in sync)")
        return "already"

    audio_key = f"{series_id}/ep_{PREVIEW_EP_NUM:02d}/audio.{fmt}"
    audio_body = _get_bytes(s3, bucket, audio_key)
    if audio_body is None:
        raise ValueError(f"{series_id}: {audio_key} not in bucket")

    preview_body, duration = make_preview_bytes(audio_body, fmt)
    stamp = utc_stamp()
    # 3. preview object first — new key, metadata not pointing at it yet.
    _put(s3, bucket, preview_key, preview_body, _AUDIO_CT[fmt], dry_run=dry_run)
    # 4. metadata flag — the visibility flip. Atomic single-object replace.
    patched = patch_preview_meta(meta, duration_sec=duration, stamp=stamp)
    body = json.dumps(patched, ensure_ascii=False, indent=2).encode("utf-8")
    _put(s3, bucket, f"{series_id}/metadata.json", body, _JSON_CT, dry_run=dry_run)
    # 5. index entry — the only thing an already-installed client will ever see.
    #    Ordering mirrors step 3→4: the authoritative object lands first, the
    #    pointer that advertises it lands second, so every interruption is a
    #    safe state that a re-run drives forward.
    index = _get_json(s3, bucket, "index.json")
    if isinstance(index, list):
        patched_index, changed = patch_index_stamp(index, series_id=series_id, stamp=stamp)
        if changed:
            index_body = json.dumps(patched_index, ensure_ascii=False, indent=2).encode("utf-8")
            _put(s3, bucket, "index.json", index_body, _JSON_CT, dry_run=dry_run)
        else:
            print(f"  ⚠ {series_id} has no index.json entry — catalog fingerprint NOT bumped; "
                  "installed clients will not see this preview until the series is republished",
                  file=sys.stderr)
    else:
        print("  ⚠ index.json missing/malformed — catalog fingerprint NOT bumped", file=sys.stderr)
    return "published"


def _list_series_ids(s3, bucket: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    ids = set()
    for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
        for p in page.get("CommonPrefixes", []) or []:
            sid = p["Prefix"].rstrip("/")
            if sid:
                ids.add(sid)
    return sorted(ids)


def check(s3, *, bucket: str, series_ids: list[str]) -> dict:
    """Read-only drift report for preview ⟷ metadata consistency. Per series:
      - in_sync:               preview object present AND metadata flags ep1
      - preview_without_flag:  preview object in S3 but metadata not flagged
                               (step 4 never completed)
      - flag_without_preview:  metadata flagged but no preview object (→ free 404)
      - missing:               neither (needs backfill)
    """
    rows = {}
    for sid in series_ids:
        meta = _get_json(s3, bucket, f"{sid}/metadata.json")
        if not isinstance(meta, dict):
            rows[sid] = "no_metadata"
            continue
        try:
            fmt = resolve_audio_format(s3, bucket, sid, meta)
        except ValueError as exc:
            _LOGGER.debug("Skipping series %s in backfill check: no episode1 preview format (%s)", sid, exc)
            rows[sid] = "no_ep1_audio"
            continue
        ep1 = next((e for e in meta.get("episodes", []) if e.get("episodeNumber") == PREVIEW_EP_NUM), None)
        flagged = bool(ep1 and ep1.get("previewAvailable"))
        has_obj = _key_exists(s3, bucket, f"{sid}/ep_{PREVIEW_EP_NUM:02d}/preview.{fmt}")
        if flagged and has_obj:
            state = "in_sync"
        elif has_obj and not flagged:
            state = "preview_without_flag"
        elif flagged and not has_obj:
            state = "flag_without_preview"
        else:
            state = "missing"
        rows[sid] = state
    drift = {s: st for s, st in rows.items()
             if st in ("preview_without_flag", "flag_without_preview", "missing")}
    return {"states": rows, "drift": drift, "in_sync": not drift}


def _make_client(region: str, endpoint_url: str | None):
    import boto3
    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def _resolve_series_set(s3, args) -> list[str]:
    if bool(args.series) == bool(args.all):
        raise ValueError("pass exactly one of --series / --all")
    return args.series if args.series else _list_series_ids(s3, args.bucket)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill free-tier preview clips for published podcast series")
    p.add_argument("--bucket", default=os.getenv("PODCAST_BUCKET"))
    p.add_argument("--region", default=os.getenv("PODCAST_BUCKET_REGION", "ap-northeast-1"))
    p.add_argument("--endpoint-url", default=os.getenv("PODCAST_BUCKET_ENDPOINT_URL") or None)
    p.add_argument("--series", action="append", default=None, help="series id(s) (repeatable)")
    p.add_argument("--all", action="store_true", help="every series in the bucket")
    p.add_argument("--execute", action="store_true", help="actually write (default: dry-run)")
    p.add_argument("--check", action="store_true",
                   help="read-only preview⟷metadata drift report; exit non-zero on drift")
    args = p.parse_args(argv)

    if not args.bucket:
        print("✗ --bucket / $PODCAST_BUCKET not set", file=sys.stderr)
        return 2

    s3 = _make_client(args.region, args.endpoint_url)

    try:
        series_ids = _resolve_series_set(s3, args)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.check:
        report = check(s3, bucket=args.bucket, series_ids=series_ids)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["in_sync"]:
            print(f"✗ drift: {len(report['drift'])} series need backfill", file=sys.stderr)
            return 1
        print("✓ previews ↔ metadata in sync")
        return 0

    dry_run = not args.execute
    summary = {"published": [], "already": [], "failed": {}}
    for sid in series_ids:
        print(f"▶ preview: {sid}")
        try:
            state = backfill_series(s3, bucket=args.bucket, series_id=sid, dry_run=dry_run)
            summary[state].append(sid)
        except (ValueError, RuntimeError) as exc:
            # Per-series fault is recorded and surfaced, not silently skipped;
            # one bad series must not abort the whole batch (the others are
            # independent), but the run is reported as failed.
            print(f"  ✗ {exc}", file=sys.stderr)
            summary["failed"][sid] = str(exc)

    print(json.dumps({**summary, "dry_run": dry_run}, ensure_ascii=False, indent=2))
    if dry_run:
        print("ℹ dry-run — re-run with --execute to publish")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
