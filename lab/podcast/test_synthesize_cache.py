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
"""Regression tests for #2096: TTS cache freshness.

根因:batch cache 只以 batch 序號命名(`batch_NN.wav`),檔案存在就重用,
不看文字、聲線或模型;episode 層 main() 只要輸出音檔存在就 SKIP。改稿後
dashboard rerun synthesize 回報成功卻什麼都沒變;刪掉 m4a 也只會用舊 batch
重組舊音訊,字幕再把新文字對齊到舊音訊上。

修法契約(這裡逐條釘死):
- batch cache key = hash(送進 API 的 prompt(system prompt + 對白) + 兩個
  voice + TTS_MODEL),只有內容變了的 batch 才打 API。
- episode 只在 `.meta.json` 的 synthesis fingerprint 與當前輸入一致時 SKIP;
  缺 fingerprint(舊 sidecar)或不一致 → 重新生成,並作廢衍生的 `.srt`。

測試替身是 fake genai client:記錄每次 generate_content 的 prompt,回傳靜音
PCM。走真的 `_generate_with_retry` → `_synthesize_one` → cache 路徑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydub import AudioSegment

import synthesize


# ─── fake TTS client ───


class _Part:
    def __init__(self, data: bytes, mime: str) -> None:
        self.inline_data = type("D", (), {"data": data, "mime_type": mime})()


class _Cand:
    def __init__(self, parts: list[_Part]) -> None:
        self.content = type("C", (), {"parts": parts})()


class _Response:
    def __init__(self, audio: bytes) -> None:
        self.candidates = [_Cand([_Part(audio, "audio/L16;rate=24000")])]
        self.usage_metadata = None


class FakeClient:
    """Stands in for genai.Client: `client.models.generate_content(...)`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.models = self

    def generate_content(self, *, model, contents, config):  # noqa: ARG002
        self.calls.append({"model": model, "prompt": contents})
        # 200 ms of 16-bit mono PCM silence @ 24 kHz.
        return _Response(b"\x00\x00" * 4800)


def _turn(speaker: str, text: str) -> dict[str, str]:
    return {"speaker": speaker, "text": text}


_BATCHES = [
    [_turn("Speaker1", "Welcome back to the show, today we read slowly.")],
    [_turn("Speaker2", "I brought three questions about the second chapter.")],
    [_turn("Speaker1", "Then let us start with the hardest question first.")],
]


@pytest.fixture
def tts(monkeypatch):
    """Deterministic module state; monkeypatch restores every global after."""
    monkeypatch.setattr(synthesize, "TTS_MODEL", "gemini-2.5-flash-tts")
    monkeypatch.setattr(synthesize, "VOICE_SPEAKER1", "Puck")
    monkeypatch.setattr(synthesize, "VOICE_SPEAKER2", "Charon")
    monkeypatch.setattr(synthesize, "OUTPUT_FORMAT", "wav")
    monkeypatch.setattr(synthesize, "MASTER_ENABLED", False)
    monkeypatch.setattr(synthesize, "MAX_WORDS_PER_BATCH", 12)
    monkeypatch.setattr(synthesize, "_EVENTS_WORKSPACE", None)
    client = FakeClient()
    monkeypatch.setattr(synthesize, "build_client", lambda: client)
    return client


def _synth(client: FakeClient, cache_dir: Path, batches, system: str = "sys") -> None:
    synthesize.synthesize_batches(
        client=client,
        speech_config=None,
        system_instructions=system,
        batches=batches,
        cache_dir=cache_dir,
        episode_label="Test",
    )


# ─── batch-level cache key ───


def test_changed_turn_resynthesizes_only_that_batch(tts, tmp_path):
    cache = tmp_path / "cache"
    _synth(tts, cache, _BATCHES)
    assert len(tts.calls) == 3

    edited = [list(b) for b in _BATCHES]
    edited[1] = [
        _turn("Speaker2", "I brought four questions about the second chapter.")
    ]
    tts.calls.clear()
    _synth(tts, cache, edited)

    assert len(tts.calls) == 1, (
        f"expected exactly the edited batch to hit the API, got {len(tts.calls)} calls "
        "— batch cache is not keyed by content"
    )
    assert "four questions" in tts.calls[0]["prompt"]


