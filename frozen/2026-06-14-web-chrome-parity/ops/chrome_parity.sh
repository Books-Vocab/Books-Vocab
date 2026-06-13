#!/usr/bin/env bash
#
# chrome_parity.sh — Chrome extension ⟷ iOS visual-parity tooling.
#
# Renders every UI *case* of the extension in real headless Chrome (zero
# install — reuses the chrome_verify transport: CDP over --remote-debugging-pipe
# + Extensions.loadUnpacked), drives each surface into its target state with an
# in-page mock, captures it at 1179×2556 (iPhone @3x — same dims as Catalog
# snapshot PNGs), then composites each Chrome shot beside the iOS Catalog
# surface it should mirror into ONE contact sheet. With --audit, also emits
# per-case diff, zoomed crop strips, palette summaries, and numeric metrics.
#
# iOS references come from the Catalog snapshot system (source-SoT, regenerable
# via `./ops/ios_ops.sh catalog snapshots`), addressed by {surface, scenario,
# appearance} in chrome-extension/tools/parity-manifest.mjs — no hand-shot
# reference folder.
#
# The contact sheet is only the overview. Use --audit whenever precise parity
# matters: inspect diff.png for pixel displacement, zoom.png for close reading,
# palette.txt for color drift, and metrics.json/summary.json for trends.
#
# Output:
#   chrome-extension/tools/shots/*.png      per-case Chrome renders
#   chrome-extension/tools/compare/*.png    per-case Chrome|iOS pairs
#   chrome-extension/tools/compare/contact.png   the single review sheet
#   chrome-extension/tools/audit/<case>/*   --audit drill-down artifacts
#   (all git-ignored — regenerable)
#
# Usage:  ops/chrome_parity.sh [--audit] [--verbose] [--only <case-substring>]
# Env:    CHROME_BIN       override Chrome/Chromium binary
#         KG_CATALOG_ROOT  catalog snapshot root override (default: newest
#                          usable build/snapshots/catalog-full-*/)
set -euo pipefail

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_DIR="$(cd "$SCRIPT_DIR/../chrome-extension" && pwd)"
cd "$EXT_DIR"

AUDIT=0
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --audit)
      AUDIT=1
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

echo "▸ rendering surfaces (real headless Chrome) …"
if [[ "${#ARGS[@]}" -gt 0 ]]; then
  node tools/shots.mjs "${ARGS[@]}"
else
  node tools/shots.mjs
fi

echo "▸ compositing contact sheet …"
node tools/compare.mjs

if [[ "$AUDIT" == "1" ]]; then
  echo "▸ auditing per-case pixel/color parity …"
  if [[ "${#ARGS[@]}" -gt 0 ]]; then
    node tools/parity-audit.mjs "${ARGS[@]}"
  else
    node tools/parity-audit.mjs
  fi
fi

echo "✅ open chrome-extension/tools/compare/contact.png"
if [[ "$AUDIT" == "1" ]]; then
  echo "✅ inspect chrome-extension/tools/audit/<case>/{diff.png,zoom.png,palette.txt,metrics.json}"
fi
