#!/usr/bin/env bash
# test_ui_quality_gate.sh — behavior tests for ops/ui_quality_gate.sh.
#
# Covers: dry-run plan, execute fast static gates, tier filtering, JSON report,
# and the two non-symmetric answers to a missing injection baseline (bootstrap
# degrade vs. caller error).
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
for id in structure.ui_deadcode structure.ui_graph behavior.uitest_flows perf.review_flip_probe; do
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

section "--include-ci stays green on a clean tree"
# The plane requires `run:` only of the gates it owns (`gate: manual`), and
# some others cannot have one — snapshot.review_card_layout_golden's entrypoint is a
# Swift test file that `ios_ops.sh test` enforces. Failing those here would
# make validate and the runner disagree about the same file and turn a
# documented flag permanently red on an unmodified checkout.
CI_JSON="$($GATE --tier all --dry-run --all-mechanisms --include-ci --json 2>/dev/null)"
if jq -e '.summary.failed == 0' <<<"$CI_JSON" >/dev/null 2>&1; then
  ok "--include-ci reports no failures on the real plane"
else
  fail_t "--include-ci fails on a clean tree: $(jq -c '[.results[] | select(.status=="failed") | .id]' <<<"$CI_JSON")"
fi

section "A mechanism nothing can run fails the gate, it does not sit unrun"
# The defect this whole change exists for (IMP-0041): the runner kept its own
# command table, so a mechanism declared in the plane but absent from that
# table resolved to no command, was recorded as unrun, and unrun is not
# counted as failed — the gate returned 0. validate now refuses such a
# mechanism, but the runner must not depend on validate having been run: an
# unrunnable mechanism reaching the runner is a failure, not a deferral.
# The ghost plane lives in a temp dir and is `rm -rf`'d inline at the end of
# this section; nothing here touches the working tree.
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

section "A named-but-missing injection baseline is a caller error, not a degrade"
# The two directions are deliberately NOT symmetric:
#
#   KG_INJECTION_BASELINE unset and no baseline on disk → bootstrap. Nobody has
#     run `--baseline` yet, so --report with a warning (exit 0) is the only thing
#     left to offer.
#   KG_INJECTION_BASELINE set to a path that is not there → the caller named that
#     path. A typo, or a stale export from an earlier session. Degrading *here* is
#     a silent green: --report always exits 0 and `warn` is excluded from
#     summary.failed, so the gate returns 0 with injection enforcement switched
#     off. `ui_quality_gate.sh --tier fast --execute` is a **block**-level cutover
#     gate (ops/worktree_orchestrate.py:428) and a pre-commit hook
#     (.githooks/pre-commit:43); both inherit the caller's environment, and
#     cutover is offline so CI cannot cover for it. One stale export would have
#     disabled the lint everywhere without a word — and this is the variable the
#     docs now tell people to reach for. It has to be red.
#
# "Missing" is staged by pointing the gate at a path that does not exist, via
# the same KG_INJECTION_BASELINE seam ops/injection_lint.py already reads. The
# version-controlled ops/injection_baseline.txt is never touched.
#
# It used to be `mv`d aside for the length of this section and put back by a
# `trap ... EXIT`. On 2026-08-04 a concurrent repo-root `git add -A` landed
# inside that window and staged the absence: 400bd6c5f committed the file away,
# 9037aca00 put it back. A restoring trap is not a transaction — the tracked
# file has to stay on disk *while* the gate runs, which is what the watcher
# below measures rather than assumes (IMP-0048).
TRACKED_BASELINE="ops/injection_baseline.txt"
MISSING_BASELINE="$(mktemp -u)"

# Checking the tracked file after the gate returns is precisely what the old
# EXIT trap already delivered, so it would prove nothing. Snapshot it, then
# `cmp` the live path against that snapshot every 100ms for as long as the gate
# runs. A typo'd path cannot pass quietly: the snapshot `cp` fails and every
# sample is a violation. A watcher that never ran cannot pass either — the
# sample count is asserted non-zero. The iteration cap makes an orphaned
# watcher (suite SIGKILLed) expire on its own; it only ever reads.
WATCH_SNAPSHOT="$(mktemp)"
WATCH_SAMPLES="$(mktemp)"
WATCH_RUNNING="$(mktemp)"
if ! cp "$TRACKED_BASELINE" "$WATCH_SNAPSHOT"; then
  fail_t "$TRACKED_BASELINE is not on disk before this section starts — nothing below can mean anything"
