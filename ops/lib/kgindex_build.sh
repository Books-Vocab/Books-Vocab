#!/usr/bin/env bash
# Build-once-cache for the `kgindex` IndexStore extractor (ops/swiftpm).
#
# Prints the absolute path of the built release binary on stdout. Builds it via
# SwiftPM into the shared `.cache/ops-swift-build/` (git-ignored) only when the
# cached binary is missing or older than any source under ops/swiftpm.
#
# Overrides:
#   KG_KGINDEX_BINARY  — use this prebuilt binary, skip building entirely.
#
# All diagnostics go to stderr so stdout stays a clean single path for `$(...)`.
set -euo pipefail

log() { printf '%s\n' "$*" >&2; }

if [[ -n "${KG_KGINDEX_BINARY:-}" ]]; then
  [[ -x "$KG_KGINDEX_BINARY" ]] || { log "kgindex_build: KG_KGINDEX_BINARY not executable: $KG_KGINDEX_BINARY"; exit 1; }
  printf '%s\n' "$KG_KGINDEX_BINARY"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SPM_ROOT="$OPS_DIR/swiftpm"
[[ -f "$SPM_ROOT/Package.swift" ]] || { log "kgindex_build: missing $SPM_ROOT/Package.swift"; exit 1; }

# Anchor cache at git-common-dir so all worktrees share one build.
GIT_COMMON_DIR="$(git -C "$OPS_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [[ -n "$GIT_COMMON_DIR" && -d "$GIT_COMMON_DIR" ]]; then
  CACHE_ROOT="$(dirname "$GIT_COMMON_DIR")/.cache/ops-swift-build"
else
  CACHE_ROOT="$(cd "$OPS_DIR/.." && pwd)/.cache/ops-swift-build"
fi
BIN="$CACHE_ROOT/release/kgindex"

newest_src="$(find "$SPM_ROOT/Sources" "$SPM_ROOT/Package.swift" -type f -name '*.swift' -o -name 'Package.swift' 2>/dev/null \
  | xargs stat -f '%m' 2>/dev/null | sort -rn | head -1 || true)"
bin_mtime="$(stat -f '%m' "$BIN" 2>/dev/null || echo 0)"

if [[ -x "$BIN" && -n "$newest_src" && "$bin_mtime" -ge "$newest_src" ]]; then
  printf '%s\n' "$BIN"
  exit 0
fi

log "kgindex_build: building (cache: $CACHE_ROOT) ..."
mkdir -p "$CACHE_ROOT"
( cd "$SPM_ROOT" && swift build -c release --build-path "$CACHE_ROOT" >&2 )
[[ -x "$BIN" ]] || { log "kgindex_build: build succeeded but binary missing at $BIN"; exit 1; }
printf '%s\n' "$BIN"
