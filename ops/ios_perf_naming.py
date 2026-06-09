#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Performance Baseline Naming Contract — single source of truth (test/ops side).

This module defines the metric-name grammar that the iOS test harness and the
log-assertion parser (`ios_log_assert.py`) agree on. It does NOT touch the app:
nothing here emits metrics; it only *names* and *validates* them, so every
feature stops inventing its own ad-hoc bucket.

    Grammar:  feature.scenario.action.metric   (exactly 4 lowerCamel segments)

    Examples:
        podcast.player.play.readyLatency
        reader.open.firstPaint
        notebook.list.scroll.frames

Segment rules:
  - exactly 4 dot-separated segments
  - each segment matches  [a-z][a-zA-Z0-9]*  (lowerCamelCase, no underscores)
  - `feature` (segment 1) SHOULD be one of KNOWN_FEATURES; `strict=True` enforces it
  - `metric` (segment 4) is classified into a bucket (frame / latency / count)
    by suffix so the parser can route it to the right summary surface

CLI:
    ios_perf_naming.py validate <name> [<name> ...]   # exit 1 if any invalid
    ios_perf_naming.py validate --strict <name> ...     # also gate feature registry
    ios_perf_naming.py list-features
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

# Feature registry — aligned with the iOS feature_boundary surfaces / tab set.
# Adding a new feature here is the deliberate, reviewed way to widen the contract.
KNOWN_FEATURES: frozenset[str] = frozenset({
    "app",         # shell / lifecycle / launch
    "bookshelf",   # 書庫 tab
    "reader",      # EPUB/PDF reader
    "vocabulary",  # 單字 / today-review / KG
    "notebook",    # 單字本
    "podcast",     # 播客 player / series
    "settings",    # 設定
    "sync",        # backend sync lifecycle
    "overview",    # 總覽 / stats
})

SEGMENT_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")

# Metric-bucket classification by camelCase WORD membership (not substring —
# `ms` must not leak into `items`, `time` must not leak into `runtime`). The
# metric leaf is split on camelCase / digit boundaries into whole words, then
# matched against these sets. Order matters: frame signals win over latency.
_FRAME_WORDS = frozenset({
    "frame", "frames", "hitch", "hitches", "fps", "jank", "drop", "drops", "dropped",
})
_LATENCY_WORDS = frozenset({
    "latency", "paint", "duration", "ms", "time", "elapsed",
})

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _words(metric: str) -> list[str]:
    """Split a camelCase/digit metric leaf into lowercased whole words.

    'firstPaint' -> ['first', 'paint']; 'durationMs' -> ['duration', 'ms'];
    'readyLatency' -> ['ready', 'latency']; 'itemsCount' -> ['items', 'count'].
    """
    return [w.lower() for w in _WORD_RE.findall(metric)]


def classify_metric(metric: str) -> str:
    """Return the bucket for a metric leaf: 'frame' | 'latency' | 'count'."""
    words = set(_words(metric))
    if words & _FRAME_WORDS:
        return "frame"
    if words & _LATENCY_WORDS:
        return "latency"
    return "count"


@dataclass(frozen=True)
class MetricName:
    feature: str
    scenario: str
    action: str
    metric: str
    kind: str  # frame | latency | count

    @property
    def name(self) -> str:
        return f"{self.feature}.{self.scenario}.{self.action}.{self.metric}"

    @property
    def feature_known(self) -> bool:
        return self.feature in KNOWN_FEATURES


def parse(name: str, *, strict: bool = False) -> MetricName:
    """Parse/validate a metric name. Raise ValueError on any grammar violation.

    With strict=True the feature segment must be in KNOWN_FEATURES.
    """
    parts = name.split(".")
    if len(parts) != 4:
        raise ValueError(
            f"metric name must have exactly 4 segments "
            f"(feature.scenario.action.metric), got {len(parts)}: {name!r}"
        )
    for seg in parts:
        if not SEGMENT_RE.match(seg):
            raise ValueError(
                f"segment {seg!r} in {name!r} must match [a-z][a-zA-Z0-9]* "
                f"(lowerCamelCase, no underscores)"
            )
    feature, scenario, action, metric = parts
    if strict and feature not in KNOWN_FEATURES:
        raise ValueError(
            f"unknown feature {feature!r} (strict): not in {sorted(KNOWN_FEATURES)}"
        )
    return MetricName(feature, scenario, action, metric, classify_metric(metric))


def is_valid(name: str, *, strict: bool = False) -> bool:
    try:
        parse(name, strict=strict)
        return True
    except ValueError:
        return False


# Detect a dotted metric token (optionally `=<num><unit>` or `:<num>`) inside a
# free-form log message. Used by ios_log_assert.py. Unit is optional.
# Boundary-anchored so an over-long dotted path (5+ segments) or a dotted prefix
# FAILS to match rather than silently truncating to the first/last 4 segments:
#   (?<![\w.]) — no word-char or dot immediately before the first segment
#   (?![\w.])  — no word-char or dot immediately after the 4th segment
#                (the optional `=value` starts with `=`/`:`/space, so it still
#                 matches; a 5th `.segment` is rejected).
METRIC_TOKEN_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<name>[a-z][a-zA-Z0-9]*(?:\.[a-z][a-zA-Z0-9]*){3})"
    r"(?![\w.])"
    r"(?:\s*[=:]\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>ms|s|fps|%)?)?"
)


def _cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Performance Baseline Naming Contract")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate one or more metric names")
    v.add_argument("names", nargs="+")
    v.add_argument("--strict", action="store_true", help="also gate feature registry")
    sub.add_parser("list-features", help="print the known feature registry")
    args = ap.parse_args(argv)

    if args.cmd == "list-features":
        for f in sorted(KNOWN_FEATURES):
            print(f)
        return 0

    bad = 0
    for name in args.names:
        try:
            m = parse(name, strict=args.strict)
            print(f"  ✓ {m.name}  [{m.kind}]" + ("" if m.feature_known else "  (feature not in registry)"))
        except ValueError as exc:
            print(f"  ✗ {name}: {exc}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