fi
(
  n=0
  while [[ -e "$WATCH_RUNNING" && "$n" -lt 3000 ]]; do
    if cmp -s "$TRACKED_BASELINE" "$WATCH_SNAPSHOT"; then
      echo intact >>"$WATCH_SAMPLES"
    else
      echo VIOLATION >>"$WATCH_SAMPLES"
    fi
    n=$((n + 1))
    sleep 0.1
  done
) &
WATCH_PID=$!

# The enforcing shape, unscoped: the same fast tier cutover and the pre-commit
# hook run. Deliberately not narrowed with --exclude — the failed set is asserted
# to be *exactly* static.injection below, so the non-zero exit is attributable to
# this mechanism rather than to some other lint happening to be red.
JSON="$(KG_INJECTION_BASELINE="$MISSING_BASELINE" $GATE --files "$SAMPLE_FILE" --tier fast --execute --json 2>/dev/null)"
RC=$?
# Human mode, narrowed to the one row under test so it costs a process start
# rather than another full lint sweep. A refusal has to be legible to whoever
# typed the bad path, not just to jq.
ROW_OUT="$(KG_INJECTION_BASELINE="$MISSING_BASELINE" $GATE --files "$SAMPLE_FILE" --tier fast --execute \
  --exclude static.ui_token --exclude static.plain_deadzone --exclude static.i18n --exclude static.catalyst 2>&1)"
# KG_INJECTION_BASELINE= (empty) is the split-brain input: the parent used to
# read it with `if override:` and fall back to the tracked file while the child
# read `os.environ.get(..., default)`, resolved Path("") to the repo root, and
# died with IsADirectoryError. Dry-run is enough — the refusal is decided before
# the mode branch, and no child should be started at all.
EMPTY_JSON="$(KG_INJECTION_BASELINE= $GATE --files "$SAMPLE_FILE" --tier fast --dry-run --json 2>/dev/null)"
EMPTY_RC=$?

rm -f "$WATCH_RUNNING"
wait "$WATCH_PID" 2>/dev/null || true
SAMPLES="$(wc -l <"$WATCH_SAMPLES" | tr -d ' ')"
VIOLATIONS="$(grep -c VIOLATION "$WATCH_SAMPLES" || true)"

FAILED_IDS="$(jq -c '[.results[] | select(.status=="failed") | .id]' <<<"$JSON" 2>/dev/null)"
if [[ "$RC" -ne 0 ]] && [[ "$FAILED_IDS" == '["static.injection"]' ]]; then
  ok "a stale KG_INJECTION_BASELINE export fails the gate (rc=$RC), and static.injection is the only thing failing it"
else
  fail_t "gate exited $RC with failed=$FAILED_IDS summary=$(jq -c '.summary' <<<"$JSON" 2>/dev/null) — a caller-named baseline that is not there must not pass; --report always exits 0 and warn is not counted in summary.failed"
fi
# The mechanism row, not the summary: `warn=0`/`failed=1` counters in the
# summary line can satisfy a loose grep on a run where the mechanism did the
# opposite of what is claimed.
if jq -e '.results[] | select(.id=="static.injection")
          | .status=="failed" and .rc==2 and (.args|length)==0
            and (.command|contains("--report")|not)' <<<"$JSON" >/dev/null 2>&1; then
  ok "static.injection refused to run (rc=2, no args) instead of degrading to an always-exit-0 --report"
else
  fail_t "static.injection row was $(jq -c '.results[]|select(.id=="static.injection")|{status,rc,command,warning}' <<<"$JSON" 2>/dev/null) — a warning must not launder a red one level up"
fi
# Anchored on the static.injection row, deliberately not a bare /FAIL/ or
# /KG_INJECTION_BASELINE/: both appear elsewhere in the output. The matched text
# is human_summary's rendering of the refusal's own warning — if the child had
# merely exited 1 the row would read `[FAIL] ops/injection_lint.sh
# --baseline-check (rc=1)` and name nothing.
if grep -qE '^static\.injection +\[FAIL\].*KG_INJECTION_BASELINE' <<<"$ROW_OUT"; then
  ok "the human row says FAIL and names the variable that caused it"
else
  fail_t "static.injection's row does not explain the refusal: $(grep -E '^static\.injection' <<<"$ROW_OUT")"
fi
if [[ "$EMPTY_RC" -ne 0 ]] && jq -e '.results[] | select(.id=="static.injection")
          | .status=="failed" and (.command|contains("--baseline-check")|not)' <<<"$EMPTY_JSON" >/dev/null 2>&1; then
  ok "an empty KG_INJECTION_BASELINE is refused by the parent (rc=$EMPTY_RC), not planned as a --baseline-check the child resolves to the repo root"
