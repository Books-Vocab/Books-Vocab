#!/usr/bin/env bash
# i18n_lint.sh — Detect raw Chinese literals, static formatters, and xcstrings needs_review entries.
#
# Modes:
#   --report   (default) Print findings, exit 0 regardless. Use for local discovery.
#   --baseline Write current findings count to ops/i18n_baseline.txt. Use to lock in a watermark.
#   --baseline-check
#              Compare current findings to baseline; fail if regressed (count > baseline).
#   --strict   Any finding fails. Use in CI / Xcode Run Script Phase after sweep done.
#              Adds three coverage checks on top of the legacy finding count:
#                A. Key Coverage — every static key referenced from .swift must exist
#                   in en.lproj/Localizable.strings or .stringsdict.
#                B. EN Purity — en.lproj values may not contain CJK Unified Ideographs.
#                C. Plural Coverage — for L10n.format keys whose en.lproj value contains
#                   %lld/%d, a matching .stringsdict entry must exist.
#
# Allowlist:
#   - Per-line:  `// i18n-allow: <reason>`  on the same line to exempt
#                (e.g. brand names, proper nouns, ASCII-only technical IDs).
#   - Per-file:  `// i18n-allow: locale-neutral` anywhere in the file exempts the
#                file from the static-formatter check (use for wire-format /
#                internal-key formatters that pin Locale to en_US_POSIX with
#                ASCII format tokens like "yyyy-MM-dd" or "HH:mm:ss").
#   - Auto:      ISO8601DateFormatter declarations are always exempt (wire format).
#   - Auto:      `#Preview { ... }` blocks and `private struct *Preview` view
#                containers are stripped before scanning (demo-only, not user-
#                facing). See ops/_i18n_strip_previews.py.
#
# Patterns scanned (Swift):
#   - Text("中") / Button("中") / Label("中") / .navigationTitle("中") / Section("中")
#   - Text(verbatim: "中") / .alert("中") / Toggle("中") / Picker("中") / Menu("中")
#   - .confirmationDialog("中") / TextField(".*中") / .accessibilityHint("中")
#   - <*toast*>.(success|error|info|warning)("中") / reportError("中")
#     (matches toastCoordinator AND local aliases like `let toast = toastCoordinator`)
#   - ProgressView("中") / vocabLabelChip(title: "中") / .accessibilityLabel("中")
#   - static let \w+ = (DateFormatter|RelativeDateTimeFormatter|NumberFormatter)
#
# Exclusions: *Preview*.swift, *Tests*.swift, *PreviewData*, .localized / L10n. usage on same line.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IOS_SRC="$ROOT_DIR/ios/BooksAndVocab"
XCSTRINGS="$IOS_SRC/Localization/Localizable.xcstrings"
BASELINE_FILE="$ROOT_DIR/ops/i18n_baseline.txt"
STRIP_PREVIEWS="$ROOT_DIR/ops/_i18n_strip_previews.py"
KEY_EXTRACTOR="$ROOT_DIR/ops/_i18n_extract_keys.py"
EN_STRINGS="$IOS_SRC/en.lproj/Localizable.strings"
EN_STRINGSDICT="$IOS_SRC/en.lproj/Localizable.stringsdict"

MODE="${1:---report}"

if ! command -v rg >/dev/null 2>&1; then
  echo "[i18n_lint] error: ripgrep (rg) not installed" >&2
  exit 2
fi

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi
PY_BIN="$("$UV_BIN" python find 3.13)"
PY_CMD=("$PY_BIN")

# ---- pattern definitions ----------------------------------------------------

