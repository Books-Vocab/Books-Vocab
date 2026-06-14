#!/usr/bin/env -S uv run --python 3.13 --with boto3 python
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
import time
from datetime import datetime
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
            print(
                f"[podcast_ops] cost aggregate failed for workspace={ws.name}; keeping 0.0",
                file=sys.stderr,
            )
        row = {
            "name": s["name"], "status": s["status"],
            "episode_count": s["episode_count"], "progress": s["progress"],
            "total_usd": round(total_usd, 4), "gates": gate_state,
            "last_activity": s.get("last_activity"),
        }
        # Make every non-terminal state actionable: WHY it's there + the exact
        # next command. The #1 dogfood complaint was "failed/awaiting but no clue
        # why or what to do".
        if s["status"] == "failed":
            fs = s.get("failed_stage")
            row["failed_stage"] = fs
            row["failed_at"] = s.get("failed_at")
            row["error"] = s.get("error")
            why = (f"{fs} stage failed" if fs else "unresolved pipeline failure")
            if s.get("error"):
                why += f": {s['error']}"
            row["reason"] = why
            if fs:
                row["next_step"] = (f"cd lab/podcast && uv run pipeline.py "
                                    f"workspaces/{s['name']} --skip-to {fs}")
        elif s["status"] == "awaiting":
            gate = s.get("awaiting_gate") or (
                "plan" if gate_state.get("plan") == "awaiting" else "script")
            row["awaiting_gate"] = gate
            row["reason"] = (
                "plan complete — pending plan-gate approval" if gate == "plan"
                else "scripts complete — pending script-gate approval")
            # Same cwd (lab/podcast) as the failed/idle hints so the line is
            # copy-paste-safe regardless of where the operator stands.
            row["next_step"] = (
                f"cd lab/podcast && touch workspaces/{s['name']}/.{gate}_approved "
                f"&& uv run pipeline.py workspaces/{s['name']}")
        elif s["status"] == "idle":
            # resume_stage is the marker-derived first-incomplete stage, but
            # markers DRIFT (a 81%-done ws can show 'prep' if early markers are
            # missing) — so the advertised command is the BARE auto-resume, which
            # runs the pipeline's own detect_resume_point and re-reads artifacts.
            # resume_stage stays in JSON as the raw marker truth, drift and all.
            row["resume_stage"] = s.get("resume_stage")
            row["reason"] = "artifacts present, pipeline idle — resume to continue"
            row["next_step"] = (f"cd lab/podcast && uv run pipeline.py "
                                f"workspaces/{s['name']}")
        rows.append(row)

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
    # Dedupe (the same 'events.jsonl missing' fires once per workspace) and never
    # truncate silently — say how many were suppressed.
    seen: set[str] = set()
    uniq = [w for w in warnings if not (w in seen or seen.add(w))]
    shown = uniq[:10]
    if len(uniq) > 10:
        shown.append(f"… +{len(uniq) - 10} more distinct warnings (suppressed)")
    return {
        "scope": "all",
        "total_usd": round(total, 4),
        "by_workspace": by_ws,
        "by_model": {m: {"usd": round(v["usd"], 4), "calls": v["calls"]}
                     for m, v in by_model.items()},
        "warnings": shown,
    }


def collect_covers(workspaces_dir: Path) -> dict:
    """Workspaces that have synthesized audio (i.e. are publishable) but lack a
    cover image (plan/cover.png). Pure disk — no S3 needed. Both `present` and
    `missing` are lists (symmetric) so a script can act on either set."""
    missing: list[dict] = []
    present: list[str] = []
    for ws in _iter_workspaces(workspaces_dir):
        if not wss._workspace_has_audio(ws):
            continue
        if (ws / "plan" / "cover.png").exists():
            present.append(ws.name)
        else:
            missing.append({"workspace": ws.name, "reason": "no_cover_png"})
    return {"missing": missing, "present": present}


def collect_logs(ws: Path, last: int = 20, errors_only: bool = False) -> dict:
    """The last *last* meaningful pipeline_log events for one workspace —
    stage_start / stage_end / error / gate_wait (info noise dropped). This is the
    headless `tail pipeline_log.jsonl | jq` an operator reached for after seeing a
    'failed' status: the error msg + ts that say WHY, without leaving the CLI."""
    plog = ws / "pipeline_log.jsonl"
    tail = wss._read_tail(plog)
    keep = {"error"} if errors_only else {"stage_start", "stage_end", "error", "gate_wait"}
    events = [obj for _i, obj in wss._iter_log(tail)
              if obj.get("event") in keep] if tail else []
    return {"workspace": ws.name, "events": events[-last:]}


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


