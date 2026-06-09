#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Log Assertion Parser — test/ops-side summariser for iOS runtime logs.

Pure consumer. It never touches the app's logging implementation; it reads what
the device already emits via Apple Unified Logging and folds it into a
feature / category / rate / frame summary that tests and ops can assert on.

Inputs (auto-detected from stdin or --input):
  1. `kg.ios.logs.v1` envelope  — output of `./ops/ios_ops.sh logs --json`
     (an object with `.entries[]`; note its jq projection drops `messageType`,
      so error-rate is unavailable from this source — reported as null).
  2. raw NDJSON                  — `log stream/show --style ndjson` lines
     (one JSON object per line; `messageType` present → error-rate available).
  3. a bare JSON array of event objects.

Metric extraction honours the Performance Baseline Naming Contract
(`ios_perf_naming.py`): any `feature.scenario.action.metric` token in a message
is parsed, optionally with a `=<num><unit>` value, and bucketed by kind.

CLI:
    ./ops/ios_ops.sh logs --json | ./ops/ios_log_assert.py
    ./ops/ios_log_assert.py --input log.ndjson --json
    ... | ./ops/ios_log_assert.py --max-error-rate 0.05 --require-feature podcast
          --min-events 10        # non-zero exit if any assertion fails
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ios_perf_naming", Path(__file__).resolve().parent / "ios_perf_naming.py"
)
naming = importlib.util.module_from_spec(_spec)
sys.modules["ios_perf_naming"] = naming  # dataclass annotation resolution needs this
_spec.loader.exec_module(naming)

SCHEMA = "kg.ios.log-assert.v1"
_ERROR_LEVELS = {"Error", "Fault"}


@dataclass
class Event:
    timestamp: str | None
    subsystem: str | None
    category: str | None
    message: str
    event_type: str | None
    level: str | None  # messageType: Default/Info/Debug/Error/Fault — None if absent


def _event_from_obj(obj: dict) -> Event:
    msg = obj.get("message") or obj.get("eventMessage") or obj.get("formatString") or ""
    return Event(
        timestamp=obj.get("timestamp"),
        subsystem=obj.get("subsystem"),
        category=obj.get("category"),
        message=msg,
        event_type=obj.get("eventType"),
        level=obj.get("messageType"),
    )


def normalize_events(raw: str) -> list[Event]:
    """Auto-detect envelope / array / NDJSON and return a flat Event list.

    Garbage lines in NDJSON are silently skipped (robust against partial streams).
    """
    text = raw.strip()
    if not text:
        return []
    # Try whole-text JSON first (envelope or array or single object).
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = None
    if doc is not None:
        if isinstance(doc, dict) and isinstance(doc.get("entries"), list):
            return [_event_from_obj(e) for e in doc["entries"] if isinstance(e, dict)]
        if isinstance(doc, list):
            return [_event_from_obj(e) for e in doc if isinstance(e, dict)]
        if isinstance(doc, dict):
            return [_event_from_obj(doc)]
    # Fall back to NDJSON, one object per line, skipping unparseable lines.
    events: list[Event] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(_event_from_obj(obj))
    return events


def _count(items) -> dict:
    out: dict[str, int] = {}
    for it in items:
        key = it if it not in (None, "") else "unknown"
        out[key] = out.get(key, 0) + 1
    return out


def extract_metrics(events: list[Event]) -> dict:
    """Scan messages for contract-named metrics, aggregate per name."""
    acc: dict[str, dict] = {}
    for ev in events:
        for m in naming.METRIC_TOKEN_RE.finditer(ev.message):
            name = m.group("name")
            try:
                parsed = naming.parse(name)
            except ValueError:
                continue
            slot = acc.setdefault(name, {
                "kind": parsed.kind,
                "feature": parsed.feature,
                "count": 0,
                "unit": None,
                "_values": [],
            })
            slot["count"] += 1
            val = m.group("value")
            if val is not None:
                slot["_values"].append(float(val))
                if m.group("unit") and slot["unit"] is None:
                    slot["unit"] = m.group("unit")
    # finalise min/max/avg
    out: dict[str, dict] = {}
    for name, slot in acc.items():
        vals = slot.pop("_values")
        if vals:
            slot["min"] = min(vals)
            slot["max"] = max(vals)
            slot["avg"] = round(sum(vals) / len(vals), 4)
        else:
            slot["min"] = slot["max"] = slot["avg"] = None
        out[name] = slot
    return out


