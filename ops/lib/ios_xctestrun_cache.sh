#!/usr/bin/env bash
# Shared, source-only xctestrun/cache primitives.
#
# Callers own policy (scope selection, build/test commands, locks, heartbeats,
# and output receipts).  These functions deliberately take all lifecycle data
# as arguments so ios_test.sh and Catalog cannot silently grow divergent cache
# semantics again.

ios_xctestrun_cache_build_key() {
  local project_root="$1" platform="$2" arch="$3" scope="$4" scheme="$5"
  local configuration="$6" coverage="$7" signing="$8" xcode_version="$9"
  local path
  [[ -d "$project_root" ]] || return 1
  {
    printf 'platform=%s\n' "$platform"
    printf 'arch=%s\n' "$arch"
    printf 'scope=%s\n' "$scope"
    printf 'scheme=%s\n' "$scheme"
    printf 'configuration=%s\n' "$configuration"
    printf 'coverage=%s\n' "$coverage"
    printf 'signing=%s\n' "$signing"
    printf 'xcode=%s\n' "$xcode_version"
    # Input paths arrive on stdin, one path per line.  Missing generated files
    # are intentionally ignored: a fresh worktree may not have Package.resolved
    # until Xcode resolves SwiftPM, and a missing path must not become a false
    # cache failure.  Keep the path in shasum output so two equal file blobs at
    # different paths cannot collide.
    while IFS= read -r path; do
      [[ -n "$path" && -f "$project_root/$path" ]] || continue
      printf '%s\0' "$path"
    done | (cd "$project_root" && xargs -0 shasum -a 256 2>/dev/null)
  } | shasum -a 256 | awk '{print $1}'
}

ios_xctestrun_cache_find() {
  local derived_data_root="$1" candidate
  [[ -d "$derived_data_root" ]] || return 1
  while IFS= read -r candidate; do
    [[ -f "$candidate" ]] || continue
    [[ "$candidate" == *.scoped.xctestrun ]] && continue
    printf '%s\n' "$candidate"
    return 0
  done < <(find "$derived_data_root" -type f -name '*.xctestrun' ! -name '*.scoped.xctestrun' -print | sort)
  return 1
}

ios_xctestrun_cache_list() {
  local derived_data_root="$1"
  [[ -d "$derived_data_root" ]] || return 0
  find "$derived_data_root" -type f -name '*.xctestrun' ! -name '*.scoped.xctestrun' -print | sort
}

ios_xctestrun_cache_products_ready() {
  local xctestrun_path="$1" configuration="$2" sdk_suffix="$3" scope="$4"
  local products_root app_bundle unit_bundle ui_bundle
  [[ -n "$xctestrun_path" && -f "$xctestrun_path" ]] || return 1
  products_root="$(dirname "$xctestrun_path")"
  app_bundle="$products_root/$configuration-$sdk_suffix/BooksAndVocab.app"
  unit_bundle="$app_bundle/PlugIns/BooksAndVocabTests.xctest"
  ui_bundle="$products_root/$configuration-$sdk_suffix/BooksAndVocabUITests-Runner.app"
  [[ -d "$app_bundle" ]] || return 1
  case "$scope" in
    unit|catalog) [[ -d "$unit_bundle" ]] || return 1 ;;
    ui) [[ -d "$ui_bundle" ]] || return 1 ;;
    all) [[ -d "$unit_bundle" && -d "$ui_bundle" ]] || return 1 ;;
    *) return 64 ;;
  esac
}

ios_xctestrun_cache_env_roots() {
  local path="$1" configuration=0 target
  [[ -f "$path" && -x /usr/libexec/PlistBuddy ]] || return 1
  while /usr/libexec/PlistBuddy -c "Print :TestConfigurations:$configuration" "$path" >/dev/null 2>&1; do
    target=0
    while /usr/libexec/PlistBuddy -c "Print :TestConfigurations:$configuration:TestTargets:$target" "$path" >/dev/null 2>&1; do
      printf ':TestConfigurations:%s:TestTargets:%s:TestingEnvironmentVariables\n' "$configuration" "$target"
      target=$((target + 1))
    done
    configuration=$((configuration + 1))
  done
}

ios_xctestrun_cache_sanitize_env_root() {
  local plist_path="$1" env_root="$2" sanitize_csv="$3" sanitize_key
  [[ -f "$plist_path" && -n "$env_root" ]] || return 1
  while IFS= read -r sanitize_key; do
    [[ -n "$sanitize_key" ]] || continue
    /usr/libexec/PlistBuddy -c "Delete $env_root:$sanitize_key" "$plist_path" 2>/dev/null || true
  done < <(printf '%s\n' "$sanitize_csv" | tr ',' '\n')
}

