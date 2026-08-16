#!/usr/bin/env -S uv run --python 3.13 python
"""Build a standalone UIreview.html root for one UITest run.

This evidence belongs to one executed UITest flow and is independent from the
interactive Catalog agent workbench.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import shutil
import tempfile
from pathlib import Path

from png_integrity import png_metadata
from uitest_review_contract import REVIEW_HTML_NAME
from uitest_review_ui import artifact_link, esc, image_modal_script, shell_css, status_badge


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


def load_manifest(path: Path, *, screenshot_dir: Path | None = None) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("schema", "kg.visual-review.sheet.v1")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("UI evidence manifest must contain at least one step item")
    if screenshot_dir is not None:
        seen: set[str] = set()
        seen_asset_ids: set[str] = set()
        seen_file_identity: dict[tuple[int, int], str] = {}
        screenshot_root = screenshot_dir.resolve()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"UI evidence manifest item {index} is not an object")
            asset_id = item.get("assetID")
            if not isinstance(asset_id, str) or not asset_id.strip():
                raise ValueError(f"UI evidence manifest item {index} must contain assetID")
            if asset_id in seen_asset_ids:
                raise ValueError(f"UI evidence manifest contains duplicate assetID: {asset_id}")
            seen_asset_ids.add(asset_id)
            rel = item.get("relPath")
            if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise ValueError(f"UI evidence manifest item {index} has unsafe relPath: {rel!r}")
            if rel in seen:
                raise ValueError(f"UI evidence manifest contains duplicate relPath: {rel}")
            seen.add(rel)
            artifact = (screenshot_dir / rel).resolve()
            try:
                artifact.relative_to(screenshot_root)
            except ValueError as error:
                raise ValueError(
                    f"UI evidence manifest item {index} resolves outside screenshot root: {rel!r}"
                ) from error
            if not artifact.is_file():
                raise ValueError(f"UI evidence manifest references missing step PNG: {artifact}")
            identity = (artifact.stat().st_dev, artifact.stat().st_ino)
            if identity in seen_file_identity:
                raise ValueError(
                    "UI evidence manifest maps multiple assets to the same artifact file: "
                    f"{seen_file_identity[identity]} and {rel}"
                )
            seen_file_identity[identity] = rel
            metadata = png_metadata(artifact)
            for key in ("width", "height", "byteSize", "sha256"):
                expected = item.get(key)
                if expected is None:
                    raise ValueError(f"UI evidence manifest item {rel} missing {key}")
                if expected != metadata[key]:
                    raise ValueError(
                        f"UI evidence manifest item {rel} {key} mismatch: expected {expected}, actual {metadata[key]}"
                    )
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


def infer_flow_id(test_file: str | None, out_root: Path) -> str:
    if test_file:
        return Path(test_file).stem
    name = out_root.name
    parts = name.split("-", 2)
    if len(parts) == 3:
        return parts[2]
    return name


def run_record(
    *,
    out_root: Path,
    artifact_root: Path | None = None,
    manifest: dict,
    videos: list[dict],
    log: Path | None,
    flow_id: str | None,
    variant_id: str | None,
    status: str | None,
    test_file: str | None,
    device: str | None,
    last_run_at: str | None = None,
) -> dict:
    artifact_root = artifact_root or out_root
    log_rel = None
    if log and log.is_file():
        target = artifact_root / log.name
        link_or_copy(log, target)
        log_rel = log.name

    video_rel = videos[0]["src"] if videos else None
    items = manifest.get("items", [])
    return {
        "runId": out_root.name,
        "flowId": flow_id or infer_flow_id(test_file, out_root),
        "variantId": variant_id or "default",
        "status": status or "unknown",
        "lastRunAt": last_run_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "testFile": test_file,
        "device": device,
        "stepCount": len(items),
        "steps": [
            {
                "assetID": item.get("assetID"),
                "stateLabel": item.get("stateLabel"),
                "relPath": item.get("relPath"),
            }
            for item in items
        ],
        "artifacts": {
            "reviewHtml": REVIEW_HTML_NAME,
            "manifest": "review_manifest.json",
            "video": video_rel,
            "log": log_rel,
        },
    }


def _esc(value) -> str:
    return esc(value)


def render_run_html(manifest: dict, run: dict, videos: list[dict], sheets: list[str]) -> str:
    items = manifest.get("items") or []
    artifacts = run.get("artifacts") or {}
    video_href = videos[0].get("src") if videos else None
    log_href = Path(artifacts["log"]).name if artifacts.get("log") else None
    local_artifacts = (
        ("video", video_href, "video missing"),
        ("log", log_href, "log missing"),
        ("manifest", "review_manifest.json", "manifest missing"),
    )
    artifact_links = "\n".join(
        artifact_link(href, label, missing_label=missing)
        for label, href, missing in local_artifacts
    )
    video_blocks = "\n".join(
        f"""
        <figure class="panel">
          <video controls preload="metadata" src="{_esc(video.get('src'))}"></video>
          <figcaption><strong>{_esc(video.get('file'))}</strong><span>{_esc(video.get('sizeBytes'))} bytes</span></figcaption>
        </figure>
        """
        for video in videos
    )
    sheet_blocks = "\n".join(
        f"""
        <figure class="panel">
          <button class="shot-button" type="button" data-modal-src="{_esc(sheet)}" data-modal-title="{_esc(sheet)}">
            <img src="{_esc(sheet)}" alt="{_esc(sheet)}">
          </button>
          <figcaption><strong>{_esc(sheet)}</strong><span>contact sheet</span></figcaption>
        </figure>
        """
        for sheet in sheets
    )
    sheet_links = "\n".join(artifact_link(sheet, sheet) for sheet in sheets)
    step_blocks = "\n".join(
        f"""
        <figure class="panel">
          <button class="shot-button" type="button" data-modal-src="{_esc(item.get('relPath'))}" data-modal-title="{_esc(item.get('assetID') or item.get('stateLabel'))}">
            <img src="{_esc(item.get('relPath'))}" alt="{_esc(item.get('assetID') or item.get('stateLabel'))}">
          </button>
          <figcaption>
            <strong>{_esc(item.get('assetID'))}</strong>
            <span>{_esc(item.get('stateLabel'))}</span>
            <code>{_esc(item.get('relPath'))}</code>
          </figcaption>
        </figure>
        """
        for item in items
        if item.get("relPath")
    )
    if not step_blocks:
        step_blocks = '<p class="empty">No step screenshots were emitted for this UITest run.</p>'
    if not video_blocks:
        video_blocks = '<p class="empty">No video artifact was archived for this UITest run.</p>'
    if not sheet_blocks:
        sheet_blocks = '<p class="empty">contact sheets missing</p>'
    if not sheet_links:
        sheet_links = '<span class="artifact missing">contact sheets missing</span>'

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG UITest Run Review</title>
  <style>
{shell_css()}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">KG UITest Run Review <span>Evidence Cockpit</span></div>
    <div class="top-actions">
      <a class="btn" href="review_manifest.json">manifest</a>
    </div>
  </div>
  <main class="page">
    <section class="hero">
      <div class="panel pad">
        <div class="eyebrow">Run Evidence</div>
        <div class="headline-row">
          <div>
            <h1>{_esc(run.get('flowId'))}</h1>
            <p class="path">{_esc(run.get('variantId') or 'default')} · {_esc(run.get('testFile') or 'unknown test file')}</p>
          </div>
          {status_badge(run.get('status'))}
        </div>
        <div class="hero-meta">
          <span>lastRunAt={_esc(run.get('lastRunAt'))}</span>
          <span>device={_esc(run.get('device') or 'unknown')}</span>
          <span>steps={_esc(run.get('stepCount'))}</span>
        </div>
        <div class="artifact-row">{artifact_links}{sheet_links}</div>
      </div>
      <div class="panel pad metric-grid">
        <div class="metric"><div class="value">{_esc(run.get('stepCount'))}</div><div class="label">steps</div></div>
        <div class="metric"><div class="value">{_esc(len(videos))}</div><div class="label">video</div></div>
        <div class="metric"><div class="value">{_esc(len(sheets))}</div><div class="label">sheets</div></div>
        <div class="metric"><div class="value">{_esc(run.get('status'))}</div><div class="label">status</div></div>
      </div>
    </section>
    <section class="section">
      <h2>Artifacts</h2>
      <div class="artifact-row">{artifact_links}{sheet_links}</div>
    </section>
    <section class="section">
      <h2>Video</h2>
      <div class="media-grid">{video_blocks}</div>
    </section>
    <section class="section">
      <h2>Contact Sheets</h2>
      <div class="media-grid">{sheet_blocks}</div>
    </section>
    <section class="section">
      <h2>Step Screenshots</h2>
      <div class="media-grid">{step_blocks}</div>
    </section>
  </main>
  <div class="modal" id="image-modal" aria-hidden="true">
    <div class="modal-inner">
      <div class="modal-head">
        <span id="modal-title"></span>
        <button class="btn" type="button" data-close-modal="true">close</button>
      </div>
      <img id="modal-image" alt="">
    </div>
  </div>
  <script>
{image_modal_script()}
  </script>
</body>
</html>
"""


