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