@pytest.mark.parametrize(
    "attr,value",
    [
        ("VOICE_SPEAKER1", "Kore"),
        ("VOICE_SPEAKER2", "Fenrir"),
        ("TTS_MODEL", "gemini-3.1-flash-tts-preview"),
    ],
)
def test_voice_or_model_change_resynthesizes_every_batch(
    tts, tmp_path, monkeypatch, attr, value
):
    cache = tmp_path / "cache"
    _synth(tts, cache, _BATCHES)
    tts.calls.clear()

    monkeypatch.setattr(synthesize, attr, value)
    _synth(tts, cache, _BATCHES)

    assert len(tts.calls) == 3, (
        f"{attr} change reused stale batches ({len(tts.calls)}/3 calls)"
    )


def test_system_prompt_change_resynthesizes_every_batch(tts, tmp_path):
    cache = tmp_path / "cache"
    _synth(tts, cache, _BATCHES, system="sys v1")
    tts.calls.clear()

    _synth(tts, cache, _BATCHES, system="sys v2")

    assert len(tts.calls) == 3


def test_unchanged_batches_reuse_cache(tts, tmp_path):
    cache = tmp_path / "cache"
    _synth(tts, cache, _BATCHES)
    tts.calls.clear()

    _synth(tts, cache, _BATCHES)

    assert tts.calls == []


def test_legacy_index_named_cache_is_not_reused_and_is_pruned(tts, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    for i in range(1, 4):
        AudioSegment.silent(duration=50).export(
            str(cache / f"batch_{i:02d}.wav"), format="wav"
        )

    _synth(tts, cache, _BATCHES)

    assert len(tts.calls) == 3, (
        "index-named legacy batch audio has unknown content and must not be reused"
    )
    assert not list(cache.glob("batch_0?.wav")), (
        "legacy cache files survived a successful synthesis"
    )


def test_interrupted_cache_write_leaves_no_partial_batch(tts, tmp_path, monkeypatch):
    def boom(self, out, *a, **kw):
        with open(out, "wb") as f:
            f.write(b"RIFFtrunc")
        raise OSError("simulated SIGKILL mid-export")

    monkeypatch.setattr(AudioSegment, "export", boom)
    cache_path = tmp_path / "cache" / "batch_x.wav"

    with pytest.raises(OSError):
        synthesize._synthesize_one(
            tts, None, "prompt", 1, 1, 1, 1, cache_path=cache_path, episode_label="Test"
        )

    assert not cache_path.exists(), (
        "a truncated batch wav would be reused as cached audio"
    )


# ─── episode-level skip (main) ───


_SCRIPT_TURNS = [
    ("Maya", "Welcome back to the show, today we read slowly."),
    ("Kai", "I brought three questions about the second chapter."),
    ("Maya", "Then let us start with the hardest question first."),
]


def _write_overview(ws: Path, voice1: str = "Puck", voice2: str = "Charon") -> None:
    (ws / "plan" / "overview.md").write_text(
        "### Voice Mapping\n"
        f"- **Maya ({voice1})**: Speaker1\n"
        f"- **Kai ({voice2})**: Speaker2\n",
        encoding="utf-8",
    )


def _write_script(ws: Path, turns=_SCRIPT_TURNS) -> Path:
    script = ws / "scripts" / "ep_1_script.md"
    lines = ["# Episode 1", ""] + [f"**{name}:** {text}" for name, text in turns]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "plan").mkdir(parents=True)
    (ws / "scripts").mkdir()
    _write_overview(ws)
    _write_script(ws)
    # main() reassigns the voice globals from overview.md; register them with
    # monkeypatch so the reassignment is undone after the test.
    monkeypatch.setattr(synthesize, "VOICE_SPEAKER1", "")
    monkeypatch.setattr(synthesize, "VOICE_SPEAKER2", "")
    return ws


