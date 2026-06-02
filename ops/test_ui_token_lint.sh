#!/usr/bin/env bash
# test_ui_token_lint.sh — behavioral verification for ops/ui_token_lint.sh.
#
# Asserts the four-mode contract (--report / --baseline / --baseline-check /
# --strict), the inline `// token-allow:` exemption, file-level exclusions, and
# the line-drift-resistant set-difference baseline. Runs against an isolated
# fixture tree (KG_UI_TOKEN_SRC override) so it never depends on live src state.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
LINT="$WORKSPACE/ops/ui_token_lint.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

# ── fixture tree ─────────────────────────────────────────────────────────────
FIX="$(mktemp -d)"
BASE="$(mktemp)"
cleanup() { rm -rf "$FIX" "$BASE"; }
trap cleanup EXIT

mkdir -p "$FIX/Views" "$FIX/Debug" "$FIX/Models"

# A genuinely dirty view file: raw padding number, raw shadow, raw cornerRadius,
# raw hex color, raw system font size.
cat > "$FIX/Views/Dirty.swift" <<'SWIFT'
import SwiftUI
struct Dirty: View {
    var body: some View {
        Text("x")
            .padding(7)
            .shadow(color: .black.opacity(0.3), radius: 2, y: 1)
            .background(RoundedRectangle(cornerRadius: 12))
            .foregroundColor(Color(hex: "#FF0000"))
            .font(.system(size: 17))
    }
}
SWIFT

# A clean view file: everything tokenized, plus one exempted raw value.
cat > "$FIX/Views/Clean.swift" <<'SWIFT'
import SwiftUI
struct Clean: View {
    var body: some View {
        Text("x")
            .padding(AppSpacing.s2)
            .appElevation(.z1)
            .background(RoundedRectangle(cornerRadius: AppRadius.card))
            .foregroundColor(AppColors.accent)
            .padding(3) // token-allow: intentional one-off hairline
    }
}
SWIFT

# Excluded paths must NOT contribute findings even when dirty.
cat > "$FIX/Debug/DebugScratch.swift" <<'SWIFT'
import SwiftUI
struct DebugScratch: View { var body: some View { Text("x").padding(9) } }
SWIFT
cat > "$FIX/Views/Thing_Preview.swift" <<'SWIFT'
import SwiftUI
struct ThingPreview: View { var body: some View { Text("x").padding(9) } }
SWIFT
cat > "$FIX/Views/ThingTests.swift" <<'SWIFT'
import SwiftUI
struct ThingTests: View { var body: some View { Text("x").padding(9) } }
SWIFT
cat > "$FIX/Models/AppColors.swift" <<'SWIFT'
import SwiftUI
enum AppColors { static let accent = Color(hex: "#00FF00") }
SWIFT

run() { KG_UI_TOKEN_SRC="$FIX" KG_UI_TOKEN_BASELINE="$BASE" bash "$LINT" "$@"; }

# ── 1. Syntax ─────────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$LINT" && ok "ui_token_lint.sh syntax" || fail_t "ui_token_lint.sh syntax"

# ── 2. --report never fails ───────────────────────────────────────────────────
section "--report exit 0"
if run --report >/dev/null 2>&1; then ok "--report exits 0 with findings present"
else fail_t "--report exited non-zero"; fi

# ── 3. --strict fails on raw findings + names the file ────────────────────────
section "--strict fails on raw findings"
out="$(run --strict 2>&1 || true)"
if echo "$out" | grep -q 'Dirty.swift'; then ok "--strict reports Dirty.swift"
else fail_t "--strict did not name Dirty.swift"; fi
if run --strict >/dev/null 2>&1; then fail_t "--strict exited 0 despite findings"
else ok "--strict exits non-zero with findings"; fi

# Each pattern category fires.
for pat in 'padding' 'shadow' 'cornerRadius|RoundedRectangle' 'hex|Color' 'system'; do
  echo "$out" | grep -qiE "$pat" && ok "strict detects category /$pat/" || fail_t "missing category /$pat/"
done

# ── 4. Exclusions & exemptions produce no Clean/excluded findings ─────────────
section "Exclusions & inline exemption"
echo "$out" | grep -q 'Clean.swift'        && fail_t "Clean.swift wrongly flagged" || ok "Clean.swift not flagged"
echo "$out" | grep -q 'DebugScratch.swift' && fail_t "Debug/ wrongly flagged"      || ok "Debug/ excluded"
echo "$out" | grep -q 'Thing_Preview.swift' && fail_t "*Preview* wrongly flagged"  || ok "*Preview* excluded"
echo "$out" | grep -q 'ThingTests.swift'   && fail_t "*Tests* wrongly flagged"     || ok "*Tests* excluded"
echo "$out" | grep -q 'AppColors.swift'    && fail_t "AppColors.swift wrongly flagged" || ok "AppColors.swift excluded"

# ── 5. baseline write + baseline-check on unchanged src exits 0 ───────────────
section "Baseline set-difference"
run --baseline >/dev/null 2>&1 && ok "--baseline writes file" || fail_t "--baseline failed"
[[ -s "$BASE" ]] && ok "baseline file non-empty" || fail_t "baseline file empty"
if run --baseline-check >/dev/null 2>&1; then ok "--baseline-check exits 0 on unchanged src"
else fail_t "--baseline-check regressed on unchanged src"; fi

# ── 6. baseline is line-drift resistant ───────────────────────────────────────
section "Baseline resists pure line drift"
# Prepend blank lines to Dirty.swift → every finding's line number shifts, but
# the normalized finding set is unchanged. baseline-check must still pass.
{ printf '\n\n\n'; cat "$FIX/Views/Dirty.swift"; } > "$FIX/Views/Dirty.swift.tmp"
mv "$FIX/Views/Dirty.swift.tmp" "$FIX/Views/Dirty.swift"
if run --baseline-check >/dev/null 2>&1; then ok "line drift does not regress baseline"
else fail_t "line drift falsely regressed baseline"; fi

# ── 7. genuinely new violation regresses ──────────────────────────────────────
section "New violation regresses"
cat > "$FIX/Views/Newbad.swift" <<'SWIFT'
import SwiftUI
struct Newbad: View { var body: some View { Text("x").cornerRadius(4) } }
SWIFT
if run --baseline-check >/dev/null 2>&1; then fail_t "new violation not detected by baseline-check"
else ok "new file violation regresses baseline-check"; fi

# ── result ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
