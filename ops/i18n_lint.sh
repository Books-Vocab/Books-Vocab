#!/usr/bin/env bash
# i18n_lint.sh — Detect raw Chinese literals and static formatters.
#
# Modes:
#   --report   (default) Print findings, exit 0 regardless. Use for local discovery.
#   --baseline Write current findings count to ops/i18n_baseline.txt. Use to lock in a watermark.
#   --baseline-check
#              Compare current findings to baseline; fail if regressed (count > baseline).
#   --strict   Any finding fails, plus the localized_calls watermark. CI gate (ui-quality-gate).
#              Adds three coverage checks on top of the legacy finding count:
#                A. Key Coverage — every static key referenced from .swift must exist
#                   in en.lproj/Localizable.strings or .stringsdict.
#                B. EN Purity — en.lproj values may not contain CJK Unified Ideographs.
#                C. Plural Rules — for L10n.format keys whose en.lproj value contains
#                   %lld/%d (or that already have an en .stringsdict entry), every
#                   locale (en/zh-Hant/zh-Hans/ja/ko) must have a .stringsdict entry
#                   whose variables are NSStringPluralRuleType with ValueType lld
#                   (plural_missing / plural_type); en must define `one` and `other`
#                   (plural_form).
#                D. Locale Parity — every en.lproj .strings key must exist in zh-Hans/
#                   ja/ko (locale_missing; zh-Hant keys are the source text), and no
#                   value in any locale may mix numbered %1$@ with unnumbered %@
#                   (format_mixed).
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
# Localization files (every mode): a key defined twice in one .strings/.stringsdict
# (the runtime keeps the last value; ops/_i18n_duplicate_keys.py). Never debt:
# kept out of `total`, and --baseline / --baseline-check / --strict all fail on it.
# KG_I18N_SRC / KG_I18N_BASELINE redirect root / baseline for ops/tests/test_i18n_lint.sh.
#
# Exclusions: *Preview*.swift, *Tests*.swift, *PreviewData*, .localized / L10n. usage on same line.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IOS_SRC="${KG_I18N_SRC:-$ROOT_DIR/ios/BooksAndVocab}"
BASELINE_FILE="${KG_I18N_BASELINE:-$ROOT_DIR/ops/i18n_baseline.txt}"
STRIP_PREVIEWS="$ROOT_DIR/ops/_i18n_strip_previews.py"
KEY_EXTRACTOR="$ROOT_DIR/ops/_i18n_extract_keys.py"
DUPLICATE_KEYS="$ROOT_DIR/ops/_i18n_duplicate_keys.py"
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
  # agent-only visual scenes, never user-facing — same rationale as #Preview exclusion.
  --glob '!**/Debug/Scenarios/*.swift'
)

# ---- helpers ----------------------------------------------------------------

# Filter results to drop allowlisted lines and ones that are inside L10n / .localized usage.
filter_results() {
  # Drop any line containing `// i18n-allow` or that already routes through L10n / .localized.
  rg --invert-match --line-buffered 'i18n-allow|L10n\.|\.localized' || true
}

# Preview-stripped mirror of the candidate .swift files, built once per run:
#   1. Enumerate candidate .swift files (excluding *Preview*.swift / tests).
#   2. One ops/_i18n_strip_previews.py --mirror process blanks out #Preview {}
#      blocks and `private struct *Preview` containers (line numbers
#      preserved) into $STRIPPED_DIR/<path relative to $IOS_SRC>.
# It used to start one interpreter per file per pattern (~100s on the real
# tree), which is what timed the pre-commit fast tier out.
#
# The build fails closed: a stripper that dies midway (disk full, runtime error)
# leaves a partial or empty mirror, and scanning it would report zero findings
# so --baseline-check / --strict would pass on input that was never linted.
# Diagnostics are captured and replayed on stderr; exit 2 is the tool-error code.
STRIPPED_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_i18n_stripped_XXXXXX")"
MIRROR_ERR="$STRIPPED_DIR.err"
trap 'rm -rf "$STRIPPED_DIR" "$MIRROR_ERR"' EXIT
set +e
rg --files --type swift "${EXCLUDE_GLOBS[@]}" "$IOS_SRC" 2>"$MIRROR_ERR" \
  | "${PY_CMD[@]}" "$STRIP_PREVIEWS" --mirror "$IOS_SRC" "$STRIPPED_DIR" 2>>"$MIRROR_ERR"
