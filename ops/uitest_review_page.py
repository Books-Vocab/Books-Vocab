#!/usr/bin/env -S uv run --python 3.13 python
"""Build a standalone UIreview.html root for one UITest run.

This evidence belongs to one executed UITest flow and is independent from the
interactive Catalog agent workbench.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
import shutil
from pathlib import Path

from uitest_review_contract import REVIEW_HTML_NAME
from uitest_review_ui import artifact_link, esc, image_modal_script, shell_css, status_badge
from uitest_review_workspace import (
    ensure_workspace,
    render_workspace_html as render_persistent_workspace_html,
    write_workspace_index as write_persistent_workspace_index,
)

log = logging.getLogger(__name__)


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


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        log.warning("Silently handled exception; using fallback response", exc_info=True)
        return str(path)


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
    workspace_root = out_root.parent
    log_rel = None
    if log and log.is_file():
        target = out_root / log.name
        link_or_copy(log, target)
        log_rel = relpath(target, workspace_root)

    review_html = out_root / REVIEW_HTML_NAME
    manifest_path = out_root / "review_manifest.json"
    video_rel = videos[0]["src"] if videos else None
    if video_rel:
        video_rel = relpath(out_root / video_rel, workspace_root)
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
            "reviewHtml": relpath(review_html, workspace_root),
            "manifest": relpath(manifest_path, workspace_root),
            "video": video_rel,
            "log": log_rel,
        },
    }


def workspace_summary(runs: list[dict]) -> dict:
    ok = sum(1 for run in runs if run.get("status") in {"ok", "pass"})
    fail = sum(1 for run in runs if run.get("status") in {"fail", "failed", "error"})
    flows = {run.get("flowId") for run in runs if run.get("flowId")}
    variants = {
        (run.get("flowId"), run.get("variantId"))
        for run in runs
        if run.get("flowId") and run.get("variantId")
    }
    return {
        "totalRuns": len(runs),
        "okRuns": ok,
        "failRuns": fail,
        "flows": len(flows),
        "variants": len(variants),
    }


def flow_records(runs: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        grouped.setdefault(run.get("flowId") or "unknown", []).append(run)
    flows = []
    for flow_id, flow_runs in sorted(grouped.items()):
        latest = flow_runs[0]
        variants = sorted({run.get("variantId") or "default" for run in flow_runs})
        flows.append(
            {
                "flowId": flow_id,
                "runs": len(flow_runs),
                "latestStatus": latest.get("status") or "unknown",
                "lastRunAt": latest.get("lastRunAt"),
                "variants": variants,
            }
        )
    return flows


def load_workspace_index(workspace_root: Path) -> dict:
    path = workspace_root / "index.json"
    if not path.is_file():
        return {
            "schema": "kg.ios.uitest-review-workspace.v1",
            "summary": workspace_summary([]),
            "runs": [],
            "flows": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("schema", "kg.ios.uitest-review-workspace.v1")
    data.setdefault("runs", [])
    return data


def write_workspace_index(workspace_root: Path, run: dict) -> dict:
    return write_persistent_workspace_index(workspace_root, run)


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
      <a class="btn" href="../UIreview.html">workspace</a>
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


def render_workspace_html(index: dict) -> str:
    return render_persistent_workspace_html(index)


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
    sheets = [sheet.name for sheet in (contact_sheet, quick4_sheet) if sheet and sheet.is_file()]

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
    run = run_record(
        out_root=out_root,
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
    html_path.write_text(render_run_html(manifest, run, videos, sheets), encoding="utf-8")
    workspace = write_workspace_index(out_root.parent, run)

    return {
        "schema": "kg.ios.uitest-review.v1",
        "root": str(out_root),
        "html": str(html_path),
        "manifest": str(out_root / "review_manifest.json"),
        "state": str(out_root / "review_state.json"),
        "videos": videos,
        "workspace": {
            "root": str(out_root.parent),
            "html": str(out_root.parent / REVIEW_HTML_NAME),
            "index": str(out_root.parent / "index.json"),
            "summary": workspace.get("summary", {}),
        },
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
