"""Canonical book-genre taxonomy — single source of truth.

The pipeline reasons about a book's genre in three stages, which historically
each carried their OWN vocabulary and drifted apart:

- `prompts/architect.md` had an 8-row compression table (Fiction epic, Biography,
  Technical, ...) driving episode length / compression ratio.
- `prompts/scriptwriter.md` had only 4 "Genre-Specific Guidance" buckets
  (fiction, trauma, self-help, research) — so a Biography, a business book, or a
  technical manual fell through to generic craft with no tailored guidance, and a
  mystery got no spoiler discipline at all.

This module pins the taxonomy in ONE place and `test_genre_taxonomy_consistency.py`
asserts the architect table and the scriptwriter buckets/overlays stay aligned
with it — the same drift-guard pattern as `tts_tags` + `test_palette_consistency`.

Two orthogonal axes:

1. **GENRE → BUCKET** — every architect genre maps to exactly one scriptwriter
   writing-guidance bucket. Buckets are about *how to talk about this kind of
   book*; several genres can share one (all fiction shares `fiction-narrative`).

2. **OVERLAYS** — cross-cutting concerns that are NOT a function of genre and are
   triggered by analyst flags instead:
     - `spoiler`: twist/mystery/whodunit narrative → reveal discipline.
     - `trauma`: heavy clinical / abuse / violence content → content warnings,
       no second-person victim immersion, generous pauses.
   An overlay stacks ON TOP of the primary bucket (a literary novel about abuse
   is `fiction-narrative` + `trauma`).
"""

from __future__ import annotations

# Architect genre (lowercased table key) → scriptwriter guidance bucket.
GENRE_TO_BUCKET: dict[str, str] = {
    "fiction epic": "fiction-narrative",
    "fiction mystery": "fiction-narrative",
    "fiction literary": "fiction-narrative",
    "nonfiction self-help": "self-help-practical",
    "nonfiction business": "business",
    "nonfiction science": "research-academic",
    "biography": "biography",
    "technical": "technical",
}

# The full genre set the architect's compression table must enumerate.
GENRES: frozenset[str] = frozenset(GENRE_TO_BUCKET)

# The full bucket set the scriptwriter's guidance must define.
BUCKETS: frozenset[str] = frozenset(GENRE_TO_BUCKET.values())

# Cross-cutting overlays — triggered by analyst content/structure flags, applied
# on top of the primary bucket regardless of genre.
OVERLAYS: frozenset[str] = frozenset({"spoiler", "trauma"})
