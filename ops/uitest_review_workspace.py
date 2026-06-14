#!/usr/bin/env -S uv run --python 3.13 python
"""Build and refresh the persistent UITest UIreview workspace."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from catalog_review_sync import REVIEW_HTML_NAME


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


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _artifact_link(run: dict, key: str, label: str) -> str:
    href = (run.get("artifacts") or {}).get(key)
    if not href:
        return f'<span class="muted">{_esc(label)} missing</span>'
    return f'<a href="{_esc(href)}">{_esc(label)}</a>'


def _flow_status(flow: dict) -> str:
    status = str(flow.get("latestStatus") or "unknown")
    if status in {"ok", "pass", "passed"}:
        return "passed"
    if status in {"fail", "failed", "error"}:
        return "failed"
    if status == "never-run":
        return "pending"
    return "idle"


def _method_list(methods: list[str], *, limit: int = 4) -> str:
    if not methods:
        return '<span class="muted">no test methods discovered</span>'
    visible = methods[:limit]
    items = "".join(f"<span>{_esc(method)}</span>" for method in visible)
    if len(methods) > limit:
        items += f'<span class="muted">+{len(methods) - limit} more</span>'
    return items


def _pending_card(flow: dict) -> str:
    methods = flow.get("methods") or []
    command = flow.get("runCommand") or f"./ops/ios_ops.sh test --ui --file {flow.get('testFile')} --lease --json"
    return f"""
            <article class="flow-card status-pending" data-status="pending" data-flow="{_esc(flow.get('flowId'))}" data-text="{_esc(' '.join([flow.get('flowId') or '', flow.get('testFile') or '', ' '.join(methods)]))}">
              <div class="card-top">
                <span class="badge pending">never-run</span>
                <span class="count-pill">{_esc(len(methods))} tests</span>
              </div>
              <h3>{_esc(flow.get('flowId'))}</h3>
              <p class="path">{_esc(flow.get('testFile'))}</p>
              <div class="command-row"><code>{_esc(command)}</code></div>
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
            <article class="flow-card status-{_esc(status_class)}" data-status="{_esc(status_class)}" data-flow="{_esc(run.get('flowId'))}" data-text="{_esc(text)}">
              <div class="card-top">
                <span class="badge {_esc(status_class)}">{_esc(run.get('status'))}</span>
                <span class="count-pill">{_esc(run.get('stepCount'))} steps</span>
              </div>
              <h3>{_esc(run.get('flowId'))}</h3>
              <p class="path">{_esc(run.get('testFile'))} · {_esc(run.get('variantId') or 'default')}</p>
              <div class="links">
                {_artifact_link(run, 'reviewHtml', 'review')}
                {_artifact_link(run, 'video', 'video')}
                {_artifact_link(run, 'log', 'log')}
                {_artifact_link(run, 'manifest', 'manifest')}
              </div>
              <p class="meta">lastRunAt={_esc(run.get('lastRunAt'))}</p>
              <p class="meta">device={_esc(run.get('device') or 'unknown')}</p>
            </article>
            """


def _flow_table_row(flow: dict) -> str:
    status_class = _flow_status(flow)
    methods = flow.get("methods") or []
    command = flow.get("runCommand") or f"./ops/ios_ops.sh test --ui --file {flow.get('testFile')} --lease --json"
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
        <tr class="flow-row" data-status="{_esc(status_class)}" data-text="{_esc(searchable)}">
          <td>
            <a class="flow-link" href="#flow-{_esc(flow.get('flowId'))}">{_esc(flow.get('flowId'))}</a>
            <div class="path">{_esc(flow.get('testFile') or '')}</div>
          </td>
          <td><span class="badge {_esc(status_class)}">{_esc(flow.get('latestStatus'))}</span></td>
          <td>{_esc(flow.get('lastRunAt') or 'not run')}</td>
          <td>{_esc(flow.get('runs'))}</td>
          <td>{_esc(len(methods))}</td>
          <td>{_esc(', '.join(flow.get('variants') or []) or 'none')}</td>
          <td><code class="inline-command">{_esc(command)}</code></td>
        </tr>
        """


