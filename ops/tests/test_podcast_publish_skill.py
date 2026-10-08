"""podcast-publish skill must route by mode, not name upload.sh the sole wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "podcast-publish" / "SKILL.md"


@pytest.fixture(scope="module")
def text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_cover_only_routes_to_cover_publish(text: str) -> None:
    assert "podcast_cover_publish.py" in text
    assert "--execute" in text


def test_preview_backfill_routes_to_backfill(text: str) -> None:
    assert "podcast_preview_backfill.py" in text


def test_no_sole_wrapper_claim(text: str) -> None:
    assert "唯一 publish wrapper" not in text


def test_upload_sh_restricted_to_full_republish(text: str) -> None:
    lines = [ln for ln in text.splitlines() if "podcast_upload.sh" in ln]
    joined = "\n".join(lines)
    assert "podcast_upload.sh" in text
    assert "--dry-run" in text
    assert "prune" in text
    assert "完整" in joined or "full" in joined.lower()


def test_cover_route_precedes_upload_route_in_workflow(text: str) -> None:
    body = text.split("## 標準路徑", 1)[1]
    assert body.index("podcast_cover_publish.py") < body.index("podcast_upload.sh")
