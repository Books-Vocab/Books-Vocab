"""Genre-taxonomy drift guard.

The book-genre taxonomy is defined once in `genre_taxonomy` and consumed across
three prompt stages. This test asserts the prompts stay aligned with it, so the
8-vs-4 drift that left Biography / business / technical / mystery without tailored
scriptwriter guidance can never silently reappear.

Marker contract:

- `prompts/architect.md` wraps its compression table in
      <!-- GENRE_TYPES:START --> ... <!-- GENRE_TYPES:END -->
  and the first column of each data row is a canonical genre key.

- `prompts/scriptwriter.md` wraps its Genre-Specific Guidance in
      <!-- GENRE_GUIDANCE:START --> ... <!-- GENRE_GUIDANCE:END -->
  with one `#### Bucket: <bucket-id>` header per bucket and one
  `#### Overlay: <overlay-id>` header per overlay.

Any taxonomy edit must touch genre_taxonomy.py AND the prompts or this fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import genre_taxonomy

PROMPTS = Path(__file__).parent / "prompts"
ARCHITECT = PROMPTS / "architect.md"
SCRIPTWRITER = PROMPTS / "scriptwriter.md"

_TYPES_BLOCK = re.compile(
    r"<!--\s*GENRE_TYPES:START\s*-->(.*?)<!--\s*GENRE_TYPES:END\s*-->", re.DOTALL
)
_GUIDANCE_BLOCK = re.compile(
    r"<!--\s*GENRE_GUIDANCE:START\s*-->(.*?)<!--\s*GENRE_GUIDANCE:END\s*-->", re.DOTALL
)
# A markdown table data row: leading "|", first cell is the genre key. Skips the
# header row ("Book Type") and the separator row ("---").
_TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|", re.MULTILINE)
_BUCKET_HDR = re.compile(r"^#+\s*Bucket:\s*([a-z][a-z0-9-]*)\s*$", re.MULTILINE)
_OVERLAY_HDR = re.compile(r"^#+\s*Overlay:\s*([a-z][a-z0-9-]*)\s*$", re.MULTILINE)


def _block(pattern: re.Pattern[str], path: Path) -> str:
    blocks = pattern.findall(path.read_text(encoding="utf-8"))
    assert blocks, f"{path.name}: missing marker block for {pattern.pattern[:30]}"
    assert len(blocks) == 1, f"{path.name}: expected exactly 1 block, got {len(blocks)}"
    return blocks[0]


def _architect_genres() -> set[str]:
    body = _block(_TYPES_BLOCK, ARCHITECT)
    rows = [m.strip().lower() for m in _TABLE_ROW.findall(body)]
    # Drop the header label and any markdown separator artifacts.
    return {r for r in rows if r and r != "book type" and set(r) - set("-: ")}


def test_architect_table_matches_taxonomy() -> None:
    genres = _architect_genres()
    missing = genre_taxonomy.GENRES - genres
    extra = genres - genre_taxonomy.GENRES
    assert not missing and not extra, (
        "architect.md compression table out of sync with genre_taxonomy.GENRES\n"
        f"  missing from table: {sorted(missing)}\n"
        f"  extra in table: {sorted(extra)}"
    )


def test_scriptwriter_buckets_match_taxonomy() -> None:
    body = _block(_GUIDANCE_BLOCK, SCRIPTWRITER)
    buckets = set(_BUCKET_HDR.findall(body))
    missing = genre_taxonomy.BUCKETS - buckets
    extra = buckets - genre_taxonomy.BUCKETS
    assert not missing and not extra, (
        "scriptwriter.md guidance buckets out of sync with genre_taxonomy.BUCKETS\n"
        f"  missing from prompt: {sorted(missing)}\n"
        f"  extra in prompt: {sorted(extra)}"
    )


def test_scriptwriter_overlays_match_taxonomy() -> None:
    body = _block(_GUIDANCE_BLOCK, SCRIPTWRITER)
    overlays = set(_OVERLAY_HDR.findall(body))
    missing = genre_taxonomy.OVERLAYS - overlays
    extra = overlays - genre_taxonomy.OVERLAYS
    assert not missing and not extra, (
        "scriptwriter.md overlays out of sync with genre_taxonomy.OVERLAYS\n"
        f"  missing from prompt: {sorted(missing)}\n"
        f"  extra in prompt: {sorted(extra)}"
    )


def test_every_genre_has_a_bucket() -> None:
    for genre, bucket in genre_taxonomy.GENRE_TO_BUCKET.items():
        assert bucket in genre_taxonomy.BUCKETS, f"{genre} → unknown bucket {bucket}"
