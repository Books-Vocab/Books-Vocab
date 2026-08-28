#!/usr/bin/env bash
# Bounded disk policy shared by iOS build, test, release, and the recurring guard.
#
# This file is sourced by callers that already own the iOS build lock.  It must
# stay side-effect free: it only measures known, rebuildable KG cache roots and
# returns a structured fail-closed result when the writer budget is exhausted.

KG_IOS_DISK_BUDGET_EXIT=75

kg_ios_disk_budget_number() {
  case "${1:-}" in
    ''|*[!0-9]*) printf '0' ;;
    *) printf '%s' "$1" ;;
  esac
}

kg_ios_disk_budget_roots() {
  local project_root="${1:?project root is required}"
  local configured_root
  if [[ -n "${KG_IOS_DISK_CACHE_ROOTS:-}" ]]; then
    while IFS= read -r configured_root; do
      [[ -d "$configured_root" ]] && printf '%s\n' "$configured_root"
    done < <(printf '%s\n' "$KG_IOS_DISK_CACHE_ROOTS" | tr ':' '\n')
    return 0
  fi
  local root
  for root in \
    "$project_root/.cache/ios-build-derived-data" \
    "$project_root/.cache/ios-test-derived-data" \
    "$project_root/.cache/ios-catalyst-derived-data" \
    "$project_root/.cache/ios-release-derived-data" \
    "$project_root/.cache/ops-swift-build" \
    "$project_root/ios/build"; do
    [[ -d "$root" ]] && printf '%s\n' "$root"
  done
}

kg_ios_disk_budget_free_bytes() {
  local project_root="${1:?project root is required}"
  if [[ -n "${KG_IOS_DISK_FREE_BYTES:-}" ]]; then
    case "$KG_IOS_DISK_FREE_BYTES" in
      ''|*[!0-9]*) printf '' ;;
      *) printf '%s' "$KG_IOS_DISK_FREE_BYTES" ;;
    esac
    return 0
  fi
  df -Pk "$project_root" 2>/dev/null | awk 'NR==2 {print $4 * 1024; exit}'
}

kg_ios_disk_budget_cache_kb() {
  local project_root="${1:?project root is required}"
  local root size total=0
  while IFS= read -r root; do
    size="$(du -sk "$root" 2>/dev/null | awk 'NR==1 {print $1}')"
    [[ "$size" =~ ^[0-9]+$ ]] || return 2
    total=$((total + size))
  done < <(kg_ios_disk_budget_roots "$project_root")
  printf '%s' "$total"
}

kg_ios_disk_budget_config() {
  local budget_gib="${KG_IOS_DISK_CACHE_BUDGET_GIB:-16}"
  local headroom_gib="${KG_IOS_DISK_CACHE_HEADROOM_GIB:-6}"
  local min_free_gib="${KG_IOS_DISK_MIN_FREE_GIB:-20}"
  [[ "$budget_gib" =~ ^[0-9]+$ && "$headroom_gib" =~ ^[0-9]+$ && "$min_free_gib" =~ ^[0-9]+$ ]] || return 1
  printf '%s %s %s\n' "$((budget_gib * 1048576))" "$((headroom_gib * 1048576))" "$((min_free_gib * 1073741824))"
}

kg_ios_disk_budget_preflight() {
  local project_root="${1:?project root is required}"
  local operation="${2:-ios-write}"
  local config budget_kb headroom_kb min_free_bytes free_bytes cache_kb
  config="$(kg_ios_disk_budget_config 2>/dev/null || true)"
  if [[ ! "$config" =~ ^[0-9]+\ [0-9]+\ [0-9]+$ ]]; then
    echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=block reason=invalid-budget-config" >&2
    return "$KG_IOS_DISK_BUDGET_EXIT"
  fi
  read -r budget_kb headroom_kb min_free_bytes <<<"$config"
  free_bytes="$(kg_ios_disk_budget_free_bytes "$project_root")"
  if [[ ! "$free_bytes" =~ ^[0-9]+$ ]]; then
    echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=block reason=free-space-unknown" >&2
    return "$KG_IOS_DISK_BUDGET_EXIT"
  fi
  cache_kb="$(kg_ios_disk_budget_cache_kb "$project_root" 2>/dev/null || true)"
  if [[ ! "$cache_kb" =~ ^[0-9]+$ ]]; then
    echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=block reason=cache-size-unknown freeBytes=$free_bytes" >&2
    return "$KG_IOS_DISK_BUDGET_EXIT"
  fi
  if (( free_bytes < min_free_bytes )); then
    echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=block reason=free-space-below-floor freeBytes=$free_bytes minFreeBytes=$min_free_bytes cacheKB=$cache_kb budgetKB=$budget_kb headroomKB=$headroom_kb" >&2
    return "$KG_IOS_DISK_BUDGET_EXIT"
  fi
  if (( cache_kb + headroom_kb > budget_kb )); then
    if (( cache_kb > budget_kb )); then
      echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=block reason=cache-budget-exceeded freeBytes=$free_bytes cacheKB=$cache_kb budgetKB=$budget_kb headroomKB=$headroom_kb" >&2
    else
      echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=block reason=cache-budget-headroom-exhausted freeBytes=$free_bytes cacheKB=$cache_kb budgetKB=$budget_kb headroomKB=$headroom_kb" >&2
    fi
    return "$KG_IOS_DISK_BUDGET_EXIT"
  fi
  echo "schema=kg.ios.disk-budget.v1 operation=$operation verdict=pass freeBytes=$free_bytes cacheKB=$cache_kb budgetKB=$budget_kb headroomKB=$headroom_kb" >&2
  return 0
}