def _run_main(monkeypatch, ws: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["synthesize.py", str(ws / "scripts")])
    synthesize.main()


def _meta(ws: Path) -> dict:
    return json.loads(
        (ws / "scripts" / "ep_1_flash.meta.json").read_text(encoding="utf-8")
    )


def test_unchanged_rerun_skips_episode(tts, workspace, monkeypatch, capsys):
    _run_main(monkeypatch, workspace)
    assert len(tts.calls) == 3
    tts.calls.clear()

    _run_main(monkeypatch, workspace)

    assert tts.calls == []
    assert "SKIP ep_1_script" in capsys.readouterr().out


def test_edited_script_regenerates_episode_with_only_changed_batch(
    tts, workspace, monkeypatch
):
    _run_main(monkeypatch, workspace)
    before = _meta(workspace)
    tts.calls.clear()

    turns = list(_SCRIPT_TURNS)
    turns[1] = ("Kai", "I brought four questions about the second chapter.")
    _write_script(workspace, turns)
    _run_main(monkeypatch, workspace)

    assert len(tts.calls) == 1, (
        f"edited script must regenerate the episode via the one changed batch, got "
        f"{len(tts.calls)} API calls — episode was silently skipped"
    )
    assert "four questions" in tts.calls[0]["prompt"]
    after = _meta(workspace)
    assert after["synthesis_fingerprint"] != before["synthesis_fingerprint"]
    assert after["script_sha256"] != before["script_sha256"]


def test_voice_change_in_overview_regenerates_every_batch(tts, workspace, monkeypatch):
    _run_main(monkeypatch, workspace)
    tts.calls.clear()

    _write_overview(workspace, voice1="Kore")
    _run_main(monkeypatch, workspace)

    assert len(tts.calls) == 3
    assert _meta(workspace)["voices"] == {"Speaker1": "Kore", "Speaker2": "Charon"}


def test_model_change_with_same_filename_tag_regenerates(tts, workspace, monkeypatch):
    _run_main(monkeypatch, workspace)
    tts.calls.clear()

    # Both ids collapse to the `_flash` filename tag → same output path.
    monkeypatch.setattr(synthesize, "TTS_MODEL", "gemini-3.1-flash-tts-preview")
    _run_main(monkeypatch, workspace)

    assert len(tts.calls) == 3
    assert _meta(workspace)["tts_model"] == "gemini-3.1-flash-tts-preview"


def test_legacy_sidecar_without_fingerprint_regenerates(tts, workspace, monkeypatch):
    scripts = workspace / "scripts"
    AudioSegment.silent(duration=50).export(
        str(scripts / "ep_1_flash.wav"), format="wav"
    )
    (scripts / "ep_1_flash.meta.json").write_text(
        json.dumps({"tts_model": "gemini-2.5-flash-tts"}) + "\n", encoding="utf-8"
    )

    _run_main(monkeypatch, workspace)

    assert len(tts.calls) == 3, (
        "pre-fingerprint audio cannot be verified fresh — must not SKIP"
    )
    assert _meta(workspace)["synthesis_fingerprint"]


def test_regeneration_invalidates_stale_subtitle(tts, workspace, monkeypatch):
    _run_main(monkeypatch, workspace)
    srt = workspace / "scripts" / "ep_1_flash.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nold\n", encoding="utf-8")

    _run_main(monkeypatch, workspace)  # unchanged → SKIP keeps the subtitle
    assert srt.exists()

    turns = list(_SCRIPT_TURNS)
    turns[2] = ("Maya", "Then let us start with the easiest question first.")
    _write_script(workspace, turns)
    _run_main(monkeypatch, workspace)

    assert not srt.exists(), (
        "subtitle aligned to the replaced audio must be invalidated"
    )
