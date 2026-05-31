"""Saga CLI argument-validation + post-prep marker-guard tests.

The marker guard is the deterministic backstop for the one LLM-trust point in the
saga flow (prep copying the saga_book comment). CLI validation tests cover the
--saga / multi-target argument surface without needing real EPUBs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pipeline

HERE = Path(__file__).parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HERE / "pipeline.py"), *args],
        capture_output=True, text=True, cwd=HERE,
    )


# ─── Marker guard (deterministic) ───


def _make_saga_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "saga_ws"
    (ws / "source" / "chapters").mkdir(parents=True)
    (ws / "series.md").write_text("# Saga\n<!-- READING_ORDER:START -->\n<!-- READING_ORDER:END -->\n")
    return ws


def test_marker_coverage_all_present(tmp_path: Path) -> None:
    ws = _make_saga_ws(tmp_path)
    for i in (1, 2, 3):
        (ws / "source" / "chapters" / f"ch_{i:02d}.md").write_text(
            f"<!-- saga_book: {i} (0{i}_x) -->\n# Chapter {i}\nbody"
        )
    assert pipeline.check_saga_marker_coverage(ws) == []


def test_marker_coverage_detects_missing(tmp_path: Path) -> None:
    ws = _make_saga_ws(tmp_path)
    (ws / "source" / "chapters" / "ch_01.md").write_text("<!-- saga_book: 1 (01_x) -->\n# Chapter 1")
    (ws / "source" / "chapters" / "ch_02.md").write_text("# Chapter 2\nno marker here")  # dropped
    assert pipeline.check_saga_marker_coverage(ws) == ["ch_02.md"]


def test_is_saga_detection(tmp_path: Path) -> None:
    single = tmp_path / "single"
    single.mkdir()
    assert not pipeline.is_saga(single)
    saga_ws = _make_saga_ws(tmp_path)
    assert pipeline.is_saga(saga_ws)


# ─── CLI argument validation (no EPUB needed — these all parser.error early) ───


def test_saga_requires_two_epubs(tmp_path: Path) -> None:
    fake = tmp_path / "a.epub"
    fake.write_text("x")
    r = _run(str(fake), "--saga", "Mistborn", "--spoiler-mode", "readalong")
    assert r.returncode == 2
    assert "at least 2 EPUBs" in r.stderr


def test_saga_conflicting_mode_rejected(tmp_path: Path) -> None:
    a, b = tmp_path / "a.epub", tmp_path / "b.epub"
    a.write_text("x"); b.write_text("y")
    r = _run(str(a), str(b), "--saga", "Mistborn", "--mode", "fiction", "--spoiler-mode", "readalong")
    assert r.returncode == 2
    assert "--saga implies --mode saga" in r.stderr


def test_multi_target_without_saga_rejected(tmp_path: Path) -> None:
    a, b = tmp_path / "a.epub", tmp_path / "b.epub"
    a.write_text("x"); b.write_text("y")
    r = _run(str(a), str(b))
    assert r.returncode == 2
    assert "only allowed with --saga" in r.stderr


def test_saga_nonepub_target_rejected(tmp_path: Path) -> None:
    a = tmp_path / "a.epub"
    b = tmp_path / "b.txt"
    a.write_text("x"); b.write_text("y")
    r = _run(str(a), str(b), "--saga", "Mistborn", "--spoiler-mode", "readalong")
    assert r.returncode == 2
    assert "must be EPUB" in r.stderr
