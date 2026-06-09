"""Tests for ops/podcast_backfill_disk.py — served-disk → S3 podcast backfill.

Run via the backend uv env (has pytest + boto3); the script itself takes an
injected S3 client so these tests stub it with unittest.mock — no moto needed.

    uv run --project backend python -m pytest ops/tests/test_podcast_backfill_disk.py -v
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "podcast_backfill_disk.py"
_spec = importlib.util.spec_from_file_location("podcast_backfill_disk", _SCRIPT)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


# --- fixtures --------------------------------------------------------------

def _make_served_disk(root: Path, *, fmt: str = "mp3", eps: int = 2) -> Path:
    """Build a served-disk podcasts layout under root: index.json + one series
    (flow_x) with metadata.json + ep_NN/audio.<fmt> (+ ep_01 subtitle/script)."""
    podcasts = root / "podcasts"
    sid = "flow_x"
    sdir = podcasts / sid
    for n in range(1, eps + 1):
        ep = sdir / f"ep_{n:02d}"
        ep.mkdir(parents=True)
        (ep / f"audio.{fmt}").write_bytes(b"\x00" * 16)
        if n == 1:
            (ep / "subtitle.srt").write_text("1\n00:00 --> 00:01\nhi\n")
            (ep / "script.md").write_text("# ep1")
    meta = {"id": sid, "title": "Flow X", "episodes": [{"episodeNumber": n} for n in range(1, eps + 1)]}
    (sdir / "metadata.json").write_text(json.dumps(meta))
    (podcasts / "index.json").write_text(json.dumps([{"id": sid, "title": "Flow X", "episodeCount": eps}]))
    return podcasts


class _NoSuchKey(Exception):
    pass


class _S3Fault(Exception):
    """A non-404 fault (e.g. AccessDenied / throttling) — must NOT be mistaken
    for 'key absent'."""
    def __init__(self, code: str = "AccessDenied"):
        self.response = {"Error": {"Code": code}}


def _stub_s3(existing_keys: set[str] | None = None,
             fault_keys: set[str] | None = None) -> MagicMock:
    """MagicMock S3 client. head_object: returns for keys in existing_keys,
    raises _S3Fault for keys in fault_keys, else raises _NoSuchKey (true 404)."""
    existing = existing_keys or set()
    faults = fault_keys or set()
    s3 = MagicMock()
    s3.exceptions.NoSuchKey = _NoSuchKey

    def _head(Bucket, Key):  # noqa: N803
        if Key in faults:
            raise _S3Fault()
        if Key in existing:
            return {"ContentLength": 16}
        raise _NoSuchKey()

    s3.head_object.side_effect = _head
    return s3


# --- content-type ----------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("audio.mp3", "audio/mpeg"),
    ("audio.m4a", "audio/mp4"),
    ("subtitle.srt", "text/plain; charset=utf-8"),
    ("metadata.json", "application/json; charset=utf-8"),
    ("script.md", "text/markdown; charset=utf-8"),
    ("weird.bin", "application/octet-stream"),
])
def test_content_type_for(name, expected):
    assert backfill.content_type_for(name) == expected


# --- key layout + audioFormat injection ------------------------------------

def test_upload_keys_and_audioformat_injected(tmp_path):
    podcasts = _make_served_disk(tmp_path, fmt="mp3", eps=2)
    s3 = _stub_s3()
    backfill.backfill(
        s3, bucket="b", data_dir=podcasts, dry_run=False, skip_existing=False,
    )
    puts = {c.kwargs["Key"]: c.kwargs for c in s3.put_object.call_args_list}
    # served-disk layout maps 1:1 to S3 keys
    assert "flow_x/metadata.json" in puts
    assert "flow_x/ep_01/audio.mp3" in puts
    assert "flow_x/ep_02/audio.mp3" in puts
    assert "flow_x/ep_01/subtitle.srt" in puts
    assert "index.json" in puts
    # content-type set per extension
    assert puts["flow_x/ep_01/audio.mp3"]["ContentType"] == "audio/mpeg"
    assert puts["flow_x/ep_01/subtitle.srt"]["ContentType"] == "text/plain; charset=utf-8"
    # audioFormat injected into metadata.json before upload (Phase 0 reads it)
    meta_body = puts["flow_x/metadata.json"]["Body"]
    meta = json.loads(meta_body if isinstance(meta_body, (bytes, str)) else meta_body.read())
    assert meta["audioFormat"] == "mp3"


def test_dry_run_does_not_put(tmp_path):
    podcasts = _make_served_disk(tmp_path)
    s3 = _stub_s3()
    report = backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=True, skip_existing=False)
    s3.put_object.assert_not_called()
    assert report["planned"] > 0


def test_never_deletes(tmp_path):
    podcasts = _make_served_disk(tmp_path)
    s3 = _stub_s3()
    backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=False, skip_existing=False)
    s3.delete_object.assert_not_called()
    s3.delete_objects.assert_not_called()


def test_skip_existing_keys(tmp_path):
    podcasts = _make_served_disk(tmp_path, eps=2)
    # ep_01 audio already in bucket → skipped; ep_02 uploaded
    s3 = _stub_s3(existing_keys={"flow_x/ep_01/audio.mp3"})
    backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=False, skip_existing=True)
    put_keys = {c.kwargs["Key"] for c in s3.put_object.call_args_list}
    assert "flow_x/ep_01/audio.mp3" not in put_keys
    assert "flow_x/ep_02/audio.mp3" in put_keys


# --- reconcile (--check) ---------------------------------------------------

def test_reconcile_reports_missing_in_s3(tmp_path):
    podcasts = _make_served_disk(tmp_path, eps=2)
    s3 = _stub_s3(existing_keys=set())  # bucket empty → everything missing
    report = backfill.reconcile(s3, bucket="b", data_dir=podcasts)
    assert "flow_x/ep_01/audio.mp3" in report["missing_in_s3"]
    assert report["in_sync"] is False


def test_reconcile_in_sync_when_all_present(tmp_path):
    podcasts = _make_served_disk(tmp_path, eps=1)
    all_keys = {
        "index.json", "flow_x/metadata.json", "flow_x/ep_01/audio.mp3",
        "flow_x/ep_01/subtitle.srt", "flow_x/ep_01/script.md",
    }
    s3 = _stub_s3(existing_keys=all_keys)
    report = backfill.reconcile(s3, bucket="b", data_dir=podcasts)
    assert report["missing_in_s3"] == []
    assert report["in_sync"] is True


def test_reconcile_propagates_real_fault_not_false_drift(tmp_path):
    """A non-404 fault (perms/throttle) on head_object must raise, NOT be
    reported as missing_in_s3 (鐵律 1: no silent fallback). A safety net that
    false-alarms is broken."""
    podcasts = _make_served_disk(tmp_path, eps=1)
    s3 = _stub_s3(fault_keys={"flow_x/ep_01/audio.mp3"})
    with pytest.raises(_S3Fault):
        backfill.reconcile(s3, bucket="b", data_dir=podcasts)


def test_key_exists_reraises_real_fault(tmp_path):
    s3 = _stub_s3(fault_keys={"k"})
    with pytest.raises(Exception):
        backfill._key_exists(s3, "b", "k")


def test_audioformat_m4a_path(tmp_path):
    podcasts = _make_served_disk(tmp_path, fmt="m4a", eps=1)
    s3 = _stub_s3()
    backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=False, skip_existing=False)
    puts = {c.kwargs["Key"]: c.kwargs for c in s3.put_object.call_args_list}
    assert "flow_x/ep_01/audio.m4a" in puts
    assert puts["flow_x/ep_01/audio.m4a"]["ContentType"] == "audio/mp4"
    meta = json.loads(puts["flow_x/metadata.json"]["Body"])
    assert meta["audioFormat"] == "m4a"


def test_index_always_reput_even_when_existing(tmp_path):
    """index.json must never be skipped — a stale/partial index in the bucket
    is the exact visibility bug we recover from."""
    podcasts = _make_served_disk(tmp_path, eps=1)
    s3 = _stub_s3(existing_keys={"index.json"})  # index already there
    backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=False, skip_existing=True)
    put_keys = {c.kwargs["Key"] for c in s3.put_object.call_args_list}
    assert "index.json" in put_keys


def test_rebuild_index_strips_episodes_adds_count(tmp_path):
    podcasts = _make_served_disk(tmp_path, eps=3)
    s3 = _stub_s3()
    backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=False,
                      skip_existing=False, rebuild_index=True)
    puts = {c.kwargs["Key"]: c.kwargs for c in s3.put_object.call_args_list}
    idx = json.loads(puts["index.json"]["Body"])
    assert idx[0]["id"] == "flow_x"
    assert "episodes" not in idx[0]
    assert idx[0]["episodeCount"] == 3


def test_series_filter_limits_scope(tmp_path):
    podcasts = _make_served_disk(tmp_path, eps=1)
    # only series on disk is flow_x; filtering to a non-existent id → nothing
    s3 = _stub_s3()
    report = backfill.backfill(s3, bucket="b", data_dir=podcasts, dry_run=True,
                               series_filter=["does_not_exist"])
    assert report["series"] == []


def test_main_missing_bucket_exits_2(tmp_path, monkeypatch):
    podcasts = _make_served_disk(tmp_path, eps=1)
    monkeypatch.delenv("PODCAST_BUCKET", raising=False)
    rc = backfill.main(["--data-dir", str(podcasts)])
    assert rc == 2


def test_main_check_drift_exits_1(tmp_path, monkeypatch):
    podcasts = _make_served_disk(tmp_path, eps=1)
    monkeypatch.setattr(backfill, "_make_client", lambda region, endpoint: _stub_s3())
    rc = backfill.main(["--data-dir", str(podcasts), "--bucket", "b", "--check"])
    assert rc == 1  # bucket empty → drift


def test_main_dry_run_default_does_not_write(tmp_path, monkeypatch):
    podcasts = _make_served_disk(tmp_path, eps=1)
    s3 = _stub_s3()
    monkeypatch.setattr(backfill, "_make_client", lambda region, endpoint: s3)
    rc = backfill.main(["--data-dir", str(podcasts), "--bucket", "b"])  # no --execute
    assert rc == 0
    s3.put_object.assert_not_called()