def _rel_age(ts_iso: str | None) -> str:
    """Compact 'time since' for a pipeline_log ISO timestamp ('3d' / '2h' / '5m'
    / 'now'), or '-' when there's no activity to age."""
    if not ts_iso:
        return "-"
    try:
        delta = time.time() - datetime.fromisoformat(ts_iso).timestamp()
    except ValueError:
        log.warning("Silently handled exception; using fallback response", exc_info=True)
        return "-"
    if delta < 60:
        return "now"
    for unit, secs in (("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= secs:
            return f"{int(delta // secs)}{unit}"
    return "now"


def _print_status(out: dict) -> None:
    rows = out["workspaces"]
    s = out["summary"]
    print(f"podcast workspaces ({out['workspaces_dir']}) — {s['total']} total, "
          f"${s['total_usd']:.2f}")
    if not rows:
        print("  (none)")
        return
    # AUD = episodes with synthesized audio (NOT total planned — dogfood found the
    # old 'EPS' header read as a total). AGE = since last pipeline_log activity.
    print(f"  {'STATUS':<9}{'AUD':>4}  {'PROG':>5}  {'COST':>8}  {'AGE':>5}  "
          f"{'GATES(plan/script)':<20} NAME")
    for r in sorted(rows, key=lambda x: x["name"]):
        g = r.get("gates", {})
        gates = f"{g.get('plan','-')}/{g.get('script','-')}"
        glyph = _STATUS_GLYPH.get(r["status"], "?")
        print(f"  {glyph} {r['status']:<7}{r['episode_count']:>4}  "
              f"{r['progress']*100:>4.0f}%  ${r['total_usd']:>6.2f}  "
              f"{_rel_age(r.get('last_activity')):>5}  {gates:<20} {r['name']}")
    # Every non-terminal row gets a WHY line + a copy-pasteable next command.
    for r in sorted(rows, key=lambda x: x["name"]):
        if r["status"] in ("failed", "awaiting", "idle") and (
                r.get("reason") or r.get("next_step")):
            mark = "✗" if r["status"] == "failed" else "⏳" if r["status"] == "awaiting" else "·"
            print(f"  {mark} {r['name']}: {r.get('reason', r['status'])}")
            if r.get("next_step"):
                print(f"      → {r['next_step']}")


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
    print(f"covers — {len(out['present'])} present, {len(out['missing'])} missing")
    for m in out["missing"]:
        print(f"  ✗ {m['workspace']}")


def _print_logs(out: dict) -> None:
    print(f"logs — {out['workspace']} (last {len(out['events'])})")
    if not out["events"]:
        print("  (no pipeline_log.jsonl)")
        return
    for e in out["events"]:
        ev = e.get("event", "?")
        ts = e.get("ts", "")
        if ev == "stage_end":
            tag = "OK " if e.get("success", True) else "FAIL"
            detail = f"{tag} {e.get('stage','?')} ({e.get('elapsed_s','?')}s)"
        elif ev == "error":
            detail = f"ERROR {e.get('msg','')}"
        elif ev == "gate_wait":
            detail = f"GATE  {e.get('phase','?')} (before {e.get('stage','?')})"
        else:
            detail = f"{ev} {e.get('stage', e.get('msg',''))}"
        print(f"  {ts}  {detail}")


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


def _fail(msg: str, as_json: bool, rc: int = 3) -> int:
    """Emit an error honouring the --json contract: structured JSON to stdout in
    JSON mode (so `| jq` never chokes on an empty stdout), human text to stderr
    otherwise. Returns rc for the caller to propagate."""
    if as_json:
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    else:
        print(f"✗ {msg}", file=sys.stderr)
    return rc


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
    lg = sub.add_parser("logs", parents=[common],
                        help="last pipeline_log events for one workspace (the WHY)")
    lg.add_argument("workspace", help="workspace name")
    lg.add_argument("--last", type=int, default=20, help="number of events (default 20)")
    lg.add_argument("--errors-only", action="store_true", help="only error events")
    sub.add_parser("reconcile", parents=[common],
                   help="synthesized-but-unpublished drift vs S3 (needs PODCAST_BUCKET + boto3)")
    sub.add_parser("series", parents=[common],
                   help="published S3 catalog listing (needs PODCAST_BUCKET + boto3)")
    args = ap.parse_args(argv)

    wsdir: Path = args.workspaces_dir
    # P0: a non-existent workspaces-dir must hard-fail, never fake '0 total, ok'.
    # (An existing-but-empty dir is legitimately 0 and still exits 0.)
    if not wsdir.exists():
        return _fail(f"workspaces-dir not found: {wsdir}", args.json, rc=3)

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
            return _fail(f"workspace not found: {args.workspace}", args.json)
        _emit(collect_episodes(ws), args.json, _print_episodes)
        return 0

    if args.cmd == "cost":
        if args.workspace and not (wsdir / args.workspace).is_dir():
            return _fail(f"workspace not found: {args.workspace}", args.json)
        _emit(collect_cost(wsdir, args.workspace), args.json, _print_cost)
        return 0

    if args.cmd == "covers":
        _emit(collect_covers(wsdir), args.json, _print_covers)
        return 0

    if args.cmd == "logs":
        ws = wsdir / args.workspace
        if not ws.is_dir():
            return _fail(f"workspace not found: {args.workspace}", args.json)
        _emit(collect_logs(ws, last=args.last, errors_only=args.errors_only),
              args.json, _print_logs)
        return 0

    # S3-backed commands — degrade cleanly when boto3/PODCAST_BUCKET absent.
    try:
        if args.cmd == "reconcile":
            _emit(collect_reconcile(wsdir), args.json, _print_reconcile)
        elif args.cmd == "series":
            _emit(collect_series(), args.json, _print_series)
    except Exception as exc:  # noqa: BLE001 — RemoteError/ImportError → clean exit
        log.warning("Silently handled exception; using fallback response", exc_info=True)
        return _fail(f"{args.cmd} failed (S3/boto3): {exc}", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