# Raw Chinese in SwiftUI text-bearing positions.
# Unicode range [\x{4e00}-\x{9fff}] covers CJK Unified Ideographs Block.
# We anchor on the opening API call to reduce false positives.
RAW_CHINESE_PATTERN='(Text|Button|Label|Section|Toggle|Picker|Menu|TextField)\("[^"]*[\x{4e00}-\x{9fff}]|\.navigationTitle\("[^"]*[\x{4e00}-\x{9fff}]|Text\(verbatim:\s*"[^"]*[\x{4e00}-\x{9fff}]|\.alert\("[^"]*[\x{4e00}-\x{9fff}]|\.confirmationDialog\("[^"]*[\x{4e00}-\x{9fff}]|\.accessibilityHint\("[^"]*[\x{4e00}-\x{9fff}]|\b\w*[Tt]oast\w*\.(success|error|info|warning)\("[^"]*[\x{4e00}-\x{9fff}]|\breportError\("[^"]*[\x{4e00}-\x{9fff}]|ProgressView\("[^"]*[\x{4e00}-\x{9fff}]|vocabLabelChip\(title:\s*"[^"]*[\x{4e00}-\x{9fff}]|\.accessibilityLabel\("[^"]*[\x{4e00}-\x{9fff}]'

# Raw Chinese returned from a function / computed property — catches the
# enum-label-getter blind spot (e.g. `var label: String { case .x: return "中" }`).
# These reach UI via variable references (`Text(option.label)`) which
# RAW_CHINESE_PATTERN cannot statically see.
# Filtered by filter_results (drops L10n. / .localized / i18n-allow lines).
RAW_RETURN_CHINESE_PATTERN='\breturn\s+"[^"]*[\x{4e00}-\x{9fff}]'

STATIC_FORMATTER_PATTERN='static\s+let\s+\w+.*(DateFormatter|RelativeDateTimeFormatter|NumberFormatter)'
LOCALIZED_USAGE_PATTERN='\.localized\b'

EXCLUDE_GLOBS=(
  --glob '!**/*Preview*.swift'
  --glob '!**/*Tests*.swift'
  --glob '!**/*PreviewData*'
  # DEBUG-only Playbook catalog fixtures (#if DEBUG && canImport(Playbook));
  # visual-regression scenes, never user-facing — same rationale as #Preview exclusion.
  --glob '!**/Debug/Scenarios/*.swift'
)

# ---- helpers ----------------------------------------------------------------

# Filter results to drop allowlisted lines and ones that are inside L10n / .localized usage.
filter_results() {
  # Drop any line containing `// i18n-allow` or that already routes through L10n / .localized.
  rg --invert-match --line-buffered 'i18n-allow|L10n\.|\.localized' || true
}

# Scan candidate .swift files for a raw-CJK PCRE2 pattern:
#   1. Enumerate candidate .swift files (excluding *Preview*.swift / tests).
#   2. For each, pipe through ops/_i18n_strip_previews.py to blank out
#      #Preview {} blocks and `private struct *Preview` containers
#      (line numbers preserved).
#   3. Run rg with --line-number on the stripped stream, prefix the file path.
#   4. Drop allowlisted / L10n-routed lines via filter_results.
_scan_pattern() {
  local pattern="$1"
  local files file stripped hits
  files=$(rg --files --type swift "${EXCLUDE_GLOBS[@]}" "$IOS_SRC" 2>/dev/null || true)
  if [ -z "$files" ]; then
    return 0
  fi
  hits=""
  while IFS= read -r file; do
    [ -z "$file" ] && continue
    stripped=$("${PY_CMD[@]}" "$STRIP_PREVIEWS" "$file" 2>/dev/null) || continue
    local file_hits
    file_hits=$(printf '%s\n' "$stripped" \
      | rg --no-heading -n --pcre2 "$pattern" 2>/dev/null \
      | sed "s|^|$file:|" || true)
    if [ -n "$file_hits" ]; then
      if [ -z "$hits" ]; then
        hits="$file_hits"
      else
        hits="$hits
$file_hits"
      fi
    fi
  done <<< "$files"
  printf '%s' "$hits" | filter_results || true
}

scan_raw_chinese() {
  _scan_pattern "$RAW_CHINESE_PATTERN"
}

