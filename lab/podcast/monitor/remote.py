"""S3 (Lightsail Object Storage) client for the monitor dashboard.

Post-Track-B: podcast media lives in S3, not on the Lightsail instance disk.
This module replaces the prior SSH/rsync wrappers but keeps the same public
API so ``server.py`` doesn't need to know which backend it's talking to:

- ``list_remote_series()``      — list what's published (from ``index.json``)
- ``remote_disk_usage()``       — bucket usage (no real "disk" concept in S3,
                                  but the dashboard's storage-pressure UI still
                                  expects total/used/avail bytes)
- ``delete_remote_series(id)``  — delete all keys under ``{id}/`` then rebuild
                                  ``index.json``

Configuration is via env vars, NOT the ``ops/podcast_upload.sh`` constants:
``PODCAST_BUCKET`` (required), ``PODCAST_BUCKET_REGION`` (default
``ap-northeast-1``), optional ``PODCAST_BUCKET_ENDPOINT_URL`` for non-AWS S3-
compatible providers. AWS credentials follow the standard boto3 chain (env →
``~/.aws/credentials`` → IAM role).

The previous PODCAST_SSH_KEY / PODCAST_REMOTE_SERVER / PODCAST_REMOTE_DIR
envs are now unused — kept undocumented for one release so a stale shell that
exports them doesn't actively break, but they have no effect.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# Quota knob for the dashboard storage UI. Lightsail Object Storage bundles
# (as of 2026-06): small_1_0=5GB/$1, medium_1_0=100GB/$3, large_1_0=250GB/$5.
# Default matches the deployed small_1_0; override via env when upgrading.
BUCKET_QUOTA_BYTES = int(os.getenv("PODCAST_BUCKET_QUOTA_BYTES", str(5 * 1024**3)))

# Series ID validation — MUST mirror backend `_SERIES_ID_RE` in routers/podcast.py.
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")


class RemoteError(RuntimeError):
    """S3 operation failed. Same wire shape as the SSH era so server.py is
    backend-agnostic.

    Fields kept for log/API compatibility:
      * ``code``: HTTP status from S3 when available (0 otherwise)
      * ``stderr``: error message string
      * ``cmd``: best-effort operation label list (was the ssh argv)
    """

    def __init__(self, code: int, stderr: str, cmd: list[str]):
        self.code = code
        self.stderr = stderr
        self.cmd = cmd
        super().__init__(f"s3 op failed ({code}): {stderr.strip()[:200]}")


# ─── boto3 client (lazy) ─────────────────────────────────────────────────────


def _bucket() -> str:
    bucket = os.getenv("PODCAST_BUCKET", "").strip()
    if not bucket:
        raise RemoteError(
            0,
            "PODCAST_BUCKET env not set — monitor cannot reach the podcast bucket",
            ["env", "PODCAST_BUCKET"],
        )
    return bucket


def _region() -> str:
    return os.getenv("PODCAST_BUCKET_REGION", "ap-northeast-1")


def _endpoint_url() -> str | None:
    url = os.getenv("PODCAST_BUCKET_ENDPOINT_URL", "").strip()
    return url or None


_client_cache: dict[tuple[str, str | None], Any] = {}


def _client():
    """Lazy boto3 client — local import so the monitor's test runner doesn't
    need boto3 just to import this module. Cached per (region, endpoint)."""
    key = (_region(), _endpoint_url())
    cached = _client_cache.get(key)
    if cached is not None:
        return cached
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RemoteError(
            0,
            f"boto3 not installed in monitor env: {exc}",
            ["import", "boto3"],
        ) from exc
    client = boto3.client(
        "s3",
        region_name=key[0],
        endpoint_url=key[1],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    _client_cache[key] = client
    return client


def _map_client_error(exc: Exception, op: str) -> RemoteError:
    """Translate a botocore ClientError into RemoteError preserving HTTP code."""
    response = getattr(exc, "response", {}) or {}
    http = int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
    code = response.get("Error", {}).get("Code", type(exc).__name__)
    msg = response.get("Error", {}).get("Message") or str(exc)
    return RemoteError(http, f"{op}: {code} {msg}", [op])


# ─── Public API ──────────────────────────────────────────────────────────────


def validate_series_id(series_id: str) -> str:
    if not _SERIES_ID_RE.match(series_id):
        raise ValueError(
            f"invalid series_id {series_id!r} — must match {_SERIES_ID_RE.pattern}"
        )
    return series_id


def list_remote_series() -> list[dict]:
    """Return parsed ``index.json`` + per-series byte size.

    Surfaces "orphan" series (present as a directory but not in the index)
    the same way as the SSH version so the dashboard can flag half-uploaded
    series for cleanup.
    """
    bucket = _bucket()
    s3 = _client()

    # 1. Pull the published index (one GetObject).
    try:
        obj = s3.get_object(Bucket=bucket, Key="index.json")
        index_raw = obj["Body"].read().decode("utf-8", errors="replace")
        index = json.loads(index_raw) if index_raw.strip() else []
    except s3.exceptions.NoSuchKey:
        index = []
    except json.JSONDecodeError:
        # Mirror SSH behaviour: index unreadable → treat as empty + show orphans.
        index = []
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response"):
            err = exc.response.get("Error", {})  # type: ignore[attr-defined]
            if err.get("Code") in ("NoSuchKey", "404"):
                index = []
            else:
                raise _map_client_error(exc, "get_object index.json") from exc
        else:
            raise RemoteError(0, f"get_object index.json: {exc}", ["get_object"]) from exc

    if not isinstance(index, list):
        index = []

    # 2. List one level deep to compute per-series byte sizes.
    #    Use delimiter='/' to discover series prefixes; then per-series
    #    list_objects_v2 to sum sizes. The total object count is bounded by
    #    the number of episodes — well under any pagination concern.
    sizes: dict[str, int] = {}
    try:
        paginator = s3.get_paginator("list_objects_v2")
        # First pass: find the set of series prefixes.
        prefixes: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
            for p in page.get("CommonPrefixes", []) or []:
                pref = p["Prefix"]
                sid = pref.rstrip("/")
                if sid:
                    prefixes.append(pref)
        # Second pass: tally bytes per prefix.
        for pref in prefixes:
            sid = pref.rstrip("/")
            total = 0
            for page in paginator.paginate(Bucket=bucket, Prefix=pref):
                for obj in page.get("Contents", []) or []:
                    total += int(obj.get("Size", 0))
            sizes[sid] = total
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response"):
            raise _map_client_error(exc, "list_objects_v2") from exc
        raise RemoteError(0, f"list_objects_v2: {exc}", ["list_objects_v2"]) from exc

    # Stitch + flag orphans (same shape as the SSH version).
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
    """Bucket usage in the same JSON shape the dashboard expects.

    S3 has no real "disk" — ``total_bytes`` is the configured plan quota
    (``PODCAST_BUCKET_QUOTA_BYTES`` env, default 5 GiB = Lightsail small_1_0).
    ``used_bytes`` is the live sum of every object in the bucket.
    """
    bucket = _bucket()
    s3 = _client()
    used = 0
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []) or []:
                used += int(obj.get("Size", 0))
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response"):
            raise _map_client_error(exc, "list_objects_v2") from exc
        raise RemoteError(0, f"list_objects_v2: {exc}", ["list_objects_v2"]) from exc
    total = BUCKET_QUOTA_BYTES
    avail = max(0, total - used)
    pct = f"{(used * 100) // total}%" if total > 0 else "?"
    return {
        "total_bytes": total,
        "used_bytes": used,
        "avail_bytes": avail,
        "use_percent": pct,
        "podcast_bytes": used,
    }


def delete_remote_series(series_id: str) -> dict:
    """Delete every object under ``{series_id}/`` then rebuild ``index.json``.

    Return shape matches the SSH version so the dashboard / API needs no
    change:
      * ``deleted``: the series id
      * ``fully_deleted``: True if zero residual objects exist under the prefix
      * ``remaining``: number of series in the rebuilt index
      * ``rm_errors``: list of per-object delete errors (empty on success)
      * ``bad_metadata_files``: list of metadata.json keys that wouldn't parse
        (those series are skipped in the rebuilt index)
    """
    validate_series_id(series_id)
    bucket = _bucket()
    s3 = _client()
    prefix = f"{series_id}/"

    # 1. Collect all keys under the prefix.
    keys: list[str] = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                keys.append(obj["Key"])
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response"):
            raise _map_client_error(exc, "list_objects_v2 (delete)") from exc
        raise RemoteError(0, f"list_objects_v2: {exc}", ["list_objects_v2"]) from exc

    # 2. Batch-delete (up to 1000 per call per S3 API).
    rm_errors: list[dict] = []
    for batch_start in range(0, len(keys), 1000):
        batch = keys[batch_start : batch_start + 1000]
        try:
            resp = s3.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [{"Key": k} for k in batch],
                    "Quiet": False,
                },
            )
            for err in resp.get("Errors", []) or []:
                rm_errors.append(
                    {"path": err.get("Key", ""), "err": f"{err.get('Code')}: {err.get('Message')}"},
                )
        except Exception as exc:  # noqa: BLE001
            if hasattr(exc, "response"):
                raise _map_client_error(exc, "delete_objects") from exc
            raise RemoteError(0, f"delete_objects: {exc}", ["delete_objects"]) from exc

    # 3. Re-verify the prefix is empty (catches eventual-consistency surprises).
    still_exists = False
    try:
        check = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
        if int(check.get("KeyCount", 0)) > 0:
            still_exists = True
    except Exception as exc:  # noqa: BLE001
        # Don't blow up the delete on a verify failure — log via rm_errors.
        rm_errors.append({"path": prefix, "err": f"verify list_objects_v2: {exc}"})

    # 4. Rebuild index.json by walking remaining series.
    bad_metadata_files: list[dict] = []
    rebuilt: list[dict] = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        series_ids: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
            for p in page.get("CommonPrefixes", []) or []:
                sid = p["Prefix"].rstrip("/")
                if sid and sid != series_id:  # the just-deleted one
                    series_ids.append(sid)
        for sid in sorted(series_ids):
            key = f"{sid}/metadata.json"
            try:
                obj = s3.get_object(Bucket=bucket, Key=key)
                meta = json.loads(obj["Body"].read())
            except Exception as exc:  # noqa: BLE001
                bad_metadata_files.append(
                    {"path": key, "err": f"{type(exc).__name__}: {exc}"},
                )
                continue
            entry = {k: v for k, v in meta.items() if k != "episodes"}
            entry["episodeCount"] = len(meta.get("episodes", []))
            rebuilt.append(entry)
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response"):
            raise _map_client_error(exc, "rebuild index list_objects_v2") from exc
        raise RemoteError(0, f"rebuild index: {exc}", ["list_objects_v2"]) from exc

    # 5. Write the rebuilt index back.
    try:
        s3.put_object(
            Bucket=bucket,
            Key="index.json",
            Body=(json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "response"):
            raise _map_client_error(exc, "put_object index.json") from exc
        raise RemoteError(0, f"put_object index.json: {exc}", ["put_object"]) from exc

    return {
        "deleted": series_id,
        "fully_deleted": not still_exists and not rm_errors,
        "remaining": len(rebuilt),
        "rm_errors": rm_errors,
        "bad_metadata_files": bad_metadata_files,
    }
