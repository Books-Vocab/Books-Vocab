"""delete_remote_series must not publish a shortened index.json.

Run:
    uv run --no-project --python 3.13 --with boto3 --with pytest \
        python -m pytest lab/podcast/monitor/test_remote_delete_index.py -q
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import remote  # noqa: E402


class _Paginator:
    def __init__(self, s3):
        self.s3 = s3

    def paginate(self, Bucket, Prefix=None, Delimiter=None):  # noqa: N803
        if Delimiter:
            yield {"CommonPrefixes": [{"Prefix": f"{s}/"} for s in self.s3.series]}
        else:
            yield {"Contents": []}


class _FakeS3:
    def __init__(self, series):
        self.series = series
        self.puts = []

    def get_paginator(self, _name):
        return _Paginator(self)

    def delete_objects(self, **_kw):
        return {}

    def list_objects_v2(self, **_kw):
        return {"KeyCount": 0}

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key.startswith("b/"):
            raise RuntimeError("throttled")
        return {"Body": io.BytesIO(json.dumps({"id": "a", "episodes": []}).encode())}

    def put_object(self, **kw):
        self.puts.append(kw)


def _patch(monkeypatch, s3):
    monkeypatch.setattr(remote, "_client", lambda: s3)
    monkeypatch.setattr(remote, "_bucket", lambda: "bkt")


def test_unreadable_metadata_aborts_without_rewriting_index(monkeypatch):
    s3 = _FakeS3(("a", "b"))
    _patch(monkeypatch, s3)
    with pytest.raises(remote.RemoteError):
        remote.delete_remote_series("gone")
    assert s3.puts == []


def test_all_readable_rewrites_index(monkeypatch):
    s3 = _FakeS3(("a",))
    _patch(monkeypatch, s3)
    out = remote.delete_remote_series("gone")
    assert out["remaining"] == 1
    assert len(s3.puts) == 1
