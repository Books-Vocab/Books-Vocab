#!/usr/bin/env bash
# test_ui_quality_gate.sh — behavior tests for ops/ui_quality_gate.sh.
#
# Covers: dry-run plan, execute fast static gates, tier filtering, JSON report,
# and graceful handling of a missing injection baseline.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi

GATE="./ops/ui_quality_gate.sh"

pass=0
fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

SAMPLE_FILE="ios/BooksAndVocab/Views/Vocabulary/Components/VocabCalendarGrid.swift"
NOIMPACT_FILE="docs/sop/ios.md"

section "Script existence and syntax"
if [[ -x "$GATE" ]]; then
  ok "ui_quality_gate.sh exists and is executable"
else
  fail_t "ui_quality_gate.sh missing or not executable"
fi
if bash -n "$GATE"; then
  ok "ui_quality_gate.sh syntax OK"
else
  fail_t "ui_quality_gate.sh syntax failed"
fi
if [[ -f "ops/ui_quality_gate.py" ]]; then
  ok "ui_quality_gate.py exists"
else
  fail_t "ui_quality_gate.py missing"
fi

section "Dry-run fast tier lists the static gates"
OUT="$($GATE --files "$SAMPLE_FILE" --tier fast --dry-run 2>&1)"
RC=$?
if [[ "$RC" -eq 0 ]]; then
  ok "dry-run exits 0"
else
  fail_t "dry-run exited $RC"
fi
for id in static.ui_token static.plain_deadzone static.i18n static.catalyst static.injection; do
  if grep -q "$id" <<<"$OUT"; then
    ok "dry-run lists $id"
  else
    fail_t "dry-run missing $id"
  fi
done
if grep -q '\[DRY-RUN\]' <<<"$OUT"; then
  ok "dry-run marks commands with [DRY-RUN]"
else
  fail_t "dry-run missing [DRY-RUN] marker"
fi

section "Execute fast tier passes on current source"
OUT="$($GATE --files "$SAMPLE_FILE" --tier fast --execute 2>&1)"
RC=$?
if [[ "$RC" -eq 0 ]]; then
  ok "execute fast tier exits 0"
else
  fail_t "execute fast tier exited $RC: $OUT"
fi
for id in static.ui_token static.plain_deadzone static.i18n static.catalyst; do
  if grep -q "${id}.*\(PASS\|passed\|ok\)" <<<"$OUT" || grep -q "${id}.*status.*pass" <<<"$OUT"; then
    ok "execute reports $id passed"
  else
    fail_t "execute did not report $id passed"
  fi
done

section "Dry-run slow tier does not run heavy commands"
OUT="$($GATE --files "$SAMPLE_FILE" --tier slow --dry-run 2>&1)"
RC=$?
if [[ "$RC" -eq 0 ]]; then
  ok "slow dry-run exits 0"
else
  fail_t "slow dry-run exited $RC"
fi
for id in structure.ui_deadcode perf.review_flip_probe visual.catalog_regression; do
  if grep -q "$id" <<<"$OUT"; then
    ok "slow tier lists $id"
  else
    fail_t "slow tier missing $id"
  fi
done
if grep -q '\[DRY-RUN\]' <<<"$OUT"; then
  ok "slow tier marks commands with [DRY-RUN]"
else
  fail_t "slow tier missing [DRY-RUN] marker"
fi
if grep -q -- '--dataset marketing_demo' <<<"$OUT"; then
  fail_t "slow tier should not inject marketing_demo without an explicit UI World: $OUT"
else
  ok "slow tier does not silently inject marketing_demo"
fi
if grep -q 'requires --dataset' <<<"$OUT"; then
  ok "slow tier explains UI World dataset requirement"
else
  fail_t "slow tier missing UI World requirement warning: $OUT"
fi

section "Slow UI World gates use explicit dataset"
OUT="$($GATE --files "$SAMPLE_FILE" --tier slow --dry-run --dataset marketing_demo 2>&1)"
if grep -q -- '--dataset marketing_demo' <<<"$OUT"; then
  ok "explicit --dataset is forwarded to slow UI World gates"
else
  fail_t "explicit --dataset was not forwarded: $OUT"
fi

section "Invalid UI World dataset fails before planning"
BAD_DATASET="$(mktemp)"
printf '{"schema":"kg.fixture.dataset.v1","datasetID":"bad"}\n' >"$BAD_DATASET"
OUT="$($GATE --files "$SAMPLE_FILE" --tier slow --dry-run --dataset-file "$BAD_DATASET" 2>&1)"
RC=$?
rm -f "$BAD_DATASET"
if [[ "$RC" -ne 0 ]] && grep -q 'schema 必須是 kg.fixture.dataset.v2' <<<"$OUT"; then
  ok "invalid --dataset-file is rejected before dry-run plan"
