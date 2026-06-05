#!/usr/bin/env python3
"""Headless podcast-pipeline observability CLI.

The podcast monitor's observability logic (status cascade, per-episode gates,
cost aggregation, workspace↔S3 drift) historically lived ONLY behind the FastAPI
dashboard (lab/podcast/monitor/server.py) — you had to start uvicorn and curl to
learn anything. This CLI exposes the same disk-derived truth headlessly: usable
over SSH, in cron, piped to jq. It imports the dashboard's pure primitives
(monitor/workspace_status.py, monitor/cost.py) so there is no second
implementation to drift.

Subcommands:
  status      per-workspace status / episode count / progress / cost (pure disk)
  episodes    per-episode gate matrix (plan/script/audio/subtitle) for one ws
  cost        TTS + LLM spend, per-workspace or aggregate (pure disk)
  covers      workspaces with synthesized audio but no plan/cover.png (pure disk)
  reconcile   synthesized-but-unpublished drift vs the S3 catalog (needs boto3)
  series      published S3 catalog listing (needs boto3)

JSON contract (mirrors ops_cli / infra_health): with --json, stdout carries ONLY
the JSON document (parseable with zero preamble); all banners/diagnostics go to
stderr.

Exit codes for `status` give cron a health signal:
  0 = all workspaces ok      1 = some awaiting an approval gate
  2 = some failed            3 = collection error (e.g. S3 unreachable)

Run:
  uv run --no-project --with boto3 python ops/podcast_ops.py status
  uv run --no-project --with boto3 python ops/podcast_ops.py cost --json | jq .
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the dashboard's pure primitives. monitor/ holds cost.py +
# workspace_status.py (both stdlib-only); remote.py is imported lazily inside the
# S3 subcommands so this CLI runs without boto3 for the pure-disk commands.
_REPO = Path(__file__).resolve().parents[1]
_PODCAST = _REPO / "lab" / "podcast"
_MONITOR = _PODCAST / "monitor"
for _p in (_PODCAST, _MONITOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import workspace_status as wss  # noqa: E402
from cost import aggregate_workspace  # noqa: E402

DEFAULT_WORKSPACES = _PODCAST / "workspaces"


# ─── Collection (pure functions — the testable core) ─────────────────────────

def _iter_workspaces(workspaces_dir: Path) -> list[Path]:
    if not workspaces_dir.exists():
        return []
    return sorted(p for p in workspaces_dir.iterdir() if p.is_dir())


def collect_status(workspaces_dir: Path) -> dict:
    """Disk-derived status + episode count + progress + total cost per workspace,
    plus a roll-up summary. Never raises on a bad workspace — one broken dir must
    not blind the whole report."""
    rows: list[dict] = []
    for ws in _iter_workspaces(workspaces_dir):
        try:
            s = wss.headless_summary(ws)
        except Exception as exc:  # noqa: BLE001 — degrade, never blind the report
            rows.append({
                "name": ws.name, "status": "error", "episode_count": 0,
                "progress": 0.0, "total_usd": 0.0,
                "gates": {}, "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        gate_state = {g["key"]: g["state"] for g in s["gates"]}
        total_usd = 0.0
        try:
            total_usd = float(aggregate_workspace(ws).get("total_usd") or 0.0)
        except Exception:  # noqa: BLE001 — cost is best-effort, status still stands
            pass
        rows.append({
            "name": s["name"], "status": s["status"],
            "episode_count": s["episode_count"], "progress": s["progress"],
            "total_usd": round(total_usd, 4), "gates": gate_state,
        })

    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {
        "workspaces_dir": str(workspaces_dir),
        "workspaces": rows,
        "summary": {
            "total": len(rows),
            "by_status": by_status,
            "total_usd": round(sum(r["total_usd"] for r in rows), 4),
        },
    }


def collect_episodes(ws: Path) -> dict:
    """Per-episode gate matrix for a single workspace."""
    return {"workspace": ws.name, "episodes": wss._episode_status(ws)}


def collect_cost(workspaces_dir: Path, workspace: str | None = None) -> dict:
    """TTS+LLM spend. Single workspace → full per-stage/model breakdown.
    Aggregate → per-workspace totals (desc) + per-model roll-up across all."""
    if workspace:
        agg = aggregate_workspace(workspaces_dir / workspace)
        return {
            "scope": workspace,
            "total_usd": agg.get("total_usd", 0.0),
            "by_stage": agg.get("by_stage", {}),
            "by_model": agg.get("by_model", {}),
            "warnings": agg.get("warnings", []),
        }

    by_ws: list[dict] = []
    by_model: dict[str, dict] = {}
    total = 0.0
    warnings: list[str] = []
    for ws in _iter_workspaces(workspaces_dir):
        agg = aggregate_workspace(ws)
        usd = float(agg.get("total_usd") or 0.0)
        total += usd
        by_ws.append({"workspace": ws.name, "total_usd": round(usd, 4)})
        for model, mb in (agg.get("by_model") or {}).items():
            acc = by_model.setdefault(model, {"usd": 0.0, "calls": 0})
            acc["usd"] += float(mb.get("usd") or 0.0)
            acc["calls"] += int(mb.get("calls") or 0)
        warnings.extend(agg.get("warnings", []))
    by_ws.sort(key=lambda r: r["total_usd"], reverse=True)
    return {
        "scope": "all",
        "total_usd": round(total, 4),
        "by_workspace": by_ws,
        "by_model": {m: {"usd": round(v["usd"], 4), "calls": v["calls"]}
                     for m, v in by_model.items()},
        "warnings": warnings[:10],
    }


def collect_covers(workspaces_dir: Path) -> dict:
    """Workspaces that have synthesized audio (i.e. are publishable) but lack a
    cover image (plan/cover.png). Pure disk — no S3 needed."""
    missing: list[dict] = []
    present = 0
    for ws in _iter_workspaces(workspaces_dir):
        if not wss._workspace_has_audio(ws):
            continue
        if (ws / "plan" / "cover.png").exists():
            present += 1
        else:
            missing.append({"workspace": ws.name, "reason": "no_cover_png"})
    return {"missing": missing, "present": present}


def collect_reconcile(workspaces_dir: Path) -> dict:
    """Synthesized-but-unpublished drift: workspaces with audio whose series id
    is absent from the S3 catalog. Needs boto3 + PODCAST_BUCKET (raises cleanly
    via remote.RemoteError otherwise)."""
    import remote  # lazy: only this path needs boto3
    series = remote.list_remote_series()
    published = {e.get("id") for e in series if isinstance(e, dict)}
    drifted = wss.reconcile_workspaces(workspaces_dir, published)
    return {"drifted": drifted, "publishedCount": len(published)}


def collect_series() -> dict:
    """Published S3 catalog (index.json + per-series byte size + orphan flags)."""
    import remote  # lazy
    return {"series": remote.list_remote_series(),
            "usage": remote.remote_disk_usage()}


# ─── Text rendering (human stdout for non-JSON mode) ─────────────────────────

_STATUS_GLYPH = {
    "running": "▶", "done": "✓", "failed": "✗", "awaiting": "⏳",
    "idle": "·", "fresh": "○", "error": "⚠",
}


def _print_status(out: dict) -> None:
    rows = out["workspaces"]
    s = out["summary"]
    print(f"podcast workspaces ({out['workspaces_dir']}) — {s['total']} total, "
          f"${s['total_usd']:.2f}")
    if not rows:
        print("  (none)")
        return
    print(f"  {'STATUS':<9}{'EPS':>4}  {'PROG':>5}  {'COST':>8}  "
          f"{'GATES p/s':<14} NAME")
    for r in sorted(rows, key=lambda x: x["name"]):
        g = r.get("gates", {})
        gates = f"{g.get('plan','-')}/{g.get('script','-')}"
        glyph = _STATUS_GLYPH.get(r["status"], "?")
        print(f"  {glyph} {r['status']:<7}{r['episode_count']:>4}  "
              f"{r['progress']*100:>4.0f}%  ${r['total_usd']:>6.2f}  "
              f"{gates:<14} {r['name']}")
    failed = [r["name"] for r in rows if r["status"] == "failed"]
    awaiting = [r["name"] for r in rows if r["status"] == "awaiting"]
    if failed:
        print(f"  ✗ {len(failed)} failed: {', '.join(failed)}")
    if awaiting:
        print(f"  ⏳ {len(awaiting)} awaiting approval: {', '.join(awaiting)}")


def _print_episodes(out: dict) -> None:
    print(f"episodes — {out['workspace']}")
    eps = out["episodes"]
    if not eps:
        print("  (no episodes)")
        return
    print(f"  {'EP':>3}  PLAN SCRIPT AUDIO SUBTITLE  VARIANT")
    for e in eps:
        def mk(b):  # noqa: E306
            return "  ✓ " if b else "  · "
        print(f"  {e['ep']:>3}  {mk(e['plan'])} {mk(e['script'])} {mk(e['audio'])}"
              f"  {mk(e['subtitle'])}    {e.get('variant') or '-'}")


def _print_cost(out: dict) -> None:
    if out["scope"] == "all":
        print(f"podcast cost — all workspaces: ${out['total_usd']:.4f}")
        for r in out["by_workspace"]:
            if r["total_usd"] > 0:
                print(f"  ${r['total_usd']:>9.4f}  {r['workspace']}")
        if out.get("by_model"):
            print("  by model:")
            for m, v in sorted(out["by_model"].items(),
                               key=lambda kv: kv[1]["usd"], reverse=True):
                print(f"    ${v['usd']:>9.4f}  {m}  ({v['calls']} calls)")
    else:
        print(f"podcast cost — {out['scope']}: ${out['total_usd']:.4f}")
        for stage, b in out.get("by_stage", {}).items():
            print(f"  ${float(b.get('usd', 0)):>9.4f}  {stage}")
    for w in out.get("warnings", []):
        print(f"  ⚠ {w}", file=sys.stderr)


def _print_covers(out: dict) -> None:
    print(f"covers — {out['present']} present, {len(out['missing'])} missing")
    for m in out["missing"]:
        print(f"  ✗ {m['workspace']}")


def _print_reconcile(out: dict) -> None:
    d = out["drifted"]
    print(f"reconcile — {out['publishedCount']} published, {len(d)} drifted "
          f"(synthesized but not on S3)")
    for x in d:
        print(f"  ✗ {x['workspace']}")


def _print_series(out: dict) -> None:
    u = out["usage"]
    print(f"S3 catalog — {len(out['series'])} series, "
          f"{u['used_bytes'] / 1024 / 1024:.1f} MB / {u['use_percent']}")
    for s in out["series"]:
        flag = " [orphan]" if s.get("orphan") else ""
        size = s.get("sizeBytes", 0) / 1024 / 1024
        print(f"  {size:>7.1f} MB  {s.get('id', '?')}{flag}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _emit(payload: dict, as_json: bool, printer) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        printer(payload)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="podcast_ops", description="Headless podcast pipeline observability")
    # Common options live on a parent so they're accepted AFTER the subcommand
    # (git-style: `podcast_ops status --json`), the form operators reach for.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspaces-dir", type=Path, default=DEFAULT_WORKSPACES,
                        help=f"workspaces root (default: {DEFAULT_WORKSPACES})")
    common.add_argument("--json", action="store_true",
                        help="emit JSON to stdout only")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[common],
                   help="per-workspace status / episodes / progress / cost")
    ep = sub.add_parser("episodes", parents=[common],
                        help="per-episode gate matrix for one workspace")
    ep.add_argument("workspace", help="workspace name")
    cp = sub.add_parser("cost", parents=[common],
                        help="TTS + LLM spend (aggregate or single)")
    cp.add_argument("--workspace", help="limit to one workspace (full breakdown)")
    sub.add_parser("covers", parents=[common],
                   help="publishable workspaces missing plan/cover.png")
    sub.add_parser("reconcile", parents=[common],
                   help="synthesized-but-unpublished drift vs S3")
    sub.add_parser("series", parents=[common],
                   help="published S3 catalog listing")
    args = ap.parse_args(argv)

    wsdir: Path = args.workspaces_dir

    if args.cmd == "status":
        out = collect_status(wsdir)
        _emit(out, args.json, _print_status)
        bs = out["summary"]["by_status"]
        if bs.get("failed") or bs.get("error"):
            return 2
        if bs.get("awaiting"):
            return 1
        return 0

    if args.cmd == "episodes":
        ws = wsdir / args.workspace
        if not ws.is_dir():
            print(f"✗ workspace not found: {args.workspace}", file=sys.stderr)
            return 3
        _emit(collect_episodes(ws), args.json, _print_episodes)
        return 0

    if args.cmd == "cost":
        if args.workspace and not (wsdir / args.workspace).is_dir():
            print(f"✗ workspace not found: {args.workspace}", file=sys.stderr)
            return 3
        _emit(collect_cost(wsdir, args.workspace), args.json, _print_cost)
        return 0

    if args.cmd == "covers":
        _emit(collect_covers(wsdir), args.json, _print_covers)
        return 0

    # S3-backed commands — degrade cleanly when boto3/PODCAST_BUCKET absent.
    try:
        if args.cmd == "reconcile":
            _emit(collect_reconcile(wsdir), args.json, _print_reconcile)
        elif args.cmd == "series":
            _emit(collect_series(), args.json, _print_series)
    except Exception as exc:  # noqa: BLE001 — RemoteError/ImportError → clean exit
        print(f"✗ {args.cmd} failed (S3/boto3): {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
