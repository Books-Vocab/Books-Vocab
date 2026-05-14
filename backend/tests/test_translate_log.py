import pytest
from kg.translate_log import record, lookup, get_log, _reset

@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    _reset()
    yield
    _reset()

def test_record_and_lookup():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="The story evokes memories.", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起","p":"v.","r":"evoke"}', latency_ms=150,
    )
    hit = lookup("evoke", "abc123", "en", "zh-Hant", "translate_quick")
    assert hit == '{"t":"喚起","p":"v.","r":"evoke"}'

def test_lookup_miss():
    assert lookup("evoke", "abc123", "en", "zh-Hant", "translate_quick") is None

def test_cross_user_cache():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="ctx", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起"}', latency_ms=100,
    )
    hit = lookup("evoke", "abc123", "en", "zh-Hant", "translate_quick")
    assert hit == '{"t":"喚起"}'

def test_different_context_no_hit():
    record(
        user_id="u1", operation="translate_quick", word="bank",
        context="river bank", context_hash="river_hash",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"河岸"}', latency_ms=100,
    )
    assert lookup("bank", "finance_hash", "en", "zh-Hant", "translate_quick") is None

def test_different_operation_no_hit():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="ctx", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起"}', latency_ms=100,
    )
    assert lookup("evoke", "abc123", "en", "zh-Hant", "translate_explain") is None

def test_get_log():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="ctx", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起"}', latency_ms=100,
    )
    record(
        user_id="u2", operation="translate_explain", word="bank",
        context="river", context_hash="def456",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"e":"解釋"}', latency_ms=200,
    )
    logs = get_log("u1")
    assert len(logs) == 1
    assert logs[0]["word"] == "evoke"


def test_lookup_expired_cache(tmp_path, monkeypatch):
    """Entries older than CACHE_TTL_DAYS should not be returned by lookup."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="old",
        context="ctx", context_hash="hash1",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"舊"}', latency_ms=100,
    )

    # Backdate the entry to 60 days ago
    from datetime import datetime, timedelta, UTC
    old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    from kg.translate_log import _get_conn, _lock
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE translate_log SET created_at=? WHERE word='old'", (old_ts,))
        conn.commit()

    # Should miss (expired)
    assert lookup("old", "hash1", "en", "zh-Hant", "translate_quick") is None

    # Fresh entry should still hit
    record(
        user_id="u1", operation="translate_quick", word="new",
        context="ctx", context_hash="hash2",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"新"}', latency_ms=100,
    )
    assert lookup("new", "hash2", "en", "zh-Hant", "translate_quick") == '{"t":"新"}'

    _reset()


def _backdate(word: str, days: float) -> None:
    """Set created_at of `word` row to `days` ago (UTC)."""
    from datetime import datetime, timedelta, UTC
    from kg.translate_log import _get_conn, _lock
    ts = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE translate_log SET created_at=? WHERE word=?", (ts, word))
        conn.commit()


def test_ttl_env_override_shortens_cache(tmp_path, monkeypatch):
    """TRANSLATE_CACHE_TTL_DAYS=7 → entry aged 10 days should miss."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "7")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="mid",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"中"}', latency_ms=100,
    )
    _backdate("mid", 10)

    assert lookup("mid", "h", "en", "zh-Hant", "translate_quick") is None
    _reset()


def test_ttl_env_override_extends_cache(tmp_path, monkeypatch):
    """TRANSLATE_CACHE_TTL_DAYS=90 → entry aged 60 days should still hit."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "90")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="long",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"長"}', latency_ms=100,
    )
    _backdate("long", 60)

    assert lookup("long", "h", "en", "zh-Hant", "translate_quick") == '{"t":"長"}'
    _reset()


def test_ttl_boundary_inside_window(tmp_path, monkeypatch):
    """Entry aged TTL-1 days → hit. (boundary inside)"""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "30")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="edgein",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"邊內"}', latency_ms=100,
    )
    _backdate("edgein", 29)

    assert lookup("edgein", "h", "en", "zh-Hant", "translate_quick") == '{"t":"邊內"}'
    _reset()


def test_ttl_boundary_outside_window(tmp_path, monkeypatch):
    """Entry aged TTL+1 days → miss. (boundary outside)"""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "30")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="edgeout",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"邊外"}', latency_ms=100,
    )
    _backdate("edgeout", 31)

    assert lookup("edgeout", "h", "en", "zh-Hant", "translate_quick") is None
    _reset()


def test_ttl_invalid_env_falls_back_to_default(tmp_path, monkeypatch):
    """Garbage env value → default 30 days; aged 60 days → miss."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "not-a-number")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="garbage",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"亂"}', latency_ms=100,
    )
    _backdate("garbage", 60)

    assert lookup("garbage", "h", "en", "zh-Hant", "translate_quick") is None
    _reset()


def test_ttl_negative_env_falls_back_to_default(tmp_path, monkeypatch):
    """Negative env → default 30 days; aged 60 days → miss."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "-5")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="neg",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"負"}', latency_ms=100,
    )
    _backdate("neg", 60)

    assert lookup("neg", "h", "en", "zh-Hant", "translate_quick") is None
    _reset()


def test_ttl_zero_disables_cache(tmp_path, monkeypatch):
    """TRANSLATE_CACHE_TTL_DAYS=0 → cache disabled; even fresh entry misses."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "0")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="zero",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"零"}', latency_ms=100,
    )
    # Even the just-recorded entry should miss when cache is disabled.
    assert lookup("zero", "h", "en", "zh-Hant", "translate_quick") is None
    _reset()


def test_ttl_float_env_falls_back(tmp_path, monkeypatch):
    """Float-string env (e.g. '30.5') → invalid int → default 30 days; aged 60 → miss."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "30.5")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="flt",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"浮"}', latency_ms=100,
    )
    _backdate("flt", 60)

    assert lookup("flt", "h", "en", "zh-Hant", "translate_quick") is None
    _reset()


def test_ttl_empty_env_uses_default(tmp_path, monkeypatch):
    """Empty-string env → default 30 days; aged 10 → hit (inside default window)."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "")
    _reset()

    record(
        user_id="u1", operation="translate_quick", word="empty",
        context="ctx", context_hash="h",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"空"}', latency_ms=100,
    )
    _backdate("empty", 10)

    # Within default 30-day window → hit.
    assert lookup("empty", "h", "en", "zh-Hant", "translate_quick") == '{"t":"空"}'
    _reset()
