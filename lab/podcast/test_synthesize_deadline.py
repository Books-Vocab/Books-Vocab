#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-genai",
#     "python-dotenv",
#     "pydub",
#     "audioop-lts",
#     "pytest",
# ]
# ///
"""Regression test: synthesize_batches must enforce TTS_BATCH_TIMEOUT wall-clock.

根因：舊碼 `as_completed(futures)` 無 timeout，且 client 無 http timeout，一個
卡死的 batch 會讓 as_completed 永久阻塞、`with ThreadPoolExecutor` 退出時 join
也跟著卡死，docstring 宣稱的 per-batch wall-clock cap 形同虛設。本測試以一個
睡眠超過 timeout 的 batch 驗證：函式必須在 timeout 內回收、把卡住的 batch 標為
stuck 並 raise，而非等到睡眠結束。
"""
import time

import pytest

import synthesize


def _batch(text: str):
    return [{"speaker": "Speaker1", "text": text}]


def test_stuck_batch_fails_within_wallclock(monkeypatch):
    monkeypatch.setattr(synthesize, "TTS_BATCH_TIMEOUT", 1)

    def stub(client, speech_config, prompt, index, total,
             batch_words, turns_count, cache_path, episode_label):
        if index == 2:
            time.sleep(8)  # >> timeout：模擬卡死的 Gemini 呼叫
        return index, object()

    monkeypatch.setattr(synthesize, "_synthesize_one", stub)

    batches = [_batch("alpha"), _batch("bravo stuck"), _batch("charlie")]

    t0 = time.time()
    with pytest.raises(RuntimeError, match=r"\b2\b"):
        synthesize.synthesize_batches(
            client=None,
            speech_config=None,
            system_instructions="sys",
            batches=batches,
            cache_dir=None,
            episode_label="Test",
        )
    elapsed = time.time() - t0
    # 必須在 wall-clock cap 內回收，而非等滿 8s 睡眠
    assert elapsed < synthesize.TTS_BATCH_TIMEOUT + 2.5, (
        f"synthesize_batches hung {elapsed:.1f}s — wall-clock cap not enforced"
    )
