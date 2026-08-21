"""Unit tests for admin host statistics."""
from __future__ import annotations

from types import SimpleNamespace

from kg.admin.stats import _collect_disks


def _disk_usage(*, total: int, used: int, free: int, percent: float):
    return SimpleNamespace(total=total, used=used, free=free, percent=percent)


def test_collect_disks_keeps_distinct_paths_with_equal_capacity(monkeypatch):
    monkeypatch.setattr("kg.admin.stats.os.path.exists", lambda path: True)
    usage_by_path = {
        "/": _disk_usage(total=100, used=40, free=60, percent=40.0),
        "/app/data": _disk_usage(total=100, used=70, free=30, percent=70.0),
    }
    psutil = SimpleNamespace(disk_usage=usage_by_path.__getitem__)

    disks = _collect_disks(psutil)

    assert [disk["path"] for disk in disks] == ["/", "/app/data"]
    assert [disk["used"] for disk in disks] == [40, 70]