def summarize(events: list[Event]) -> dict:
    total = len(events)
    levels = [e.level for e in events if e.level is not None]
    by_level = _count(levels) if levels else None
    if by_level is not None:
        errors = sum(by_level.get(lvl, 0) for lvl in _ERROR_LEVELS)
        error_rate = errors / total if total else 0.0
    else:
        error_rate = None  # source dropped messageType (envelope) → unknown

    metrics = extract_metrics(events)
    frames = {n: a for n, a in metrics.items() if a["kind"] == "frame"}

    # group contract-named metrics by their feature segment
    features: dict[str, dict] = {}
    for name, agg in metrics.items():
        feat = agg["feature"]
        bucket = features.setdefault(feat, {"events": 0, "metrics": {}})
        bucket["metrics"][name] = agg
    # per-feature event count: events whose message carries ≥1 metric of that feature
    for ev in events:
        seen: set[str] = set()
        for m in naming.METRIC_TOKEN_RE.finditer(ev.message):
            try:
                seen.add(naming.parse(m.group("name")).feature)
            except ValueError:
                continue
        for feat in seen:
            if feat in features:
                features[feat]["events"] += 1

    return {
        "schema": SCHEMA,
        "totalEvents": total,
        "byCategory": _count([e.category for e in events]),
        "byEventType": _count([e.event_type for e in events]),
        "byLevel": by_level,
        "errorRate": error_rate,
        "metrics": metrics,
        "frames": frames,
        "features": features,
    }


def run_assertions(
    summary: dict,
    *,
    max_error_rate: float | None = None,
    min_events: int | None = None,
    require_features: list[str] | None = None,
    require_metrics: list[str] | None = None,
) -> list[str]:
    """Return a list of human-readable failure strings ([] == all passed)."""
    failures: list[str] = []
    if max_error_rate is not None:
        rate = summary.get("errorRate")
        if rate is None:
            failures.append(
                "max-error-rate requested but error rate is unavailable "
                "(source has no messageType — use raw ndjson, not the envelope)"
            )
        elif rate > max_error_rate:
            failures.append(f"error rate {rate:.3f} exceeds max {max_error_rate:.3f}")
    if min_events is not None and summary.get("totalEvents", 0) < min_events:
        failures.append(
            f"only {summary.get('totalEvents', 0)} events, expected >= {min_events}"
        )
    for feat in require_features or []:
        if feat not in summary.get("features", {}):
            failures.append(f"required feature {feat!r} has no metrics in the log")
    for name in require_metrics or []:
        if name not in summary.get("metrics", {}):
            failures.append(f"required metric {name!r} not found in the log")
    return failures


def _render_text(summary: dict) -> str:
    lines = [
        f"# {summary['schema']}",
        f"events: {summary['totalEvents']}",
    ]
    rate = summary["errorRate"]
    lines.append(f"errorRate: {'n/a (no messageType)' if rate is None else f'{rate:.3f}'}")
    if summary["byLevel"]:
        lines.append("byLevel: " + ", ".join(f"{k}={v}" for k, v in sorted(summary["byLevel"].items())))
    lines.append("byCategory: " + (", ".join(f"{k}={v}" for k, v in sorted(summary["byCategory"].items())) or "—"))
    if summary["metrics"]:
        lines.append("metrics:")
        for name, a in sorted(summary["metrics"].items()):
            u = a["unit"] or ""
            stat = f"avg={a['avg']}{u} min={a['min']}{u} max={a['max']}{u} n={a['count']}" if a["avg"] is not None else f"n={a['count']} (no values)"
            lines.append(f"  [{a['kind']}] {name}: {stat}")
    else:
        lines.append("metrics: (none matched the naming contract)")
    return "\n".join(lines)


def _cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Log Assertion Parser for iOS runtime logs")
    ap.add_argument("--input", help="read from file instead of stdin")
    ap.add_argument("--json", action="store_true", help="emit the summary as JSON")
    ap.add_argument("--max-error-rate", type=float, default=None)
    ap.add_argument("--min-events", type=int, default=None)
    ap.add_argument("--require-feature", action="append", dest="require_features", default=[])
    ap.add_argument("--require-metric", action="append", dest="require_metrics", default=[])
    args = ap.parse_args(argv)

    raw = Path(args.input).read_text() if args.input else sys.stdin.read()
    summary = summarize(normalize_events(raw))

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(_render_text(summary))

    failures = run_assertions(
        summary,
        max_error_rate=args.max_error_rate,
        min_events=args.min_events,
        require_features=args.require_features,
        require_metrics=args.require_metrics,
    )
    if failures:
        print("\nASSERTION FAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
