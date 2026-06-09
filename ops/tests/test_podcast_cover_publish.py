"""Tests for ops/podcast_cover_publish.py — atomic, audio-decoupled cover publish.

Run via the backend uv env (has pytest); the script takes an injected S3 client
so these tests use a small dict-backed FakeS3 — no moto, no network.

    uv run --project backend python -m pytest ops/tests/test_podcast_cover_publish.py -v
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "podcast_cover_publish.py"
_spec = importlib.util.spec_from_file_location("podcast_cover_publish", _SCRIPT)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

_PNG = cp._PNG_MAGIC + b"\x00\x01rest-of-image"
_NOT_PNG = b"<html>404</html>"


# --- FakeS3 ----------------------------------------------------------------

class _NoSuchKey(Exception):
    pass


class _Fault(Exception):
    """Non-404 fault (e.g. AccessDenied) — must NOT be mistaken for 'absent'."""
    def __init__(self, code: str = "AccessDenied"):
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


class _Paginator:
    def __init__(self, store: dict):
        self._store = store

    def paginate(self, Bucket, Delimiter=None, Prefix=""):  # noqa: N803
        keys = [k for k in self._store if k.startswith(Prefix)]
        if Delimiter == "/":
            prefixes = set()
            contents = []
            for k in keys:
                rest = k[len(Prefix):]
                if "/" in rest:
                    prefixes.add(Prefix + rest.split("/", 1)[0] + "/")
                else:
                    contents.append({"Key": k})
            yield {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)],
                   "Contents": contents}
        else:
            yield {"Contents": [{"Key": k} for k in sorted(keys)]}


class FakeS3:
    """Minimal dict-backed S3: stores {key: (body, content_type)} and records
    the exact order of put_object calls (to assert the cover→metadata→index
    ordering invariant). fault_keys raise a non-404 on any access."""
    def __init__(self, fault_keys: set[str] | None = None):
        self.store: dict[str, tuple[bytes, str]] = {}
        self.put_order: list[str] = []
        self.faults = fault_keys or set()
        self.deleted: list[str] = []

        class _Exc:
            NoSuchKey = _NoSuchKey
        self.exceptions = _Exc()

    def _check_fault(self, key):
        if key in self.faults:
            raise _Fault()

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803
        self._check_fault(Key)
        self.store[Key] = (Body, ContentType)
        self.put_order.append(Key)
        return {}

    def get_object(self, Bucket, Key):  # noqa: N803
        self._check_fault(Key)
        if Key not in self.store:
            raise _NoSuchKey()
        return {"Body": _Body(self.store[Key][0])}

    def head_object(self, Bucket, Key):  # noqa: N803
        self._check_fault(Key)
        if Key not in self.store:
            raise _NoSuchKey()
        return {"ContentLength": len(self.store[Key][0])}

    def delete_object(self, **kw):
        self.deleted.append(kw.get("Key"))

    def delete_objects(self, **kw):
        self.deleted.append("BATCH")

    def get_paginator(self, name):
        return _Paginator(self.store)

    # helpers for tests
    def seed_series(self, sid: str, *, eps: int = 2, cover_url=None, title=None):
        meta = {"id": sid, "title": title or sid, "createdAt": "2026-01-01T00:00:00+00:00",
                "coverImageURL": cover_url, "color": "#5B8C5A", "coverPattern": "waves",
                "episodes": [{"episodeNumber": n, "title": f"e{n}"} for n in range(1, eps + 1)]}
        self.store[f"{sid}/metadata.json"] = (
            json.dumps(meta).encode("utf-8"), cp._JSON_CT)
        self.store[f"{sid}/ep_01/audio.mp3"] = (b"\x00" * 8, "audio/mpeg")

    def meta(self, sid: str) -> dict:
        return json.loads(self.store[f"{sid}/metadata.json"][0])


# --- pure helpers ----------------------------------------------------------

@pytest.mark.parametrize("body,expected", [
    (_PNG, True),
    (_NOT_PNG, False),
    (b"", False),
    (b"\x89PNG", False),  # truncated magic
])
def test_is_png(body, expected):
    assert cp.is_png(body) is expected


def test_cover_url_for():
    assert cp.cover_url_for("flow_x") == "/api/podcasts/flow_x/cover"
    assert cp.cover_url_for("flow_x", _PNG) == f"/api/podcasts/flow_x/cover?v={cp.cover_version(_PNG)}"
    assert cp.cover_url_for("flow_x", _PNG) != cp.cover_url_for("flow_x", _PNG + b"new")


def test_patch_cover_url_sets_url_preserves_everything_else():
    meta = {"id": "s", "title": "T", "createdAt": "2026-01-01T00:00:00+00:00",
            "coverImageURL": None, "episodes": [{"episodeNumber": 1}], "color": "#5B8C5A"}
    out = cp.patch_cover_url(meta, "s", _PNG)
    assert out["coverImageURL"] == f"/api/podcasts/s/cover?v={cp.cover_version(_PNG)}"
    # everything else verbatim — createdAt NOT reset, episodes intact, no updatedAt bump
    assert out["createdAt"] == "2026-01-01T00:00:00+00:00"
    assert out["episodes"] == [{"episodeNumber": 1}]
    assert out["color"] == "#5B8C5A"
    assert "updatedAt" not in out  # stable body → idempotent
    assert meta["coverImageURL"] is None  # input not mutated


# --- publish_cover_object: ordering, content-type, guards -------------------

def test_publish_orders_cover_before_metadata():
    """Ordering invariant: cover.png must be PUT before metadata.json points at
    it — otherwise a crash between leaves metadata referencing an absent cover."""
    s3 = FakeS3()
    s3.seed_series("flow_x")
    cp.publish_cover_object(s3, bucket="b", series_id="flow_x", cover_body=_PNG, dry_run=False)
    assert s3.put_order.index("flow_x/cover.png") < s3.put_order.index("flow_x/metadata.json")


def test_publish_sets_content_types_and_url():
    s3 = FakeS3()
    s3.seed_series("flow_x")
    cp.publish_cover_object(s3, bucket="b", series_id="flow_x", cover_body=_PNG, dry_run=False)
    assert s3.store["flow_x/cover.png"][1] == "image/png"
    assert s3.store["flow_x/metadata.json"][1] == "application/json; charset=utf-8"
    assert s3.meta("flow_x")["coverImageURL"] == f"/api/podcasts/flow_x/cover?v={cp.cover_version(_PNG)}"
    assert s3.meta("flow_x")["createdAt"] == "2026-01-01T00:00:00+00:00"  # preserved


def test_publish_aborts_on_unpublished_series():
    """Refuse to drop a cover onto a series with no metadata.json (never published)."""
    s3 = FakeS3()  # empty bucket
    with pytest.raises(ValueError, match="not published"):
        cp.publish_cover_object(s3, bucket="b", series_id="ghost", cover_body=_PNG, dry_run=False)
    assert s3.put_order == []  # nothing written


def test_publish_aborts_on_non_png():
    s3 = FakeS3()
    s3.seed_series("flow_x")
    with pytest.raises(ValueError, match="not a PNG"):
        cp.publish_cover_object(s3, bucket="b", series_id="flow_x", cover_body=_NOT_PNG, dry_run=False)
    assert s3.put_order == []


def test_publish_aborts_on_bad_series_id():
    s3 = FakeS3()
    with pytest.raises(ValueError, match="invalid series_id"):
        cp.publish_cover_object(s3, bucket="b", series_id="Bad-ID", cover_body=_PNG, dry_run=False)


def test_publish_real_fault_propagates_not_silent():
    """AccessDenied reading metadata must raise, not be treated as 'unpublished'."""
    s3 = FakeS3(fault_keys={"flow_x/metadata.json"})
    s3.store["flow_x/metadata.json"] = (b"{}", cp._JSON_CT)  # present but faults
    with pytest.raises(_Fault):
        cp.publish_cover_object(s3, bucket="b", series_id="flow_x", cover_body=_PNG, dry_run=False)


# --- batch publish + index -------------------------------------------------

def test_publish_dry_run_writes_nothing():
    s3 = FakeS3()
    s3.seed_series("flow_x")
    report = cp.publish(s3, bucket="b", covers={"flow_x": _PNG}, dry_run=True)
    assert s3.put_order == []
    assert report["dry_run"] is True
    assert report["count"] == 1


def test_publish_rebuilds_index_without_dropping_other_series():
    """Cover-only change to A and B must keep C in the index (the upload.sh
    reconcile hazard this tool exists to avoid, at the index level)."""
    s3 = FakeS3()
    s3.seed_series("a_x", eps=2)
    s3.seed_series("b_x", eps=3)
    s3.seed_series("c_x", eps=1, cover_url="/api/podcasts/c_x/cover")  # untouched, already has cover
    cp.publish(s3, bucket="b", covers={"a_x": _PNG, "b_x": _PNG}, dry_run=False)
    index = json.loads(s3.store["index.json"][0])
    by_id = {e["id"]: e for e in index}
    assert set(by_id) == {"a_x", "b_x", "c_x"}              # C not dropped
    assert by_id["a_x"]["coverImageURL"] == f"/api/podcasts/a_x/cover?v={cp.cover_version(_PNG)}"
    assert by_id["b_x"]["coverImageURL"] == f"/api/podcasts/b_x/cover?v={cp.cover_version(_PNG)}"
    assert by_id["c_x"]["coverImageURL"] == "/api/podcasts/c_x/cover"  # preserved
    assert by_id["b_x"]["episodeCount"] == 3               # episodes stripped → count
    assert "episodes" not in by_id["b_x"]


def test_publish_is_idempotent():
    """Running twice yields byte-identical metadata + index (stable body)."""
    s3 = FakeS3()
    s3.seed_series("flow_x")
    cp.publish(s3, bucket="b", covers={"flow_x": _PNG}, dry_run=False)
    meta1 = s3.store["flow_x/metadata.json"][0]
    idx1 = s3.store["index.json"][0]
    cp.publish(s3, bucket="b", covers={"flow_x": _PNG}, dry_run=False)
    assert s3.store["flow_x/metadata.json"][0] == meta1
    assert s3.store["index.json"][0] == idx1


def test_dry_run_index_preview_reflects_target_state():
    """In dry-run, the index body is computed but not written; it should reflect
    the post-publish coverImageURL via overrides (preview accuracy)."""
    s3 = FakeS3()
    s3.seed_series("flow_x")
    body = cp.rebuild_index_body(
        s3, bucket="b", overrides={"flow_x": cp.patch_cover_url(s3.meta("flow_x"), "flow_x", _PNG)})
    entry = json.loads(body)[0]
    assert entry["coverImageURL"] == f"/api/podcasts/flow_x/cover?v={cp.cover_version(_PNG)}"


# --- re-entry / interruption recovery --------------------------------------

def test_reentry_after_cover_put_without_metadata_patch_converges():
    """Simulate a crash after step 1 (cover.png PUT) but before step 2 (metadata
    patch): check must flag cover_png_without_url drift, and re-running publish
    must drive it back to in_sync."""
    s3 = FakeS3()
    s3.seed_series("flow_x")
    # crash state: cover.png present, metadata still coverImageURL=None
    s3.store["flow_x/cover.png"] = (_PNG, "image/png")

    report = cp.check(s3, bucket="b", series_ids=["flow_x"])
    assert report["states"]["flow_x"] == "cover_png_without_url"
    assert report["in_sync"] is False

    cp.publish(s3, bucket="b", covers={"flow_x": _PNG}, dry_run=False)
    report2 = cp.check(s3, bucket="b", series_ids=["flow_x"])
    assert report2["states"]["flow_x"] == "in_sync"
    assert report2["in_sync"] is True


def test_publish_never_deletes():
    s3 = FakeS3()
    s3.seed_series("flow_x")
    cp.publish(s3, bucket="b", covers={"flow_x": _PNG}, dry_run=False)
    assert s3.deleted == []  # audio-decoupled: no reconcile, no prune


# --- check: drift classification -------------------------------------------

def test_check_states():
    s3 = FakeS3()
    s3.seed_series("synced", cover_url="/api/podcasts/synced/cover")
    s3.store["synced/cover.png"] = (_PNG, "image/png")
    s3.seed_series("dangling_url", cover_url="/api/podcasts/dangling_url/cover")  # url, no png
    s3.seed_series("orphan_png")  # png, no url
    s3.store["orphan_png/cover.png"] = (_PNG, "image/png")
    s3.seed_series("legacy")  # neither

    report = cp.check(s3, bucket="b",
                      series_ids=["synced", "dangling_url", "orphan_png", "legacy"])
    assert report["states"] == {
        "synced": "in_sync",
        "dangling_url": "url_without_cover_png",
        "orphan_png": "cover_png_without_url",
        "legacy": "unpublished",
    }
    assert set(report["drift"]) == {"dangling_url", "orphan_png"}
    assert report["in_sync"] is False


def test_check_propagates_real_fault_on_cover_png():
    """check() probes cover.png via _key_exists; an AccessDenied there must
    raise, NOT be misread as 'cover.png absent' and false-report drift on an
    actually in-sync series (鐵律 1)."""
    s3 = FakeS3(fault_keys={"flow_x/cover.png"})
    s3.seed_series("flow_x", cover_url="/api/podcasts/flow_x/cover")
    with pytest.raises(_Fault):
        cp.check(s3, bucket="b", series_ids=["flow_x"])


def test_check_pending_publish_when_local_cover_exists():
    s3 = FakeS3()
    s3.seed_series("legacy")  # no cover in S3
    report = cp.check(s3, bucket="b", series_ids=["legacy"], local_covers={"legacy": _PNG})
    assert report["states"]["legacy"] == "pending_publish"
    assert set(report["pending"]) == {"legacy"}
    assert report["in_sync"] is False


def test_check_pending_publish_when_local_cover_version_changed():
    s3 = FakeS3()
    old_png = _PNG + b"old"
    new_png = _PNG + b"new"
    s3.seed_series("flow_x", cover_url=cp.cover_url_for("flow_x", old_png))
    s3.store["flow_x/cover.png"] = (old_png, cp._COVER_CT)

    report = cp.check(s3, bucket="b", series_ids=["flow_x"], local_covers={"flow_x": new_png})

    assert report["states"]["flow_x"] == "pending_publish"
    assert set(report["pending"]) == {"flow_x"}
    assert report["drift"] == {}
    assert report["in_sync"] is False


# --- cover source resolution -----------------------------------------------

def test_collect_covers_all_scans_workspaces(tmp_path):
    for sid in ("a_x", "b_x"):
        (tmp_path / sid / "plan").mkdir(parents=True)
        (tmp_path / sid / "plan" / "cover.png").write_bytes(_PNG)
    (tmp_path / "no_cover" / "plan").mkdir(parents=True)  # no cover.png → skipped
    covers = cp._collect_covers(workspaces_dir=tmp_path, workspace=None, series=None,
                                cover=None, all_=True)
    assert set(covers) == {"a_x", "b_x"}
    assert covers["a_x"] == _PNG


def test_collect_covers_workspace_uses_basename(tmp_path):
    ws = tmp_path / "flow_x"
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "cover.png").write_bytes(_PNG)
    covers = cp._collect_covers(workspaces_dir=None, workspace=ws, series=None,
                                cover=None, all_=False)
    assert set(covers) == {"flow_x"}


def test_collect_covers_rejects_conflicting_modes(tmp_path):
    """--workspace / --all / --series are mutually exclusive — a conflicting
    combo must raise, not silently drop one (e.g. --workspace A --series B)."""
    ws = tmp_path / "flow_x"
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "cover.png").write_bytes(_PNG)
    with pytest.raises(ValueError, match="mutually exclusive"):
        cp._collect_covers(workspaces_dir=None, workspace=ws, series=["other"],
                           cover=None, all_=False)
    with pytest.raises(ValueError, match="mutually exclusive"):
        cp._collect_covers(workspaces_dir=tmp_path, workspace=None, series=["x"],
                           cover=None, all_=True)


def test_collect_covers_missing_cover_skipped(tmp_path):
    ws = tmp_path / "flow_x"
    (ws / "plan").mkdir(parents=True)  # no cover.png
    covers = cp._collect_covers(workspaces_dir=None, workspace=ws, series=None,
                                cover=None, all_=False)
    assert covers == {}


# --- main ------------------------------------------------------------------

def test_main_missing_bucket_exits_2(monkeypatch):
    monkeypatch.delenv("PODCAST_BUCKET", raising=False)
    assert cp.main(["--all"]) == 2


def test_main_dry_run_default_does_not_write(tmp_path, monkeypatch):
    ws = tmp_path / "flow_x"
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "cover.png").write_bytes(_PNG)
    s3 = FakeS3()
    s3.seed_series("flow_x")
    monkeypatch.setattr(cp, "_make_client", lambda region, endpoint: s3)
    rc = cp.main(["--bucket", "b", "--workspace", str(ws)])  # no --execute
    assert rc == 0
    assert "flow_x/cover.png" not in s3.store  # dry-run wrote nothing

def test_main_check_drift_exits_1(monkeypatch):
    s3 = FakeS3()
    s3.seed_series("dangling", cover_url="/api/podcasts/dangling/cover")  # url, no png
    monkeypatch.setattr(cp, "_make_client", lambda region, endpoint: s3)
    rc = cp.main(["--bucket", "b", "--check", "--series", "dangling"])
    assert rc == 1


def test_main_check_pending_publish_exits_1(tmp_path, monkeypatch):
    ws = tmp_path / "flow_x"
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "cover.png").write_bytes(_PNG + b"new")
    s3 = FakeS3()
    s3.seed_series("flow_x", cover_url=cp.cover_url_for("flow_x", _PNG + b"old"))
    s3.store["flow_x/cover.png"] = (_PNG + b"old", cp._COVER_CT)
    monkeypatch.setattr(cp, "_make_client", lambda region, endpoint: s3)

    rc = cp.main(["--bucket", "b", "--check", "--workspace", str(ws)])

    assert rc == 1


def test_main_execute_publishes(tmp_path, monkeypatch):
    ws = tmp_path / "flow_x"
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "cover.png").write_bytes(_PNG)
    s3 = FakeS3()
    s3.seed_series("flow_x")
    monkeypatch.setattr(cp, "_make_client", lambda region, endpoint: s3)
    rc = cp.main(["--bucket", "b", "--workspace", str(ws), "--execute"])
    assert rc == 0
    assert s3.meta("flow_x")["coverImageURL"] == f"/api/podcasts/flow_x/cover?v={cp.cover_version(_PNG)}"
    assert "flow_x/cover.png" in s3.store
