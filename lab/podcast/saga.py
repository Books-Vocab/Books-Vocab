"""Saga layout — group multiple EPUBs into ONE continuous-feed workspace.

A saga (a trilogy, a complete series) must NOT become N disconnected single-book
workspaces: that re-invents the hosts per book, re-explains the world, and — worst
— spoils book K+1 while discussing book K. The saga layout solves the structural
half of that problem (the prompt/agent half comes in later phases):

    workspaces/<saga_slug>_<saga_hash>/          ← ONE workspace, one feed
      series.md                                   ← series manifest (reading order + horizon)
      books/
        01_<book_slug>/                           ← per-book sub-workspace, reading-order prefixed
          source/ raw_chapters/ ...               ← same layout a single book has
        02_<book_slug>/
        03_<book_slug>/
      plan/ scripts/ ...                          ← series-level plan + the unified episode feed

The reading order is the spine. Episodes number continuously across the whole
saga (Book 1 = EP1..n, Book 2 continues at EP n+1, ...), and the cross-book
spoiler horizon is "everything from book index > current book is off-limits in
readalong mode". `series.md` is the single source of truth both facts come from.

This module is deliberately PURE: it plans the layout and renders the manifest
from already-extracted metadata. Disk I/O and EPUB parsing live in pipeline.py,
so the planning logic stays unit-testable without fixtures or tokens.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


def _sanitize_slug(text: str, max_len: int = 30) -> str:
    """Lowercase → collapse non-alphanumerics to `_` → trim → cap length.

    Mirrors pipeline._sanitize_slug so saga slugs satisfy the same backend
    ``^[a-z0-9_]+$`` series_id contract that single-book slugs do.
    """
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s or "untitled"


@dataclass(frozen=True)
class BookEntry:
    """One book's place in the saga's reading order (1-based index)."""

    index: int
    title: str
    author: str
    slug: str  # reading-order-prefixed dir name, e.g. "01_the_final_empire"


def saga_slug(saga_title: str) -> str:
    return _sanitize_slug(saga_title)


def saga_dirname(saga_title: str, book_titles: list[str]) -> str:
    """Deterministic saga workspace dir name: ``<slug>_<hash>``.

    The hash binds the saga identity to its EXACT ordered book set, so adding a
    book or reordering produces a distinct workspace (no silent cross-contamination
    with a previously-built partial saga). Order is part of identity.
    """
    payload = saga_title + "||" + "||".join(book_titles)
    h = hashlib.md5(payload.encode()).hexdigest()[:8]
    return f"{saga_slug(saga_title)}_{h}"


def plan_books(book_metas: list[dict]) -> list[BookEntry]:
    """Assign reading-order indices + prefixed slugs to extracted book metadata.

    `book_metas` is an ordered list (reading order = list order) of dicts with at
    least ``title`` and ``author`` keys (as produced by pipeline.extract_epub).
    The reading-order prefix (01_, 02_, ...) makes the directory sort match the
    listen order and makes "book N" unambiguous for the spoiler horizon.
    """
    if not book_metas:
        raise ValueError("a saga needs at least one book")
    entries: list[BookEntry] = []
    for i, meta in enumerate(book_metas, 1):
        title = meta["title"]
        slug = f"{i:02d}_{_sanitize_slug(title)}"
        entries.append(BookEntry(index=i, title=title, author=meta["author"], slug=slug))
    return entries


def render_series_manifest(saga_title: str, books: list[BookEntry]) -> str:
    """Render ``series.md`` — the reading-order + spoiler-horizon source of truth.

    Machine-parseable: the reading-order table is wrapped in
    ``<!-- READING_ORDER:START/END -->`` markers and each row is
    ``| <index> | <slug> | <title> | <author> |`` so downstream code (and tests)
    can recover the ordered book set without re-parsing EPUBs.
    """
    lines = [
        f"# {saga_title}",
        "",
        "> Multi-book saga rendered as one continuous podcast feed.",
        "",
        "## Reading Order",
        "",
        "Episodes number continuously across books in this order. In readalong "
        "spoiler mode, any book with a higher index is OFF-LIMITS until the feed "
        "reaches it — never reveal a later book's events while discussing an "
        "earlier one.",
        "",
        "<!-- READING_ORDER:START -->",
        "| # | Dir | Title | Author |",
        "|---|-----|-------|--------|",
    ]
    for b in books:
        lines.append(f"| {b.index} | {b.slug} | {b.title} | {b.author} |")
    lines.append("<!-- READING_ORDER:END -->")
    lines.append("")
    return "\n".join(lines)


_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_BLOCK_RE = re.compile(
    r"<!--\s*READING_ORDER:START\s*-->(.*?)<!--\s*READING_ORDER:END\s*-->", re.DOTALL
)


def parse_series_manifest(text: str) -> list[BookEntry]:
    """Recover the ordered book list from a ``series.md`` body.

    Inverse of `render_series_manifest`. Used by resume + the spoiler-horizon
    logic so reading order is read from disk, never re-derived from argv order.
    """
    block = _BLOCK_RE.search(text)
    if not block:
        raise ValueError("series.md missing READING_ORDER markers")
    entries: list[BookEntry] = []
    for m in _ROW_RE.finditer(block.group(1)):
        idx, slug, title, author = m.groups()
        entries.append(
            BookEntry(index=int(idx), title=title.strip(), author=author.strip(), slug=slug.strip())
        )
    if not entries:
        raise ValueError("series.md reading-order table is empty")
    # Reading order must be a contiguous 1..N with no gaps/dupes — else the
    # spoiler horizon ("books after index k") would be ill-defined.
    indices = [e.index for e in entries]
    if indices != list(range(1, len(entries) + 1)):
        raise ValueError(f"reading order is not contiguous 1..N: {indices}")
    return entries


def spoiler_horizon_books(books: list[BookEntry], current_index: int) -> list[BookEntry]:
    """Books that are OFF-LIMITS when discussing the book at `current_index`
    under readalong spoiler mode — i.e. every later book in reading order."""
    return [b for b in books if b.index > current_index]


@dataclass(frozen=True)
class FlatChapter:
    """One source chapter in the saga's continuous, cross-book numbering."""

    seq: int  # 1-based position across the WHOLE saga
    book_index: int  # which book (reading order) it belongs to
    book_slug: str
    name: str  # original in-book section name (provenance)
    text: str


