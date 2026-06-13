#!/usr/bin/env -S uv run --python 3.13 python
"""Build a standalone UIreview.html root for one UITest run.

The catalog gallery and UITest flow review share the same HTML renderer, but
their artifact roots are different: catalog owns surface/state review; UITest
owns a single flow/session with screenshots, contact sheets, and the run video.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
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


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
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
    workspace_root.mkdir(parents=True, exist_ok=True)
    index = load_workspace_index(workspace_root)
    runs = [
        existing
        for existing in index.get("runs", [])
        if (existing.get("flowId"), existing.get("variantId")) != (run.get("flowId"), run.get("variantId"))
    ]
    runs.insert(0, run)
    index["runs"] = runs
    index["summary"] = workspace_summary(runs)
    index["flows"] = flow_records(runs)
    (workspace_root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace_root / REVIEW_HTML_NAME).write_text(render_workspace_html(index), encoding="utf-8")
    return index


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _artifact_link(run: dict, key: str, label: str) -> str:
    href = (run.get("artifacts") or {}).get(key)
    if not href:
        return f'<span class="muted">{_esc(label)} missing</span>'
    return f'<a href="{_esc(href)}">{_esc(label)}</a>'


def render_workspace_html(index: dict) -> str:
    summary = index.get("summary") or {}
    flows = index.get("flows") or []
    runs = index.get("runs") or []
    flow_rows = "\n".join(
        f"""
        <tr>
          <td><a href="#flow-{_esc(flow.get('flowId'))}">{_esc(flow.get('flowId'))}</a></td>
          <td>{_esc(flow.get('latestStatus'))}</td>
          <td>{_esc(flow.get('lastRunAt'))}</td>
          <td>{_esc(flow.get('runs'))}</td>
          <td>{_esc(', '.join(flow.get('variants') or []))}</td>
        </tr>
        """
        for flow in flows
    )
    flow_sections = []
    for flow in flows:
        flow_id = flow.get("flowId")
        flow_runs = [run for run in runs if run.get("flowId") == flow_id]
        cards = "\n".join(
            f"""
            <article class="run-card status-{_esc(run.get('status'))}">
              <div class="run-head">
                <div>
                  <h3>{_esc(run.get('variantId') or 'default')}</h3>
                  <p>{_esc(run.get('testFile'))} · {_esc(run.get('device'))}</p>
                </div>
                <strong>{_esc(run.get('status'))}</strong>
              </div>
              <div class="links">
                {_artifact_link(run, 'reviewHtml', 'review')}
                {_artifact_link(run, 'video', 'video')}
                {_artifact_link(run, 'log', 'log')}
                {_artifact_link(run, 'manifest', 'manifest')}
              </div>
              <p class="meta">lastRunAt={_esc(run.get('lastRunAt'))}</p>
              <p class="meta">run={_esc(run.get('runId'))} steps={_esc(run.get('stepCount'))}</p>
            </article>
            """
            for run in flow_runs
        )
        flow_sections.append(
            f"""
            <section id="flow-{_esc(flow_id)}" class="flow">
              <h2>{_esc(flow_id)}</h2>
              <div class="run-grid">{cards}</div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG UITest Review</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Noto Sans TC", sans-serif; background: #f8f7f4; color: #2a2520; }}
    header {{ position: sticky; top: 0; background: #fcfbfa; border-bottom: 1px solid #dbd6cd; padding: 16px 22px; z-index: 1; }}
    h1 {{ margin: 0; font-size: 18px; letter-spacing: .04em; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 22px; }}
    .stats {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0; }}
    .stat {{ border: 1px solid #dbd6cd; background: #fcfbfa; border-radius: 4px; padding: 10px 14px; min-width: 110px; }}
    .stat strong {{ display: block; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 22px; }}
    .stat span {{ color: #7a756c; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }}
    table {{ width: 100%; border-collapse: collapse; background: #fcfbfa; border: 1px solid #dbd6cd; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e8e4db; text-align: left; font-size: 13px; }}
    th {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; text-transform: uppercase; color: #7a756c; }}
    a {{ color: #2a2520; text-decoration-thickness: 1px; }}
    .flow {{ margin-top: 26px; }}
    .flow h2 {{ border-bottom: 1px solid #dbd6cd; padding-bottom: 8px; font-size: 15px; }}
    .run-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
    .run-card {{ background: #fcfbfa; border: 1px solid #dbd6cd; border-radius: 4px; padding: 13px; }}
    .run-card.status-fail, .run-card.status-failed, .run-card.status-error {{ border-color: #b45b4c; }}
    .run-head {{ display: flex; justify-content: space-between; gap: 12px; }}
    .run-head h3 {{ margin: 0; font-size: 15px; }}
    .run-head p, .meta, .muted {{ color: #7a756c; font-size: 12px; }}
    .links {{ display: flex; gap: 9px; flex-wrap: wrap; margin-top: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <header><h1>KG UITest Review</h1></header>
  <main>
    <section class="stats">
      <div class="stat"><strong>{_esc(summary.get('totalRuns', 0))}</strong><span>runs</span></div>
      <div class="stat"><strong>{_esc(summary.get('okRuns', 0))}</strong><span>ok</span></div>
      <div class="stat"><strong>{_esc(summary.get('failRuns', 0))}</strong><span>fail</span></div>
      <div class="stat"><strong>{_esc(summary.get('flows', 0))}</strong><span>flows</span></div>
      <div class="stat"><strong>{_esc(summary.get('variants', 0))}</strong><span>variants</span></div>
    </section>
    <section>
      <h2>Flows</h2>
      <table>
        <thead><tr><th>Flow</th><th>Latest</th><th>Last Run</th><th>Runs</th><th>Variants</th></tr></thead>
        <tbody>{flow_rows}</tbody>
      </table>
    </section>
    {''.join(flow_sections)}
  </main>
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
