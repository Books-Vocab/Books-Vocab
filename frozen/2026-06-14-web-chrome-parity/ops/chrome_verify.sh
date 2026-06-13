#!/usr/bin/env bash
#
# chrome_verify.sh — Chrome extension startup verification.
#
# Passing this means: the extension LOADS and every surface renders a correct
# initial state in real Chrome — no manifest/asset/syntax breakage, and no
# `hidden` element left visible by a CSS cascade (the class of bug that froze
# the side panel on an empty word-detail panel). It does NOT replace manual
# QA of interaction flows or audio — it is a *startup* gate.
#
# Three layers, fail-fast:
#   1. static  — manifest integrity, JS syntax, HTML asset refs, i18n keys
#   2. unit    — node:test (pure logic + CSS/inline-mirror/background effect guards)
#   3. smoke   — loads the unpacked extension into the system Chrome headless
#                (zero install, isolated profile) and asserts every [hidden]
#                element computes display:none + no uncaught errors on load
#
# Usage:  ops/chrome_verify.sh [--verbose] [--static-only]
#   --static-only   skip Layer 3 (fast; for CI hosts without a browser)
# Env:    CHROME_BIN  override the Chrome/Chromium binary path
set -euo pipefail

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT_DIR="$(cd "$SCRIPT_DIR/../chrome-extension" && pwd)"
cd "$EXT_DIR"

VERBOSE=""
STATIC_ONLY=0
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    --verbose) VERBOSE="--verbose" ;;
    --static-only) STATIC_ONLY=1 ;;
    *) echo "unknown arg: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

echo "▸ Layer 1: static integrity"
node tools/static.mjs

echo "▸ Layer 2: unit tests"
node --test --test-reporter=dot shared/*.test.js content/*.test.js background.test.mjs

if [ "$STATIC_ONLY" -eq 1 ]; then
  echo "▸ Layer 3: skipped (--static-only)"
else
  chrome_found=0
  if [ -n "${CHROME_BIN:-}" ] && [ -x "${CHROME_BIN}" ]; then chrome_found=1; fi
  if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then chrome_found=1; fi
  if command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then chrome_found=1; fi
  if [ "$chrome_found" -eq 1 ]; then
    echo "▸ Layer 3: render smoke (real Chrome headless)"
    node tools/smoke.mjs $VERBOSE
  else
    echo "▸ Layer 3: skipped (no Chrome found — set CHROME_BIN, or pass --static-only)" >&2
  fi
fi

echo "✅ chrome_verify passed"
