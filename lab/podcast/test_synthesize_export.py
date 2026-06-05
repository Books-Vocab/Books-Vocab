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
"""Regression tests for combine_and_export atomicity + helper extraction.

根因(A):combine_and_export 直寫 output_path(master 路徑與 fallback export
皆然)。若 export 過程被 SIGKILL/OOM/Ctrl-C 中斷,output_path 會留下截斷或
0-byte 檔。main() resume 以 out.exists() 判斷「已完成」→ skip → 截斷音檔直送
publish。修法:全部寫到同目錄 .part temp,最後 os.replace 原子搬入 output_path。

(B):_model_tag helper — process_file 與 _output_path_for 原本逐字複製推導。
(C):_generate_with_retry backoff 分類 + usage 事件 emit 兩路覆蓋。
"""
import pytest

import synthesize
from pydub import AudioSegment


def _seg(ms: int = 100) -> AudioSegment:
    return AudioSegment.silent(duration=ms)


# ─── A. atomic export ───


def test_export_interrupt_leaves_no_truncated_final(monkeypatch, tmp_path):
    """若 export 寫入後爆掉,output_path 不可存在(原子性)。

    否則 main() resume 會把截斷檔當完成 skip,直送 publish。
    """
    # 走 fallback (非 master) 路徑,確定性最高
    monkeypatch.setattr(synthesize, "MASTER_ENABLED", False)
    monkeypatch.setattr(synthesize, "OUTPUT_FORMAT", "wav")

    def boom(self, out, *a, **kw):
        # 模擬:檔已被部分寫出後,程序被打斷
        with open(out, "wb") as f:
            f.write(b"RIFFtrunc")  # 截斷垃圾
        raise OSError("simulated SIGKILL mid-export")

    monkeypatch.setattr(AudioSegment, "export", boom)

    output_path = tmp_path / "ep_1_flash.wav"
    with pytest.raises(OSError):
        synthesize.combine_and_export([_seg()], output_path)

    assert not output_path.exists(), (
        "中斷的 export 留下了終檔 — resume 會誤判已完成並 publish 截斷音檔"
    )


