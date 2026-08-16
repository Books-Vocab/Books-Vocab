"""Unit tests for ops/podcast_preview_backfill.py core logic.

No moto in the test env, so S3 is a minimal in-memory ``FakeS3`` implementing
exactly the surface the script uses (get_object / head_object / put_object /
get_paginator). ffmpeg-dependent tests skip when ffmpeg is absent. This proves
the security-critical claims without a real bucket:

* a preview object is generated + uploaded for ep 1,
* metadata episode 1 is flagged ``previewAvailable`` (the visibility flip),
* a second run is idempotent (``already``, no re-PUT),
* the drift report classifies preview ⟷ metadata states correctly.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_OPS = Path(__file__).resolve().parents[2] / "ops" / "podcast_preview_backfill.py"
_spec = importlib.util.spec_from_file_location("podcast_preview_backfill", _OPS)
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_required = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
TEST_STAMP = "2026-08-16T00:00:00+00:00"


class _NoSuchKey(Exception):
    pass


class FakeS3:
    """Minimal in-memory S3 implementing only the methods the script calls."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects: dict[str, bytes] = dict(objects or {})

        class _Exc:
            NoSuchKey = _NoSuchKey

        self.exceptions = _Exc()

    def _err(self):
        e = _NoSuchKey("not found")
        e.response = {"Error": {"Code": "NoSuchKey"}}
        return e

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self._err()
        body = self.objects[Key]
        return {"Body": _Body(body)}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self._err()
        return {"ContentLength": len(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body if isinstance(Body, bytes) else bytes(Body)

    def get_paginator(self, _name):
        objs = self.objects

        class _Pag:
            def paginate(self, Bucket, Delimiter="/"):
                prefixes = sorted({k.split("/", 1)[0] for k in objs if "/" in k})
                yield {"CommonPrefixes": [{"Prefix": f"{p}/"} for p in prefixes]}

        return _Pag()


class _Body:
    def __init__(self, b: bytes):
        self._b = b

    def read(self):
        return self._b


def _make_m4a(seconds: int) -> bytes:
    """A real (tiny) AAC/m4a clip via ffmpeg lavfi."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "a.m4a"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"sine=frequency=440:duration={seconds}",
             "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)],
            check=True,
        )
        return out.read_bytes()


def _meta(series_id: str, *, preview_flag: bool = False) -> dict:
    ep1 = {"episodeNumber": 1, "title": "One", "audioAvailable": True}
    if preview_flag:
        ep1["previewAvailable"] = True
        ep1["previewDurationSec"] = 180
    return {
        "id": series_id, "title": "S", "audioFormat": "m4a",
        "episodes": [ep1, {"episodeNumber": 2, "title": "Two", "audioAvailable": True}],
    }


# ── pure metadata transform (no ffmpeg / no S3) ──────────────────────────────

def test_patch_preview_meta_flags_ep1_only():
    out = bf.patch_preview_meta(_meta("s_a"), duration_sec=180, stamp=TEST_STAMP)
    eps = {e["episodeNumber"]: e for e in out["episodes"]}
    assert eps[1]["previewAvailable"] is True
    assert eps[1]["previewDurationSec"] == 180
    assert "previewAvailable" not in eps[2]  # ep2 untouched
    assert out["updatedAt"] == TEST_STAMP


def test_patch_preview_meta_preserves_other_fields():
    meta = _meta("s_a")
    meta["createdAt"] = "2020-01-01T00:00:00+00:00"
    meta["customField"] = {"keep": True}
    out = bf.patch_preview_meta(meta, duration_sec=180, stamp=TEST_STAMP)
    assert out["createdAt"] == "2020-01-01T00:00:00+00:00"
    assert out["customField"] == {"keep": True}
    assert out["updatedAt"] == TEST_STAMP
    assert "updatedAt" not in meta


def test_patch_preview_meta_raises_when_no_ep1():
    with pytest.raises(ValueError, match="no episode 1"):
        bf.patch_preview_meta(
            {"episodes": [{"episodeNumber": 2}]},
            duration_sec=180,
            stamp=TEST_STAMP,
        )


def test_patch_preview_meta_requires_stamp():
    with pytest.raises(TypeError, match="stamp"):
        bf.patch_preview_meta(_meta("s_a"), duration_sec=180)


def test_patch_preview_meta_rejects_positional_stamp():
    with pytest.raises(TypeError, match="positional"):
        bf.patch_preview_meta(_meta("s_a"), 180, TEST_STAMP)


def test_patch_index_stamp_updates_only_target_entry():
    index = [
        {"id": "s_a", "title": "A", "updatedAt": "old"},
        {"id": "other", "title": "Other", "updatedAt": "other-old"},
    ]

    out, changed = bf.patch_index_stamp(index, series_id="s_a", stamp=TEST_STAMP)

    assert changed is True
    assert out == [
        {"id": "s_a", "title": "A", "updatedAt": TEST_STAMP},
        {"id": "other", "title": "Other", "updatedAt": "other-old"},
    ]
    assert index[0]["updatedAt"] == "old"


# ── ffmpeg-backed preview generation ─────────────────────────────────────────

@ffmpeg_required
def test_make_preview_bytes_truncates_to_180s():
    full = _make_m4a(300)
    preview, duration = bf.make_preview_bytes(full, "m4a")
    assert 178 <= duration <= 182  # stream-copy cuts at packet boundary ≈ 180
    assert len(preview) < len(full)  # preview is strictly smaller than full


@ffmpeg_required
def test_make_preview_bytes_shorter_than_window():
    """A <180s ep1 yields a preview ≈ the whole thing (no error)."""
    full = _make_m4a(30)
    preview, duration = bf.make_preview_bytes(full, "m4a")
    assert 28 <= duration <= 32


# ── end-to-end backfill against FakeS3 ───────────────────────────────────────

@ffmpeg_required
def test_backfill_publishes_preview_and_flags_metadata():
    full = _make_m4a(300)
    s3 = FakeS3({
        "s_a/metadata.json": json.dumps(_meta("s_a")).encode(),
        "s_a/ep_01/audio.m4a": full,
    })
    state = bf.backfill_series(s3, bucket="b", series_id="s_a", dry_run=False)
    assert state == "published"
    # preview object now exists, smaller than the full audio
    assert "s_a/ep_01/preview.m4a" in s3.objects
    assert len(s3.objects["s_a/ep_01/preview.m4a"]) < len(full)
    # metadata ep1 flagged
    meta = json.loads(s3.objects["s_a/metadata.json"])
    ep1 = next(e for e in meta["episodes"] if e["episodeNumber"] == 1)
    assert ep1["previewAvailable"] is True
    assert ep1["previewDurationSec"] > 0


@ffmpeg_required
def test_backfill_is_idempotent():
    full = _make_m4a(60)
    s3 = FakeS3({
        "s_a/metadata.json": json.dumps(_meta("s_a")).encode(),
        "s_a/ep_01/audio.m4a": full,
    })
    assert bf.backfill_series(s3, bucket="b", series_id="s_a", dry_run=False) == "published"
    preview_bytes = s3.objects["s_a/ep_01/preview.m4a"]
    # second run: preview present + metadata flagged → skip, no re-PUT
    assert bf.backfill_series(s3, bucket="b", series_id="s_a", dry_run=False) == "already"
    assert s3.objects["s_a/ep_01/preview.m4a"] == preview_bytes


def test_backfill_dry_run_writes_nothing():
    if not _HAS_FFMPEG:
        pytest.skip("ffmpeg not on PATH")
    # dry-run still generates the preview bytes (ffmpeg runs, to report size) but
    # must not PUT anything. A real clip is needed so make_preview_bytes succeeds.
    s3 = FakeS3({
        "s_a/metadata.json": json.dumps(_meta("s_a")).encode(),
        "s_a/ep_01/audio.m4a": _make_m4a(10),
    })
    bf.backfill_series(s3, bucket="b", series_id="s_a", dry_run=True)
    assert "s_a/ep_01/preview.m4a" not in s3.objects  # nothing written
    meta = json.loads(s3.objects["s_a/metadata.json"])
    ep1 = next(e for e in meta["episodes"] if e["episodeNumber"] == 1)
    assert "previewAvailable" not in ep1  # metadata untouched in dry-run


def test_backfill_missing_metadata_raises():
    s3 = FakeS3({"s_a/ep_01/audio.m4a": b"x"})
    with pytest.raises(ValueError, match="not published"):
        bf.backfill_series(s3, bucket="b", series_id="s_a", dry_run=True)


def test_backfill_invalid_series_id_raises():
    s3 = FakeS3()
    with pytest.raises(ValueError, match="invalid series_id"):
        bf.backfill_series(s3, bucket="b", series_id="Bad-Id", dry_run=True)


# ── cross-file constant drift guard ──────────────────────────────────────────

def test_preview_ep_num_matches_backend_policy():
    """The previewable-episode number is hand-synced between the backend gate
    (podcast_access.FREE_PREVIEW_EP_NUM) and this ops tool. Assert they agree so
    a future edit to one can't silently break the other."""
    from kg.podcast_access import FREE_PREVIEW_EP_NUM

    assert bf.PREVIEW_EP_NUM == FREE_PREVIEW_EP_NUM


# ── drift report ─────────────────────────────────────────────────────────────

def test_check_classifies_states():
    s3 = FakeS3({
        # in_sync: preview obj + metadata flagged
        "sync/metadata.json": json.dumps(_meta("sync", preview_flag=True)).encode(),
        "sync/ep_01/audio.m4a": b"a",
        "sync/ep_01/preview.m4a": b"p",
        # missing: audio but no preview, not flagged
        "missing/metadata.json": json.dumps(_meta("missing")).encode(),
        "missing/ep_01/audio.m4a": b"a",
        # flag_without_preview: flagged but no object → free 404
        "ghost/metadata.json": json.dumps(_meta("ghost", preview_flag=True)).encode(),
        "ghost/ep_01/audio.m4a": b"a",
        # preview_without_flag: object but metadata not flagged
        "orphan/metadata.json": json.dumps(_meta("orphan")).encode(),
        "orphan/ep_01/audio.m4a": b"a",
        "orphan/ep_01/preview.m4a": b"p",
    })
    report = bf.check(s3, bucket="b", series_ids=["sync", "missing", "ghost", "orphan"])
    assert report["states"] == {
        "sync": "in_sync",
        "missing": "missing",
        "ghost": "flag_without_preview",
        "orphan": "preview_without_flag",
    }
    assert report["in_sync"] is False
    assert set(report["drift"]) == {"missing", "ghost", "orphan"}
