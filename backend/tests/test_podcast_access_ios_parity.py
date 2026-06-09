"""Cross-layer contract guard for podcast tier policy.

The backend is the security boundary, while iOS mirrors the same previewable
episode number for lock badges and gate routing. This test intentionally reads
the Swift source so changing either side without the other fails in CI.
"""
from __future__ import annotations

import re
from pathlib import Path

from kg.podcast_access import FREE_PREVIEW_EP_NUM

ROOT = Path(__file__).resolve().parents[2]
IOS_PODCAST_ACCESS = ROOT / "ios" / "BooksAndVocab" / "Views" / "Podcast" / "PodcastAccess.swift"


def test_ios_free_preview_episode_matches_backend_policy() -> None:
    source = IOS_PODCAST_ACCESS.read_text(encoding="utf-8")
    match = re.search(r"static\s+let\s+freePreviewEpisodeNumber\s*=\s*(\d+)", source)

    assert match is not None, "PodcastAccess.freePreviewEpisodeNumber must stay explicit"
    assert int(match.group(1)) == FREE_PREVIEW_EP_NUM
