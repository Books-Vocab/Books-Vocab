#!/usr/bin/env bash
# ios_run_metrics.sh — append-only run-metrics log for build/test/release.
#
# Each invocation appends ONE compact JSONL line (timestamp + verdict timings)
# to <main-repo>/.cache/ios-run-metrics.jsonl. This is the data source for
# answering "is the global build lock actually a bottleneck?" — the per-run
# verdict files only keep the last run, so without this there is no history of
# lockWaitMs under real multi-agent usage.
#
# Hard rule: logging must NEVER fail the caller. Every step degrades to a no-op.

append_run_metric() {
  local verdict_json="$1"
  [[ -f "$verdict_json" ]] || return 0
  command -v jq >/dev/null 2>&1 || return 0

  local anchor common root metrics_file ts
  anchor="${PROJECT_ROOT:-${ROOT:-$PWD}}"
  common="$(git -C "$anchor" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$common" && -d "$common" ]]; then
    root="$(dirname "$common")"
  else
    root="$anchor"
  fi

  metrics_file="$root/.cache/ios-run-metrics.jsonl"
  mkdir -p "$root/.cache" 2>/dev/null || return 0
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || return 0

  jq -c --arg ts "$ts" '{
    ts: $ts,
    kind: (.kind // (.schema // "" | sub("^kg\\.ios\\.";"") | sub("\\..*$";""))),
    result: .result,
    caller: .caller,
    cache: (.cache.status? // null),
    timings: .timings
  }' "$verdict_json" >>"$metrics_file" 2>/dev/null || true
}
