#!/usr/bin/env -S uv run --python 3.13 --with boto3 python
"""Atomic, idempotent podcast **cover** (re)publish — decoupled from audio.

Why this exists separately from ``ops/podcast_upload.sh``:
``podcast_upload.sh`` consumes a *lab workspace*, re-stages every episode's
audio, and then reconciles (prunes S3 orphans). That is correct for a *full*
publish, but **catastrophic for a cover-only change** when the local workspace
is not a perfect mirror of S3 — e.g. ``the_let_them_theory`` has 5 local audio
files but 8 published episodes; running upload.sh there would prune ep_06..08
off the bucket. Cover (re)publish must therefore be a path that touches the
cover and the cover-pointing metadata **only**, never audio, never reconcile.

What it does, for a series already published to S3:
  1. PUT ``<sid>/cover.png``           — a *new* key; metadata does not point at
                                         it yet, so clients still see the old
                                         (procedural-cover) state. No side effect.
  2. read-modify-write ``<sid>/metadata.json`` setting
     ``coverImageURL = /api/podcasts/<sid>/cover?v=<sha16>`` — a single-object atomic PUT.
                                         THIS is the step that makes the cover
                                         visible. Ordering 1→2 guarantees: when
                                         metadata points at the cover, the cover
                                         object already exists.
  3. rebuild ``index.json`` (series-list view) from every series' metadata —
                                         read from the bucket so other series are
                                         never dropped.

Atomicity = ordering, not a transaction. S3 has no multi-object transaction, but
single-object PUT is atomic (GetObject always sees a whole old or whole new
object), and the 1→2→3 order makes **every interruption point a safe state**:
  - crash after 1, before 2: cover.png exists, metadata doesn't point at it →
                             client still shows procedural cover (old state). Re-run completes 2.
  - crash after 2, before 3: metadata points at the (present) cover → detail
                             page shows it; index not yet rebuilt → list view
                             briefly shows procedural cover. Re-run completes 3.
  - after 3: fully consistent.
Re-running always drives a series toward the "cover published" terminal state →
**re-entrant + idempotent** (re-running with the same cover.png yields the same
bytes; PUTs are last-writer-wins).

``coverImageURL`` includes a deterministic SHA-256 prefix query token. The
backend ignores the query string (same route/object), while iOS uses the URL
token in its local filename so replacing existing cover art refreshes
automatically on the next catalog sync.

Usage:
    # one series from its workspace (series_id = basename)
    ops/podcast_cover_publish.py --workspace lab/podcast/workspaces/<sid> [--execute]
    # every series under a workspaces dir that has a plan/cover.png
    ops/podcast_cover_publish.py --all --workspaces-dir lab/podcast/workspaces [--execute]
    # read-only drift report (cover.png ⟷ coverImageURL consistency), exit≠0 on drift
    ops/podcast_cover_publish.py --all --workspaces-dir lab/podcast/workspaces --check

Default is dry-run; ``--execute`` required to write. Credentials/bucket come from
the env (``PODCAST_BUCKET`` / ``AWS_PROFILE`` etc.), same model as upload.sh —
source ``lab/podcast/.env`` before running outside the monitor.
"""
from __future__ import annotations

import argparse
import logging
import hashlib
import json
import os
import re
import sys
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# \A..\Z (not ^..$): Python's $ also matches before a trailing newline, so "x\n"
# would pass here but be rejected by the backend. Match backend SoT byte-for-byte
# (routers/podcast.py:49 _SERIES_ID_RE) + upload.sh's _SERIES_ID_RE.
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")
_COVER_CT = "image/png"
_JSON_CT = "application/json; charset=utf-8"


def cover_version(cover_body: bytes) -> str:
    return hashlib.sha256(cover_body).hexdigest()[:16]


def cover_url_for(series_id: str, cover_body: bytes | None = None) -> str:
    """The backend proxy path iOS fetches (GET /api/podcasts/<sid>/cover).

    When cover bytes are available, append a deterministic query token for
    client cache busting. The backend route still serves the same cover object.
    """
    base = f"/api/podcasts/{series_id}/cover"
    if cover_body is None:
        return base
    return f"{base}?v={cover_version(cover_body)}"