def flatten_chapters(
    books: list[BookEntry], per_book_chapters: list[list[tuple[str, str]]]
) -> list[FlatChapter]:
    """Map per-book chapter lists onto ONE continuous saga-wide sequence.

    `books` is the reading order (from `plan_books`); `per_book_chapters[i]` is
    book i's ``[(name, text), ...]`` as produced by extract_epub, in the SAME
    order as `books`. Returns a flat list whose `seq` runs 1..N across all books
    — so the existing single-book prep/analyst stages, which expect a flat
    `raw_chapters/`, work unchanged on a saga while each chapter still records
    which book it came from (the book boundary the spoiler horizon needs).
    """
    if len(books) != len(per_book_chapters):
        raise ValueError(
            f"books ({len(books)}) and per_book_chapters ({len(per_book_chapters)}) length mismatch"
        )
    flat: list[FlatChapter] = []
    seq = 1
    for book, chapters in zip(books, per_book_chapters):
        for name, text in chapters:
            flat.append(
                FlatChapter(
                    seq=seq, book_index=book.index, book_slug=book.slug,
                    name=name, text=text,
                )
            )
            seq += 1
    return flat


def render_chapter_map(flat: list[FlatChapter]) -> str:
    """Render the chapter→book boundary map appended to series.md.

    Gives the architect the book boundaries in the flattened raw-chapter
    numbering. NOTE: prep drops front/back matter and may split oversized
    chapters, so these RAW ranges shift after cleaning — they are an initial
    guide, NOT a post-prep guarantee. The durable per-chapter signal is the
    `<!-- saga_book: N -->` comment prep copies onto each cleaned ch_NN.md; the
    architect should trust that marker over these raw ranges when they disagree.
    """
    bounds = book_boundaries(flat)
    lines = [
        "",
        "## Chapter Map (flattened raw_chapters → book)",
        "",
        "Book boundaries in the ORIGINAL raw_ch numbering. prep preserves the "
        "per-chapter `<!-- saga_book: N -->` marker, which is authoritative after "
        "cleaning; these raw ranges are the pre-prep guide. Use book membership "
        "to keep episodes within book boundaries and enforce the reading-order "
        "spoiler horizon (later books off-limits in readalong).",
        "",
        "<!-- CHAPTER_MAP:START -->",
        "| Book | Raw chapter range |",
        "|------|-------------------|",
    ]
    for idx in sorted(bounds):
        lo, hi = bounds[idx]
        lines.append(f"| {idx} | raw_ch_{lo:02d}–raw_ch_{hi:02d} |")
    lines.append("<!-- CHAPTER_MAP:END -->")
    lines.append("")
    return "\n".join(lines)


def book_boundaries(flat: list[FlatChapter]) -> dict[int, tuple[int, int]]:
    """Map each book_index → (first_seq, last_seq) in the flat numbering.

    This is what `architect` needs to know where one book ends and the next
    begins in the continuous chapter stream, and what the spoiler horizon uses to
    bound "chapters belonging to later books."
    """
    bounds: dict[int, tuple[int, int]] = {}
    for fc in flat:
        lo, hi = bounds.get(fc.book_index, (fc.seq, fc.seq))
        bounds[fc.book_index] = (min(lo, fc.seq), max(hi, fc.seq))
    return bounds
