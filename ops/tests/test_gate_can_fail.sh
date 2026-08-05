#!/usr/bin/env bash
# Every block-level cutover gate must be provably able to go red AND green.
#
# This is the only mechanism that catches "the checker isn't really there", and no
# other quality measure catches it:
#   - `ios-quality-impact` sat on cutover routed to ui_quality_plane's PLANNER, every
#     return 0 — structurally incapable of failing, and called a quality gate.
#   - `.github/workflows/ui-quality-gate.yml` returned green with `planned=0` for two
#     straight months.
#   - the i18n baseline sat at 51 while actual findings were 0 — a threshold in name.
# Their common feature: nothing had ever asked "feed it a known-bad input, does it go
# red?"
#
# The mirror image is just as harmful, and this file used to miss it: `ios-build-catalyst`
# answered "can it go red" perfectly while being able to go ONLY red (no signing identity
# on this machine, exit 65 every time). It blocked every iOS cutover for two months, and
# the only visible way past it was to leave the process. A gate is healthy when BOTH
# directions are reachable — a green-only gate gives no signal, a red-only gate trains
# everyone to route around it.
#
# Two further rules, both learned from defects found in this very file:
#   1. A non-zero exit is NOT a proof. The old docs-lint proof passed an absolute temp
#      path, which docs_lint.sh rejects as a usage error BEFORE reading a byte — deleting
#      conflict-marker detection entirely would not have turned it red. So every executed
#      proof must name the CAUSE it expects in the output.
#   2. What is declared cheap must actually be executed. The final section fails if the
#      set of executed proofs differs from the set declared cheap, in either direction.
#
# Expensive gates (xcodebuild, pytest suites) cannot be run both ways here. Their red
# route is recorded and explicitly NOT executed; their green is read from the gate
# history journal — real recorded behaviour, never an assumption. A gate that has been
# tried repeatedly and has never once passed FAILS this test; a gate with no history on
# this machine is reported as unproven, which is the honest state of a fresh clone.

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; else UV_BIN="uv"; fi
fi

pass=0; fail=0
executed_kind() { [[ "$1" == "cheap" || "$1" == "fixture" ]]; }
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
note() { echo "  · $*"; }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d)"
PROBE="ios/BooksAndVocab/Views/Settings/KGCanFailProbe.swift"
DOCS_PROBE="docs/.gate_can_fail_probe.md"
cleanup() { rm -rf "$TMP"; rm -f "$PROBE" "$DOCS_PROBE"; }
trap cleanup EXIT

# gate | red proof | green proof | note
#   cheap     — executed by this file, in both directions, against the real tool
#   fixture   — executed here, but against a synthetic input rather than a production
#               tool, because the gate has no fixed tool: `ops-shell` runs whichever
#               script the diff routed to, so its contract is "run it, propagate its
#               exit code", and that is what gets proven. The note must say why the
#               production tool cannot serve.
#   expensive — running it here would cost minutes of xcodebuild / a full pytest suite
#   journal   — green read from recorded gate history (.cache/worktree_gates/history.jsonl)
# `note` is mandatory: an expensive classification without a stated route is a silent
# coverage hole wearing a checkmark.
PROOFS=(
  "ui-quality-fast|cheap|cheap|raw-CJK Text() turns it red; the untouched tree is green"
  "review-receipts|cheap|cheap|a commit with / without a Reviewed-by trailer"
  "docs-lint|cheap|cheap|a doc with / without a conflict marker"
  "docs-conflict-markers|cheap|cheap|internal gate, driven through its real function"
  "ops-shell-syntax|cheap|cheap|a script that does not parse vs one that does"
  "ops-shell|fixture|fixture|no fixed tool: the routed script IS the command, so what is provable here is the gate's contract — run it, propagate its exit code — driven through _run_gate against a script that exits 3"
  "ios-build|expensive|journal|ops/test_ios_ops.sh covers xcodebuild failure propagation"
  "ios-build-catalyst|expensive|journal|same runner as ios-build; green needs a real Catalyst compile"
  "ios-test-unit|expensive|journal|ops/tests/test_ios_run_verdict.sh false-green section"
  "ios-test-ui|expensive|journal|ops/tests/test_ios_run_verdict.sh false-green section"
  "ios-live-demo-uitest-compile|expensive|journal|Release iphoneos compile gate, see test_ios_ops.sh"
  "design-system|expensive|journal|ops/verify_design_system.sh has its own regression suite"
  "backend-pytest|expensive|journal|pytest's own non-zero exit"
  "ops-pytest|expensive|journal|pytest's own non-zero exit"
)

