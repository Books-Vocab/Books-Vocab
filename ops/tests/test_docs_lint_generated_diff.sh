#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMPDIR="$(mktemp -d -t kg_docs_diff_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT INT TERM

pass=0
fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }

build_sandbox() {
  local sb="$1" generator_body="$2" product="$3"
  mkdir -p "$sb/docs/snapshot" "$sb/ops"
  git -C "$sb" init -q
  printf '%s\n' "$product" > "$sb/docs/snapshot/probe.md"
  printf 'after\n' > "$sb/docs/snapshot/after.md"
  printf '%s\n' "$generator_body" > "$sb/ops/fake_gen.sh"
  chmod +x "$sb/ops/fake_gen.sh"
  cp "$ROOT/ops/docs_lint.sh" "$sb/ops/docs_lint.sh"
  chmod +x "$sb/ops/docs_lint.sh"
  {
    echo "documents:"
    echo "  - id: generated.probe"
    echo "    path: docs/snapshot/probe.md"
    echo "    kind: generated"
    echo "    authority: generated"
    echo "    generator: ops/fake_gen.sh"
    echo "    check: ./ops/fake_gen.sh --check docs/snapshot/probe.md"
    echo "  - id: reference.after"
    echo "    path: docs/snapshot/after.md"
    echo "    kind: reference"
    echo "    authority: reference"
  } > "$sb/docs/registry.yml"
}

run_lint() {
  local sb="$1" log="$2"
  ( cd "$sb" && ./ops/docs_lint.sh --registry ) > "$log" 2>&1
  return $?
}

remove_diff_call() {
  local sb="$1"
  sed -i.bak '/emit_generated_diff "\$id" "\$path" "\$generator"/d' \
    "$sb/ops/docs_lint.sh"
}

assert_mutation_is_caught() {
  local sb="$1" log="$2" rc
  remove_diff_call "$sb"
  run_lint "$sb" "$log"
  rc=$?
  if [ "$rc" -eq 1 ] && ! grep -qF "drift diff (generated.probe):" "$log"; then
    ok "removing diff emission is observable"
  else
    fail_t "removing diff emission was not observable (rc=$rc)"
  fi
}

# 1. Basic drift: a usable generator provides a bounded, named diff.
SB1="$TMPDIR/basic"
build_sandbox "$SB1" $'#!/usr/bin/env bash\nif [ "${1:-}" = "--check" ]; then exit 1; fi\nprintf "%s\\n" "expected line 1" "expected line 2"' "actual line"
LOG1="$TMPDIR/basic.log"
run_lint "$SB1" "$LOG1"; RC1=$?
if [ "$RC1" -eq 1 ] &&
   grep -qF "ERROR registry — generated.probe 產物與 generator 輸出不一致" "$LOG1" &&
   grep -qF "drift diff (generated.probe):" "$LOG1" &&
   grep -qF "expected line 1" "$LOG1"; then
  ok "basic drift prints named diff"
else
  fail_t "basic drift missing named diff (rc=$RC1)"
fi
assert_mutation_is_caught "$SB1" "$TMPDIR/basic-mutant.log"

# 2. An unusable generator must preserve the old error and not print guessed data.
SB2="$TMPDIR/fallback"
build_sandbox "$SB2" $'#!/usr/bin/env bash\nexit 7' "actual line"
LOG2="$TMPDIR/fallback.log"
run_lint "$SB2" "$LOG2"; RC2=$?
if [ "$RC2" -eq 1 ] &&
   grep -qF "ERROR registry — generated.probe 產物與 generator 輸出不一致" "$LOG2" &&
   ! grep -qF "drift diff (generated.probe):" "$LOG2"; then
  ok "unusable generator falls back honestly"
else
  fail_t "unusable generator did not fall back honestly (rc=$RC2)"
fi
assert_mutation_is_caught "$SB2" "$TMPDIR/fallback-mutant.log"

# 3. Large drift is bounded and states how much was omitted.
SB3="$TMPDIR/large"
LARGE_BODY=$'#!/usr/bin/env bash\nif [ "${1:-}" = "--check" ]; then exit 1; fi\ni=1\nwhile [ "$i" -le 80 ]; do echo "expected-$i"; i=$((i+1)); done'
build_sandbox "$SB3" "$LARGE_BODY" "actual line"
LOG3="$TMPDIR/large.log"
run_lint "$SB3" "$LOG3"; RC3=$?
if [ "$RC3" -eq 1 ] &&
   grep -qF "drift diff (generated.probe):" "$LOG3" &&
   grep -qF "還有" "$LOG3" &&
   grep -qF "行差異未顯示" "$LOG3"; then
  ok "large drift is bounded with remainder count"
else
  fail_t "large drift was not bounded (rc=$RC3)"
fi
assert_mutation_is_caught "$SB3" "$TMPDIR/large-mutant.log"

echo "docs-lint-generated-diff: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
