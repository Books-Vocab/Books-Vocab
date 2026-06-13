#!/usr/bin/env -S uv run --python 3.13 python
"""Build a standalone UIreview.html root for one UITest run.

The catalog gallery and UITest flow review share the same HTML renderer, but
their artifact roots are different: catalog owns surface/state review; UITest
owns a single flow/session with screenshots, contact sheets, and the run video.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from catalog_review_renderer import render_html
from catalog_review_sync import REVIEW_HTML_NAME


def link_or_copy(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("schema", "kg.visual-review.sheet.v1")
    return manifest


def video_entry(video: Path, out_root: Path) -> list[dict]:
    if not video.is_file():
        return []
    name = video.name
    rel = Path("uitest-videos") / name
    link_or_copy(video, out_root / rel)
    return [
        {
            "file": name,
            "src": rel.as_posix(),
            "scope": "ui",
            "caller": "uitest",
            "sizeBytes": video.stat().st_size,
        }
    ]


def build_review_root(
    *,
    screenshot_dir: Path,
    manifest_path: Path,
    contact_sheet: Path | None,
    quick4_sheet: Path | None,
    video: Path | None,
    out_root: Path,
) -> dict:
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)

    for item in manifest.get("items", []):
        rel = item.get("relPath")
        if not rel:
            continue
        link_or_copy(screenshot_dir / rel, out_root / rel)

    for sheet in (contact_sheet, quick4_sheet):
        if sheet and sheet.is_file():
            link_or_copy(sheet, out_root / sheet.name)

    manifest["imageRoot"] = str(out_root)
    (out_root / "review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_root / "review_state.json").write_text(
        json.dumps({"schema": "kg.ui.review-state.v1", "entries": {}}, indent=2) + "\n",
        encoding="utf-8",
    )

    videos = video_entry(video, out_root) if video else []
    html_path = out_root / REVIEW_HTML_NAME
    html_path.write_text(render_html(manifest, ui_test_videos=videos), encoding="utf-8")

    return {
        "schema": "kg.ios.uitest-review.v1",
        "root": str(out_root),
        "html": str(html_path),
        "manifest": str(out_root / "review_manifest.json"),
        "state": str(out_root / "review_state.json"),
        "videos": videos,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument("--quick4-sheet", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_review_root(
        screenshot_dir=args.screenshot_dir,
        manifest_path=args.manifest,
        contact_sheet=args.contact_sheet,
        quick4_sheet=args.quick4_sheet,
        video=args.video,
        out_root=args.out_root,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(payload["html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
