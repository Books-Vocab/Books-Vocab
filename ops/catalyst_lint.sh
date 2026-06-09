#!/usr/bin/env bash
# catalyst_lint.sh — Catch SwiftUI patterns that crash on Mac Catalyst.
#
# Rule 1 (toolbar-popover): `.popover(` lexically nested inside a `.toolbar { }`
#   or `ToolbarItem { }` block. On Mac Catalyst, presenting a popover anchored to
#   a toolbar button traps inside UIKit's keyboard-scene pin path
#   (_pinInputViewsForKeyboardSceneDelegate) → EXC_BREAKPOINT, no app frame.
#   Use `.sheet` instead. See docs/sop/ios.md「Catalyst 雷區」.
#
# Modes:
#   --report  (default) print findings, exit 0. Local discovery.
#   --strict  any finding fails (exit 1). CI gate. Baseline is 0.
#
# Allowlist: `// catalyst-allow: <reason>` on the same line as the `.popover(`.
#
# Scope: ios/BooksAndVocab/**/*.swift, excluding *Preview*.swift / *Tests*.swift.

set -euo pipefail

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/ios/BooksAndVocab"
MODE="--report"

case "$#" in
  0)
    ;;
  1)
    case "${1:-}" in
      -h|--help)
        usage
        exit 0
        ;;
      --report|--strict)
        MODE="$1"
        ;;
      *)
        echo "✗ unknown option: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  *)
    echo "✗ catalyst_lint 只接受單一 mode 參數" >&2
    usage >&2
    exit 2
    ;;
esac

found=0
while IFS= read -r -d '' f; do
  awk -v FN="$f" '
    function count(s, ch,   n, i) { n = 0; for (i = 1; i <= length(s); i++) if (substr(s, i, 1) == ch) n++; return n }
    {
      line = $0
      if (active && line ~ /\.popover\(/ && line !~ /catalyst-allow/) {
        printf "%s:%d: .popover() inside a toolbar block — crashes on Mac Catalyst, use .sheet\n", FN, FNR
        bad++
      }
      if (!active && line ~ /(\.toolbar[[:space:]]*[{(]|ToolbarItem)/) { active = 1; base = depth }
      depth += count(line, "{") - count(line, "}")
      if (active && depth <= base) active = 0
    }
    END { exit (bad > 0 ? 1 : 0) }
  ' "$f" || found=$((found + 1))
done < <(find "$SRC" -name '*.swift' ! -name '*Preview*.swift' ! -name '*Tests*.swift' -print0)

echo "[catalyst_lint] toolbar-popover findings in files: $found"
if [[ "$MODE" == "--strict" && "$found" -gt 0 ]]; then
  echo "[catalyst_lint] FAIL — fix the above or annotate with // catalyst-allow: <reason>" >&2
  exit 1
fi