# Drop any hit whose source file contains a file-wide
# `// i18n-allow: locale-neutral` opt-out marker. Used by AppDateFormatters
# (POSIX locale + ASCII wire-format tokens) and its centralized aliases.
filter_locale_neutral_files() {
  awk -F: '
    {
      file = $1
      if (!(file in seen)) {
        seen[file] = 0
        # Inline scan for marker.
        while ((getline line < file) > 0) {
          if (line ~ /\/\/[[:space:]]*i18n-allow:[[:space:]]*locale-neutral/) {
            seen[file] = 1
            break
          }
        }
        close(file)
      }
      if (seen[file] == 0) print $0
    }
  '
}

scan_raw_return_chinese() {
  # Mirror of scan_raw_chinese for `return "中..."` lines.
  _scan_pattern "$RAW_RETURN_CHINESE_PATTERN"
}

scan_static_formatter() {
  rg --no-heading -n --pcre2 --type swift "${EXCLUDE_GLOBS[@]}" \
    "$STATIC_FORMATTER_PATTERN" "$IOS_SRC" 2>/dev/null \
    | rg --invert-match --line-buffered 'i18n-allow|LocaleAwareFormatter|ISO8601DateFormatter|=\s*AppDateFormatters\.' \
    | filter_locale_neutral_files || true
}

scan_localized_usage() {
  rg --no-heading -n --pcre2 --type swift "${EXCLUDE_GLOBS[@]}" \
    "$LOCALIZED_USAGE_PATTERN" "$IOS_SRC" 2>/dev/null || true
}

# Parse .xcstrings JSON for entries with state=needs_review and empty value.
# We use plain JSON parsing (Python) to keep zero deps beyond stdlib.
scan_xcstrings_needs_review() {
  if [ ! -f "$XCSTRINGS" ]; then
    return 0
  fi
  "${PY_CMD[@]}" - <<PY 2>/dev/null || true
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

# ---- strict-only coverage checks --------------------------------------------
#
# These run only in --strict mode (gated by main). They compare the Swift call
# sites against en.lproj as the canonical English source. Any miss = guaranteed
# English-mode regression to Chinese (via L10n fallback `current → en → key`).

# Check A: every static key from .swift must exist in en.lproj/.strings or
# .stringsdict. Reports missing keys.
scan_key_coverage() {
  [ -f "$KEY_EXTRACTOR" ] || return 0
  [ -f "$EN_STRINGS" ] || return 0
  "${PY_CMD[@]}" - "$KEY_EXTRACTOR" "$EN_STRINGS" "$EN_STRINGSDICT" <<'PY' || true
import json, plistlib, re, subprocess, sys
extractor, en_strings, en_stringsdict = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    payload = json.loads(subprocess.check_output([sys.executable, extractor], text=True))
except Exception as e:
    sys.stderr.write(f"[i18n_lint] key extractor failed: {e}\n")
    sys.exit(0)
# Parse en.lproj/Localizable.strings — simple "key" = "value"; entries; ignore
# // and /* */ comments. Tolerant rather than strict — we want every defined key.
defined = set()
try:
    src = open(en_strings, "r", encoding="utf-8").read()
except Exception as e:
    sys.stderr.write(f"[i18n_lint] cannot read {en_strings}: {e}\n")
    sys.exit(0)
src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"(?:[^"\\]|\\.)*"\s*;', src):
    defined.add(m.group(1))
# Add stringsdict keys (plist).
try:
    with open(en_stringsdict, "rb") as f:
        d = plistlib.load(f)
        defined.update(d.keys())
except FileNotFoundError:
    pass
except Exception as e:
    sys.stderr.write(f"[i18n_lint] cannot parse {en_stringsdict}: {e}\n")
missing = sorted(k for k in payload.get("keys", []) if k not in defined)
for k in missing:
    print(f"missing_key: {k}")
PY
}