def render_workspace_html(index: dict) -> str:
    summary = index.get("summary") or {}
    flows = index.get("flows") or []
    runs = index.get("runs") or []
    flow_rows = "\n".join(_flow_table_row(flow) for flow in flows)
    status_counts = {
        "all": len(flows),
        "pending": sum(1 for flow in flows if _flow_status(flow) == "pending"),
        "passed": sum(1 for flow in flows if _flow_status(flow) == "passed"),
        "failed": sum(1 for flow in flows if _flow_status(flow) == "failed"),
        "ran": sum(1 for flow in flows if int(flow.get("runs") or 0) > 0),
    }
    flow_sections = []
    for flow in flows:
        flow_id = flow.get("flowId")
        flow_runs = [run for run in runs if run.get("flowId") == flow_id]
        status_class = _flow_status(flow)
        if flow_runs:
            cards = "\n".join(_run_card(run) for run in flow_runs)
        else:
            cards = _pending_card(flow)
        flow_sections.append(
            f"""
            <section id="flow-{_esc(flow_id)}" class="flow-section" data-status="{_esc(status_class)}" data-text="{_esc(flow_id)}">
              <div class="section-head">
                <h2>{_esc(flow_id)}</h2>
                <span>{_esc(flow.get('runs'))} run · { _esc(len(flow.get('methods') or [])) } tests</span>
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+TC:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #f8f7f4;
      --surface: #fcfbfa;
      --border: #dbd6cd;
      --border-l: #e8e4db;
      --ink: #2a2520;
      --ink-light: #5a5550;
      --sub: #7a756c;
      --passed: #256246;
      --passed-bg: rgba(37,98,70,.08);
      --failed: #a7372a;
      --failed-bg: rgba(167,55,42,.08);
      --warn: #9b6b16;
      --warn-bg: rgba(155,107,22,.08);
      --idle: #69727d;
      --idle-bg: rgba(105,114,125,.08);
      --mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
      --sans: 'Noto Sans TC', system-ui, -apple-system, sans-serif;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ margin: 0; font-family: var(--sans); background: var(--bg); color: var(--ink); font-size: 14px; line-height: 1.76; min-height: 100vh; }}
    .nav {{ position: sticky; top: 0; z-index: 20; height: 52px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 0 16px; background: var(--surface); border-bottom: 1px solid var(--border); }}
    .brand {{ font-family: var(--mono); font-size: 12px; text-transform: uppercase; white-space: nowrap; display: flex; align-items: center; gap: 8px; }}
    .brand .tag {{ border: 1px solid var(--ink); background: var(--ink); color: #fff; border-radius: 2px; padding: 1px 7px; font-size: 10px; font-weight: 500; }}
    .nav-actions {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    .counts {{ font-family: var(--mono); font-size: 10px; color: var(--sub); text-transform: uppercase; }}
    .btn {{ display: inline-flex; align-items: center; justify-content: center; height: 30px; padding: 0 10px; border: 1px solid var(--border); border-radius: 3px; background: transparent; color: var(--ink-light); font-family: var(--mono); font-size: 10px; text-transform: uppercase; text-decoration: none; cursor: pointer; white-space: nowrap; }}
    .btn:hover {{ border-color: var(--ink); color: var(--ink); }}
    .tabs {{ display: flex; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); background: var(--surface); flex-wrap: wrap; }}
    .tab {{ height: 30px; padding: 0 12px; border: 1px solid var(--border); border-radius: 3px; background: transparent; color: var(--ink-light); font-family: var(--mono); font-size: 11px; text-transform: uppercase; cursor: pointer; }}
    .tab:hover {{ border-color: var(--ink); color: var(--ink); }}
    .tab.active {{ background: var(--ink); border-color: var(--ink); color: #fff; }}
    .tab .n {{ opacity: .7; margin-left: 5px; }}
    .toolbar {{ display: flex; align-items: center; gap: 10px; padding: 12px 16px 4px; background: var(--bg); }}
    .filter-input {{ flex: 1; min-width: 260px; padding: 8px 11px; border: 1px solid var(--border); border-radius: 2px; font: inherit; color: var(--ink); background: var(--surface); outline: none; }}
    .filter-input:focus {{ border-color: var(--ink); }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 8px; padding: 8px 16px 0; max-width: 1320px; margin: 0 auto; }}
    .stat {{ border: 1px solid var(--border); border-radius: 3px; background: var(--surface); padding: 9px 12px; }}
    .stat .v {{ font-family: var(--mono); font-size: 24px; line-height: 1.1; color: var(--ink); }}
    .stat .l {{ font-family: var(--mono); font-size: 10px; color: var(--sub); text-transform: uppercase; margin-top: 2px; }}
    .main {{ max-width: 1320px; margin: 0 auto; padding: 16px 16px 56px; }}
    .section-title {{ font-family: var(--mono); font-size: 11px; color: var(--sub); text-transform: uppercase; margin: 18px 0 10px; }}
    .table-wrap {{ border: 1px solid var(--border); background: var(--surface); border-radius: 3px; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border-l); text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #f3f0ea; color: var(--sub); font-family: var(--mono); font-size: 10px; text-transform: uppercase; z-index: 1; }}
    td {{ font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    .flow-link {{ color: var(--ink); font-weight: 500; text-decoration-thickness: 1px; }}
    .path, .meta, .muted {{ color: var(--sub); font-size: 12px; }}
    .path {{ margin-top: 2px; }}
    .badge {{ display: inline-flex; align-items: center; border: 1px solid var(--border); border-radius: 2px; padding: 1px 7px; font-family: var(--mono); font-size: 10px; text-transform: uppercase; color: var(--ink-light); white-space: nowrap; }}
    .badge.pending {{ color: var(--warn); border-color: var(--warn); background: var(--warn-bg); }}
    .badge.passed {{ color: var(--passed); border-color: var(--passed); background: var(--passed-bg); }}
    .badge.failed {{ color: var(--failed); border-color: var(--failed); background: var(--failed-bg); }}
    .badge.idle {{ color: var(--idle); border-color: var(--idle); background: var(--idle-bg); }}
    .inline-command {{ display: block; max-width: 360px; white-space: normal; overflow-wrap: anywhere; font-family: var(--mono); font-size: 11px; color: var(--ink-light); background: #f1eee8; border: 1px solid var(--border-l); border-radius: 2px; padding: 4px 6px; }}
    .flow-section {{ margin-top: 18px; }}
    .section-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding-bottom: 7px; margin-bottom: 12px; }}
    .section-head h2 {{ font-family: var(--mono); font-size: 13px; text-transform: uppercase; font-weight: 700; }}
    .section-head span {{ font-family: var(--mono); font-size: 10px; color: var(--sub); }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }}
    .flow-card {{ border: 1px solid var(--border); border-radius: 3px; background: var(--surface); padding: 12px; min-width: 0; }}
    .flow-card.status-pending {{ border-style: dashed; }}
    .flow-card.status-failed {{ border-color: rgba(167,55,42,.45); }}
    .card-top {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }}
    .count-pill {{ font-family: var(--mono); font-size: 10px; color: var(--sub); }}
    .flow-card h3 {{ font-size: 15px; font-weight: 500; line-height: 1.25; margin-bottom: 2px; overflow-wrap: anywhere; }}
    .command-row code {{ display: block; margin: 10px 0; padding: 8px; background: #f1eee8; border: 1px solid var(--border-l); border-radius: 2px; font-family: var(--mono); font-size: 11px; line-height: 1.45; white-space: normal; overflow-wrap: anywhere; }}
    .method-list {{ display: flex; flex-direction: column; gap: 2px; color: var(--ink-light); font-size: 12px; }}
    .method-list span {{ overflow-wrap: anywhere; }}
    .links {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; font-family: var(--mono); font-size: 11px; }}
    a {{ color: var(--ink); }}
    .hidden {{ display: none !important; }}
    .empty {{ border: 1px dashed var(--border); background: var(--surface); color: var(--sub); padding: 24px; border-radius: 3px; }}
    @media (max-width: 760px) {{
      .nav {{ align-items: flex-start; height: auto; padding: 12px 16px; flex-direction: column; }}
      .nav-actions {{ justify-content: flex-start; }}
      .toolbar {{ flex-direction: column; align-items: stretch; }}
      .filter-input {{ min-width: 0; width: 100%; }}
      .card-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="nav">
    <div class="brand">KG UITest Review <span class="tag">FLOW</span></div>
    <div class="nav-actions">
      <span class="counts" id="visible-count">{_esc(len(flows))} flow · {_esc(summary.get('totalRuns', 0))} run · {_esc(summary.get('pendingFlows', 0))} pending</span>
      <a class="btn" href="index.json">index</a>
    </div>
  </div>
  <div class="tabs" id="tabs">
    <button class="tab active" data-filter="all">all <span class="n">{_esc(status_counts['all'])}</span></button>
    <button class="tab" data-filter="pending">pending <span class="n">{_esc(status_counts['pending'])}</span></button>
    <button class="tab" data-filter="passed">pass <span class="n">{_esc(status_counts['passed'])}</span></button>
    <button class="tab" data-filter="failed">fail <span class="n">{_esc(status_counts['failed'])}</span></button>
    <button class="tab" data-filter="ran">ran <span class="n">{_esc(status_counts['ran'])}</span></button>
  </div>
  <div class="toolbar">
    <input id="search" class="filter-input" type="search" placeholder="搜尋 flow / file / method / variant">
  </div>
  <section class="stats">
    <div class="stat"><div class="v">{_esc(summary.get('flows', 0))}</div><div class="l">flows</div></div>
    <div class="stat"><div class="v">{_esc(summary.get('pendingFlows', 0))}</div><div class="l">pending</div></div>
    <div class="stat"><div class="v">{_esc(summary.get('totalRuns', 0))}</div><div class="l">runs</div></div>
    <div class="stat"><div class="v">{_esc(summary.get('okRuns', 0))}</div><div class="l">ok</div></div>
    <div class="stat"><div class="v">{_esc(summary.get('failRuns', 0))}</div><div class="l">fail</div></div>
    <div class="stat"><div class="v">{_esc(summary.get('variants', 0))}</div><div class="l">variants</div></div>
  </section>
  <main>
    <section class="main">
      <h2 class="section-title">Flow Inventory</h2>
      <div class="table-wrap">
      <table id="flow-table">
        <thead><tr><th>Flow</th><th>Status</th><th>Last Run</th><th>Runs</th><th>Tests</th><th>Variants</th><th>Command</th></tr></thead>
        <tbody>{flow_rows}</tbody>
      </table>
      </div>
      <h2 class="section-title">Flow Details</h2>
      <div id="empty" class="empty hidden">No flows match the current filter.</div>
      {''.join(flow_sections)}
    </section>
  </main>
  <script>
    const search = document.getElementById('search');
    const tabs = Array.from(document.querySelectorAll('.tab'));
    const rows = Array.from(document.querySelectorAll('.flow-row'));
    const sections = Array.from(document.querySelectorAll('.flow-section'));
    const empty = document.getElementById('empty');
    const visibleCount = document.getElementById('visible-count');
    let activeFilter = 'all';

    function matchesStatus(node) {{
      if (activeFilter === 'all') return true;
      if (activeFilter === 'ran') {{
        const row = rows.find((item) => item.dataset.text && node.dataset.text && item.dataset.text.includes(node.dataset.text.split(' ')[0]));
        return node.dataset.status !== 'pending' || (row && row.children[3] && Number(row.children[3].textContent.trim()) > 0);
      }}
      return node.dataset.status === activeFilter;
    }}

    function applyFilters() {{
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      rows.forEach((row) => {{
        const ok = matchesStatus(row) && (!q || row.dataset.text.toLowerCase().includes(q));
        row.classList.toggle('hidden', !ok);
        if (ok) shown += 1;
      }});
      sections.forEach((section) => {{
        const ok = matchesStatus(section) && (!q || section.dataset.text.toLowerCase().includes(q) || section.textContent.toLowerCase().includes(q));
        section.classList.toggle('hidden', !ok);
      }});
      empty.classList.toggle('hidden', shown !== 0);
      visibleCount.textContent = `${{shown}} flow · {_esc(summary.get('totalRuns', 0))} run · {_esc(summary.get('pendingFlows', 0))} pending`;
    }}

    tabs.forEach((tab) => {{
      tab.addEventListener('click', () => {{
        activeFilter = tab.dataset.filter;
        tabs.forEach((item) => item.classList.toggle('active', item === tab));
        applyFilters();
      }});
    }});
    search.addEventListener('input', applyFilters);
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