mirror_rcs=("${PIPESTATUS[@]}")
set -e
# rg exits 1 when no file matches (an empty candidate list is a valid, empty mirror).
if [ "${mirror_rcs[0]}" -gt 1 ] || [ "${mirror_rcs[1]}" -ne 0 ]; then
  echo "[i18n_lint] error: preview-stripped mirror build failed (rg=${mirror_rcs[0]} strip=${mirror_rcs[1]}); refusing to lint a partial mirror" >&2
  cat "$MIRROR_ERR" >&2
  exit 2
fi

# Scan the stripped mirror for a raw-CJK PCRE2 pattern, map hits back to the
# on-disk path (`$IOS_SRC/<rel>:<line>:<content>`), and drop allowlisted /
# L10n-routed lines via filter_results. The mirror holds exactly the filtered
# candidate list, so rg is told not to apply ignore/hidden rules a second time.
_scan_pattern() {
  local pattern="$1"
  rg --no-heading -n --pcre2 --no-ignore --hidden --sort path "$pattern" "$STRIPPED_DIR" 2>/dev/null \
    | sed "s|^$STRIPPED_DIR/|$IOS_SRC/|" \
    | filter_results || true
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

# A helper crash is itself a finding: the gate must not read "could not scan" as clean.
scan_duplicate_keys() {
  "${PY_CMD[@]}" "$DUPLICATE_KEYS" "$IOS_SRC" || echo "duplicate-key scan failed: $DUPLICATE_KEYS"
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
    print("missing_key: <key extractor failed; coverage unverified>")  # fail closed
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

# Check D: (1) every key in en.lproj/Localizable.strings must exist in zh-Hans, ja
# and ko — L10n falls back to en on a miss, so a gap silently ships English (#2435).
# zh-Hant is the source language: its keys ARE the Chinese fallback, so a gap there
# is harmless and skipped. A locale without a Localizable.strings is skipped (the
# plural check and the duplicate-key scan already flag missing locale files).
# (2) no value in any locale may mix numbered (%1$@) and unnumbered (%@) specs:
# NSString(format:) then drops the arguments the numbered spec skipped (#2430).
scan_locale_parity() {
  [ -f "$EN_STRINGS" ] || return 0
  "${PY_CMD[@]}" - "$IOS_SRC" <<'PY' || echo "locale_missing: <parity scan failed; coverage unverified>"
import os, re, sys
root = sys.argv[1]
ENTRY = re.compile(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;')
SPEC = re.compile(r'%%|%(\d+\$)?[-+ #0]*\d*(?:\.\d+)?(?:hh?|ll?|[qzjtL])?[@a-zA-Z]')
def load(loc):
    path = os.path.join(root, f"{loc}.lproj", "Localizable.strings")
    if not os.path.isfile(path):
        return None
    src = re.sub(r"/\*.*?\*/", "", open(path, encoding="utf-8").read(), flags=re.DOTALL)
    return {m.group(1): m.group(2) for m in ENTRY.finditer(src)}
tables = {loc: load(loc) for loc in ("en", "zh-Hant", "zh-Hans", "ja", "ko")}
en = tables["en"] or {}
for loc in ("zh-Hans", "ja", "ko"):
    if tables[loc] is None:
        continue
    for k in sorted(k for k in en if k not in tables[loc]):
        print(f"locale_missing: [{loc}] {k!r}")
for loc, table in tables.items():
    for k, v in sorted((table or {}).items()):
        specs = [m.group(1) for m in SPEC.finditer(v) if m.group(0) != "%%"]
        if any(specs) and not all(specs):
            print(f"format_mixed: [{loc}] {k!r} -> {v!r}")
PY
}

# Check C: plural keys (L10n.format keys whose en .strings value uses %lld/%d,
# plus any L10n.format key already in the en .stringsdict) must have, in every
# shipped locale, a .stringsdict entry whose variables are plural rules with
# ValueType lld. `d` truncates Int64 counts to 32 bits at runtime; a missing
# locale entry silently falls back to the raw .strings template.
scan_plural_coverage() {
  [ -f "$KEY_EXTRACTOR" ] || return 0
  [ -f "$EN_STRINGS" ] || return 0
  "${PY_CMD[@]}" - "$KEY_EXTRACTOR" "$EN_STRINGS" "$IOS_SRC" <<'PY' || true
import json, plistlib, re, subprocess, sys
extractor, en_strings, ios_src = sys.argv[1], sys.argv[2], sys.argv[3]
LOCALES = ("en", "zh-Hant", "zh-Hans", "ja", "ko")
try:
    payload = json.loads(subprocess.check_output([sys.executable, extractor], text=True))
except Exception as e:
    sys.stderr.write(f"[i18n_lint] key extractor failed: {e}\n")
    print("plural_missing: <key extractor failed; coverage unverified>")  # fail closed
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
sd = {}      # locale -> parsed stringsdict (None = file missing)
broken = set()
for loc in LOCALES:
    path = f"{ios_src}/{loc}.lproj/Localizable.stringsdict"
    try:
        with open(path, "rb") as f:
            sd[loc] = plistlib.load(f)
    except FileNotFoundError:
        sd[loc] = {}
    except Exception as e:
        sys.stderr.write(f"[i18n_lint] cannot parse {path}: {e}\n")
        sd[loc] = {}
        broken.add(loc)
for loc in sorted(broken):
    print(f"plural_missing: <{loc}.lproj stringsdict unparseable; coverage unverified>")
int_spec = re.compile(r"%(?:\d+\$)?(?:[+\- 0#]*\d*(?:\.\d+)?)?(?:ll|l|h|hh|z|j|t)?[di]")
keys = set()
for k in payload.get("plural_keys", []):
    if k in sd["en"] or int_spec.search(en_value.get(k) or ""):
        keys.add(k)
for k in sorted(keys):
    for loc in LOCALES:
        if loc in broken:
            continue
        entry = sd[loc].get(k)
        if not isinstance(entry, dict):
            print(f"plural_missing: {k!r} (no stringsdict entry in {loc})")
            continue
        for var, body in entry.items():
            if var == "NSStringLocalizedFormatKey" or not isinstance(body, dict):
                continue
            spec = body.get("NSStringFormatSpecTypeKey")
            vt = body.get("NSStringFormatValueTypeKey")
            if spec != "NSStringPluralRuleType" or vt != "lld":
                print(f"plural_type: {k!r} [{loc}] var {var!r} SpecType={spec} ValueType={vt} (want NSStringPluralRuleType/lld)")
            if loc == "en" and not {"one", "other"} <= body.keys():
                print(f"plural_form: {k!r} [en] var {var!r} missing one/other")
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
localized_hits="$(scan_localized_usage)"
dup_hits="$(scan_duplicate_keys)"

raw_count=$(count_lines "$raw_hits")
ret_count=$(count_lines "$ret_hits")
fmt_count=$(count_lines "$fmt_hits")
localized_count=$(count_lines "$localized_hits")
dup_count=$(count_lines "$dup_hits")
total=$((raw_count + ret_count + fmt_count))

# Strict-only extras — computed lazily; counts default to 0 in non-strict modes.
missing_key_hits=""
en_cjk_hits=""
plural_missing_hits=""
parity_hits=""
missing_key_count=0
en_cjk_count=0
plural_missing_count=0
parity_count=0

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
  if [ -n "$dup_hits" ]; then
    echo "=== Duplicate localization keys ($dup_count) ==="
    printf '%s\n' "$dup_hits"
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
    echo "=== Plural rule problems ($plural_missing_count) ==="
    printf '%s\n' "$plural_missing_hits"
    echo
  fi
  if [ -n "$parity_hits" ]; then
    echo "=== Locale parity / mixed format specs ($parity_count) ==="
    printf '%s\n' "$parity_hits"
    echo
  fi
  echo "[i18n_lint] total: $total (raw=$raw_count return=$ret_count fmt=$fmt_count missing_keys=$missing_key_count en_cjk=$en_cjk_count plural=$plural_missing_count dup=$dup_count localized_calls=$localized_count)"
}

# Duplicate keys are never debt: no gating mode may fold them into a watermark.
reject_duplicates() {
  [ "$dup_count" -eq 0 ] && return 0
  echo "[i18n_lint] FAIL: $dup_count duplicate-key finding(s); fix them, they cannot be baselined" >&2
  exit 1
}

# True when the baseline carries any localized_calls= line, even a malformed one.
has_localized_watermark() {
  grep -q '^localized_calls=' "$BASELINE_FILE" 2>/dev/null
}

# .localized debt only ratchets down; --strict (CI) requires the watermark to exist.
# Fail closed (exit 2, tool error) unless it is exactly one non-negative integer:
# a malformed value would make `[ -gt ]` error, read false inside `if`, and pass.
check_localized_watermark() {
  local lines n
  lines=$(grep '^localized_calls=' "$BASELINE_FILE" 2>/dev/null || true)
  if [ -z "$lines" ]; then
    echo "[i18n_lint] error: no localized_calls= watermark in $BASELINE_FILE" >&2
    exit 2
  fi
  n=$(printf '%s\n' "$lines" | grep -c .)
  if [ "$n" -ne 1 ]; then
    echo "[i18n_lint] error: duplicate localized_calls watermark ($n lines) in $BASELINE_FILE" >&2
    exit 2
  fi
  localized_baseline=${lines#localized_calls=}
  case "$localized_baseline" in
    ''|*[!0-9]*)
      echo "[i18n_lint] error: malformed localized_calls watermark '$localized_baseline' in $BASELINE_FILE (want a non-negative integer)" >&2
      exit 2
      ;;
  esac
  if [ "$localized_count" -gt "$localized_baseline" ]; then
    echo "[i18n_lint] REGRESSION: localized_calls $localized_count > baseline $localized_baseline" >&2
    exit 1
  fi
}

case "$MODE" in
  --baseline)
    print_findings
    reject_duplicates
    cat > "$BASELINE_FILE" <<EOF
findings=$total
localized_calls=$localized_count
EOF
    echo "[i18n_lint] baseline written to $BASELINE_FILE (findings=$total localized_calls=$localized_count)"
    exit 0
    ;;
  --baseline-check)
    print_findings
    reject_duplicates
    if [ ! -f "$BASELINE_FILE" ]; then
      echo "[i18n_lint] error: $BASELINE_FILE missing; run --baseline first" >&2
      exit 2
    fi
    baseline=$(awk -F= '/^findings=/{print $2}' "$BASELINE_FILE")
    if [ -z "$baseline" ]; then
      baseline=$(tr -d '[:space:]' < "$BASELINE_FILE")
    fi
    case "$baseline" in
      ''|*[!0-9]*)  # empty, non-numeric or multi-line: `[ -gt ]` would error and read false
        echo "[i18n_lint] error: malformed findings baseline '$baseline' in $BASELINE_FILE (want one non-negative integer)" >&2
        exit 2
        ;;
    esac
    if [ "$total" -gt "$baseline" ]; then
      echo "[i18n_lint] REGRESSION: $total > baseline $baseline" >&2
      exit 1
    fi
    ! has_localized_watermark || check_localized_watermark
    echo "[i18n_lint] ok: $total <= baseline $baseline"
    exit 0
    ;;
  --strict)
    # Compute coverage / purity / plural checks (strict-only — they require
    # Python stdlib plistlib and the extractor script).
    missing_key_hits="$(scan_key_coverage)"
    en_cjk_hits="$(scan_en_purity)"
    plural_missing_hits="$(scan_plural_coverage)"
    parity_hits="$(scan_locale_parity)"
    missing_key_count=$(count_lines "$missing_key_hits")
    en_cjk_count=$(count_lines "$en_cjk_hits")
    plural_missing_count=$(count_lines "$plural_missing_hits")
    parity_count=$(count_lines "$parity_hits")
    strict_total=$((total + missing_key_count + en_cjk_count + plural_missing_count + parity_count))
    print_findings
    reject_duplicates
    if [ "$strict_total" -gt 0 ]; then
      echo "[i18n_lint] FAIL strict: $strict_total findings (legacy=$total, coverage=$missing_key_count, en_cjk=$en_cjk_count, plural=$plural_missing_count, parity=$parity_count)" >&2
      exit 1
    fi
    check_localized_watermark
    echo "[i18n_lint] ok strict: 0 findings, localized_calls $localized_count <= baseline $localized_baseline"
    exit 0
    ;;
  --report|*)
    print_findings
    exit 0
    ;;
esac