# Check B: en.lproj values may not contain CJK Unified Ideographs (would render
# in English mode after L10n fallback). Scans both .strings (values only) and
# .stringsdict (every leaf string).
scan_en_purity() {
  "${PY_CMD[@]}" - "$EN_STRINGS" "$EN_STRINGSDICT" <<'PY' || true
import plistlib, re, sys
en_strings, en_stringsdict = sys.argv[1], sys.argv[2]
cjk = re.compile(r"[一-鿿]")
# .strings: extract value side only
try:
    src = open(en_strings, "r", encoding="utf-8").read()
except FileNotFoundError:
    src = ""
src_nc = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', src_nc):
    key, val = m.group(1), m.group(2)
    if cjk.search(val):
        print(f"en_cjk:strings: {key!r} -> {val!r}")
# .stringsdict: every str leaf except the structural NSStringFormat* metadata keys
try:
    with open(en_stringsdict, "rb") as f:
        d = plistlib.load(f)
except FileNotFoundError:
    d = {}
except Exception as e:
    sys.stderr.write(f"[i18n_lint] cannot parse {en_stringsdict}: {e}\n")
    d = {}
def walk(node, trail):
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, trail + [str(k)])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, trail + [f"[{i}]"])
    elif isinstance(node, str):
        if cjk.search(node):
            print(f"en_cjk:stringsdict:{'/'.join(trail)}: {node!r}")
for k, v in d.items():
    walk(v, [str(k)])
PY
}

# Check C: for L10n.format keys whose en.lproj/.strings value uses %lld/%d
# (integer specifier likely intended as plural-rule subject), a matching
# .stringsdict NSStringLocalizedFormatKey entry MUST exist. Otherwise English
# falls back to the singular-only template and 1/many distinction is lost.
scan_plural_coverage() {
  [ -f "$KEY_EXTRACTOR" ] || return 0
  [ -f "$EN_STRINGS" ] || return 0
  "${PY_CMD[@]}" - "$KEY_EXTRACTOR" "$EN_STRINGS" "$EN_STRINGSDICT" <<'PY' || true
import json, plistlib, re, subprocess, sys
extractor, en_strings, en_stringsdict = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    payload = json.loads(subprocess.check_output([sys.executable, extractor], text=True))
except Exception as e:
    sys.stderr.write(f"[i18n_lint] key extractor failed: {e}\n")
    sys.exit(0)
src = ""
try:
    src = open(en_strings, "r", encoding="utf-8").read()
except FileNotFoundError:
    pass
src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
en_value = {}
for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', src):
    en_value[m.group(1)] = m.group(2)
sd_keys = set()
try:
    with open(en_stringsdict, "rb") as f:
        sd_keys = set(plistlib.load(f).keys())
except FileNotFoundError:
    pass
except Exception as e:
    sys.stderr.write(f"[i18n_lint] cannot parse {en_stringsdict}: {e}\n")
int_spec = re.compile(r"%(?:\d+\$)?(?:[+\- 0#]*\d*(?:\.\d+)?)?(?:ll|l|h|hh|z|j|t)?[di]")
for k in sorted(payload.get("plural_keys", [])):
    val = en_value.get(k)
    if not val:
        continue
    if int_spec.search(val) and k not in sd_keys:
        print(f"plural_missing: {k!r} (en value uses %d/%lld but no stringsdict entry)")
PY
}

# ---- main -------------------------------------------------------------------

# Count non-empty lines in a hits blob. Empty input short-circuits to 0 so the
# count stays correct regardless of trailing-newline quirks (and without the
# blanket `|| true` that would mask a real grep failure).
count_lines() {
  [ -z "$1" ] && { echo 0; return; }
  printf '%s\n' "$1" | grep -c .
}

raw_hits="$(scan_raw_chinese)"
ret_hits="$(scan_raw_return_chinese)"
fmt_hits="$(scan_static_formatter)"
xc_hits="$(scan_xcstrings_needs_review)"
localized_hits="$(scan_localized_usage)"

raw_count=$(count_lines "$raw_hits")
ret_count=$(count_lines "$ret_hits")
fmt_count=$(count_lines "$fmt_hits")
xc_count=$(count_lines "$xc_hits")
localized_count=$(count_lines "$localized_hits")
total=$((raw_count + ret_count + fmt_count + xc_count))