proof_for() {  # $1 = gate name -> "red|green|note", or non-zero if undeclared
  local g="$1" e
  for e in "${PROOFS[@]}"; do
    [[ "${e%%|*}" == "$g" ]] && { printf '%s\n' "${e#*|}"; return 0; }
  done
  return 1
}

# Gates whose BOTH directions must stay executed here (cheap or fixture). A ratchet, in
# the same spirit as the i18n baseline being pinned at 0: without it, the cheapest way
# past a failing proof is to reclassify the gate as `expensive|journal` and delete the
# proof body, and nothing would object. Downgrading one of these is then a deliberate,
# visible edit.
CHEAP_FLOOR="ui-quality-fast review-receipts docs-lint docs-conflict-markers ops-shell-syntax ops-shell"

# Registry of proofs this run actually ran, tagged by SOURCE. The source matters: a
# journal-sourced green is real evidence but it is not an executed proof, and without
# the tag it can stand in for one — declare `ios-build|expensive|cheap`, write no proof
# body at all, and one historical pass in the journal satisfies the reconciliation.
PROVEN=""
record_proof() { PROVEN="$PROVEN $1:$2:$3"; }  # gate, direction, executed|journal

# Both helpers REQUIRE a marker. A red asserted only on rc≠0 is how this file shipped a
# proof that was really testing argument validation.
assert_red() {  # <gate> <expected marker> <output file> <rc>
  local g="$1" marker="$2" out="$3" rc="$4"
  if [[ "$rc" -eq 0 ]]; then
    fail_t "$g stayed green on a known-bad input"
  elif ! grep -qF -- "$marker" "$out"; then
    fail_t "$g exited $rc but not for the expected reason (no '$marker' in output) — a non-zero exit from a different cause is not a proof"
    head -5 "$out" | sed 's/^/      /'
  else
    ok "$g goes red on a known-bad input, citing '$marker' (exit $rc)"
    record_proof "$g" red executed
  fi
}

assert_green() {  # <gate> <expected marker> <output file> <rc>
  local g="$1" marker="$2" out="$3" rc="$4"
  if [[ "$rc" -ne 0 ]]; then
    fail_t "$g cannot go green on a known-good input (exit $rc) — a gate that only ever goes red blocks everything and teaches people to bypass the process"
    tail -5 "$out" | sed 's/^/      /'
  elif ! grep -qF -- "$marker" "$out"; then
    fail_t "$g exited 0 but without '$marker' — a green no-op is not a green check"
    head -5 "$out" | sed 's/^/      /'
  else
    ok "$g goes green on a known-good input, citing '$marker'"
    record_proof "$g" green executed
  fi
}

section "every block-level gate declares BOTH directions"
BLOCK_GATES="$(
  "$UV_BIN" run --no-project --python 3.13 python - <<'PY'
import importlib.util as u
s = u.spec_from_file_location("wo", "ops/worktree_orchestrate.py")
m = u.module_from_spec(s); s.loader.exec_module(m)
probes = [
    ["ios/BooksAndVocab/Views/X.swift"],
    ["ios/BooksAndVocabUITests/FooTests.swift"],
    ["ios/BooksAndVocabUITests/LiveDemoAccessUITests.swift"],
    ["docs/reference/tech_index.md"],
    ["backend/src/kg/app.py"], ["backend/tests/test_x.py"],
    ["ops/worktree_orchestrate.py"], ["ops/docs_lint.sh"],
    ["design-system/tokens.json"],
    ["README.md"],
]
names = set()
for files in probes:
    for g in m.plan_gates(files, ops_test_exists=lambda rel: True, base="main"):
        if g["level"] == "block":
            names.add(g["name"].split(":")[0])
