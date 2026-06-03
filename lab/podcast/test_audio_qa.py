#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pydub",
#     "audioop-lts",
#     "pytest",
# ]
# ///
"""Resilience tests for audio_qa.analyze — a single corrupt/undecodable file
must yield a FAIL verdict instead of aborting the whole batch."""

from __future__ import annotations

from pathlib import Path

import pytest

import audio_qa


def test_corrupt_file_yields_fail_verdict_not_raise(tmp_path: Path):
    """A 0-byte / non-audio file must NOT raise — analyze returns verdict=FAIL.

    audio_qa exists precisely to catch broken renders; a file pydub can't even
    decode is the most broken render of all and must be reported, not crash."""
    bad = tmp_path / "ep_1_pro.mp3"
    bad.write_bytes(b"")  # 0-byte: pydub.AudioSegment.from_file raises

    r = audio_qa.analyze(bad)  # must not raise

    assert r["verdict"] == "FAIL"
    assert r["file"] == "ep_1_pro.mp3"
    assert any(level == "FAIL" for level, _ in r["findings"])
    assert any("decode" in msg.lower() for _, msg in r["findings"])
    # safe defaults so downstream printing / report writing never KeyErrors
    assert r["duration_s"] == 0
    assert r["word_count"] == 0
    assert r["wpm"] == 0
    assert r["long_silence_count"] == 0


def test_corrupt_file_does_not_abort_batch(tmp_path: Path, monkeypatch, capsys):
    """main() over a dir containing one bad file completes, writes a report,
    counts the bad file as FAIL, and exits 1 (FAIL present)."""
    bad = tmp_path / "ep_1_pro.mp3"
    bad.write_bytes(b"not an mp3")
    report = tmp_path / "report.json"

    monkeypatch.setattr(
        "sys.argv",
        ["audio_qa.py", str(tmp_path), "--report", str(report)],
    )
    with pytest.raises(SystemExit) as exc:
        audio_qa.main()
    assert exc.value.code == 1  # FAIL present

    import json
    data = json.loads(report.read_text())
    assert data["summary"]["fail"] == 1
    assert data["results"][0]["verdict"] == "FAIL"
