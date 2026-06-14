#!/usr/bin/env -S uv run --python 3.13 --with boto3 python
"""Served-disk → S3 podcast backfill + drift reconcile.

The Track-B migration switched the backend to S3-only podcast serving
(``PODCAST_BUCKET`` set) but never uploaded the series that already lived on
the instance disk — so ``/api/podcasts`` reads an empty bucket and returns
``[]``. This tool pushes the on-disk served layout
(``{data_dir}/index.json`` + ``{sid}/metadata.json`` + ``{sid}/ep_NN/audio.*``
+ ``subtitle.srt`` / ``script.md``) up to the bucket, key-for-key.

Unlike ``ops/podcast_upload.sh`` (which consumes a *lab workspace* layout),
this consumes the *served-disk* layout directly — no staging/reshuffle — so it
can run inside the backend container where the disk + boto3 + write creds live:

    ops/devops_kg_safe.sh container-run \
        'python ops/podcast_backfill_disk.py --dry-run'     # review the plan
    ops/devops_kg_safe.sh container-run \
        'python ops/podcast_backfill_disk.py --execute'     # actually upload

Safety: dry-run is the DEFAULT (``--execute`` required to write); it NEVER
deletes (no ``--delete`` analogue); ``--skip-existing`` makes reruns idempotent.

``--check`` runs a read-only disk↔S3 reconcile and exits non-zero on drift —
the ongoing safety net against this class of silent gap.
"""
from __future__ import annotations

import argparse
import logging
import json
import os
import sys
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# Content-Type per extension. Without these, S3 defaults to
# binary/octet-stream and AVPlayer rejects the audio stream. MUST stay aligned
# with ops/podcast_upload.sh content_type_for().
_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".srt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}

# Files we publish per episode dir (everything else under a series is ignored).
_EPISODE_FILES = ("audio.m4a", "audio.mp3", "subtitle.srt", "script.md")


def content_type_for(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _series_dirs(data_dir: Path, series_filter: list[str] | None) -> list[Path]:
    """Series = immediate subdir of data_dir holding a metadata.json."""
    out = []
    for child in sorted(data_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "metadata.json").is_file():
            continue
        if series_filter and child.name not in series_filter:
            continue
        out.append(child)
    return out


def _detect_audio_format(series_dir: Path) -> str | None:
    """Return 'm4a' / 'mp3' from ep_01 (all eps in a series share one format)."""
    ep01 = series_dir / "ep_01"
    for fmt in ("m4a", "mp3"):
        if (ep01 / f"audio.{fmt}").is_file():
            return fmt
    return None


def _series_files(series_dir: Path) -> list[Path]:
    """All publishable files for a series: metadata.json + each ep_NN/<known>."""
    files = [series_dir / "metadata.json"]
    for ep in sorted(series_dir.glob("ep_*")):
        if not ep.is_dir():
            continue
        for name in _EPISODE_FILES:
            f = ep / name
            if f.is_file():
                files.append(f)
    return files


def _s3_key(data_dir: Path, path: Path) -> str:
    """Map a served-disk path to its S3 key (relative to data_dir)."""
    return path.relative_to(data_dir).as_posix()


def _metadata_body_with_audioformat(series_dir: Path) -> bytes:
    """Read a series' metadata.json and inject audioFormat (so the backend's
    S3-mode _audio_filename resolves the right extension without probing)."""
    meta = json.loads((series_dir / "metadata.json").read_text(encoding="utf-8"))
    fmt = _detect_audio_format(series_dir)
    if fmt and isinstance(meta, dict):
        meta["audioFormat"] = fmt
    return json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")


def _is_not_found(exc: Exception, s3) -> bool:
    """True iff exc is a 404 / NoSuchKey. Any other fault (perms / throttle /
    network) must surface, not be mistaken for 'key absent' — otherwise the
    --check reconcile both false-alarms and could false-clear (KG 鐵律 1)."""
    nsk = getattr(getattr(s3, "exceptions", None), "NoSuchKey", ())
    if nsk and isinstance(exc, nsk):
        return True
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return code in ("NoSuchKey", "404")


def _key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001
        if _is_not_found(exc, s3):
            _LOGGER.debug(
                "S3 object missing: bucket=%s key=%s; treating as absent",
                bucket,
                key,
                exc_info=True,
            )
            return False
        raise  # real S3 fault — loud-fail, don't treat as absent


def _put(s3, bucket: str, key: str, body: bytes, *, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] PUT s3://{bucket}/{key}  ({len(body)} B, {content_type_for(key)})")
        return
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type_for(key))
    print(f"  PUT s3://{bucket}/{key}  ({len(body)} B)")


