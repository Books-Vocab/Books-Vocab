#!/usr/bin/env -S uv run --python 3.13 python
"""Build and refresh the persistent UITest UIreview workspace."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from catalog_review_sync import REVIEW_HTML_NAME
from uitest_review_ui import artifact_link, dom_id, esc, filter_script, shell_css, status_badge, status_kind


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_ROOT = ROOT / "build" / "snapshots" / "uitest-runs"
DEFAULT_TEST_ROOT = ROOT / "ios" / "BooksAndVocabUITests"


def workspace_summary(runs: list[dict], flows: list[dict] | None = None) -> dict:
    ok = sum(1 for run in runs if run.get("status") in {"ok", "pass"})
    fail = sum(1 for run in runs if run.get("status") in {"fail", "failed", "error"})
    run_flows = {run.get("flowId") for run in runs if run.get("flowId")}
    variants = {
        (run.get("flowId"), run.get("variantId"))
        for run in runs
        if run.get("flowId") and run.get("variantId")
    }
    all_flows = {flow.get("flowId") for flow in flows or [] if flow.get("flowId")} or run_flows
    pending = sum(1 for flow in flows or [] if flow.get("latestStatus") == "never-run")
    return {
        "totalRuns": len(runs),
        "okRuns": ok,
        "failRuns": fail,
        "flows": len(all_flows),
        "variants": len(variants),
        "pendingFlows": pending,
    }


def test_methods(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return sorted(set(re.findall(r"\bfunc\s+(test[A-Za-z0-9_]+)\s*\(", text)))


def discover_flow_stubs(test_root: Path = DEFAULT_TEST_ROOT, project_root: Path = ROOT) -> list[dict]:
    if not test_root.is_dir():
        return []
    flows = []
    for path in sorted(test_root.glob("*UITests.swift")):
        flow_id = path.stem
        test_file = path.name
        command = f"./ops/ios_ops.sh test --ui --file {test_file} --lease --json"
        flows.append(
            {
                "flowId": flow_id,
                "runs": 0,
                "latestStatus": "never-run",
                "lastRunAt": None,
                "variants": [],
                "testFile": test_file,
                "testPath": _relpath(path, project_root),
                "methods": test_methods(path),
                "runCommand": command,
            }
        )
    return flows


def flow_records(runs: list[dict], stubs: list[dict] | None = None) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        grouped.setdefault(run.get("flowId") or "unknown", []).append(run)

    flows_by_id: dict[str, dict] = {}
    for flow_id, flow_runs in sorted(grouped.items()):
        latest = flow_runs[0]
        variants = sorted({run.get("variantId") or "default" for run in flow_runs})
        flows_by_id[flow_id] = {
            "flowId": flow_id,
            "runs": len(flow_runs),
            "latestStatus": latest.get("status") or "unknown",
            "lastRunAt": latest.get("lastRunAt"),
            "variants": variants,
            "testFile": latest.get("testFile"),
        }

    for stub in stubs or []:
        existing = flows_by_id.get(stub["flowId"])
        if existing:
            existing.setdefault("testFile", stub.get("testFile"))
            existing.setdefault("testPath", stub.get("testPath"))
            existing.setdefault("methods", stub.get("methods", []))
            existing.setdefault("runCommand", stub.get("runCommand"))
            continue
        flows_by_id[stub["flowId"]] = dict(stub)

    return sorted(flows_by_id.values(), key=lambda item: item.get("flowId") or "")


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
    data.setdefault("flows", [])
    return data


def ensure_workspace(
    *,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
    test_root: Path = DEFAULT_TEST_ROOT,
    project_root: Path = ROOT,
) -> dict:
    workspace_root.mkdir(parents=True, exist_ok=True)
    index = load_workspace_index(workspace_root)
    runs = sorted(index.get("runs", []), key=lambda item: item.get("lastRunAt") or "", reverse=True)
    stubs = discover_flow_stubs(test_root, project_root)
    flows = flow_records(runs, stubs)
    index["runs"] = runs
    index["flows"] = flows
    index["summary"] = workspace_summary(runs, flows)
    (workspace_root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace_root / REVIEW_HTML_NAME).write_text(render_workspace_html(index), encoding="utf-8")
    return index


def write_workspace_index(
    workspace_root: Path,
    run: dict,
    *,
    test_root: Path = DEFAULT_TEST_ROOT,
    project_root: Path = ROOT,
) -> dict:
    workspace_root.mkdir(parents=True, exist_ok=True)
    index = load_workspace_index(workspace_root)
    runs = [
        existing
        for existing in index.get("runs", [])
        if (existing.get("flowId"), existing.get("variantId")) != (run.get("flowId"), run.get("variantId"))
    ]
    runs.insert(0, run)
    runs.sort(key=lambda item: item.get("lastRunAt") or "", reverse=True)
    index["runs"] = runs
    (workspace_root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ensure_workspace(workspace_root=workspace_root, test_root=test_root, project_root=project_root)


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _flow_status(flow: dict) -> str:
    return status_kind(flow.get("latestStatus"))


def _flow_sort_key(flow: dict) -> tuple[int, float, str]:
    priority = {"failed": 0, "pending": 1, "idle": 2, "passed": 3}.get(_flow_status(flow), 4)
    value = flow.get("lastRunAt") or ""
    timestamp = 0.0
    if value:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            timestamp = 0.0
    return (priority, -timestamp, str(flow.get("flowId") or ""))


def _method_list(methods: list[str], *, limit: int = 4) -> str:
    if not methods:
        return '<span class="muted">no test methods discovered</span>'
    visible = methods[:limit]
    items = "".join(f"<span>{esc(method)}</span>" for method in visible)
    if len(methods) > limit:
        items += f'<span class="muted">+{len(methods) - limit} more</span>'
    return items


def _pending_card(flow: dict) -> str:
    methods = flow.get("methods") or []
    command = flow.get("runCommand") or f"./ops/ios_ops.sh test --ui --file {flow.get('testFile')} --lease --json"
    return f"""
            <article class="card status-pending" data-status="pending" data-flow="{esc(flow.get('flowId'))}" data-text="{esc(' '.join([flow.get('flowId') or '', flow.get('testFile') or '', ' '.join(methods)]))}">
              <div class="card-top">
                {status_badge("never-run")}
                <span class="muted">{esc(len(methods))} tests</span>
              </div>
              <h3>{esc(flow.get('flowId'))}</h3>
              <p class="path">{esc(flow.get('testFile'))}</p>
              <code class="command">{esc(command)}</code>
              <div class="method-list">{_method_list(methods)}</div>
            </article>
            """


def _run_card(run: dict) -> str:
    status_class = _flow_status({"latestStatus": run.get("status")})
    text = " ".join(
        [
            str(run.get("flowId") or ""),
            str(run.get("testFile") or ""),
            str(run.get("variantId") or ""),
            str(run.get("status") or ""),
        ]
    )
    return f"""
            <article class="card status-{esc(status_class)}" data-status="{esc(status_class)}" data-flow="{esc(run.get('flowId'))}" data-text="{esc(text)}">
              <div class="card-top">
                {status_badge(run.get('status'))}
                <span class="muted">{esc(run.get('stepCount'))} steps</span>
              </div>
              <h3>{esc(run.get('variantId') or 'default')}</h3>
              <p class="path">{esc(run.get('testFile'))} · {esc(run.get('device') or 'unknown')}</p>
              <div class="links">
                {artifact_link((run.get('artifacts') or {}).get('reviewHtml'), 'review')}
                {artifact_link((run.get('artifacts') or {}).get('video'), 'video')}
                {artifact_link((run.get('artifacts') or {}).get('log'), 'log')}
                {artifact_link((run.get('artifacts') or {}).get('manifest'), 'manifest')}
              </div>
              <p class="meta">lastRunAt={esc(run.get('lastRunAt'))}</p>
              <p class="meta">run={esc(run.get('runId'))}</p>
            </article>
            """


def _flow_table_row(flow: dict) -> str:
    status_class = _flow_status(flow)
    methods = flow.get("methods") or []
    command = flow.get("runCommand") or f"./ops/ios_ops.sh test --ui --file {flow.get('testFile')} --lease --json"
    ran = int(flow.get("runs") or 0) > 0
    flow_anchor = dom_id("flow", flow.get("flowId"))
    searchable = " ".join(
        [
            str(flow.get("flowId") or ""),
            str(flow.get("testFile") or ""),
            " ".join(methods),
            str(flow.get("latestStatus") or ""),
            str(flow.get("variants") or ""),
        ]
    )
    return f"""
        <tr class="flow-row" data-status="{esc(status_class)}" data-ran="{str(ran).lower()}" data-text="{esc(searchable)}">
          <td>
            <a class="flow-link" href="#{esc(flow_anchor)}">{esc(flow.get('flowId'))}</a>
            <div class="path">{esc(flow.get('testFile') or '')}</div>
          </td>
          <td>{status_badge(flow.get('latestStatus'))}</td>
          <td>{esc(flow.get('lastRunAt') or 'not run')}</td>
          <td>{esc(flow.get('runs'))}</td>
          <td>{esc(len(methods))}</td>
          <td>{esc(', '.join(flow.get('variants') or []) or 'none')}</td>
          <td><code>{esc(command)}</code></td>
        </tr>
        """


def render_workspace_html(index: dict) -> str:
    summary = index.get("summary") or {}
    flows = sorted(index.get("flows") or [], key=_flow_sort_key)
    runs = index.get("runs") or []
    flow_rows = "\n".join(_flow_table_row(flow) for flow in flows)
    status_counts = {
        "all": len(flows),
        "pending": sum(1 for flow in flows if _flow_status(flow) == "pending"),
        "passed": sum(1 for flow in flows if _flow_status(flow) == "passed"),
        "failed": sum(1 for flow in flows if _flow_status(flow) == "failed"),
        "ran": sum(1 for flow in flows if int(flow.get("runs") or 0) > 0),
    }
    latest = runs[0] if runs else None
    if status_counts["failed"]:
        headline = "Latest run needs attention"
    elif status_counts["pending"]:
        headline = "Never-run flows remain"
    elif latest:
        headline = "Latest run is passing"
    else:
        headline = "No UITest runs yet"
    latest_summary = (
        f"{esc(latest.get('flowId'))} · {esc(latest.get('variantId') or 'default')} · {esc(latest.get('lastRunAt'))}"
        if latest
        else "Run a UI flow to populate video, log, screenshot, and manifest links."
    )
    flow_sections = []
    for flow in flows:
        flow_id = flow.get("flowId")
        flow_runs = [run for run in runs if run.get("flowId") == flow_id]
        status_class = _flow_status(flow)
        if flow_runs:
            cards = "\n".join(_run_card(run) for run in flow_runs)
        else:
            cards = _pending_card(flow)
        flow_anchor = dom_id("flow", flow_id)
        flow_sections.append(
            f"""
            <section id="{esc(flow_anchor)}" class="flow-section section" data-status="{esc(status_class)}" data-ran="{str(bool(flow_runs)).lower()}" data-text="{esc(' '.join([str(flow_id or ''), str(flow.get('testFile') or ''), str(flow.get('latestStatus') or ''), ' '.join(flow.get('methods') or [])]))}">
              <div class="section-head">
                <h2>{esc(flow_id)}</h2>
                <span class="muted">{esc(flow.get('runs'))} run · { esc(len(flow.get('methods') or [])) } tests</span>
              </div>
              <div class="card-grid">{cards}</div>
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
{shell_css()}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">KG UITest Review <span>Debug Cockpit</span></div>
    <div class="top-actions">
      <span class="muted" id="visible-count">{esc(len(flows))} flow · {esc(summary.get('totalRuns', 0))} run · {esc(summary.get('pendingFlows', 0))} pending</span>
      <a class="btn" href="index.json">index</a>
    </div>
  </div>
  <main class="page">
    <section class="hero">
      <div class="panel pad">
        <div class="eyebrow">failed first · offline artifact desk</div>
        <div class="headline-row">
          <div>
            <h1>{esc(headline)}</h1>
            <p class="path">{latest_summary}</p>
          </div>
          {status_badge(latest.get('status') if latest else ('never-run' if status_counts['pending'] else 'unknown'))}
        </div>
        <div class="artifact-row">
          {artifact_link((latest.get('artifacts') or {}).get('reviewHtml') if latest else None, 'latest review')}
          {artifact_link((latest.get('artifacts') or {}).get('video') if latest else None, 'latest video')}
          {artifact_link((latest.get('artifacts') or {}).get('log') if latest else None, 'latest log')}
        </div>
      </div>
      <div class="panel pad metric-grid">
        <div class="metric"><div class="value">{esc(summary.get('failRuns', 0))}</div><div class="label">fail</div></div>
        <div class="metric"><div class="value">{esc(summary.get('pendingFlows', 0))}</div><div class="label">pending</div></div>
        <div class="metric"><div class="value">{esc(summary.get('okRuns', 0))}</div><div class="label">ok</div></div>
        <div class="metric"><div class="value">{esc(summary.get('totalRuns', 0))}</div><div class="label">runs</div></div>
        <div class="metric"><div class="value">{esc(summary.get('flows', 0))}</div><div class="label">flows</div></div>
        <div class="metric"><div class="value">{esc(summary.get('variants', 0))}</div><div class="label">variants</div></div>
      </div>
    </section>
    <div class="tabs" id="tabs">
      <button class="tab active" data-filter="all">all {esc(status_counts['all'])}</button>
      <button class="tab" data-filter="failed">fail {esc(status_counts['failed'])}</button>
      <button class="tab" data-filter="pending">pending {esc(status_counts['pending'])}</button>
      <button class="tab" data-filter="passed">pass {esc(status_counts['passed'])}</button>
      <button class="tab" data-filter="ran">ran {esc(status_counts['ran'])}</button>
    </div>
    <div class="toolbar">
      <input id="search" class="search" type="search" placeholder="搜尋 flow / file / method / variant / status">
    </div>
    <section class="section">
      <div class="section-head">
        <h2>Flow Inventory</h2>
        <span class="muted">failed first</span>
      </div>
      <div class="table-wrap">
      <table id="flow-table">
        <thead><tr><th>Flow</th><th>Status</th><th>Last Run</th><th>Runs</th><th>Tests</th><th>Variants</th><th>Command</th></tr></thead>
        <tbody>{flow_rows}</tbody>
      </table>
      </div>
      <div class="section-head section">
        <h2>Flow Details</h2>
        <span class="muted">Never-run flows show commands and discovered methods.</span>
      </div>
      <div id="empty" class="empty hidden">No flows match the current filter.</div>
      {''.join(flow_sections)}
    </section>
  </main>
  <script>
{filter_script(total_runs=summary.get('totalRuns', 0), pending_flows=summary.get('pendingFlows', 0))}
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the persistent UITest review workspace.")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--test-root", type=Path, default=DEFAULT_TEST_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = ensure_workspace(workspace_root=args.workspace_root, test_root=args.test_root)
    result = {
        "schema": "kg.ios.uitest-review-workspace-refresh.v1",
        "status": "ok",
        "root": str(args.workspace_root),
        "html": str(args.workspace_root / REVIEW_HTML_NAME),
        "index": str(args.workspace_root / "index.json"),
        "summary": payload.get("summary", {}),
        "flows": payload.get("flows", []),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["html"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
