#!/usr/bin/env bash
# Offline contract tests for ios_xctestrun_cache.sh.
# No xcodebuild, simulator, or project build is allowed here.

set -u -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$WORKTREE/ops/lib/ios_xctestrun_cache.sh"
TMPROOT="$(mktemp -d -t kg_xctestrun_cache_test_XXXXXX)"
trap 'rm -rf "$TMPROOT"' EXIT

pass=0
fail=0
ok() { echo "  ✓ $*"; pass=$((pass + 1)); }
bad() { echo "  ✗ $*"; fail=$((fail + 1)); }
section() { echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "✗ missing $LIB" >&2; exit 1; }
# shellcheck source=../lib/ios_xctestrun_cache.sh
source "$LIB"

section "cache key is explicit and content keyed"
key_root="$TMPROOT/key-root"
mkdir -p "$key_root/ios"
printf 'alpha\n' >"$key_root/ios/one.swift"
printf 'beta\n' >"$key_root/ios/two.swift"
inputs=$'ios/one.swift\nios/two.swift\nios/missing.swift\n'
key_a="$(printf '%s' "$inputs" | ios_xctestrun_cache_build_key "$key_root" iphonesimulator arm64 unit BooksAndVocabUnitTests Debug 0 unsigned Xcode-26.4)"
key_b="$(printf '%s' "$inputs" | ios_xctestrun_cache_build_key "$key_root" iphonesimulator arm64 unit BooksAndVocabUnitTests Debug 0 unsigned Xcode-26.4)"
key_c="$(printf '%s' "$inputs" | ios_xctestrun_cache_build_key "$key_root" iphonesimulator arm64 ui BooksAndVocabUITests Debug 0 unsigned Xcode-26.4)"
printf 'changed\n' >"$key_root/ios/two.swift"
key_d="$(printf '%s' "$inputs" | ios_xctestrun_cache_build_key "$key_root" iphonesimulator arm64 unit BooksAndVocabUnitTests Debug 0 unsigned Xcode-26.4)"
[[ "$key_a" =~ ^[0-9a-f]{64}$ && "$key_a" == "$key_b" ]] \
  && ok "same explicit inputs produce stable sha256" || bad "cache key is not stable"
[[ "$key_a" != "$key_c" ]] \
  && ok "scope participates in cache key" || bad "scope does not partition cache key"
[[ "$key_a" != "$key_d" ]] \
  && ok "file content participates in cache key" || bad "file content does not partition cache key"

section "xctestrun discovery excludes scoped overlays"
derived="$TMPROOT/derived"
mkdir -p "$derived/Build/Products"
printf 'base' >"$derived/Build/Products/base.xctestrun"
printf 'scoped' >"$derived/Build/Products/base.scoped.xctestrun"
printf 'nested' >"$derived/Build/Products/nested.xctestrun"
found="$(ios_xctestrun_cache_find "$derived")"
all_artifacts="$(ios_xctestrun_cache_list "$derived" | paste -sd '|' -)"
[[ "$found" == "$derived/Build/Products/base.xctestrun" ]] \
  && ok "find returns sorted non-scoped artifact" || bad "find returned '$found'"
[[ "$all_artifacts" == *"base.xctestrun"* && "$all_artifacts" == *"nested.xctestrun"* \
   && "$all_artifacts" != *"scoped"* ]] \
  && ok "list excludes scoped overlays" || bad "list leaked scoped artifact: $all_artifacts"

section "products readiness is scope-aware"
products="$derived/Build/Products"
mkdir -p "$products/Debug-iphonesimulator/BooksAndVocab.app/PlugIns/BooksAndVocabTests.xctest"
mkdir -p "$products/Debug-iphonesimulator/BooksAndVocabUITests-Runner.app"
for scope in unit ui all catalog; do
  if ios_xctestrun_cache_products_ready \
      "$derived/Build/Products/base.xctestrun" Debug iphonesimulator "$scope"; then
    ok "$scope products ready"
  else
    bad "$scope products unexpectedly incomplete"
  fi
done
rm -rf "$products/Debug-iphonesimulator/BooksAndVocabUITests-Runner.app"
if ! ios_xctestrun_cache_products_ready \
    "$derived/Build/Products/base.xctestrun" Debug iphonesimulator ui; then
  ok "missing UI runner blocks ui scope"
else
  bad "missing UI runner did not block ui scope"
fi

section "scoped environment overlay and cleanup"
base="$TMPROOT/base.xctestrun"
staged="$TMPROOT/base.scoped.xctestrun"
cat >"$base" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>TestConfigurations</key><array><dict><key>TestTargets</key><array>
<dict><key>TestingEnvironmentVariables</key><dict><key>KG_FIXTURE_DATASET_B64</key><string>legacy-1</string></dict></dict>
<dict><key>BlueprintName</key><string>SecondTarget</string></dict>
</array></dict></array></dict></plist>
PLIST
if ios_xctestrun_cache_stage_env \
    "$base" "$staged" KG_FIXTURE_DATASET_DEFLATE_B64 compressed KG_FIXTURE_DATASET_B64; then
  staged_value_0="$(/usr/libexec/PlistBuddy -c 'Print :TestConfigurations:0:TestTargets:0:TestingEnvironmentVariables:KG_FIXTURE_DATASET_DEFLATE_B64' "$staged")"
  staged_value_1="$(/usr/libexec/PlistBuddy -c 'Print :TestConfigurations:0:TestTargets:1:TestingEnvironmentVariables:KG_FIXTURE_DATASET_DEFLATE_B64' "$staged")"
  if [[ "$staged_value_0" == compressed && "$staged_value_1" == compressed ]] \
      && ! /usr/libexec/PlistBuddy -c 'Print :TestConfigurations:0:TestTargets:0:TestingEnvironmentVariables:KG_FIXTURE_DATASET_B64' "$staged" >/dev/null 2>&1 \
      && ! /usr/libexec/PlistBuddy -c 'Print :TestConfigurations:0:TestTargets:1:TestingEnvironmentVariables:KG_FIXTURE_DATASET_B64' "$staged" >/dev/null 2>&1; then
    ok "overlay updates every target and removes legacy key"
  else
    bad "overlay keys were not sanitized"
  fi
else
  bad "overlay failed"
fi
[[ -f "$base" ]] && ok "base xctestrun remains untouched" || bad "base xctestrun was modified"
ios_xctestrun_cache_cleanup_scoped "$staged"
[[ ! -e "$staged" ]] && ok "scoped cleanup removes only staged artifact" || bad "scoped cleanup left staged artifact"

echo ""
echo "passed=$pass failed=$fail"
[[ "$fail" -eq 0 ]]
