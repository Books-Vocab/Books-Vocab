#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""Regression test: agent stages must retry transient CLI/API failures.

根因:`claude -p` agent loop 在 extended thinking + tool use 下偶發
`400 ... thinking/redacted_thinking blocks ... cannot be modified`,CLI exit 1。
舊碼 `pipeline.py` 任一 stage 回 False 就 `sys.exit(1)`,零重試 —— 一個 transient
400 燒掉整條 pipeline。修法:在所有 agent stage 的單一入口加重試,全新 `claude -p`
(= 全新對話)繞過被汙染的 thinking 歷史。本測試鎖定:

  1. 錯誤分類器正確區分 retryable(thinking-block 400 / 429 / 5xx)vs fatal(auth / 一般 400 / timeout)。
  2. 重試迴圈在 retryable 失敗後重跑、成功即回 True。
  3. fatal 失敗不重試,立即放棄。
  4. retryable 但耗盡次數後放棄。
"""
import pytest

import pipeline


# ─── 錯誤分類器 ───

THINKING_400 = (
    "API Error: 400 messages.1.content.8: `thinking` or `redacted_thinking` "
    "blocks in the latest assistant message cannot be modified. These blocks "
    "must remain as they were in the original response."
)


@pytest.mark.parametrize("status,reason", [
    ("400", THINKING_400),          # CLI-loop thinking 汙染 → 全新對話可解
    ("429", "rate_limit_error: too many requests"),
    ("503", "service unavailable"),
    ("529", "overloaded_error: Overloaded"),
    ("500", "internal server error"),
    (None, "Connection reset by peer"),
])
def test_retryable_failures(status, reason):
    assert pipeline._is_retryable_claude_failure(status, reason) is True


@pytest.mark.parametrize("status,reason", [
    ("401", "authentication_error: invalid x-api-key"),
    ("403", "permission denied"),
    ("400", "invalid_request_error: max_tokens too large"),  # 一般 400,非 thinking
    ("timeout", "TIMEOUT after 1500s"),                       # 逾時不重試(避免燒錢)
])
def test_fatal_failures(status, reason):
    assert pipeline._is_retryable_claude_failure(status, reason) is False


# ─── 重試迴圈 ───

def _patch_no_sleep(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pipeline, "_STAGE_RETRY_BASE", 0.0)
    monkeypatch.setattr(pipeline, "_STAGE_RETRY_ATTEMPTS", 3)


class _Log:
    def event(self, *a, **k): pass
    def error(self, *a, **k): pass


def test_retry_recovers_after_transient(monkeypatch):
    _patch_no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake(cmd, workspace, label, log, timeout, prompt=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, 1.0, pipeline._ClaudeFailure("400", THINKING_400)
        return True, 1.0, None

    monkeypatch.setattr(pipeline, "_run_claude_subprocess", fake)
    ok, _ = pipeline._run_claude_with_retry(["claude"], None, "Architect", _Log(), 1500)
    assert ok is True
    assert calls["n"] == 2  # 失敗一次 → 重試 → 成功


def test_no_retry_on_fatal(monkeypatch):
    _patch_no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake(cmd, workspace, label, log, timeout, prompt=None):
        calls["n"] += 1
        return False, 1.0, pipeline._ClaudeFailure("401", "authentication_error")

    monkeypatch.setattr(pipeline, "_run_claude_subprocess", fake)
    ok, _ = pipeline._run_claude_with_retry(["claude"], None, "Architect", _Log(), 1500)
    assert ok is False
    assert calls["n"] == 1  # fatal 不重試


def test_retry_exhausts(monkeypatch):
    _patch_no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake(cmd, workspace, label, log, timeout, prompt=None):
        calls["n"] += 1
        return False, 1.0, pipeline._ClaudeFailure("503", "service unavailable")

    monkeypatch.setattr(pipeline, "_run_claude_subprocess", fake)
    ok, _ = pipeline._run_claude_with_retry(["claude"], None, "Architect", _Log(), 1500)
    assert ok is False
    assert calls["n"] == 3  # 耗盡 _STAGE_RETRY_ATTEMPTS


# ─── Agent profile / Kimi env ───

def test_kimi_profile_env_uses_existing_shell_contract(monkeypatch, tmp_path):
    key_file = tmp_path / "kimi.env"
    key_file.write_text(" kimi-test-key \n")
    monkeypatch.setenv("PODCAST_KIMI_KEY_FILE", str(key_file))
    monkeypatch.delenv("PODCAST_KIMI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    pipeline.configure_agent(profile="kimi")
    env = pipeline._agent_subprocess_env()

    assert pipeline.AGENT_PROFILE == "kimi"
    assert pipeline.MODEL == "kimi-for-coding"
    assert env["ANTHROPIC_BASE_URL"] == "https://api.kimi.com/coding"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "kimi-test-key"
    assert env["ANTHROPIC_MODEL"] == "kimi-for-coding"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "kimi-for-coding"


def test_kimi_profile_missing_key_fails_before_spawn(monkeypatch, tmp_path):
    monkeypatch.setenv("PODCAST_KIMI_KEY_FILE", str(tmp_path / "missing.env"))
    monkeypatch.delenv("PODCAST_KIMI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    pipeline.configure_agent(profile="kimi")

    with pytest.raises(RuntimeError, match="Kimi API key"):
        pipeline._agent_subprocess_env()


def test_claude_profile_keeps_legacy_model_env(monkeypatch):
    monkeypatch.setenv("PODCAST_CLAUDE_MODEL", "sonnet")
    monkeypatch.delenv("PODCAST_AGENT_MODEL", raising=False)

    pipeline.configure_agent(profile="claude")

    assert pipeline.AGENT_PROFILE == "claude"
    assert pipeline.MODEL == "sonnet"
    assert "ANTHROPIC_BASE_URL" not in pipeline._agent_subprocess_env()


def test_agent_sidecar_round_trip(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    pipeline.configure_agent(profile="kimi", model="kimi-for-coding")
    pipeline.write_agent_sidecars(ws)

    assert pipeline.read_agent_sidecars(ws) == ("kimi", "kimi-for-coding")