def cover_url_points_at(series_id: str, url: str | None) -> bool:
    base = cover_url_for(series_id)
    return url == base or (isinstance(url, str) and url.startswith(f"{base}?v="))


def is_png(body: bytes) -> bool:
    """True iff body starts with the PNG signature. Guards against publishing a
    404 HTML / JSON error page (or a truncated render) as the cover — the same
    PNG-magic gate iOS applies on download."""
    return body[:8] == _PNG_MAGIC


def patch_cover_url(meta: dict, series_id: str, cover_body: bytes | None = None) -> dict:
    """Return a copy of metadata with coverImageURL set. All other fields —
    notably createdAt and the episode list — are preserved verbatim. updatedAt
    is deliberately NOT bumped: a stable body keeps re-runs byte-identical
    (idempotent)."""
    out = dict(meta)
    out["coverImageURL"] = cover_url_for(series_id, cover_body)
    return out


def _is_not_found(exc: Exception, s3) -> bool:
    """True iff exc is a 404 / NoSuchKey. Any other fault (perms / throttle /
    network) must surface — a cover tool that mistakes AccessDenied for 'series
    absent' would skip a real publish or false-clear drift (KG 鐵律 1)."""
    nsk = getattr(getattr(s3, "exceptions", None), "NoSuchKey", ())
    if nsk and isinstance(exc, nsk):
        return True
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return code in ("NoSuchKey", "NoSuchBucket", "404")


def _get_json(s3, bucket: str, key: str):
    """GET a JSON object → parsed value, or None if the key is a true 404.
    Real faults propagate."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc, s3):
            _LOGGER.debug(
                "cover metadata missing: bucket=%s key=%s; treating as absent",
                bucket,
                key,
                exc_info=True,
            )
            return None
        raise
    return json.loads(obj["Body"].read())


def _key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc, s3):
            _LOGGER.debug(
                "cover key missing: bucket=%s key=%s; treating as absent",
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


def publish_cover_object(s3, *, bucket: str, series_id: str, cover_body: bytes,
                         dry_run: bool = True) -> dict:
    """Steps 1+2 for one series: PUT cover.png, then patch+PUT metadata.json.
    Returns the patched metadata (so the caller can rebuild index without an
    extra round-trip). Does NOT touch audio or index.json.

    Aborts (raises) if: series_id is malformed, cover_body is not a PNG, or the
    series has no metadata.json in the bucket (refuse to half-publish a cover
    onto a series that was never published)."""
    if not _SERIES_ID_RE.match(series_id):
        raise ValueError(f"invalid series_id '{series_id}' — must match ^[a-z0-9_]+$")
    if not is_png(cover_body):
        raise ValueError(f"{series_id}: cover is not a PNG (bad magic) — refusing to publish")

    meta = _get_json(s3, bucket, f"{series_id}/metadata.json")
    if meta is None:
        raise ValueError(
            f"{series_id}: no metadata.json in s3://{bucket}/{series_id}/ — "
            "series not published; run a full publish first")
    if not isinstance(meta, dict):
        raise ValueError(f"{series_id}: metadata.json is not an object")

    # 1. cover.png first — new key, metadata not pointing at it yet → no-op for clients.
    _put(s3, bucket, f"{series_id}/cover.png", cover_body, _COVER_CT, dry_run=dry_run)
    # 2. metadata.json — the visibility flip. Atomic single-object replace.
    patched = patch_cover_url(meta, series_id, cover_body)
    body = json.dumps(patched, ensure_ascii=False, indent=2).encode("utf-8")
    _put(s3, bucket, f"{series_id}/metadata.json", body, _JSON_CT, dry_run=dry_run)
    return patched


def _list_series_ids(s3, bucket: str) -> list[str]:
    """Every top-level prefix in the bucket (one per series)."""
    paginator = s3.get_paginator("list_objects_v2")
    ids = set()
    for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
        for p in page.get("CommonPrefixes", []) or []:
            sid = p["Prefix"].rstrip("/")
            if sid:
                ids.add(sid)
    return sorted(ids)


def rebuild_index_body(s3, *, bucket: str, overrides: dict[str, dict] | None = None) -> bytes:
    """Rebuild index.json from EVERY series' metadata in the bucket (so a
    cover-only change to one series never drops the others). ``overrides`` lets
    the caller supply patched metadata for series whose new metadata is not yet
    in the bucket (dry-run preview) or to avoid a re-GET (execute path)."""
    overrides = overrides or {}
    entries = []
    for sid in _list_series_ids(s3, bucket):
        meta = overrides.get(sid)
        if meta is None:
            meta = _get_json(s3, bucket, f"{sid}/metadata.json")
        if not isinstance(meta, dict):
            print(f"⚠ {sid}: metadata.json missing/unreadable; skipped from index", file=sys.stderr)
            continue
        entry = {k: v for k, v in meta.items() if k != "episodes"}
        entry["episodeCount"] = len(meta.get("episodes", []))
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")


def publish(s3, *, bucket: str, covers: dict[str, bytes], dry_run: bool = True) -> dict:
    """Publish covers for a batch of {series_id: cover_png_bytes}. PUTs each
    series' cover+metadata (steps 1+2), then rebuilds index.json once (step 3).

    Returns a summary. A per-series failure raises (loud-fail) rather than
    silently skipping — partial cover state is exactly what the ordering design
    avoids, so we don't bury the error."""
    published = {}
    for sid in sorted(covers):
        print(f"▶ cover: {sid}")
        published[sid] = publish_cover_object(
            s3, bucket=bucket, series_id=sid, cover_body=covers[sid], dry_run=dry_run)

    # 3. index.json — once, after all metadata is in place (or overridden).
    print("▶ rebuild index.json")
    index_body = rebuild_index_body(s3, bucket=bucket, overrides=published)
    _put(s3, bucket, "index.json", index_body, _JSON_CT, dry_run=dry_run)

    return {"series": sorted(covers), "count": len(covers), "dry_run": dry_run}


