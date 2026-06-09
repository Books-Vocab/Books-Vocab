#!/usr/bin/env bash
# test_ios_test_discovery.sh — behavioral verification for the -g (grep) test
# discovery logic used by ops/ios_test.sh.
#
# The discovery logic is extracted into ops/lib/ios_test_discovery.sh as a
# sourceable function `discover_only_flags <test_dir> <grep_pattern>` so it can
# be driven against an isolated fixture tree (no Xcode / no PTY needed).
#
# Regression guards:
#   1. Every test func is attributed to its OWN enclosing top-level container,
#      not the file's first struct (the historical `head -1` bug).
#   2. `@Suite struct X` (same-line) and `@Suite(.serialized)\nstruct X`
#      (split-line) containers are discovered, not silently skipped.
#   3. `final class X: XCTestCase` / `class X` containers are discovered.
#   4. Nested helper structs declared INSIDE a func body (indented) are NOT
#      treated as containers and never appear in a -only-testing path.
#   5. Files with no test container are skipped without emitting bogus flags.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$WORKSPACE/ops/lib/ios_test_discovery.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "FATAL: $LIB missing"; exit 1; }
# shellcheck source=/dev/null
source "$LIB"

# ── fixture tree ──────────────────────────────────────────────────────────────
FIX="$(mktemp -d)"
cleanup() { rm -rf "$FIX"; }
trap cleanup EXIT

# Multi top-level struct file: each func must attribute to its own struct.
cat > "$FIX/MultiStructTests.swift" <<'SWIFT'
import Testing

struct AlphaTests {
    @Test func alphaOne() {}
    @Test func alphaTwo() {
        struct NestedHelper: Error {}   // indented helper — NOT a container
    }
}

struct BravoTests {
    @Test func bravoOne() {}
}
SWIFT

# @Suite same-line containers.
cat > "$FIX/SuiteSameLineTests.swift" <<'SWIFT'
import Testing

@Suite struct CharlieTests {
    @Test func charlieOne() {}
}

@Suite struct DeltaTests {
    @Test func deltaOne() {}
}
SWIFT

# @Suite split-line + @Test-on-prev-line + a helper func that must NOT emit.
cat > "$FIX/SuiteSplitLineTests.swift" <<'SWIFT'
import Testing

@Suite(.serialized)
struct EchoTests {
    @Test func echoOne() {}
    @Test func echoTwo() {}

    @Test @MainActor
    func echoThree() throws {}

    func makeHelper() -> Int { 0 }   // plain helper — NOT a test
}
SWIFT

# XCTest class container with `func test...` (no @Test attribute).
cat > "$FIX/ClassTests.swift" <<'SWIFT'
import XCTest

final class FoxtrotTests: XCTestCase {
    func testFoxtrotOne() {}
    func testFoxtrotTwo() {}
}
SWIFT

# Parameterized @Test(arguments:) — single-line AND multiline-spanning forms.
# The func name does NOT start with `test`, so it is ONLY discoverable via the
# @Test attribute. The multiline `@Test(arguments: [ \n ... \n ])` must arm the
# next `func` across the intervening argument rows (the historical drop bug).
cat > "$FIX/ParamTests.swift" <<'SWIFT'
import Testing

struct GolfTests {
    // Single-line argument form (paren closes same line).
    @Test(arguments: [1, 2, 3])
    func golfSingleLine(_ n: Int) {}

    // Multiline argument form — paren opens here, rows below, closes later.
    @Test(arguments: [
        (1, 2.0),
        (3, 4.0),
    ])
    func golfMultiLine(_ a: Int, _ b: Double) {}

    // Display-name form on its own line above the func.
    @Test("a display name")
    func golfDisplayName() {}

    // Plain helper between tests — must NOT be armed/emitted.
    func makeFixture() -> Int { 0 }

    // Same-line @Test func still works after the multiline arm was consumed.
    @Test func golfSameLine() {}
}

// A second container right after a multiline @Test arm scenario: ensure the
// arm does not bleed across the container boundary onto Hotel's first func.
struct HotelTests {
    @Test(arguments: [
        "x",
        "y",
    ])
    func hotelMultiLine(_ s: String) {}
}
SWIFT

# No container at all — must be skipped, never emit a bogus flag.
cat > "$FIX/NoContainer.swift" <<'SWIFT'
import Foundation
enum Helpers { static func notATest() {} }
SWIFT

# helper: does the flag set contain exactly this -only-testing path?
has_flag() { printf '%s\n' "$1" | grep -qxF -e "-only-testing:BooksAndVocabTests/$2"; }

# ── 1. syntax ─────────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$LIB" && ok "lib syntax" || fail_t "lib syntax"

# ── 2. multi-struct attribution (the head -1 bug) ─────────────────────────────
section "Multi-struct attribution"
FLAGS="$(discover_only_flags "$FIX" "")"
has_flag "$FLAGS" "AlphaTests/alphaOne()" && ok "alphaOne → AlphaTests" || fail_t "alphaOne misattributed"
has_flag "$FLAGS" "AlphaTests/alphaTwo()" && ok "alphaTwo → AlphaTests" || fail_t "alphaTwo misattributed"
has_flag "$FLAGS" "BravoTests/bravoOne()" && ok "bravoOne → BravoTests (not AlphaTests)" || fail_t "bravoOne misattributed"
printf '%s\n' "$FLAGS" | grep -qF "AlphaTests/bravoOne" && fail_t "bravoOne WRONGLY under AlphaTests" || ok "bravoOne not under AlphaTests"