print("\n".join(sorted(names)))
PY
)"
[[ -n "$BLOCK_GATES" ]] || fail_t "enumerated zero block gates — the probe is broken, not the coverage"
declared_cheap=""
while IFS= read -r g; do
  [[ -z "$g" ]] && continue
  if ! entry="$(proof_for "$g")"; then
    fail_t "$g is a block gate with no declared proof — add it to PROOFS"
    continue
  fi
  red="${entry%%|*}"; rest="${entry#*|}"; green="${rest%%|*}"; gnote="${rest#*|}"
  case "$red" in cheap|fixture|expensive) ;; *) fail_t "$g: red proof kind '$red' is not cheap|fixture|expensive" ;; esac
  case "$green" in cheap|fixture|journal) ;; *) fail_t "$g: green proof kind '$green' is not cheap|fixture|journal" ;; esac
  [[ -n "$gnote" ]] || fail_t "$g: proof note is empty — an unexplained classification is a coverage hole"
  executed_kind "$red" && declared_cheap="$declared_cheap $g:red"
  executed_kind "$green" && declared_cheap="$declared_cheap $g:green"
  case " $CHEAP_FLOOR " in
    *" $g "*) { executed_kind "$red" && executed_kind "$green"; } \
      || fail_t "$g is in CHEAP_FLOOR but declared $red|$green — downgrading a gate out of executed proofs is exactly how a failing proof gets quietly retired" ;;
  esac
done <<<"$BLOCK_GATES"
# Stale-entry check, mirroring test_ops_ci_coverage.sh's third assertion. Found a real
# one on its first run: `coverage` was declared here while being a WARN gate, so it was
# never enumerated and its declaration could never be validated by anything.
for e in "${PROOFS[@]}"; do
  g="${e%%|*}"
  grep -qxF "$g" <<<"$BLOCK_GATES" \
    || fail_t "$g is declared in PROOFS but plan_gates never produces it as a block gate — stale entry"
done
(( fail == 0 )) && ok "all block gates declared in both directions, no stale entries: $(tr '\n' ' ' <<<"$BLOCK_GATES")"

section "cheap proofs are executed in BOTH directions, not asserted"

# --- ui-quality-fast ------------------------------------------------------------
# Green FIRST, on the untouched tree, then the same command with one raw-CJK string
# added. The pair is the point: only a gate that DISCRIMINATES passes both legs.
UIQ=(./ops/ui_quality_gate.sh --tier fast --execute --all-mechanisms)
# `sed -n '...p;q'` rather than `sed ... | head -1`: under `set -o pipefail` a closed
# pipe makes sed exit 141, which `set -e` turns into a silent whole-script abort.
summary_field() {  # <field> <file> -> the integer, or empty
  sed -n "s/.*summary: .*$1=\([0-9]*\).*/\1/p;/summary: /q" "$2"
}
rc=0; "${UIQ[@]}" >"$TMP/uiq_clean.out" 2>&1 || rc=$?
assert_green ui-quality-fast "failed=0" "$TMP/uiq_clean.out" "$rc"
# exit 0 alone is satisfied by executing nothing at all — which is exactly how CI stayed
# green for two months. Two independent guards against a green no-op:
#   passed >= 5   a FLOOR (five fast lints today), not an exact count — a sixth mechanism
#                 must not fail this, but a collapse to zero must.
#   unrun == 0    everything that was selected actually executed.
#   selected > 0  the plan was not empty to begin with.
# The third guard is new and is the one the two-month idle run needed: `selected` is the
# plan size, so "nothing was selected" now has its own field instead of being inferred
# from the whole tally reading zero. It used to be impossible to state — the only
# available key, `planned`, was a status tally that read `0` in a healthy run too
# (IMP-0050). Asserting it here means a future collapse to an empty plan fails loudly
# rather than presenting as a clean green.
unrun_n="$(summary_field unrun "$TMP/uiq_clean.out")"
selected_n="$(summary_field selected "$TMP/uiq_clean.out")"
passed_n="$(summary_field passed "$TMP/uiq_clean.out")"
[[ "${passed_n:-0}" -ge 5 && "${unrun_n:-0}" -eq 0 && "${selected_n:-0}" -gt 0 ]] \
  && ok "ui-quality-fast's green selected ${selected_n} and executed ${passed_n} mechanisms with none left unrun (not a green no-op)" \
  || fail_t "ui-quality-fast's green selected ${selected_n:-0}, ran ${passed_n:-0}, left ${unrun_n:-0} unrun — a green that skipped work is how CI idled for two months"

