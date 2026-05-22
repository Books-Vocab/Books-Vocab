#!/usr/bin/env bash
# i18n_lint.sh — Detect raw Chinese literals, static formatters, and xcstrings needs_review entries.
#
# Modes:
#   --report   (default) Print findings, exit 0 regardless. Use for local discovery.
#   --baseline Write current findings count to ops/i18n_baseline.txt. Use to lock in a watermark.
#   --baseline-check
#              Compare current findings to baseline; fail if regressed (count > baseline).
#   --strict   Any finding fails. Use in CI / Xcode Run Script Phase after sweep done.
#
# Allowlist:
#   Add `// i18n-allow: <reason>` on the same line to exempt (e.g. brand names, proper nouns).
#
# Patterns scanned (Swift):
#   - Text("中") / Button("中") / Label("中") / .navigationTitle("中") / Section("中")
#   - Text(verbatim: "中") / .alert("中") / Toggle("中") / Picker("中") / Menu("中")
#   - .confirmationDialog("中") / TextField(".*中") / .accessibilityHint("中")
#   - static let \w+ = (DateFormatter|RelativeDateTimeFormatter|NumberFormatter)
#
# Exclusions: *Preview*.swift, *Tests*.swift, *PreviewData*, .localized / L10n. usage on same line.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IOS_SRC="$ROOT_DIR/ios/BooksBrowser"
XCSTRINGS="$IOS_SRC/Localization/Localizable.xcstrings"
BASELINE_FILE="$ROOT_DIR/ops/i18n_baseline.txt"

MODE="${1:---report}"

if ! command -v rg >/dev/null 2>&1; then
  echo "[i18n_lint] error: ripgrep (rg) not installed" >&2
  exit 2
fi

# ---- pattern definitions ----------------------------------------------------

# Raw Chinese in SwiftUI text-bearing positions.
# Unicode range [\x{4e00}-\x{9fff}] covers CJK Unified Ideographs Block.
# We anchor on the opening API call to reduce false positives.
RAW_CHINESE_PATTERN='(Text|Button|Label|Section|Toggle|Picker|Menu|TextField)\("[^"]*[\x{4e00}-\x{9fff}]|\.navigationTitle\("[^"]*[\x{4e00}-\x{9fff}]|Text\(verbatim:\s*"[^"]*[\x{4e00}-\x{9fff}]|\.alert\("[^"]*[\x{4e00}-\x{9fff}]|\.confirmationDialog\("[^"]*[\x{4e00}-\x{9fff}]|\.accessibilityHint\("[^"]*[\x{4e00}-\x{9fff}]'

STATIC_FORMATTER_PATTERN='static\s+let\s+\w+.*(DateFormatter|RelativeDateTimeFormatter|NumberFormatter)'

EXCLUDE_GLOBS=(
  --glob '!**/*Preview*.swift'
  --glob '!**/*Tests*.swift'
  --glob '!**/*PreviewData*'
)

# ---- helpers ----------------------------------------------------------------

# Filter results to drop allowlisted lines and ones that are inside L10n / .localized usage.
filter_results() {
  # Drop any line containing `// i18n-allow` or that already routes through L10n / .localized.
  rg --invert-match --line-buffered 'i18n-allow|L10n\.|\.localized' || true
}

scan_raw_chinese() {
  rg --no-heading -n --pcre2 --type swift "${EXCLUDE_GLOBS[@]}" \
    "$RAW_CHINESE_PATTERN" "$IOS_SRC" 2>/dev/null | filter_results || true
}

scan_static_formatter() {
  rg --no-heading -n --pcre2 --type swift "${EXCLUDE_GLOBS[@]}" \
    "$STATIC_FORMATTER_PATTERN" "$IOS_SRC" 2>/dev/null \
    | rg --invert-match --line-buffered 'i18n-allow|LocaleAwareFormatter' || true
}

# Parse .xcstrings JSON for entries with state=needs_review and empty value.
# We use plain JSON parsing (Python) to keep zero deps beyond stdlib.
scan_xcstrings_needs_review() {
  if [ ! -f "$XCSTRINGS" ]; then
    return 0
  fi
  python3 - <<PY 2>/dev/null || true
import json, sys
path = "$XCSTRINGS"
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    sys.stderr.write(f"[i18n_lint] cannot parse xcstrings: {e}\n")
    sys.exit(0)
strings = data.get("strings", {})
hits = []
for key, body in strings.items():
    localizations = body.get("localizations", {}) or {}
    for lang, ldata in localizations.items():
        sv = ldata.get("stringUnit", {}) or {}
        if sv.get("state") == "needs_review" and not (sv.get("value") or "").strip():
            hits.append((lang, key))
for lang, key in hits:
    print(f"xcstrings:needs_review:{lang}: {key}")
PY
}

# ---- main -------------------------------------------------------------------

raw_hits="$(scan_raw_chinese)"
fmt_hits="$(scan_static_formatter)"
xc_hits="$(scan_xcstrings_needs_review)"

raw_count=$(printf '%s' "$raw_hits" | grep -c . || true)
fmt_count=$(printf '%s' "$fmt_hits" | grep -c . || true)
xc_count=$(printf '%s' "$xc_hits"  | grep -c . || true)
total=$((raw_count + fmt_count + xc_count))

print_findings() {
  if [ -n "$raw_hits" ]; then
    echo "=== Raw Chinese literals ($raw_count) ==="
    printf '%s\n' "$raw_hits"
    echo
  fi
  if [ -n "$fmt_hits" ]; then
    echo "=== Static formatters (no LocaleAwareFormatter) ($fmt_count) ==="
    printf '%s\n' "$fmt_hits"
    echo
  fi
  if [ -n "$xc_hits" ]; then
    echo "=== xcstrings needs_review + empty value ($xc_count) ==="
    printf '%s\n' "$xc_hits"
    echo
  fi
  echo "[i18n_lint] total: $total (raw=$raw_count fmt=$fmt_count xcstrings=$xc_count)"
}

case "$MODE" in
  --baseline)
    print_findings
    printf '%s\n' "$total" > "$BASELINE_FILE"
    echo "[i18n_lint] baseline written to $BASELINE_FILE = $total"
    exit 0
    ;;
  --baseline-check)
    print_findings
    if [ ! -f "$BASELINE_FILE" ]; then
      echo "[i18n_lint] error: $BASELINE_FILE missing; run --baseline first" >&2
      exit 2
    fi
    baseline=$(tr -d '[:space:]' < "$BASELINE_FILE")
    if [ "$total" -gt "$baseline" ]; then
      echo "[i18n_lint] REGRESSION: $total > baseline $baseline" >&2
      exit 1
    fi
    echo "[i18n_lint] ok: $total <= baseline $baseline"
    exit 0
    ;;
  --strict)
    print_findings
    if [ "$total" -gt 0 ]; then
      echo "[i18n_lint] FAIL strict: $total findings" >&2
      exit 1
    fi
    exit 0
    ;;
  --report|*)
    print_findings
    exit 0
    ;;
esac
