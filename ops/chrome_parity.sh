#!/usr/bin/env bash
#
# chrome_parity.sh — Chrome extension ⟷ iOS visual-parity contact sheet.
#
# Renders every UI *case* of the extension in real headless Chrome (zero
# install — reuses the chrome_verify transport: CDP over --remote-debugging-pipe
# + Extensions.loadUnpacked), drives each surface into its target state with an
# in-page mock, captures it at 1179×2556 (iPhone @3x — same dims as the iOS
# reference PNGs), then composites each Chrome shot beside the iOS shot it should
# mirror into ONE contact sheet.
#
# The point is low-token visual review: open the single sheet, eyeball every
# case's parity in one look, and only drill into a full-res pair if something
# looks off. No more screenshot-by-screenshot round trips.
#
# Output:
#   chrome-extension/tools/shots/*.png      per-case Chrome renders
#   chrome-extension/tools/compare/*.png    per-case Chrome|iOS pairs
#   chrome-extension/tools/compare/contact.png   the single review sheet
#   (all git-ignored — regenerable)
#
# Usage:  ops/chrome_parity.sh [--verbose] [--only <case-substring>]
# Env:    CHROME_BIN   override Chrome/Chromium binary
#         IOS_REF_DIR  iOS reference PNG folder (default: ~/Desktop/IOS截圖參考)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_DIR="$(cd "$SCRIPT_DIR/../chrome-extension" && pwd)"
cd "$EXT_DIR"

echo "▸ rendering surfaces (real headless Chrome) …"
node tools/shots.mjs "$@"

echo "▸ compositing contact sheet …"
node tools/compare.mjs

echo "✅ open chrome-extension/tools/compare/contact.png"