# ── 3. nested helper struct is never a container ──────────────────────────────
section "Nested helper exclusion"
printf '%s\n' "$FLAGS" | grep -qF "NestedHelper" && fail_t "NestedHelper leaked as container" || ok "NestedHelper not a container"

# ── 4. @Suite same-line ───────────────────────────────────────────────────────
section "@Suite same-line"
has_flag "$FLAGS" "CharlieTests/charlieOne()" && ok "charlieOne → CharlieTests" || fail_t "@Suite same-line CharlieTests skipped"
has_flag "$FLAGS" "DeltaTests/deltaOne()"     && ok "deltaOne → DeltaTests"     || fail_t "@Suite same-line DeltaTests skipped"

# ── 5. @Suite split-line ──────────────────────────────────────────────────────
section "@Suite split-line"
has_flag "$FLAGS" "EchoTests/echoOne()" && ok "echoOne → EchoTests" || fail_t "@Suite split-line skipped"
has_flag "$FLAGS" "EchoTests/echoTwo()" && ok "echoTwo → EchoTests" || fail_t "@Suite split-line skipped"
has_flag "$FLAGS" "EchoTests/echoThree()" && ok "echoThree (@Test on prev line) → EchoTests" || fail_t "@Test-on-prev-line func skipped"
printf '%s\n' "$FLAGS" | grep -qF "makeHelper" && fail_t "plain helper makeHelper leaked" || ok "plain helper makeHelper excluded"

# ── 6. XCTest class container ─────────────────────────────────────────────────
section "XCTest class container"
has_flag "$FLAGS" "FoxtrotTests/testFoxtrotOne" && ok "testFoxtrotOne → FoxtrotTests" || fail_t "class container skipped"
has_flag "$FLAGS" "FoxtrotTests/testFoxtrotTwo" && ok "testFoxtrotTwo → FoxtrotTests" || fail_t "class container skipped"

# ── 7. no-container file emits nothing ────────────────────────────────────────
section "No-container file"
printf '%s\n' "$FLAGS" | grep -qF "NoContainer" && fail_t "NoContainer leaked" || ok "NoContainer skipped"
printf '%s\n' "$FLAGS" | grep -qF "Helpers" && fail_t "Helpers enum leaked" || ok "Helpers enum not a container"

# ── 8. grep pattern filters by func name ──────────────────────────────────────
section "Grep pattern filter"
ONLY_ALPHA="$(discover_only_flags "$FIX" "alpha")"
has_flag "$ONLY_ALPHA" "AlphaTests/alphaOne()" && ok "pattern 'alpha' keeps alphaOne" || fail_t "pattern dropped alphaOne"
printf '%s\n' "$ONLY_ALPHA" | grep -qF "bravoOne" && fail_t "pattern 'alpha' leaked bravoOne" || ok "pattern 'alpha' excludes bravoOne"
printf '%s\n' "$ONLY_ALPHA" | grep -qF "charlieOne" && fail_t "pattern 'alpha' leaked charlieOne" || ok "pattern 'alpha' excludes charlieOne"

# ── 9. case-insensitive pattern (preserves -i behavior) ───────────────────────
section "Case-insensitive pattern"
ONLY_FOX="$(discover_only_flags "$FIX" "FOXTROT")"
has_flag "$ONLY_FOX" "FoxtrotTests/testFoxtrotOne" && ok "uppercase pattern matches" || fail_t "lost case-insensitivity"

# ── 10. parameterized @Test(arguments:) single + multiline ───────────────────
section "Parameterized @Test(arguments:) discovery"
has_flag "$FLAGS" "GolfTests/golfSingleLine()" && ok "golfSingleLine (single-line args) → GolfTests" || fail_t "single-line @Test(arguments:) dropped"
has_flag "$FLAGS" "GolfTests/golfMultiLine()" && ok "golfMultiLine (multiline args) → GolfTests" || fail_t "multiline @Test(arguments:) dropped"
has_flag "$FLAGS" "GolfTests/golfDisplayName()" && ok "golfDisplayName (@Test display name) → GolfTests" || fail_t "@Test(display-name) dropped"
has_flag "$FLAGS" "GolfTests/golfSameLine()" && ok "golfSameLine (@Test func after multiline arm) → GolfTests" || fail_t "same-line @Test regressed after multiline arm"
printf '%s\n' "$FLAGS" | grep -qF "makeFixture" && fail_t "plain helper makeFixture leaked" || ok "plain helper makeFixture excluded"
has_flag "$FLAGS" "HotelTests/hotelMultiLine()" && ok "hotelMultiLine → HotelTests (no cross-container bleed)" || fail_t "multiline arm dropped in HotelTests"
printf '%s\n' "$FLAGS" | grep -qF "GolfTests/hotelMultiLine" && fail_t "hotelMultiLine WRONGLY under GolfTests (arm bled across container)" || ok "no arm bleed across struct boundary"

# ── result ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
