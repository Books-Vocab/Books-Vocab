"""HTTP-level smoke tests for /api/admin/user-cost-summary."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import ADMIN_TOKEN, make_admin_client


@pytest.fixture()
def admin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import kg.token_tracker as tt

    def setup_logs(data_dir, mp):
        mp.setattr(tt, "DATA_DIR", data_dir, raising=True)
        mp.setattr(tt, "DB_PATH", data_dir / "token_usage.db", raising=True)
        tt._conn = None

    def teardown_logs():
        if tt._conn is not None:
            tt._conn.close()
            tt._conn = None

    yield from make_admin_client(
        tmp_path, monkeypatch, setup_logs=setup_logs, teardown_logs=teardown_logs
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _seed(user_id: str, call_type: str, *, t_in: int, t_out: int, when: datetime | None = None) -> None:
    import kg.token_tracker as tt

    when = when or datetime.now(UTC)
    with tt._lock:
        conn = tt._get_conn()
        conn.execute(
            "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) VALUES (?,?,?,?,?)",
            (user_id, call_type, t_in, t_out, when.isoformat()),
        )
        conn.commit()


def test_cost_summary_empty(admin_client):
    """Empty token_usage table returns zeroed shape, not 500."""
    r = admin_client.client.get(
        "/api/admin/user-cost-summary?user_id=u1&range=month",
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["range"] == "month"
    assert body["total_calls"] == 0
    assert body["total_cost_usd"] == 0.0
    assert body["by_service"] == {}
    assert body["by_model"] == {}
    assert body["pricing_assumptions"]["model_inferred_from_call_type"] is True


def test_cost_summary_aggregates_by_service(admin_client):
    """Endpoint returns aggregated by_service / by_model / totals."""
    _seed("u1", "judge", t_in=1000, t_out=200)
    _seed("u1", "translate_quick", t_in=500, t_out=100)
    _seed("u1", "embed", t_in=2000, t_out=0)

    r = admin_client.client.get(
        "/api/admin/user-cost-summary?user_id=u1&range=month",
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 3
    assert body["total_input_tokens"] == 3500
    assert body["total_output_tokens"] == 300
    assert set(body["by_service"].keys()) == {"judge", "translate", "pipeline"}
    assert set(body["by_model"].keys()) == {
        "gemini-2.5-flash-lite", "gemini-embedding-2-preview",
    }


def test_cost_summary_requires_admin(admin_client):
    r = admin_client.client.get("/api/admin/user-cost-summary?user_id=u1")
    assert r.status_code in (401, 403)


def test_cost_summary_invalid_range_returns_400(admin_client):
    r = admin_client.client.get(
        "/api/admin/user-cost-summary?user_id=u1&range=forever",
        headers=_auth(),
    )
    assert r.status_code == 400
