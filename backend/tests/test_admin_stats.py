"""Unit tests for admin host statistics."""

from __future__ import annotations

from pathlib import Path
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


# --- per-row provider pricing / tier-aware quota fallback (issue #2274) ---

import pytest  # noqa: E402

from kg import quota_service  # noqa: E402
from kg.admin.stats import admin_stats_response  # noqa: E402
from kg.admin_cost_summary import fold_user_summary, query_cost_rows  # noqa: E402
from kg.llm.providers import REGISTRY  # noqa: E402


@pytest.fixture
def tt_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.token_tracker as tt

    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    monkeypatch.setattr(tt, "DB_PATH", tmp_path / "token_usage.db")
    yield tt
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None


class _Cards:
    def __init__(self, _dir):
        pass

    def count(self):
        return 0


def _stats(tt, users):
    ent = SimpleNamespace(pro=SimpleNamespace(model_dump=lambda: {}))
    return admin_stats_response(
        load_users=lambda: users,
        get_all_stats=tt.get_all_stats,
        build_entitlements_response=lambda _info: ent,
        current_admin_grant_record=lambda _info: {},
        data_dir=Path("/nonexistent-kg-test"),
        card_store_factory=_Cards,
    )


def test_est_cost_prices_each_row_at_its_own_provider(tt_db, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    tt_db.record("u1", "judge", 1_000_000, 0, provider="gemini")
    out = _stats(tt_db, {"u1": {"email": "a@b.c"}})
    user = out["users"][0]
    expected = REGISTRY["gemini"].input_price_per_m
    assert user["est_cost_usd"] == pytest.approx(expected, rel=1e-5)
    folded = fold_user_summary(query_cost_rows(tt_db._get_conn(), user_id="u1"))
    assert user["est_cost_usd"] == pytest.approx(folded["total_cost_usd"], rel=1e-5)
    assert user["tokens"]["judge"]["input_tokens"] == 1_000_000
    assert user["tokens"]["judge"]["calls"] == 1


def test_est_cost_null_provider_uses_routed(tt_db, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    tt_db.record("u1", "judge", 1_000_000, 0)
    tt_db.record("u1", "judge", 1_000_000, 0, provider="gemini")
    out = _stats(tt_db, {"u1": {"email": "a@b.c"}})
    expected = REGISTRY["deepseek"].input_price_per_m + REGISTRY["gemini"].input_price_per_m
    assert out["users"][0]["est_cost_usd"] == pytest.approx(expected, rel=1e-5)
    assert out["users"][0]["tokens"]["judge"]["calls"] == 2


def test_no_usage_quota_fallback_uses_tier_limit(tt_db, monkeypatch):
    monkeypatch.setattr(quota_service, "PRO_DAILY_LIMIT_USD", 7.0)
    monkeypatch.setattr(quota_service, "FREE_DAILY_LIMIT_USD", 0.11)
    monkeypatch.setattr("kg.deps_quota._is_pro", lambda ctx: ctx["record"].get("pro", False))
    users = {"free": {"email": "f@x"}, "pro": {"email": "p@x", "pro": True}}
    out = _stats(tt_db, users)
    by_id = {u["user_id"]: u for u in out["users"]}
    assert by_id["free"]["quota"]["limit_usd"] == quota_service._daily_limit(False)
    assert by_id["pro"]["quota"]["limit_usd"] == quota_service._daily_limit(True)
    assert by_id["free"]["quota"]["fraction_used"] == 0.0
    assert by_id["free"]["quota"]["calls"] == {}
