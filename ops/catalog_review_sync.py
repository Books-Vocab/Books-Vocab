from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from catalog_review_renderer import render_html

# Review page filename SoT (renamed from review.html, 2026-06). Writers always
# emit the new name; readers resolving older roots go through
# catalog_review_cli_artifacts.review_html_path, which falls back to the
# legacy name when only it exists.
REVIEW_HTML_NAME = "UIreview.html"
LEGACY_REVIEW_HTML_NAME = "review.html"


def hydrate_manifest(manifest: dict, review_state: dict) -> dict:
    state_entries = review_state.get("entries", {})
    items = []
    state_counts: dict[str, int] = {}
    for item in manifest["items"]:
        state_entry = state_entries.get(item["assetID"], {})
        hydrated = dict(item)
        hydrated["reviewStatus"] = state_entry.get("status", "")
        hydrated["reviewNote"] = state_entry.get("note", "")
        items.append(hydrated)
        if hydrated["reviewStatus"]:
            state_counts[hydrated["reviewStatus"]] = state_counts.get(hydrated["reviewStatus"], 0) + 1

    next_manifest = dict(manifest)
    next_manifest["items"] = items
    next_manifest["stateCounts"] = state_counts
    return next_manifest


def sync_uitest_videos(root: Path) -> list[dict]:
    """Mirror the UITest recording archive (sibling build/snapshots/uitest-videos/,
    written by ios_test.sh) into <root>/uitest-videos/ and return page entries.

    Hard links (copy fallback) keep the review root self-contained: the http
    server serves --directory <root> and cannot reach ../, and a blessed root
    stays browsable even after the shared archive prunes older runs. Missing or
    unreadable archive = no recordings section, never an error.
    """
    index_path = root.parent / "uitest-videos" / "index.json"
    if not index_path.is_file():
        return []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        # Absent archive is the normal no-recordings case; an existing but
        # unreadable index is corruption worth surfacing, not silence.
        print(f"[catalog-review] warning: unreadable {index_path}: {error}", file=sys.stderr)
        return []
    entries = []
    for video in index.get("videos", []):
        name = video.get("file", "")
        source = index_path.parent / name
        if not name or "/" in name or not source.is_file():
            continue
        local_dir = root / "uitest-videos"
        local_dir.mkdir(exist_ok=True)
        target = local_dir / name
        if not target.exists():
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)  # cross-device fallback; streams
        entries.append({**video, "src": f"uitest-videos/{name}"})
    return entries


def write_review_outputs(root: Path, manifest: dict, review_state: dict) -> None:
    hydrated = hydrate_manifest(manifest, review_state)
    (root / "review_manifest.json").write_text(
        json.dumps(hydrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ui_test_videos = sync_uitest_videos(root)
    (root / REVIEW_HTML_NAME).write_text(
        render_html(hydrated, ui_test_videos=ui_test_videos),
        encoding="utf-8",
    )
