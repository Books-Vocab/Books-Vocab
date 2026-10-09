"""Readiness endpoint: fails closed when the data dir is broken (2026-10-09 incident).

Every test points ``app.state.kg_settings.data_dir`` at a tmp dir; no real
path is ever touched.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.api import app

READY_PATH = "/api/system/info/ready"


def _make_healthy(root):
    (root / "users").mkdir(parents=True)
    (root / ".worker.lock").touch()
    (root / "pipeline_runs.db").touch()
    return root


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = _make_healthy(tmp_path / "data")
    monkeypatch.setattr(app.state, "kg_settings", SimpleNamespace(data_dir=root), raising=False)
    # Keep the real settings object for other middleware lookups.
    return root


@pytest.fixture()
def client(data_dir):
    # No `with`: skip the lifespan so it never locks/creates the real data dir.
    c = TestClient(app, raise_server_exceptions=False)
    try:
        yield c
    finally:
        c.close()


def test_ready_200_with_good_data_dir(client, data_dir):
    r = client.get(READY_PATH)
    assert r.status_code == 200, r.text
    assert r.json() == {"ready": True}
    assert r.headers["cache-control"] == "no-store"
    assert [p.name for p in data_dir.iterdir() if p.name.startswith(".ready")] == []


def test_ready_503_when_data_dir_missing(client, data_dir):
    import shutil

    shutil.rmtree(data_dir)
    r = client.get(READY_PATH)
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert "data_dir_missing" in body["reasons"]
    assert str(data_dir) not in r.text


def test_ready_503_when_users_dir_missing(client, data_dir):
    (data_dir / "users").rmdir()
    r = client.get(READY_PATH)
    assert r.status_code == 503
    assert r.json()["reasons"] == ["users_dir_missing"]


def test_ready_503_when_data_dir_is_a_file(client, data_dir):
    import shutil

    shutil.rmtree(data_dir)
    data_dir.write_text("x")
    r = client.get(READY_PATH)
    assert r.status_code == 503
    assert "data_dir_missing" in r.json()["reasons"]


def test_ready_503_when_not_writable(client, data_dir, monkeypatch):
    real_open = os.open

    def deny(path, flags, *a, **kw):
        if os.path.basename(os.fspath(path)).startswith(".ready-probe-"):
            raise PermissionError(13, "denied")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr("kg.routers.system.os.open", deny)
    r = client.get(READY_PATH)
    assert r.status_code == 503
    assert r.json()["reasons"] == ["data_dir_not_writable"]
    assert str(data_dir) not in r.text


def test_ready_503_when_shared_db_or_lock_missing(client, data_dir):
    (data_dir / "pipeline_runs.db").unlink()
    (data_dir / ".worker.lock").unlink()
    r = client.get(READY_PATH)
    assert r.status_code == 503
    assert set(r.json()["reasons"]) == {"pipeline_db_missing", "worker_lock_missing"}


def test_ready_probe_file_is_cleaned_up_and_unique(client, data_dir):
    for _ in range(3):
        assert client.get(READY_PATH).status_code == 200
    assert sorted(p.name for p in data_dir.iterdir()) == [".worker.lock", "pipeline_runs.db", "users"]


def test_ready_is_rate_limit_exempt(client):
    from kg.rate_limit import api_limiter

    api_limiter._requests.clear()
    for _ in range(api_limiter.max_requests + 30):
        r = client.get(READY_PATH)
        assert r.status_code == 200, "readiness must never be rate limited"