printf 'import SwiftUI\n\nstruct KGCanFailProbe: View {\n    @ObserveInjection private var inject\n    var body: some View {\n        Text("紅燈探針")\n            .enableInjection()\n    }\n}\n' >"$PROBE"
rc=0; "${UIQ[@]}" >"$TMP/uiq_probe.out" 2>&1 || rc=$?
rm -f "$PROBE"
assert_red ui-quality-fast "failed=1 " "$TMP/uiq_probe.out" "$rc"
# marker is substring-matched, so keep the trailing space: bare "failed=1" also matches
# "failed=13". Harmless at five mechanisms, a false green if this helper is ever reused.
failed_n="$(summary_field failed "$TMP/uiq_probe.out")"
[[ "${failed_n:-0}" -eq 1 ]] \
  && ok "ui-quality-fast's red failed exactly the one lint the probe violates" \
  || fail_t "ui-quality-fast's red reported ${failed_n:-0} failing mechanisms — expected exactly 1 (the raw-CJK lint)"

# --- review-receipts ------------------------------------------------------------
# KG_REVIEW_AUDIT_ROOT is kept EXPLICIT, not stylistic. review_audit.sh used to cd to
# its own repo root unconditionally, so a subshell `cd "$TMP/repo"` was discarded and
# the audit silently ran against KG's own history. That is what the previous version of
# this proof did — it passed for as long as KG's recent commits lacked trailers, and
# turned GREEN (i.e. stopped proving anything) the day they all had them. A proof whose
# verdict depends on the host repo instead of its fixture is not a proof.
# IMP-0049 made the caller's cwd the default, so `cd` would now work too; naming the
# root anyway keeps this proof independent of that resolution order ever changing back.
git init -q "$TMP/repo" 2>/dev/null
git -C "$TMP/repo" config user.email t@t.test; git -C "$TMP/repo" config user.name T
: >"$TMP/repo/a.txt"; git -C "$TMP/repo" add -A; git -C "$TMP/repo" commit -qm root
git -C "$TMP/repo" branch -M main
: >"$TMP/repo/b.txt"; git -C "$TMP/repo" add -A
git -C "$TMP/repo" commit -qm "feat: no receipt at all"
rc=0
( KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$WORKSPACE/ops/review_audit.sh" --rev-range main~1..HEAD ) \
  >"$TMP/review_bad.out" 2>&1 || rc=$?
assert_red review-receipts "[review][block]" "$TMP/review_bad.out" "$rc"

git -C "$TMP/repo" checkout -q -b clean main~1
: >"$TMP/repo/c.txt"; git -C "$TMP/repo" add -A
git -C "$TMP/repo" commit -qm "feat: with receipt

Reviewed-by: gate-can-fail (positive control)"
rc=0
( KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$WORKSPACE/ops/review_audit.sh" --rev-range main~1..HEAD ) \
  >"$TMP/review_ok.out" 2>&1 || rc=$?
assert_green review-receipts "[review][ok]" "$TMP/review_ok.out" "$rc"

# --- docs-lint ------------------------------------------------------------------
# The fixture MUST live under docs/ and be a real doc: docs_lint.sh rejects any other
# --files path as a usage error before reading it, which is how the previous version of
# this proof passed while proving nothing.
write_docs_probe() {  # $1 = body
  cat >"$DOCS_PROBE" <<DOCEOF
<!-- doc-meta
tier: reference
authority: SoT
update_trigger: manual
scope:
  - ops/docs_lint.sh
verified_against: HEAD
-->
# gate-can-fail probe

$1
DOCEOF
}
write_docs_probe "plain prose, nothing wrong with it"
rc=0; ./ops/docs_lint.sh --files "$DOCS_PROBE" >"$TMP/docs_ok.out" 2>&1 || rc=$?
assert_green docs-lint "ERROR: 0" "$TMP/docs_ok.out" "$rc"

write_docs_probe "$(printf '<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\n')"
rc=0; ./ops/docs_lint.sh --files "$DOCS_PROBE" >"$TMP/docs_bad.out" 2>&1 || rc=$?
assert_red docs-lint "衝突標記" "$TMP/docs_bad.out" "$rc"
rm -f "$DOCS_PROBE"

# --- docs-conflict-markers ------------------------------------------------------
# Decided inside the orchestrator, so drive the real function rather than a shell
# entrypoint. Same discipline: both directions. (`coverage` is a WARN gate, not block,
# so it is out of this file's contract; its two directions are pinned by
# test_unrouted_file_is_named_not_dropped / test_coverage_partition_is_exact.)
"$UV_BIN" run --no-project --python 3.13 python - >"$TMP/internal.out" 2>&1 <<'PY' || true
import importlib.util as u, tempfile, pathlib
s = u.spec_from_file_location("wo", "ops/worktree_orchestrate.py")
m = u.module_from_spec(s); s.loader.exec_module(m)
root = pathlib.Path(tempfile.mkdtemp())
(root / "docs").mkdir()
(root / "docs" / "bad.md").write_text("<!-- doc-meta -->\n<<<<<<< HEAD\nx\n")
(root / "docs" / "good.md").write_text("<!-- doc-meta -->\nnothing to see\n")
bad = m._run_conflict_markers(str(root), ["docs/bad.md"])
good = m._run_conflict_markers(str(root), ["docs/good.md"])
print(f"conflict-red status={bad['status']} summary={bad['summary']}")
print(f"conflict-green status={good['status']} summary={good['summary']}")

ops = root / "ops"
ops.mkdir()
(ops / "unparseable.sh").write_text("#!/usr/bin/env bash\nif [[ -z ]; then\n")
(ops / "parseable.sh").write_text("#!/usr/bin/env bash\necho fine\n")
sbad = m._run_shell_syntax(str(root), ["ops/unparseable.sh"])
sgood = m._run_shell_syntax(str(root), ["ops/parseable.sh"])
print(f"syntax-red status={sbad['status']} summary={sbad['summary']}")
print(f"syntax-green status={sgood['status']} summary={sgood['summary']}")

# ops-shell has no fixed tool — the routed script IS the command — so what is provable
# is the gate's contract: run it, propagate its exit code. A script exiting 3 makes the
# propagation itself the marker; a generic failure cannot produce that number.
for name, body in (("routed_red.sh", "#!/bin/sh\necho probe-ran\nexit 3\n"),
                   ("routed_green.sh", "#!/bin/sh\necho probe-ran\nexit 0\n")):
    f = ops / name
    f.write_text(body)
    f.chmod(0o755)
gbad = m._run_gate(m._shell("ops-shell:routed_red.sh", "ops",
                            ["ops/routed_red.sh"], "block"), str(root))
ggood = m._run_gate(m._shell("ops-shell:routed_green.sh", "ops",
                             ["ops/routed_green.sh"], "block"), str(root))
print(f"shell-red status={gbad['status']} rc={gbad['rc']}")
print(f"shell-green status={ggood['status']} rc={ggood['rc']}")
PY
grep -q "conflict-red status=block" "$TMP/internal.out" \
  && { ok "docs-conflict-markers goes red on a marker"; record_proof docs-conflict-markers red executed; } \
  || fail_t "docs-conflict-markers did not block on a file containing a conflict marker"
grep -q "conflict-green status=pass" "$TMP/internal.out" \
  && { ok "docs-conflict-markers goes green on a clean doc"; record_proof docs-conflict-markers green executed; } \
  || fail_t "docs-conflict-markers did not pass a doc with no markers"

# --- ops-shell-syntax -----------------------------------------------------------
# The red must name the offending FILE, not merely exit non-zero: a syntax gate that
# reports "something failed" is unactionable, and one that blocks on the wrong file is
# worse than none.
grep -q "syntax-red status=block" "$TMP/internal.out" && grep -q "unparseable.sh" "$TMP/internal.out" \
  && { ok "ops-shell-syntax goes red on a script that does not parse, naming it"; record_proof ops-shell-syntax red executed; } \
  || fail_t "ops-shell-syntax did not block (or did not name the file) on an unparseable script"
grep -q "syntax-green status=pass" "$TMP/internal.out" \
  && { ok "ops-shell-syntax goes green on a script that parses"; record_proof ops-shell-syntax green executed; } \
  || fail_t "ops-shell-syntax did not pass a well-formed script"

# --- ops-shell ------------------------------------------------------------------
# rc=3 is the marker: it can only come from the routed script's own exit status, so a
# gate that blocked for any other reason cannot satisfy this.
grep -q "shell-red status=block rc=3" "$TMP/internal.out" \
  && { ok "ops-shell propagates the routed script's failure (rc=3, not a generic red)"; record_proof ops-shell red fixture; } \
  || fail_t "ops-shell did not block with the routed script's own exit code"
grep -q "shell-green status=pass rc=0" "$TMP/internal.out" \
  && { ok "ops-shell passes when the routed script succeeds"; record_proof ops-shell green fixture; } \
  || fail_t "ops-shell did not pass a routed script that exits 0"

section "expensive gates: green read from recorded behaviour, never assumed"
# TWO independent lists, derived from the two independent kinds. Deriving the journal
# query from the RED kind (as this first shipped) leaves `red=cheap|green=journal`
# checked by nothing at all: its green is neither executed here nor looked up.
JOURNAL_GATES=""
while IFS= read -r g; do
  [[ -z "$g" ]] && continue
  entry="$(proof_for "$g" || true)"
  [[ -z "$entry" ]] && continue
  red="${entry%%|*}"; rest="${entry#*|}"; green="${rest%%|*}"; gnote="${rest#*|}"
  [[ "$red" == "expensive" ]] && note "$g — red not executed here: $gnote"
  [[ "$green" == "journal" ]] && JOURNAL_GATES="$JOURNAL_GATES $g"
done <<<"$BLOCK_GATES"

HIST_REPORT="$("$UV_BIN" run --no-project --python 3.13 python - $JOURNAL_GATES <<'PY'
import importlib.util as u, sys
s = u.spec_from_file_location("wo", "ops/worktree_orchestrate.py")
m = u.module_from_spec(s); s.loader.exec_module(m)
# ONE reader, in the module. A second copy here is a second chance to disagree about
# the same file, and it did: this copy used to count rows for gates that never started
# (spawn failures, `executed: false`), which the module skips — so one row could read
# "never green" here and "no data" there.
path = m._gate_history_path(None)
rows = m.gate_history_rows(None)
skipped = [r for r in rows if r.get("executed") is False]
for gate, v in m.gate_history_verdicts(None, sys.argv[1:]).items():
    if v["verdict"] == "proven":
        print(f"PROVEN {gate} last-green={v['last_green']} attempts={v['attempts']}")
    elif v["verdict"] == "never-green":
        print(f"NEVERGREEN {gate} attempts={v['attempts']} heads={v['heads']}")
    else:
        print(f"UNPROVEN {gate} attempts={v['attempts']}")
print(f"HISTORY {path} exists={path.is_file()} rows={len(rows)} unexecuted-skipped={len(skipped)}")
PY
)"
while IFS= read -r line; do
  case "$line" in
    PROVEN\ *)
      g="$(cut -d' ' -f2 <<<"$line")"
      ok "${line#PROVEN }: green proven from gate history"
      record_proof "$g" green journal ;;
    NEVERGREEN\ *)
      fail_t "${line#NEVERGREEN }: recorded repeatedly at block level and NEVER once green — the ios-build-catalyst signature. Check whether this gate can pass at all before treating a red here as your change's fault." ;;
    UNPROVEN\ *)
      note "${line#UNPROVEN }: no recorded green on this machine yet (not a failure — a fresh clone knows nothing)" ;;
    HISTORY\ *) note "${line#HISTORY }" ;;
  esac
done <<<"$HIST_REPORT"

section "what is declared cheap was actually executed"
# Reconciled in both directions, and the SOURCE is load-bearing on the `missing` side: a
# journal-sourced green is real evidence of capability but it is not an executed proof,
# so it must not be able to stand in for one. Without this, declaring a gate
# `expensive|cheap`, writing no proof body, and having one historical pass in the journal
# would satisfy the whole contract.
missing=""
for want in $declared_cheap; do
  case " $PROVEN " in
    *" $want:executed "*|*" $want:fixture "*) ;;
    *) missing="$missing $want" ;;
  esac
done
extra=""
for got in $PROVEN; do
  [[ "${got##*:}" == "journal" ]] && continue     # journal greens are extras by design
  entry="${got%:*}"
  case " $declared_cheap " in
    *" $entry "*) continue ;;
  esac
  extra="$extra $entry"
done
[[ -z "$missing" ]] || fail_t "declared cheap but never executed here:$missing"
[[ -z "$extra" ]] || fail_t "executed a proof for something not declared cheap:$extra"
[[ -z "$missing" && -z "$extra" ]] && ok "declared-cheap set matches executed set"

echo ""
echo "gate-can-fail: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