else
  fail_t "empty override: rc=$EMPTY_RC row=$(jq -c '.results[]|select(.id=="static.injection")|{status,rc,command}' <<<"$EMPTY_JSON" 2>/dev/null) — parent and child disagree on the same variable again (IsADirectoryError)"
fi
if [[ "$SAMPLES" -gt 0 && "$VIOLATIONS" -eq 0 ]]; then
  ok "tracked injection baseline stayed byte-identical throughout the run ($SAMPLES samples)"
else
  fail_t "tracked $TRACKED_BASELINE changed while the gate ran: $VIOLATIONS/$SAMPLES samples violated"
fi
if cmp -s "$TRACKED_BASELINE" "$WATCH_SNAPSHOT"; then
  ok "tracked injection baseline is untouched after the run"
else
  fail_t "$TRACKED_BASELINE differs from its pre-section snapshot — this test modified a version-controlled file"
fi
rm -f "$WATCH_SNAPSHOT" "$WATCH_SAMPLES"

# The bootstrap direction cannot be staged through the CLI without taking the
# tracked baseline off disk, which is the thing IMP-0048 exists to stop. Ask the
# decision function itself instead, in a root that has no baseline — that keeps
# "degrade" and "refuse" pinned as two different answers rather than one.
_inj() { # <root> — prints "<resolved args|UNRUNNABLE>|<warn|nowarn>" for the ambient env
  "$UV_BIN" run --python 3.13 python -c "
import sys
from pathlib import Path
import importlib.util as u
s=u.spec_from_file_location('g','ops/ui_quality_gate.py'); m=u.module_from_spec(s); s.loader.exec_module(m)
a,w=m.injection_args(Path(sys.argv[1]))
print(('UNRUNNABLE' if a is m.UNRUNNABLE else ' '.join(a)) + '|' + ('warn' if w else 'nowarn'))" "$1"
}
EMPTY_ROOT="$(mktemp -d)"
[[ "$(unset KG_INJECTION_BASELINE; _inj "$EMPTY_ROOT")" == "--report|warn" ]] \
  && ok "unset + no baseline anywhere → --report with a warning (bootstrap keeps its exit 0)" \
  || fail_t "the bootstrap degrade is gone: an unset variable in a tree with no baseline must still offer --report, not refuse"
[[ "$(unset KG_INJECTION_BASELINE; _inj "$ROOT")" == "--baseline-check|nowarn" ]] \
  && ok "unset + tracked baseline present → --baseline-check, no warning (bit-identical to before the override existed)" \
  || fail_t "the default path regressed: an unset variable on this repo must enforce"
[[ "$( (export KG_INJECTION_BASELINE="$MISSING_BASELINE"; _inj "$ROOT") )" == "UNRUNNABLE|warn" ]] \
  && ok "set + missing → UNRUNNABLE with a warning (caller error)" \
  || fail_t "a named-but-missing baseline did not resolve to UNRUNNABLE"
[[ "$( (export KG_INJECTION_BASELINE=""; _inj "$ROOT") )" == "UNRUNNABLE|warn" ]] \
  && ok "set-but-empty → UNRUNNABLE, the same answer the child's Path('') deserves" \
  || fail_t "empty override took the parent's fallback while the child takes the repo root — the split brain is back"
[[ "$( (export KG_INJECTION_BASELINE="$TRACKED_BASELINE"; _inj "$ROOT") )" == "--baseline-check|nowarn" ]] \
  && ok "a relative override resolves against the repo root — the same anchor the child uses, whatever cwd either was invoked from" \
  || fail_t "a relative override does not resolve like the child's"
rmdir "$EMPTY_ROOT"

# Everything above is parent-side. If ops/injection_lint.py stopped honouring the
# variable, or drifted to a different default, the parent alone would still print
# exactly what those assert and every one of them would stay green.
#
# This probe used to compare the two *unresolved* strings — Path("ops/…") on both
# sides — and was green for as long as the defect it was meant to catch was live:
# two equal relative strings prove nothing about where each side lands, and the
# child resolved its one against the caller's cwd (IMP-20260807-1674d1). Compare
# the resolved files, and the anchors they resolve against.
CONTRACT="$("$UV_BIN" run --python 3.13 python - <<'PY'
import os, sys
from pathlib import Path
import importlib.util as u
sys.path.insert(0, "ops")
def load(name, path):
    s = u.spec_from_file_location(name, path)
    m = u.module_from_spec(s)
    s.loader.exec_module(m)
    return m
