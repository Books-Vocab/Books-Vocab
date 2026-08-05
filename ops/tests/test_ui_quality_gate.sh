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
if jq -e '.summary.unrun > 0' <<<"$JSON" >/dev/null 2>&1; then
  ok "JSON summary.unrun > 0"
else
  fail_t "JSON summary.unrun not positive"
fi

section "'nothing was selected' has its own word"
# `planned=0` used to mean both "everything ran" and "nothing matched" — the
# latter is exactly the string CI printed while it no-op'd for two months
# (IMP-0050). `selected` is the plan size and cannot be confused with a
# healthy run; `unrun` counts mechanisms that stayed unexecuted.
if jq -e '(.summary | has("planned")) | not' <<<"$JSON" >/dev/null 2>&1; then
  ok "summary no longer carries the overloaded 'planned' key"
else
  fail_t "summary still has 'planned' — the ambiguous token is back"
fi
ALL_JSON="$($GATE --tier fast --dry-run --all-mechanisms --include-ci --json 2>/dev/null)"
DECLARED_N="$(./ops/ui_quality_plane.py list --json 2>/dev/null | jq 'length')"
# The floor matters: both sides of the comparison come from the same
# `ui_quality_plane.py list --json` call, so on an empty plane DECLARED_N=0,
# selected=0, and the equality would hold while nothing whatsoever was
# selected — the exact reading this change exists to make impossible.
if jq -e --argjson n "$DECLARED_N" '.summary.selected == $n and $n >= 5' <<<"$ALL_JSON" >/dev/null 2>&1; then
  ok "--all-mechanisms selects every declared mechanism ($DECLARED_N)"
else
  fail_t "selected != the $DECLARED_N mechanisms the plane declares: $(jq -c '.summary' <<<"$ALL_JSON")"
fi
# The one non-tautological property here: the five status tallies must
# partition the plan. If a mechanism were ever dropped between `impacted` and
# `results`, selected would exceed the sum and nothing else would notice.
if jq -e '.summary | .selected == (.unrun + .passed + .failed + .warn + .skipped)' <<<"$ALL_JSON" >/dev/null 2>&1; then
  ok "the status tallies partition the plan"
else
  fail_t "tallies do not sum to selected — a mechanism went missing: $(jq -c '.summary' <<<"$ALL_JSON")"
fi
NONE_JSON="$($GATE --files "$NOIMPACT_FILE" --tier all --dry-run --json 2>/dev/null)"
if jq -e '.summary.selected == 0' <<<"$NONE_JSON" >/dev/null 2>&1; then
  ok "a no-trigger file selects 0 mechanisms — distinguishable from a healthy run"
else
  fail_t "no-trigger file did not report selected=0: $(jq -c '.summary' <<<"$NONE_JSON")"
fi

section "A mechanism nothing can run fails the gate, it does not sit unrun"
# The defect this whole change exists for (IMP-0041): the runner kept its own
# command table, so a mechanism declared in the plane but absent from that
# table resolved to no command, was recorded as unrun, and unrun is not
# counted as failed — the gate returned 0. validate now refuses such a
# mechanism, but the runner must not depend on validate having been run: an
# unrunnable mechanism reaching the runner is a failure, not a deferral.
# Cleaned up inline, deliberately not via `trap ... EXIT`: bash keeps one EXIT
# trap and the next section installs its own to put a *version-controlled*
# baseline back (see IMP-0048). Registering a second one here would silently
# replace it and leave the tracked file moved aside.
GHOST_DIR="$(mktemp -d)"
UNRUNNABLE="$GHOST_DIR/unrunnable.yml"
cat >"$UNRUNNABLE" <<'YML'
version: 1
mechanisms:
  - id: static.ghost
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: manual
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
rc=0
GHOST_JSON="$(KG_UI_PLANE_FILE="$UNRUNNABLE" $GATE --tier fast --execute --all-mechanisms --json 2>/dev/null)" || rc=$?
if [[ "$rc" -ne 0 ]] && jq -e '.summary.failed == 1 and .summary.unrun == 0' <<<"$GHOST_JSON" >/dev/null 2>&1; then
  ok "an unrunnable mechanism is failed (rc=$rc), not parked as unrun"
else
  fail_t "unrunnable mechanism did not fail the gate: rc=$rc summary=$(jq -c '.summary' <<<"$GHOST_JSON" 2>/dev/null)"
fi
rm -rf "$GHOST_DIR"

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


# ── The three silent-green paths (2026-08-03) ──────────────────────────────
section "Mode must be explicit"
# `--dry-run` was declared default=True and never read; the real switch was
# `--execute` being opt-in, so a caller that forgot it got a green no-op.
rc=0; "$GATE" --files "$SAMPLE_FILE" --tier fast >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 2 ]] && ok "bare invocation is a usage error (exit 2)" \
  || fail_t "bare invocation exited $rc — a forgotten --execute still looks like a run"

section "A warning may soften a green but never launder a red"
_ds() { "$UV_BIN" run --python 3.13 python -c "
import sys; sys.path.insert(0,'ops')
import importlib.util as u
s=u.spec_from_file_location('g','ops/ui_quality_gate.py'); m=u.module_from_spec(s); s.loader.exec_module(m)
print(m.decide_status($1, $2))"; }
[[ "$(_ds 1 "'w'")" == "failed" ]] && ok "rc=1 with a warning stays failed" \
  || fail_t "a warning laundered a failing rc into warn — it drops out of summary.failed"
[[ "$(_ds 0 "'w'")" == "warn"   ]] && ok "rc=0 with a warning is warn"   || fail_t "rc=0+warning did not yield warn"
[[ "$(_ds 0 None)"  == "passed" ]] && ok "rc=0 without a warning passes" || fail_t "clean run did not pass"

section "An unresolvable base is an error, not an empty diff"
rc=0; ./ops/ui_quality_plane.py impact --since refs/heads/no-such-ref-xyz >/dev/null 2>&1 || rc=$?
[[ "$rc" -ne 0 ]] && ok "unresolvable --since exits $rc" \
  || fail_t "unresolvable --since exited 0 — 'cannot resolve' is again indistinguishable from 'nothing changed'"

section "CI runs every mechanism, not a diff"
grep -q -- '--all-mechanisms' .github/workflows/ui-quality-gate.yml \
  && ok "workflow uses --all-mechanisms" \
  || fail_t "workflow still scopes by diff; on push HEAD==origin/main so the range is empty and the gate is a no-op"
out="$("$GATE" --tier fast --execute --all-mechanisms 2>&1 || true)"
passed_n="$(sed -n 's/.*summary: selected=[0-9]* unrun=[0-9]* passed=\([0-9]*\).*/\1/p' <<<"$out" | head -1)"
[[ "${passed_n:-0}" -ge 5 ]] && ok "--all-mechanisms executes ${passed_n} fast mechanism(s)" \
  || fail_t "--all-mechanisms executed ${passed_n:-0} mechanisms — expected all five fast lints"

section "ops suite has a CI execution surface"
grep -rq 'test_ops.sh' .github/workflows/ \
  && ok "a workflow runs ops/test_ops.sh" \
  || fail_t "no workflow runs ops/test_ops.sh — regressions in the suite stay invisible (this is how two groups sat red)"

echo ""
echo "ui-quality-gate: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