def check(s3, *, bucket: str, series_ids: list[str],
          local_covers: dict[str, bytes] | None = None) -> dict:
    """Read-only drift report for cover ⟷ coverImageURL consistency. For each
    series classifies one of:
      - in_sync:               cover.png present AND metadata points at it
                               (and, when local cover bytes are available,
                               metadata carries the matching version token)
      - url_without_cover_png: metadata points at a cover that isn't in S3 (→ 404)
      - cover_png_without_url: cover.png in S3 but metadata doesn't point at it
                               (client can't see it — step 2 never completed)
      - unpublished:           neither (legacy / pre-cover series)
    If ``local_covers`` is given, a series whose local cover is not reflected
    by metadata is flagged ``pending_publish``."""
    local_covers = local_covers or {}
    rows = {}
    for sid in series_ids:
        meta = _get_json(s3, bucket, f"{sid}/metadata.json")
        meta_url = meta.get("coverImageURL") if isinstance(meta, dict) else None
        points = cover_url_points_at(sid, meta_url)
        has_png = _key_exists(s3, bucket, f"{sid}/cover.png")
        if sid in local_covers and has_png and meta_url != cover_url_for(sid, local_covers[sid]):
            state = "pending_publish"
        elif points and has_png:
            state = "in_sync"
        elif points and not has_png:
            state = "url_without_cover_png"
        elif has_png and not points:
            state = "cover_png_without_url"
        elif sid in local_covers:
            state = "pending_publish"
        else:
            state = "unpublished"
        rows[sid] = state
    drift = {s: st for s, st in rows.items()
             if st in ("url_without_cover_png", "cover_png_without_url")}
    pending = {s: st for s, st in rows.items() if st == "pending_publish"}
    return {"states": rows, "drift": drift, "pending": pending, "in_sync": not drift and not pending}


# --- cover source resolution ----------------------------------------------

def _cover_path_for_workspace(ws: Path) -> Path:
    return ws / "plan" / "cover.png"


