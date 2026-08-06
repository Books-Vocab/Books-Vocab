#!/usr/bin/env bash
# test_gen_ios_baseline.sh — the ios_baseline source-text counters must be able to count.
#
# IMP-20260805-958999: line 25 grepped the literal "async func", which is not Swift word
# order (`func f() async`), so the published metric was structurally 0 forever while the
# tree held 290 async declarations. A permanently-constant metric is the one value an
# equality-style drift check blesses as consistent — both sides agree, and both are wrong.
# So this file does not compare the doc to a recomputation; it asks each counter to prove
# it can move: a fixture with N occurrences must count N, a fixture with none must count 0.
#
# Ground truth for the fixtures below was hand-counted, then cross-checked on the real tree
# against a Swift lexer that strips comments/strings and walks balanced parens (async funcs
# 290, @MainActor attribute lines 252). The grep pipelines are approximations of that lexer;
# their measured residual error is recorded in ops/gen_ios_baseline.sh next to each counter.
#
# KNOWN, DELIBERATE HOLES (measured 0 occurrences in ios/BooksAndVocab on 2026-08-06, so
# they are not asserted here — see the generator's comments):
#   - `@MainActor` or `) async` inside a /* block comment */ or a string literal.
#   - funcs whose only `) async` is a non-async `@escaping () async ->` parameter (2 today).
set -uo pipefail
WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"
GEN="${KG_GEN_IOS_BASELINE_SCRIPT:-ops/gen_ios_baseline.sh}"
DOC="docs/snapshot/ios_baseline.md"
pass=0; fail=0
ok(){ echo "  ✓ $*"; pass=$((pass+1)); }
fail_t(){ echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Drive the REAL assignment line out of the generator against an arbitrary tree, so the
# test can never drift from the shipped pipeline the way a re-typed copy of it would.
count_with() {  # $1 = variable name, $2 = dir to scan -> stdout: the number the generator would print
  local var="$1" IOS_DIR="$2" line
  line="$(grep -E "^${var}=" "$GEN")"
  eval "$line"
  eval "printf '%s' \"\$${var}\""
}

section "each counter is a single extractable top-level line"
for var in ASYNC_FUNC MAIN_ACTOR; do
  n="$(grep -cE "^${var}=" "$GEN")"
  [[ "$n" == "1" ]] && ok "exactly one ^${var}= line in $GEN" \
    || fail_t "expected exactly 1 ^${var}= line in $GEN, found $n (the acceptance evals this line; it must stay single-line and unindented)"
done

section "async: canonical Swift declarations are counted, including multi-line signatures"
mkdir -p "$TMP/pos"
cat > "$TMP/pos/A.swift" <<'EOF'
func alpha() async {}
func beta() async throws -> Int { 0 }
static func gamma(x: Int) async -> String { "" }
public func delta(
    first: Int,
    second: String
) async throws -> Bool { true }
func epsilon(cb: (Int) async -> Void) async {}
EOF
# Hand-counted: alpha, beta, gamma, delta (multi-line signature), epsilon = 5.
got="$(count_with ASYNC_FUNC "$TMP/pos")"
[[ "$got" == "5" ]] && ok "5 async declarations counted as 5 (4 same-line + 1 multi-line)" \
  || fail_t "async-declaration counter is wrong: 5 canonical Swift async funcs counted as '$got' (Swift word order is 'func f() async', never 'async func'; a signature may also close on a later line)"

section "async: prose, string literals and closure-typed properties are not counted"
mkdir -p "$TMP/neg"
cat > "$TMP/neg/B.swift" <<'EOF'
func plain() {}
func thrower() throws -> Int { 0 }
let hint = "async func"
// TODO: make this an async func
//    ) async throws -> Void
var sleepy: (Duration) async -> Void = { _ in }
EOF
got="$(count_with ASYNC_FUNC "$TMP/neg")"
[[ "$got" == "0" ]] && ok "no async declarations counted as 0" \
  || fail_t "async counter matches non-declarations: expected 0, got '$got'"

section "@MainActor: attributes are counted, doc-comment prose is not"
mkdir -p "$TMP/ma"
cat > "$TMP/ma/C.swift" <<'EOF'
@MainActor
final class Foo {}
@MainActor func bar() {}
/// `AuthManaging` is `@MainActor`-isolated, so construct this inside a
/// @MainActor View body.
// @MainActor here is prose too
EOF
# Hand-counted: 2 real attribute lines; the 3 comment lines must not count.
got="$(count_with MAIN_ACTOR "$TMP/ma")"
[[ "$got" == "2" ]] && ok "2 @MainActor attributes counted as 2, 3 comment mentions excluded" \
  || fail_t "@MainActor counter is wrong: expected 2, got '$got' (doc comments discussing @MainActor are prose, not concurrency annotations)"

section "real tree: the counters are not stuck at an impossible constant"
got="$(count_with ASYNC_FUNC "ios/BooksAndVocab")"
[[ "$got" =~ ^[0-9]+$ && "$got" -gt 0 ]] && ok "ios/BooksAndVocab async declarations = $got (> 0)" \
  || fail_t "ios/BooksAndVocab async declarations = '$got'; a permanently-zero metric is a bug, not a fact"
# Non-tautological: this codebase demonstrably has multi-line async signatures (71 today),
# so a counter that only sees same-line ones must come out strictly lower than the real one.
same_line="$({ grep -rE "func [^{]*\)[[:space:]]*async" ios/BooksAndVocab --include="*.swift" 2>/dev/null || true; } | wc -l | tr -d ' ')"
[[ "$got" =~ ^[0-9]+$ && "$got" -gt "$same_line" ]] && ok "multi-line signatures are counted too ($got > same-line-only $same_line)" \
  || fail_t "counter sees only same-line signatures ($got vs same-line-only $same_line); multi-line 'func f(\\n...\\n) async' declarations are being dropped"

section "published snapshot carries the same non-zero reality"
for label in "async func" "@MainActor"; do
  row="$(awk -F'|' -v l="$label" '$2 ~ l {gsub(/[[:space:]]/,"",$3); print $3; exit}' "$DOC")"
  if [[ ! "$row" =~ ^[0-9]+$ ]]; then
    fail_t "could not parse the '$label' row out of $DOC (got '$row') — the probe is broken, not the doc"
  elif [[ "$row" -gt 0 ]]; then
    ok "$DOC '$label' row = $row (> 0)"
  else
    fail_t "$DOC publishes '$label = $row'; regenerate it after fixing the generator"
  fi
done

echo ""; echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