else
  fail_t "invalid --dataset-file was not rejected: rc=$RC out=$OUT"
fi

section "Execute-slow without UI World fails before running those gates"
JSON="$($GATE --files ops/review_flip_probe.sh --tier slow --execute --execute-slow --json 2>&1)"
RC=$?
if [[ "$RC" -eq 1 ]]; then
  ok "execute-slow without dataset exits non-zero"
else
  fail_t "execute-slow without dataset exited $RC: $JSON"
fi
if jq -e '.results[] | select(.id == "perf.review_flip_probe" and .status == "failed" and (.warning | contains("requires --dataset")))' <<<"$JSON" >/dev/null 2>&1; then
  ok "execute-slow reports missing UI World as failed gate"
else
  fail_t "execute-slow missing dataset failure payload: $JSON"
fi

section "No-impact file yields empty plan"
OUT="$($GATE --files "$NOIMPACT_FILE" --tier all --dry-run 2>&1)"
RC=$?
if [[ "$RC" -eq 0 ]]; then
  ok "no-impact dry-run exits 0"
else
  fail_t "no-impact dry-run exited $RC"
fi
if grep -qi 'no.*mechanism\|triggered\|impact' <<<"$OUT"; then
  ok "no-impact output mentions no mechanisms"
else
  fail_t "no-impact output unclear: $OUT"
fi

section "JSON output is well-formed"
JSON="$($GATE --files "$SAMPLE_FILE" --tier fast --dry-run --json 2>&1)"
if jq -e '.results | type == "array"' <<<"$JSON" >/dev/null 2>&1; then
  ok "JSON has results array"
else
  fail_t "JSON missing results array: $JSON"
fi
if jq -e '.summary.planned > 0' <<<"$JSON" >/dev/null 2>&1; then
  ok "JSON summary.planned > 0"
else
  fail_t "JSON summary.planned not positive"
fi

section "Missing injection baseline is handled gracefully"
# Move the real baseline aside, run execute, then restore.
BASE="ops/injection_baseline.txt"
MOVED=""
if [[ -f "$BASE" ]]; then
  MOVED="$(mktemp)"
  mv "$BASE" "$MOVED"
fi
restore() {
  if [[ -n "$MOVED" && -f "$MOVED" ]]; then
    mv "$MOVED" "$BASE"
  fi
}
trap restore EXIT
OUT="$($GATE --files "$SAMPLE_FILE" --tier fast --execute 2>&1)"
RC=$?
if [[ "$RC" -eq 0 ]]; then
  ok "execute fast tier still exits 0 when injection baseline missing"
else
  fail_t "execute fast tier failed with missing injection baseline: $OUT"
fi
if grep -qi 'injection_baseline\|missing baseline\|WARN' <<<"$OUT"; then
  ok "output warns about missing injection baseline"
else
  fail_t "no warning about missing injection baseline: $OUT"
fi
restore

section "--tier all dry-run includes fast and slow"
OUT="$($GATE --files "$SAMPLE_FILE" --tier all --dry-run 2>&1)"
if grep -q 'static.ui_token' <<<"$OUT" && grep -q 'structure.ui_deadcode' <<<"$OUT"; then
  ok "all tier lists both fast and slow mechanisms"
else
  fail_t "all tier missing fast or slow mechanisms"
fi

section "--include-ci includes ci gates"
OUT="$($GATE --files design-system/tokens.json --tier fast --dry-run 2>&1)"
if grep -q 'value.design_system' <<<"$OUT"; then
  ok "--include-ci lists value.design_system"
else
  fail_t "--include-ci missing value.design_system: $OUT"
fi

section "--exclude skips specified gate"
OUT="$($GATE --files "$SAMPLE_FILE" --tier fast --dry-run --exclude static.ui_token 2>&1)"
if grep -q 'static.ui_token' <<<"$OUT" && grep -q 'excluded' <<<"$OUT"; then
  ok "--exclude marks static.ui_token as excluded"
else
  fail_t "--exclude did not skip static.ui_token: $OUT"
fi

section "slow tier with --execute but no --execute-slow prints hint"
OUT="$($GATE --files "$SAMPLE_FILE" --tier slow --execute 2>&1)"
if grep -qi 'hint.*--execute-slow' <<<"$OUT"; then
  ok "slow execute prints --execute-slow hint"
else
  fail_t "slow execute missing hint: $OUT"
fi

echo ""
echo "ui-quality-gate: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
