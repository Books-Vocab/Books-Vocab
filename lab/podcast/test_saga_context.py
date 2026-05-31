"""build_saga_context injection tests — the book-aware/spoiler-horizon glue."""

from __future__ import annotations

from pathlib import Path

import pipeline
import saga


def _saga_ws(tmp_path: Path, spoiler: str | None) -> Path:
    ws = tmp_path / "ws"
    (ws / "source" / "chapters").mkdir(parents=True)
    books = saga.plan_books([
        {"title": "The Final Empire", "author": "BS"},
        {"title": "The Well of Ascension", "author": "BS"},
    ])
    (ws / "series.md").write_text(saga.render_series_manifest("Mistborn", books))
    if spoiler:
        (ws / ".spoiler_mode").write_text(spoiler)
    return ws


def test_single_book_context_is_empty(tmp_path: Path) -> None:
    ws = tmp_path / "single"
    ws.mkdir()
    assert pipeline.build_saga_context(ws) == ""


def test_readalong_context_has_strict_policy(tmp_path: Path) -> None:
    ws = _saga_ws(tmp_path, "readalong")
    ctx = pipeline.build_saga_context(ws)
    assert "SAGA CONTEXT" in ctx
    assert "readalong" in ctx
    assert "index > K" in ctx  # strict horizon language
    assert "The Final Empire" in ctx and "The Well of Ascension" in ctx
    # continuous numbering instruction present
    assert "CONTINUOUS" in ctx


def test_retrospective_context_allows_crossref(tmp_path: Path) -> None:
    ws = _saga_ws(tmp_path, "retrospective")
    ctx = pipeline.build_saga_context(ws)
    assert "retrospective" in ctx
    assert "cross-reference" in ctx
    assert "index > K" not in ctx  # no strict-horizon clause in retrospective


def test_defaults_to_readalong_when_sidecar_missing(tmp_path: Path) -> None:
    ws = _saga_ws(tmp_path, None)  # no .spoiler_mode → safest default
    ctx = pipeline.build_saga_context(ws)
    assert "readalong" in ctx


def test_context_injects_via_token_only_for_saga(tmp_path: Path) -> None:
    # The base prompts carry a literal {saga_context} token; run_claude replaces
    # it. Here we just confirm a single-book workspace yields empty injection so
    # the token vanishes (base prompt unchanged).
    single = tmp_path / "s"
    single.mkdir()
    assert pipeline.build_saga_context(single) == ""