def _collect_covers(*, workspaces_dir: Path | None, workspace: Path | None,
                    series: list[str] | None, cover: Path | None,
                    all_: bool) -> dict[str, bytes]:
    """Resolve the requested cover sources to {series_id: png_bytes}. A series
    whose plan/cover.png is missing is reported and skipped (not fabricated)."""
    # --workspace / --all / --series pick the series set and are mutually
    # exclusive; --cover only *modifies* a workspace/single-series source.
    # Fail loud on a conflicting combo rather than silently taking the first
    # branch of the if-ladder (e.g. --workspace A --series B dropping B).
    if sum([workspace is not None, all_, bool(series)]) > 1:
        raise ValueError("--workspace / --all / --series are mutually exclusive — pass one")

    sources: dict[str, Path] = {}
    if workspace is not None:
        sources[workspace.name] = _cover_path_for_workspace(workspace)
        if cover is not None:
            sources[workspace.name] = cover
    elif cover is not None and series:
        sources[series[0]] = cover
    elif all_:
        if workspaces_dir is None or not workspaces_dir.is_dir():
            raise ValueError("--all needs --workspaces-dir <dir>")
        for child in sorted(workspaces_dir.iterdir()):
            if child.is_dir() and _cover_path_for_workspace(child).is_file():
                sources[child.name] = _cover_path_for_workspace(child)
    elif series and workspaces_dir is not None:
        for sid in series:
            sources[sid] = _cover_path_for_workspace(workspaces_dir / sid)
    else:
        raise ValueError("specify --workspace, --all --workspaces-dir, or --series + --workspaces-dir")

    covers: dict[str, bytes] = {}
    for sid, path in sources.items():
        if not path.is_file():
            print(f"⚠ {sid}: no cover at {path} — skipped", file=sys.stderr)
            continue
        covers[sid] = path.read_bytes()
    return covers


def _make_client(region: str, endpoint_url: str | None):
    import boto3
    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Atomic podcast cover (re)publish — audio-decoupled")
    p.add_argument("--bucket", default=os.getenv("PODCAST_BUCKET"))
    p.add_argument("--region", default=os.getenv("PODCAST_BUCKET_REGION", "ap-northeast-1"))
    p.add_argument("--endpoint-url", default=os.getenv("PODCAST_BUCKET_ENDPOINT_URL") or None)
    p.add_argument("--workspace", type=Path, default=None,
                   help="a single lab workspace dir (series_id = basename); uses plan/cover.png")
    p.add_argument("--workspaces-dir", type=Path, default=None,
                   help="root holding <series_id>/ workspaces (for --all / --series)")
    p.add_argument("--series", action="append", default=None,
                   help="series id(s) (repeatable); needs --workspaces-dir or --cover")
    p.add_argument("--cover", type=Path, default=None,
                   help="explicit cover.png (with --workspace or single --series)")
    p.add_argument("--all", action="store_true",
                   help="every workspace under --workspaces-dir with a plan/cover.png")
    p.add_argument("--execute", action="store_true", help="actually write (default: dry-run)")
    p.add_argument("--check", action="store_true",
                   help="read-only cover⟷metadata drift report; exit non-zero on drift")
    args = p.parse_args(argv)

    if not args.bucket:
        print("✗ --bucket / $PODCAST_BUCKET not set", file=sys.stderr)
        return 2

    s3 = _make_client(args.region, args.endpoint_url)

    if args.check:
        # Scope: --workspace one series, --series the listed ones, else the
        # whole bucket. (--workspace must narrow check too, not silently widen.)
        if args.workspace is not None:
            series_ids = [args.workspace.name]
        elif args.series:
            series_ids = args.series
        else:
            series_ids = _list_series_ids(s3, args.bucket)
        local = None
        try:
            local = _collect_covers(workspaces_dir=args.workspaces_dir, workspace=args.workspace,
                                    series=args.series, cover=args.cover, all_=args.all)
        except ValueError as exc:
            _LOGGER.debug("No local covers available for --check fallback: %s", exc)
            local = None  # check works without local sources
        report = check(s3, bucket=args.bucket, series_ids=series_ids, local_covers=local)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["in_sync"]:
            if report["pending"]:
                print(f"✗ pending publish: {len(report['pending'])} series", file=sys.stderr)
            else:
                print(f"✗ drift: {len(report['drift'])} series", file=sys.stderr)
            return 1
        print("✓ covers ↔ metadata in sync")
        return 0

    try:
        covers = _collect_covers(workspaces_dir=args.workspaces_dir, workspace=args.workspace,
                                 series=args.series, cover=args.cover, all_=args.all)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if not covers:
        print("✗ no covers to publish", file=sys.stderr)
        return 2

    report = publish(s3, bucket=args.bucket, covers=covers, dry_run=not args.execute)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["dry_run"]:
        print("ℹ dry-run — re-run with --execute to publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
