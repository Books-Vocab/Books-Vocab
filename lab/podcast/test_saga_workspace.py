"""setup_saga_workspace disk-layout test — no real EPUBs needed."""

from __future__ import annotations

import pipeline
import saga


def _book(title: str, n_ch: int = 2) -> tuple[dict, list[tuple[str, str]]]:
    meta = {
        "title": title,
        "author": "Brandon Sanderson",
        "language": "en",
        "total_raw_chapters": n_ch,
        "total_raw_chars": n_ch * 100,
    }
    chapters = [(f"c{i}.xhtml", f"body of {title} chapter {i} " * 10) for i in range(n_ch)]
    return meta, chapters


def test_setup_saga_workspace_builds_grouped_layout(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", tmp_path)
    books = [_book("The Final Empire"), _book("The Well of Ascension"), _book("The Hero of Ages")]
    ws = pipeline.setup_saga_workspace("Mistborn", books)

    assert ws.parent == tmp_path
    assert ws.name.startswith("mistborn_")

    # series.md round-trips to the right reading order.
    entries = saga.parse_series_manifest((ws / "series.md").read_text())
    assert [e.title for e in entries] == [
        "The Final Empire", "The Well of Ascension", "The Hero of Ages"
    ]

    # Each book has its reading-order-prefixed source dir with raw chapters.
    assert (ws / "books" / "01_the_final_empire" / "source" / "metadata.md").exists()
    assert (ws / "books" / "03_the_hero_of_ages" / "raw_chapters" / "raw_ch_01.md").exists()

    # Series-level plan/scripts dirs exist for the unified feed.
    assert (ws / "plan" / "episodes").is_dir()
    assert (ws / "scripts").is_dir()
    assert (ws / "log.md").exists()

    # Approach B: flattened root raw_chapters/ with continuous numbering, so the
    # existing single-book prep/analyst stages run unchanged. 3 books × 2 ch = 6.
    raw = sorted((ws / "raw_chapters").glob("raw_ch_*.md"))
    assert [p.name for p in raw] == [f"raw_ch_{i:02d}.md" for i in range(1, 7)]
    # Each flattened chapter records its source book for boundary preservation.
    assert "<!-- saga_book: 1 (01_the_final_empire) -->" in raw[0].read_text()
    assert "<!-- saga_book: 3 (03_the_hero_of_ages) -->" in raw[5].read_text()
    # Root metadata.md + chapter map exist for prep/analyst/architect.
    assert (ws / "source" / "metadata.md").read_text().startswith("# Mistborn")
    assert "<!-- CHAPTER_MAP:START -->" in (ws / "series.md").read_text()


def test_setup_saga_workspace_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", tmp_path)
    books = [_book("The Final Empire"), _book("The Well of Ascension")]
    ws1 = pipeline.setup_saga_workspace("Mistborn", books)
    ws2 = pipeline.setup_saga_workspace("Mistborn", books)
    assert ws1 == ws2  # same ordered book set → same workspace


def test_metadata_md_matches_single_book_format(tmp_path, monkeypatch) -> None:
    # A saga book's metadata.md must look like a single book's so the existing
    # prep/analyst prompts can consume it unchanged.
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", tmp_path)
    ws = pipeline.setup_saga_workspace("Mistborn", [_book("The Final Empire")])
    md = (ws / "books" / "01_the_final_empire" / "source" / "metadata.md").read_text()
    assert md.startswith("# The Final Empire")
    assert "- **Author**: Brandon Sanderson" in md
    assert "- **Raw chapters**: 2" in md