ios_xctestrun_cache_stage_env() {
  local base_path="$1" staged_path="$2" key="$3" value="$4" sanitize_csv="${5:-}"
  local env_root roots_file status=0
  [[ -f "$base_path" && -n "$staged_path" && -n "$key" ]] || return 1
  cp "$base_path" "$staged_path" || return 1
  # Snapshot every target path before mutating the plist.  PlistBuddy rewrites
  # the file in place; enumerating and rewriting concurrently can make the
  # reader stop early and silently leave later targets unsanitized.
  roots_file="$(mktemp "${TMPDIR:-/tmp}/kg_xctestrun_env_roots.XXXXXX")" || return 1
  if ! ios_xctestrun_cache_env_roots "$staged_path" >"$roots_file"; then
    rm -f "$roots_file"
    return 1
  fi
  if [[ ! -s "$roots_file" ]]; then
    rm -f "$roots_file"
    return 1
  fi
  while IFS= read -r env_root; do
    [[ -n "$env_root" ]] || continue
    /usr/libexec/PlistBuddy -c "Add $env_root dict" "$staged_path" 2>/dev/null || true
    if ! ios_xctestrun_cache_sanitize_env_root "$staged_path" "$env_root" "$sanitize_csv"; then
      status=1
      break
    fi
    /usr/libexec/PlistBuddy -c "Delete $env_root:$key" "$staged_path" 2>/dev/null || true
    if ! /usr/libexec/PlistBuddy -c "Add $env_root:$key string $value" "$staged_path"; then
      status=1
      break
    fi
  done <"$roots_file"
  rm -f "$roots_file"
  return "$status"
}

# xcodebuild's process environment is not inherited by test-without-building's
# XCTest runner. Evidence values that tests must attest independently therefore
# need to be written into each target's TestingEnvironmentVariables in the
# scoped xctestrun copy.
ios_xctestrun_cache_upsert_env_all_targets() {
  local plist_path="$1" key="$2" value="$3"
  local env_root roots_file status=0
  [[ -f "$plist_path" && -n "$key" ]] || return 1
  roots_file="$(mktemp "${TMPDIR:-/tmp}/kg_xctestrun_env_roots.XXXXXX")" || return 1
  if ! ios_xctestrun_cache_env_roots "$plist_path" >"$roots_file" || [[ ! -s "$roots_file" ]]; then
    rm -f "$roots_file"
    return 1
  fi
  while IFS= read -r env_root; do
    [[ -n "$env_root" ]] || continue
    /usr/libexec/PlistBuddy -c "Add $env_root dict" "$plist_path" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Delete $env_root:$key" "$plist_path" 2>/dev/null || true
    if ! /usr/libexec/PlistBuddy -c "Add $env_root:$key string $value" "$plist_path"; then
      status=1
      break
    fi
  done <"$roots_file"
  rm -f "$roots_file"
  return "$status"
}

ios_xctestrun_cache_cleanup_scoped() {
  local staged_path="$1"
  [[ "$staged_path" == *.scoped.xctestrun ]] || return 64
  rm -f "$staged_path"
}

ios_xctestrun_cache_current_worktree_root() {
  local library_path="${BASH_SOURCE[0]}"
  if [[ "$library_path" != /* ]]; then
    library_path="$(cd "$(dirname "$library_path")" 2>/dev/null && pwd -P)/$(basename "$library_path")" || return 1
  fi
  cd "$(dirname "$library_path")/../.." 2>/dev/null && pwd -P
}

ios_xctestrun_cache_path_matches_worktree() {
  local candidate="$1" expected_root="$2" resolved_candidate
  [[ -n "$candidate" && -n "$expected_root" ]] || return 1
  if [[ "$candidate" == "$expected_root" || "$candidate" == "$expected_root/" ]]; then
    return 0
  fi
  [[ -d "$candidate" ]] || return 1
  resolved_candidate="$(cd "$candidate" 2>/dev/null && pwd -P)" || return 1
  [[ "$resolved_candidate" == "$expected_root" ]]
}

ios_xctestrun_cache_worktree_path_valid() {
  local xctestrun_path="$1" expected_root="${2:-}" env_roots env_root asset_root
  [[ -f "$xctestrun_path" ]] || return 1
  if [[ -z "$expected_root" ]]; then
    expected_root="$(ios_xctestrun_cache_current_worktree_root)" || return 1
  fi
  [[ -n "$expected_root" ]] || return 1

  # KG_FIXTURE_ASSET_ROOT is copied into the xctestrun by Xcode and then
  # forwarded to the app.  A shared cache can therefore carry an absolute
  # path from a different linked worktree even when its content key matches.
  # Missing keys remain valid for non-fixture/unit caches; a present key must
  # resolve to this checkout in every test target.
  env_roots="$(ios_xctestrun_cache_env_roots "$xctestrun_path")" || return 1
  while IFS= read -r env_root; do
    [[ -n "$env_root" ]] || continue
    if asset_root="$(/usr/libexec/PlistBuddy -c "Print $env_root:KG_FIXTURE_ASSET_ROOT" "$xctestrun_path" 2>/dev/null)"; then
      [[ -n "$asset_root" ]] || return 1
      ios_xctestrun_cache_path_matches_worktree "$asset_root" "$expected_root" || return 1
    fi
  done <<<"$env_roots"
}

ios_xctestrun_cache_invalidate() {
  local sentinel_path="$1"
  [[ -n "$sentinel_path" ]] || return 1
  rm -f "$sentinel_path"
}

ios_xctestrun_cache_is_complete() {
  local sentinel_path="$1" xctestrun_path="$2" configuration="$3" sdk_suffix="$4" scope="$5"
  [[ -f "$sentinel_path" ]] || return 1
  if ! ios_xctestrun_cache_worktree_path_valid "$xctestrun_path"; then
    ios_xctestrun_cache_invalidate "$sentinel_path" || true
    return 1
  fi
  ios_xctestrun_cache_products_ready "$xctestrun_path" "$configuration" "$sdk_suffix" "$scope"
}