def backfill(s3, *, bucket: str, data_dir: Path, dry_run: bool = True,
             skip_existing: bool = True, rebuild_index: bool = False,
             series_filter: list[str] | None = None) -> dict:
    """Upload every series' files to S3. Never deletes. Returns a summary."""
    data_dir = Path(data_dir)
    series = _series_dirs(data_dir, series_filter)
    planned = 0
    uploaded = 0
    skipped = 0

    for sdir in series:
        print(f"▶ series: {sdir.name}")
        for path in _series_files(sdir):
            key = _s3_key(data_dir, path)
            if skip_existing and not dry_run and _key_exists(s3, bucket, key):
                skipped += 1
                print(f"  skip (exists): {key}")
                continue
            if path.name == "metadata.json":
                body = _metadata_body_with_audioformat(sdir)
            else:
                body = path.read_bytes()
            planned += 1
            _put(s3, bucket, key, body, dry_run=dry_run)
            if not dry_run:
                uploaded += 1

    # index.json at bucket root — ALWAYS re-PUT (never skip): it's tiny and a
    # stale/partial index left in the bucket is exactly the visibility bug we
    # are recovering from. Last-writer-wins, same model as podcast_upload.sh.
    index_key = "index.json"
    if rebuild_index:
        body = _rebuild_index_body(series)
    else:
        idx = data_dir / "index.json"
        body = idx.read_bytes() if idx.is_file() else _rebuild_index_body(series)
    planned += 1
    _put(s3, bucket, index_key, body, dry_run=dry_run)
    if not dry_run:
        uploaded += 1

    return {"series": [s.name for s in series], "planned": planned,
            "uploaded": uploaded, "skipped": skipped, "dry_run": dry_run}


def _rebuild_index_body(series: list[Path]) -> bytes:
    """Build index.json from per-series metadata (summary, no episodes)."""
    entries = []
    for sdir in series:
        meta = json.loads((sdir / "metadata.json").read_text(encoding="utf-8"))
        entry = {k: v for k, v in meta.items() if k != "episodes"}
        entry["episodeCount"] = len(meta.get("episodes", []))
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")


def reconcile(s3, *, bucket: str, data_dir: Path,
              series_filter: list[str] | None = None) -> dict:
    """Read-only disk↔S3 drift report. missing_in_s3 = on disk but not in
    bucket (the failure mode that caused the incident)."""
    data_dir = Path(data_dir)
    series = _series_dirs(data_dir, series_filter)
    expected_keys = {"index.json"}
    for sdir in series:
        for path in _series_files(sdir):
            expected_keys.add(_s3_key(data_dir, path))

    missing = sorted(k for k in expected_keys if not _key_exists(s3, bucket, k))
    return {
        "expected": sorted(expected_keys),
        "missing_in_s3": missing,
        "in_sync": len(missing) == 0,
    }


def _make_client(region: str, endpoint_url: str | None):
    import boto3
    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Served-disk → S3 podcast backfill / reconcile")
    p.add_argument("--data-dir", default="/app/data/podcasts",
                   help="served-disk podcasts dir (default: /app/data/podcasts)")
    p.add_argument("--bucket", default=os.getenv("PODCAST_BUCKET"),
                   help="target bucket (default: $PODCAST_BUCKET)")
    p.add_argument("--region", default=os.getenv("PODCAST_BUCKET_REGION", "ap-northeast-1"))
    p.add_argument("--endpoint-url", default=os.getenv("PODCAST_BUCKET_ENDPOINT_URL") or None)
    p.add_argument("--execute", action="store_true",
                   help="actually upload (default is dry-run)")
    p.add_argument("--no-skip-existing", action="store_true",
                   help="re-PUT even when a key already exists")
    p.add_argument("--rebuild-index", action="store_true",
                   help="rebuild index.json from per-series metadata instead of "
                        "uploading the on-disk index.json verbatim")
    p.add_argument("--series", action="append", default=None,
                   help="limit to these series ids (repeatable); default: all on disk")
    p.add_argument("--check", action="store_true",
                   help="read-only disk↔S3 drift report; exit non-zero on drift")
    args = p.parse_args(argv)

    if not args.bucket:
        print("✗ --bucket / $PODCAST_BUCKET not set", file=sys.stderr)
        return 2

    s3 = _make_client(args.region, args.endpoint_url)
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"✗ data dir not found: {data_dir}", file=sys.stderr)
        return 2

    if args.check:
        report = reconcile(s3, bucket=args.bucket, data_dir=data_dir, series_filter=args.series)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["in_sync"]:
            print(f"✗ drift: {len(report['missing_in_s3'])} key(s) missing in S3", file=sys.stderr)
            return 1
        print("✓ disk ↔ S3 in sync")
        return 0

    report = backfill(
        s3, bucket=args.bucket, data_dir=data_dir,
        dry_run=not args.execute,
        skip_existing=not args.no_skip_existing,
        rebuild_index=args.rebuild_index,
        series_filter=args.series,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["dry_run"]:
        print("ℹ dry-run — re-run with --execute to upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