# Strict-only extras — computed lazily; counts default to 0 in non-strict modes.
missing_key_hits=""
en_cjk_hits=""
plural_missing_hits=""
missing_key_count=0
en_cjk_count=0
plural_missing_count=0

print_findings() {
  if [ -n "$raw_hits" ]; then
    echo "=== Raw Chinese literals ($raw_count) ==="
    printf '%s\n' "$raw_hits"
    echo
  fi
  if [ -n "$ret_hits" ]; then
    echo "=== Raw Chinese in return statements ($ret_count) ==="
    printf '%s\n' "$ret_hits"
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
  if [ -n "$missing_key_hits" ]; then
    echo "=== Missing en.lproj keys ($missing_key_count) ==="
    printf '%s\n' "$missing_key_hits"
    echo
  fi
  if [ -n "$en_cjk_hits" ]; then
    echo "=== EN value contains CJK ($en_cjk_count) ==="
    printf '%s\n' "$en_cjk_hits"
    echo
  fi
  if [ -n "$plural_missing_hits" ]; then
    echo "=== Plural rule missing ($plural_missing_count) ==="
    printf '%s\n' "$plural_missing_hits"
    echo
  fi
  echo "[i18n_lint] total: $total (raw=$raw_count return=$ret_count fmt=$fmt_count xcstrings=$xc_count missing_keys=$missing_key_count en_cjk=$en_cjk_count plural=$plural_missing_count localized_calls=$localized_count)"
}

case "$MODE" in
  --baseline)
    print_findings
    cat > "$BASELINE_FILE" <<EOF
findings=$total
localized_calls=$localized_count
EOF
    echo "[i18n_lint] baseline written to $BASELINE_FILE (findings=$total localized_calls=$localized_count)"
    exit 0
    ;;
  --baseline-check)
    print_findings
    if [ ! -f "$BASELINE_FILE" ]; then
      echo "[i18n_lint] error: $BASELINE_FILE missing; run --baseline first" >&2
      exit 2
    fi
    baseline=$(awk -F= '/^findings=/{print $2}' "$BASELINE_FILE")
    localized_baseline=$(awk -F= '/^localized_calls=/{print $2}' "$BASELINE_FILE")
    if [ -z "$baseline" ]; then
      baseline=$(tr -d '[:space:]' < "$BASELINE_FILE")
    fi
    if [ "$total" -gt "$baseline" ]; then
      echo "[i18n_lint] REGRESSION: $total > baseline $baseline" >&2
      exit 1
    fi
    if [ -n "$localized_baseline" ] && [ "$localized_count" -gt "$localized_baseline" ]; then
      echo "[i18n_lint] REGRESSION: localized_calls $localized_count > baseline $localized_baseline" >&2
      exit 1
    fi
    echo "[i18n_lint] ok: $total <= baseline $baseline"
    exit 0
    ;;
  --strict)
    # Compute coverage / purity / plural checks (strict-only — they require
    # Python stdlib plistlib and the extractor script).
    missing_key_hits="$(scan_key_coverage)"
    en_cjk_hits="$(scan_en_purity)"
    plural_missing_hits="$(scan_plural_coverage)"
    missing_key_count=$(count_lines "$missing_key_hits")
    en_cjk_count=$(count_lines "$en_cjk_hits")
    plural_missing_count=$(count_lines "$plural_missing_hits")
    strict_total=$((total + missing_key_count + en_cjk_count + plural_missing_count))
    print_findings
    if [ "$strict_total" -gt 0 ]; then
      echo "[i18n_lint] FAIL strict: $strict_total findings (legacy=$total, coverage=$missing_key_count, en_cjk=$en_cjk_count, plural=$plural_missing_count)" >&2
      exit 1
    fi
    exit 0
    ;;
  --report|*)
    print_findings
    exit 0
    ;;
esac