def build_review_root(
    *,
    screenshot_dir: Path,
    manifest_path: Path,
    contact_sheet: Path | None,
    quick4_sheet: Path | None,
    video: Path | None,
    out_root: Path,
    log: Path | None = None,
    flow_id: str | None = None,
    variant_id: str | None = None,
    status: str | None = None,
    test_file: str | None = None,
    device: str | None = None,
    last_run_at: str | None = None,
) -> dict:
    if out_root.exists() and any(out_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty UI review root: {out_root}")
    manifest = load_manifest(manifest_path, screenshot_dir=screenshot_dir)
    out_root.parent.mkdir(parents=True, exist_ok=True)
    if out_root.exists():
        out_root.rmdir()
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{out_root.name}.staging.", dir=out_root.parent)
    )
    published = False
    try:
        for item in manifest.get("items", []):
            rel = item.get("relPath")
            if not rel:
                continue
            link_or_copy(screenshot_dir / rel, staging_root / rel)

        for sheet in (contact_sheet, quick4_sheet):
            if sheet and sheet.is_file():
                link_or_copy(sheet, staging_root / sheet.name)
        sheets = [
            sheet.name
            for sheet in (contact_sheet, quick4_sheet)
            if sheet and sheet.is_file()
        ]

        manifest["imageRoot"] = str(out_root)
        (staging_root / "review_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging_root / "review_state.json").write_text(
            json.dumps({"schema": "kg.ui.review-state.v2", "entries": []}, indent=2)
            + "\n",
            encoding="utf-8",
        )

        videos = video_entry(video, staging_root) if video else []
        run = run_record(
            out_root=out_root,
            artifact_root=staging_root,
            manifest=manifest,
            videos=videos,
            log=log,
            flow_id=flow_id,
            variant_id=variant_id,
            status=status,
            test_file=test_file,
            device=device,
            last_run_at=last_run_at,
        )
        (staging_root / REVIEW_HTML_NAME).write_text(
            render_run_html(manifest, run, videos, sheets), encoding="utf-8"
        )
        os.replace(staging_root, out_root)
        published = True
    except Exception as error:
        cleanup_root = out_root if published else staging_root
        if cleanup_root.exists():
            shutil.rmtree(cleanup_root)
        raise

    html_path = out_root / REVIEW_HTML_NAME

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
    parser.add_argument("--log", type=Path)
    parser.add_argument("--flow-id")
    parser.add_argument("--variant-id")
    parser.add_argument("--status")
    parser.add_argument("--test-file")
    parser.add_argument("--device")
    parser.add_argument("--last-run-at")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_review_root(
        screenshot_dir=args.screenshot_dir,
        manifest_path=args.manifest,
        contact_sheet=args.contact_sheet,
        quick4_sheet=args.quick4_sheet,
        video=args.video,
        out_root=args.out_root,
        log=args.log,
        flow_id=args.flow_id,
        variant_id=args.variant_id,
        status=args.status,
        test_file=args.test_file,
        device=args.device,
        last_run_at=args.last_run_at,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(payload["html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