def test_export_success_produces_final(monkeypatch, tmp_path):
    monkeypatch.setattr(synthesize, "MASTER_ENABLED", False)
    monkeypatch.setattr(synthesize, "OUTPUT_FORMAT", "wav")

    output_path = tmp_path / "ep_2_flash.wav"
    synthesize.combine_and_export([_seg(120)], output_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    # 不留 .part 殘檔
    assert not output_path.with_name(output_path.name + ".part").exists()


def test_export_master_path_atomic(monkeypatch, tmp_path):
    """master 成功路徑也必須原子搬入 output_path,且不留 .part。"""
    monkeypatch.setattr(synthesize, "MASTER_ENABLED", True)
    monkeypatch.setattr(synthesize, "OUTPUT_FORMAT", "wav")

    def fake_master(src_wav, dst):
        # _master_with_loudnorm 真實行為:把 ffmpeg 輸出寫到 dst
        AudioSegment.silent(duration=80).export(str(dst), format="wav")
        return True

    monkeypatch.setattr(synthesize, "_master_with_loudnorm", fake_master)

    output_path = tmp_path / "ep_3_pro.wav"
    synthesize.combine_and_export([_seg()], output_path)
    assert output_path.exists()
    assert not output_path.with_name(output_path.name + ".part").exists()


# ─── B. _model_tag helper ───


@pytest.mark.parametrize("model,expected", [
    ("gemini-2.5-pro-preview-tts", "pro"),
    ("gemini-2.5-flash-preview-tts", "flash"),
    ("gemini-3.1-pro", "pro"),
    ("weird-model", "model"),  # split("-")[1]
    ("nodash", "nodash"),
])
def test_model_tag(monkeypatch, model, expected):
    assert synthesize._model_tag(model) == expected


def test_model_tag_consistency_process_vs_output(monkeypatch, tmp_path):
    """process_file 與 _output_path_for 對同一 model 必須給出相同 tag。"""
    monkeypatch.setattr(synthesize, "TTS_MODEL", "gemini-2.5-flash-preview-tts")
    monkeypatch.setattr(synthesize, "OUTPUT_FORMAT", "m4a")
    script = tmp_path / "ep_5_script.md"
    script.write_text("**Speaker1:** hi\n", encoding="utf-8")
    assert synthesize._output_path_for(script).name == "ep_5_flash.m4a"


# ─── C. retry backoff classification ───


class _FakeErr(Exception):
    def __init__(self, code):
        super().__init__(f"err {code}")
        self.code = code


def test_retry_429_uses_quota_reset_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(synthesize.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(synthesize, "TTS_RETRY_ATTEMPTS", 3)

    calls = {"n": 0}

    class Client:
        class models:
            @staticmethod
            def generate_content(**kw):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise _FakeErr(429)
                return "ok"

    out = synthesize._generate_with_retry(Client(), "p", None, index=1)
    assert out == "ok"
    # 429 → ≥60s quota-reset backoff,非指數退避
    assert all(s >= 60 for s in sleeps), sleeps
    assert len(sleeps) == 2


def test_retry_504_uses_exponential_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(synthesize.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(synthesize, "TTS_RETRY_ATTEMPTS", 3)

    calls = {"n": 0}

    class Client:
        class models:
            @staticmethod
            def generate_content(**kw):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise _FakeErr(504)
                return "ok"

    out = synthesize._generate_with_retry(Client(), "p", None, index=1)
    assert out == "ok"
    # 504 走指數退避:每次 < 60s(明顯區別於 429)
    assert all(s < 60 for s in sleeps), sleeps


def test_retry_reraises_on_last_attempt(monkeypatch):
    monkeypatch.setattr(synthesize.time, "sleep", lambda s: None)
    monkeypatch.setattr(synthesize, "TTS_RETRY_ATTEMPTS", 2)

    class Client:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise _FakeErr(503)

    with pytest.raises(_FakeErr):
        synthesize._generate_with_retry(Client(), "p", None, index=1)


def test_retry_non_transient_reraises_immediately(monkeypatch):
    slept = []
    monkeypatch.setattr(synthesize.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(synthesize, "TTS_RETRY_ATTEMPTS", 4)

    class Client:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise ValueError("400 bad request")  # 非 transient

    with pytest.raises(ValueError):
        synthesize._generate_with_retry(Client(), "p", None, index=1)
    assert slept == []  # 不重試、不睡眠


# ─── C. usage event emit (vertex vs estimated) ───


class _Part:
    def __init__(self, data, mime):
        self.inline_data = type("D", (), {"data": data, "mime_type": mime})()


class _Cand:
    def __init__(self, parts):
        self.content = type("C", (), {"parts": parts})()


def _make_response(audio_bytes, mime, usage_metadata=None):
    r = type("R", (), {})()
    r.candidates = [_Cand([_Part(audio_bytes, mime)])]
    r.usage_metadata = usage_metadata
    return r


def _pcm_silence_bytes(ms=200):
    # 16-bit mono PCM @ 24kHz silence
    n_samples = int(24000 * ms / 1000)
    return b"\x00\x00" * n_samples


def _capture_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        synthesize, "_emit_event",
        lambda label, payload: events.append((label, payload)),
    )
    return events


def test_usage_event_uses_vertex_tokens_when_present(monkeypatch):
    events = _capture_events(monkeypatch)
    um = type("UM", (), {
        "prompt_token_count": 123,
        "candidates_token_count": 456,
        "total_token_count": 579,
    })()
    resp = _make_response(_pcm_silence_bytes(), "audio/L16;rate=24000", um)
    monkeypatch.setattr(synthesize, "_generate_with_retry",
                        lambda *a, **k: resp)

    synthesize._synthesize_one(
        client=None, speech_config=None, prompt="hello prompt",
        index=1, total=1, batch_words=2, turns_count=1,
        cache_path=None, episode_label="EP1",
    )
    assert events, "no usage event emitted"
    _, payload = events[0]
    assert payload["type"] == "tts_usage"
    assert payload["input_tokens"] == 123
    assert payload["output_tokens"] == 456
    assert payload["total_tokens"] == 579
    assert payload["usage_source"] == "vertex_api"


def test_usage_event_falls_back_to_estimate_without_metadata(monkeypatch):
    events = _capture_events(monkeypatch)
    resp = _make_response(_pcm_silence_bytes(400), "audio/L16;rate=24000",
                          usage_metadata=None)
    monkeypatch.setattr(synthesize, "_generate_with_retry",
                        lambda *a, **k: resp)

    prompt = "x" * 40
    synthesize._synthesize_one(
        client=None, speech_config=None, prompt=prompt,
        index=1, total=1, batch_words=2, turns_count=1,
        cache_path=None, episode_label="EP1",
    )
    _, payload = events[0]
    assert payload["usage_source"] == "estimated"
    # input estimate = chars // 4
    assert payload["input_tokens"] == len(prompt) // 4
    # output estimate = audio_seconds * 25, > 0 for non-empty audio
    assert payload["output_tokens"] > 0
    assert payload["total_tokens"] is None