os.environ.pop("KG_INJECTION_BASELINE", None)
gate = load("g", "ops/ui_quality_gate.py")
lint = load("l1", "ops/injection_lint.py")
os.environ["KG_INJECTION_BASELINE"] = "/tmp/kg-parent-child-contract-probe.txt"
lint2 = load("l2", "ops/injection_lint.py")
# A *relative* override is the input the two used to disagree on; the parent
# resolves it against repo_root(), the child against its own ROOT.
os.environ["KG_INJECTION_BASELINE"] = "ops/injection_baseline.txt"
lint3 = load("l3", "ops/injection_lint.py")
root = gate.repo_root()
print("%s|%s|%s|%s|%s|%s" % (
    root == lint.ROOT,
    (root / gate.DEFAULT_INJECTION_BASELINE) == lint.BASELINE_FILE,
    lint2.BASELINE_FILE == Path("/tmp/kg-parent-child-contract-probe.txt"),
    lint3.BASELINE_FILE == (root / "ops/injection_baseline.txt"),
    gate.DEFAULT_INJECTION_BASELINE,
    lint.BASELINE_FILE,
))
PY
)"
IFS='|' read -r SAME_ANCHOR SAME_DEFAULT CHILD_HONOURS SAME_RELATIVE GATE_DEFAULT LINT_DEFAULT <<<"$CONTRACT"
if [[ "$SAME_ANCHOR" == "True" && "$SAME_DEFAULT" == "True" \
      && "$CHILD_HONOURS" == "True" && "$SAME_RELATIVE" == "True" ]]; then
  ok "parent and child anchor on the same repo root and resolve the same default ($GATE_DEFAULT), absolute override and relative override to the same file"
else
  fail_t "parent/child baseline contract broken — same anchor: '$SAME_ANCHOR', same default: '$SAME_DEFAULT' (gate '$GATE_DEFAULT' vs lint '$LINT_DEFAULT'), absolute override honoured: '$CHILD_HONOURS', relative override agrees: '$SAME_RELATIVE' (raw: $CONTRACT)"
fi

# A refusal must not be re-labelled on its way out. main() forgives an
# unrunnable mechanism when `gate != manual`, because the plane only requires
# `run:` of the gates it owns and some CI-side entrypoints cannot have one. That
# forgiveness is keyed on the *reason* — no `run:` — and a mechanism that has a
# `run:` and is unrunnable for a different reason (this caller error) would
# otherwise be filed as planned under the warning "no `run:`; gate=ci runs it
# elsewhere", which is both green and untrue.
GHOST2_DIR="$(mktemp -d)"
cat >"$GHOST2_DIR/ci_injection.yml" <<'YML'
version: 1
mechanisms:
  - id: static.ghost_ci_injection
    layer: static-code
    entrypoint: ops/injection_lint.sh
    gate: ci
    run:
      - --baseline-check
    requires:
      - injection-baseline
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
rc=0
GHOST2_JSON="$(KG_UI_PLANE_FILE="$GHOST2_DIR/ci_injection.yml" KG_INJECTION_BASELINE="$MISSING_BASELINE" \
  $GATE --tier fast --dry-run --include-ci --all-mechanisms --json 2>/dev/null)" || rc=$?
if [[ "$rc" -ne 0 ]] && jq -e '.results[] | select(.id=="static.ghost_ci_injection")
        | .status=="failed" and (.warning|contains("no `run:`")|not)' <<<"$GHOST2_JSON" >/dev/null 2>&1; then
  ok "a caller error on a non-manual gate stays failed (rc=$rc) instead of being re-labelled 'no \`run:\`'"
else
  fail_t "ghost ci mechanism: rc=$rc row=$(jq -c '.results[]|select(.id=="static.ghost_ci_injection")|{status,warning}' <<<"$GHOST2_JSON" 2>/dev/null)"
fi
rm -rf "$GHOST2_DIR"

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
  || fail_t "--all-mechanisms executed ${passed_n:-0} mechanisms — expected every fast lint (floor 5; 6 today)"

section "ops suite has a CI execution surface"
grep -rq 'test_ops.sh' .github/workflows/ \
  && ok "a workflow runs ops/test_ops.sh" \
  || fail_t "no workflow runs ops/test_ops.sh — regressions in the suite stay invisible (this is how two groups sat red)"

echo ""
echo "ui-quality-gate: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
