#!/usr/bin/env bash
# Optional, CI-owned SwiftPM source-cache plumbing for Xcode invocations.
#
# DerivedData holds path-sensitive build products and is deliberately not
# portable between GitHub-hosted jobs.  SwiftPM checkouts/repositories are a
# separate, lockfile-pinned dependency graph and can be restored safely when a
# caller explicitly supplies an external cache root.

KG_IOS_SWIFTPM_XCODEBUILD_ARGS=()

kg_ios_swiftpm_configure() {
  local project_root="$1"
  local cache_root="${KG_IOS_SWIFTPM_CACHE_DIR:-}"

  KG_IOS_SWIFTPM_XCODEBUILD_ARGS=()
  [[ -n "$cache_root" ]] || return 0

  if [[ "$cache_root" != /* ]]; then
    echo "[ios_swiftpm_cache] error: KG_IOS_SWIFTPM_CACHE_DIR must be an absolute path: $cache_root" >&2
    return 64
  fi

  project_root="$(cd "$project_root" && pwd -P)"
  # `TMPDIR` on macOS can itself end with `/`; normalise the existing parent so
  # a lexical `//` spelling cannot evade the project-tree boundary below.  The
  # cache leaf need not exist yet — xcodebuild creates it on a cold runner.
  local cache_parent cache_leaf
  cache_parent="$(dirname "$cache_root")"
  cache_leaf="$(basename "$cache_root")"
  if [[ -d "$cache_parent" ]]; then
    cache_root="$(cd "$cache_parent" && pwd -P)/$cache_leaf"
  fi
  case "$cache_root" in
    "$project_root"|"$project_root"/*)
      echo "[ios_swiftpm_cache] error: KG_IOS_SWIFTPM_CACHE_DIR must live outside the project root: $cache_root" >&2
      return 64
      ;;
  esac

  local resolved_file="$project_root/ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
  if [[ ! -f "$resolved_file" ]]; then
    echo "[ios_swiftpm_cache] error: Package.resolved is required before enabling the hosted SwiftPM cache: $resolved_file" >&2
    return 65
  fi

  KG_IOS_SWIFTPM_XCODEBUILD_ARGS=(
    -clonedSourcePackagesDirPath "$cache_root"
    -packageCachePath "$cache_root/package-cache"
    -onlyUsePackageVersionsFromResolvedFile
  )
}
