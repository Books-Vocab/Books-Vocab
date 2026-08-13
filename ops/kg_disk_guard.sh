#!/usr/bin/env bash
# Bounded disk-growth monitor and conservative cache guard.
# State is atomically replaced; no append-only log is created.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${KG_DISK_GUARD_WORKSPACE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
STATE_FILE="${KG_DISK_GUARD_STATE:-$HOME/Library/Application Support/KG/disk_guard.json}"
WARN_FREE_GIB="${KG_DISK_GUARD_WARN_FREE_GIB:-20}"
CRIT_FREE_GIB="${KG_DISK_GUARD_CRIT_FREE_GIB:-10}"
GROWTH_WARN_GIB="${KG_DISK_GUARD_GROWTH_WARN_GIB:-5}"
DOCKER_WARN_GIB="${KG_DISK_GUARD_DOCKER_WARN_GIB:-2}"
DOCKER_PRUNE_UNTIL="${KG_DISK_GUARD_DOCKER_PRUNE_UNTIL:-168h}"
KEEP="${KG_DISK_GUARD_CACHE_KEEP:-3}"
MIN_AGE_HOURS="${KG_DISK_GUARD_CACHE_MIN_AGE_HOURS:-6}"
WORKTREE_CACHE_KEEP="${KG_DISK_GUARD_WORKTREE_CACHE_KEEP:-3}"
WORKTREE_CACHE_MIN_AGE_HOURS="${KG_DISK_GUARD_WORKTREE_CACHE_MIN_AGE_HOURS:-0}"
BUILD_LOCK_FILE="${KG_DISK_GUARD_BUILD_LOCK_FILE:-/tmp/kg-ios-build.lock}"
GUARD_LOCK_FILE="${KG_DISK_GUARD_LOCK_FILE:-/tmp/kg-disk-guard.lock}"
DRY_RUN="${KG_DISK_GUARD_DRY_RUN:-0}"

# shellcheck source=lib/ios_cache_evict.sh
CACHE_LIB="${KG_DISK_GUARD_CACHE_LIB:-$SCRIPT_DIR/lib/ios_cache_evict.sh}"
[[ -f "$CACHE_LIB" ]] || CACHE_LIB="$HOME/butler/bin/kg_ios_cache_evict_lib.sh"
if [[ -f "$CACHE_LIB" ]]; then
  source "$CACHE_LIB"
else
  kg_ios_cache_evict() { return 0; }
fi

number() {
  case "$1" in ''|*[!0-9-]*) printf '0' ;; *) printf '%s' "$1" ;; esac
}

previous_free() {
  [[ -f "$STATE_FILE" ]] || { printf '0'; return; }
  sed -n 's/.*"free_bytes":\([0-9][0-9]*\).*/\1/p' "$STATE_FILE" | head -1
}

free_bytes() {
  if [[ -n "${KG_DISK_GUARD_FREE_BYTES:-}" ]]; then
    printf '%s' "$KG_DISK_GUARD_FREE_BYTES"
  else
    df -Pk "$WORKSPACE" 2>/dev/null | awk 'NR==2 {print $4 * 1024; exit}'
  fi
}

process_snapshot() {
  [[ "${KG_DISK_GUARD_PROCESS_PROBE_FAIL:-0}" == "1" ]] && return 1
  ps ax 2>/dev/null
}

active_build() {
  if [[ -n "${KG_DISK_GUARD_ACTIVE_BUILD:-}" ]]; then
    [[ "$KG_DISK_GUARD_ACTIVE_BUILD" == "1" ]] && printf '1' || printf '0'
    return
  fi
  local snapshot
  snapshot="$(process_snapshot)" || { printf '2'; return; }
  grep -E '[x]codebuild|[i]os_(test|build|ops)\.sh|[u]i_quality_gate\.sh' <<<"$snapshot" >/dev/null 2>&1 && printf '1' || printf '0'
}

cache_roots() {
  local root
  for root in \
    "$WORKSPACE/.cache/ios-build-derived-data" \
    "$WORKSPACE/.cache/ios-test-derived-data" \
    "$WORKSPACE/.cache/ios-catalyst-derived-data"; do
    [[ -d "$root" ]] && printf '%s\n' "$root"
  done
  # Worktree DerivedData can be multi-GB and `du` may legitimately take minutes
  # while xcodebuild owns it.  The recurring guard must stay cheap; an operator
  # may opt in to the bounded max-depth sweep for a one-off audit.
  if [[ "${KG_DISK_GUARD_SCAN_WORKTREES:-0}" == "1" && -d "$WORKSPACE/.claude/worktrees" ]]; then
    worktree_cache_roots
  fi
}

# Do not recursively walk every worktree on each tick.  The cache roots are a
# fixed, shallow layout; globbing them is both bounded and immune to a giant
# DerivedData subtree making the monitor itself consume the machine.
worktree_cache_roots() {
  local worktree kind root
  [[ -d "$WORKSPACE/.claude/worktrees" ]] || return 0
  for worktree in "$WORKSPACE"/.claude/worktrees/*; do
    [[ -d "$worktree" ]] || continue
    for kind in ios-build-derived-data ios-test-derived-data ios-catalyst-derived-data; do
      root="$worktree/.cache/$kind"
      [[ -d "$root" ]] && printf '%s\n' "$root"
    done
  done
}

worktree_cache_keys() {
  local root count total=0
  while IFS= read -r root; do
    count="$(find "$root" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | wc -l | tr -d ' ')"
    [[ "$count" =~ ^[0-9]+$ ]] && total=$((total + count))
  done < <(worktree_cache_roots)
  printf '%s' "$total"
}

worktree_cache_kb() {
  local root count total=0 size
  # APFS free bytes is the authoritative size signal.  A recursive `du` over
  # active DerivedData can itself consume minutes and I/O; only an explicit
  # one-off audit opts into the expensive byte attribution.
  [[ "${KG_DISK_GUARD_WORKTREE_SIZE_SCAN:-0}" == "1" ]] || { printf '0'; return; }
  while IFS= read -r root; do
    count="$(find "$root" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | wc -l | tr -d ' ')"
    [[ "$count" =~ ^[0-9]+$ ]] || continue
    (( count > WORKTREE_CACHE_KEEP )) || continue
    size="$(du -sk "$root" 2>/dev/null | awk 'NR==1 {print $1}')"
    [[ "$size" =~ ^[0-9]+$ ]] && total=$((total + size))
  done < <(worktree_cache_roots)
  printf '%s' "$total"
}

cache_kb() {
  local root total=0 size
  while IFS= read -r root; do
    size="$(du -sk "$root" 2>/dev/null | awk 'NR==1 {print $1}')"
    [[ "$size" =~ ^[0-9]+$ ]] && total=$((total + size))
  done < <(cache_roots)
  printf '%s' "$total"
}

size_to_kb() {
  local raw="$1" n unit
  n="$(printf '%s' "$raw" | sed -E 's/^([0-9]+([.][0-9]+)?).*/\1/')"
  unit="$(printf '%s' "$raw" | sed -E 's/^[0-9]+([.][0-9]+)?([A-Za-z]+).*/\2/')"
  [[ "$n" =~ ^[0-9]+([.][0-9]+)?$ ]] || { printf '0'; return; }
  awk -v n="$n" -v unit="$unit" 'BEGIN{m=1; if(unit=="KB"||unit=="K")m=1; else if(unit=="MB"||unit=="M")m=1024; else if(unit=="GB"||unit=="G")m=1048576; else if(unit=="TB"||unit=="T")m=1073741824; printf "%.0f",n*m}'
}

docker_cache_kb() {
  if [[ -n "${KG_DISK_GUARD_DOCKER_CACHE_BYTES:-}" ]]; then
    printf '%s' "$((KG_DISK_GUARD_DOCKER_CACHE_BYTES / 1024))"; return
  fi
  command -v docker >/dev/null 2>&1 || { printf '0'; return; }
  local reclaim
  reclaim="$(docker system df --format '{{.Type}}|{{.Reclaimable}}' 2>/dev/null \
    | awk -F'|' '$1=="Build Cache"{print $2}' | sed 's/[[:space:]].*$//' | head -1)"
  [[ -n "$reclaim" ]] && size_to_kb "$reclaim" || printf '0'
}

docker_active() {
  if [[ -n "${KG_DISK_GUARD_DOCKER_ACTIVE:-}" ]]; then
    [[ "$KG_DISK_GUARD_DOCKER_ACTIVE" == "1" ]] && printf '1' || printf '0'; return
  fi
  local snapshot
  snapshot="$(process_snapshot)" || { printf '2'; return; }
  grep -E '[d]ocker (build|builder|compose build)|[b]uildx build' <<<"$snapshot" >/dev/null 2>&1 && printf '1' || printf '0'
}

prune_docker_cache() {
  command -v docker >/dev/null 2>&1 || return 0
  if [[ -n "${KG_DISK_GUARD_DOCKER_CACHE_BYTES:-}" ]]; then return 0; fi
  if [[ "$DRY_RUN" == "1" ]]; then
    logger -t kg-disk-guard "would-prune docker builder cache until=$DOCKER_PRUNE_UNTIL" 2>/dev/null || true
  else
    docker builder prune --force --filter "until=$DOCKER_PRUNE_UNTIL" >/dev/null 2>&1 || true
    logger -t kg-disk-guard "pruned docker builder cache until=$DOCKER_PRUNE_UNTIL" 2>/dev/null || true
  fi
}

trim_logs() {
  local raw file size max_kb keep_kb tmp
  raw="${KG_DISK_GUARD_LOG_FILES:-}"
  [[ -n "$raw" ]] || return 0
  max_kb="${KG_DISK_GUARD_LOG_MAX_KB:-2048}"
  keep_kb="${KG_DISK_GUARD_LOG_KEEP_KB:-512}"
  while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    size="$(du -k "$file" 2>/dev/null | awk 'NR==1{print $1}')"
    [[ "$size" =~ ^[0-9]+$ ]] || continue
    (( size <= max_kb )) && continue
    if [[ "$DRY_RUN" == "1" ]]; then
      logger -t kg-disk-guard "would-trim-log path=$file sizeKB=$size keepKB=$keep_kb" 2>/dev/null || true
      continue
    fi
    tmp="$file.$$.$RANDOM.tmp"
    tail -c "$((keep_kb * 1024))" "$file" > "$tmp" 2>/dev/null && cat "$tmp" > "$file" 2>/dev/null && rm -f "$tmp"
    logger -t kg-disk-guard "trimmed-log path=$file oldKB=$size keepKB=$keep_kb" 2>/dev/null || true
  done < <(printf '%s\n' "$raw" | tr ':' '\n')
}

evict_keyed_caches() {
  local root old_scan="${KG_DISK_GUARD_SCAN_WORKTREES:-0}"
  export KG_IOS_CACHE_KEEP="$KEEP"
  export KG_IOS_CACHE_EVICT_MIN_AGE_HOURS="$MIN_AGE_HOURS"
  export KG_IOS_CACHE_EVICT_DRY_RUN="$DRY_RUN"
  # Pressure is the only time we pay for worktree discovery.  active_build was
  # checked before this function, so an in-flight xcodebuild never gets scanned
  # or deleted; healthy periodic ticks remain cheap and fixed-root only.
  export KG_DISK_GUARD_SCAN_WORKTREES=1
  while IFS= read -r root; do
    kg_ios_cache_evict "$root" "" || true
  done < <(cache_roots)
  export KG_DISK_GUARD_SCAN_WORKTREES="$old_scan"
}

evict_worktree_caches() {
  local old_keep old_min old_dry
  old_keep="${KG_IOS_CACHE_KEEP:-}"
  old_min="${KG_IOS_CACHE_EVICT_MIN_AGE_HOURS:-}"
  old_dry="${KG_IOS_CACHE_EVICT_DRY_RUN:-}"
  export KG_IOS_CACHE_KEEP="$WORKTREE_CACHE_KEEP"
  export KG_IOS_CACHE_EVICT_MIN_AGE_HOURS="$WORKTREE_CACHE_MIN_AGE_HOURS"
  export KG_IOS_CACHE_EVICT_DRY_RUN="$DRY_RUN"
  while IFS= read -r root; do
    kg_ios_cache_evict "$root" "" || true
  done < <(worktree_cache_roots)
  if [[ -n "$old_keep" ]]; then export KG_IOS_CACHE_KEEP="$old_keep"; else unset KG_IOS_CACHE_KEEP; fi
  if [[ -n "$old_min" ]]; then export KG_IOS_CACHE_EVICT_MIN_AGE_HOURS="$old_min"; else unset KG_IOS_CACHE_EVICT_MIN_AGE_HOURS; fi
  if [[ -n "$old_dry" ]]; then export KG_IOS_CACHE_EVICT_DRY_RUN="$old_dry"; else unset KG_IOS_CACHE_EVICT_DRY_RUN; fi
}

acquire_build_lock_nonblocking() {
  [[ "${KG_DISK_GUARD_BUILD_LOCK_HELD:-0}" == "1" ]] && return 0
  command -v shlock >/dev/null 2>&1 || return 1
  shlock -f "$BUILD_LOCK_FILE" -p "$$" >/dev/null 2>&1
}

acquire_guard_lock_nonblocking() {
  [[ "${KG_DISK_GUARD_GUARD_LOCK_HELD:-0}" == "1" ]] && return 0
  command -v shlock >/dev/null 2>&1 || return 1
  shlock -f "$GUARD_LOCK_FILE" -p "$$" >/dev/null 2>&1
}

evict_old_app_derived_data() {
  local dd="$HOME/Library/Developer/Xcode/DerivedData" now path mtime age
  [[ -d "$dd" ]] || return 0
  now="$(date +%s)"
  while IFS= read -r path; do
    mtime="$(kg_stat_mtime "$path" 2>/dev/null || echo 0)"
    age=$((now - mtime))
    (( age < MIN_AGE_HOURS * 3600 )) && continue
    if [[ "$DRY_RUN" == "1" ]]; then
      logger -t kg-disk-guard "would-evict old app DerivedData path=$path" 2>/dev/null || true
    else
      rm -rf "$path" 2>/dev/null || true
      logger -t kg-disk-guard "evicted old app DerivedData path=$path" 2>/dev/null || true
    fi
  done < <(
    find "$dd" -mindepth 1 -maxdepth 1 -type d -name 'BooksAndVocab-*' -print 2>/dev/null \
      | while IFS= read -r path; do printf '%s\t%s\n' "$(kg_stat_mtime "$path" 2>/dev/null || echo 0)" "$path"; done \
      | sort -rn | tail -n +2 | cut -f2-
  )
}

write_state() {
  local free="$1" prev="$2" growth="$3" active="$4" cache="$5" docker_cache="$6" docker_running="$7" worktree_cache="$8" worktree_keys="$9" verdict="${10}" reason="${11}" action="${12}"
  local dir tmp
  dir="$(dirname "$STATE_FILE")"; mkdir -p "$dir" 2>/dev/null || return 1
  tmp="$STATE_FILE.$$.$RANDOM.tmp"
  printf '{"schema":"kg.disk.guard.v1","host":"%s","free_bytes":%s,"previous_free_bytes":%s,"growth_bytes":%s,"active_build":%s,"cache_kb":%s,"docker_cache_kb":%s,"docker_active":%s,"worktree_cache_kb":%s,"worktree_cache_keys":%s,"verdict":"%s","reason":"%s","action":"%s","at":"%s"}\n' \
    "$(hostname -s 2>/dev/null || echo unknown)" "$(number "$free")" "$(number "$prev")" "$(number "$growth")" \
    "$(number "$active")" "$(number "$cache")" "$(number "$docker_cache")" "$(number "$docker_running")" \
    "$(number "$worktree_cache")" "$(number "$worktree_keys")" "$verdict" "$reason" "$action" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$tmp" || { rm -f "$tmp"; return 1; }
  mv -f "$tmp" "$STATE_FILE"
}

main() {
  local free prev growth active cache docker_cache docker_running worktree_cache worktree_keys free_gib growth_gib docker_gib verdict reason action
  acquire_guard_lock_nonblocking || {
    logger -t kg-disk-guard 'skipped=already-running' 2>/dev/null || true
    return 0
  }
  free="$(number "$(free_bytes)")"; prev="$(number "$(previous_free)")"
  growth=0; (( prev > free )) && growth=$((prev - free))
  active="$(active_build)"; cache="$(cache_kb)"
  docker_cache="$(docker_cache_kb)"; docker_running="$(docker_active)"
  worktree_keys="$(worktree_cache_keys)"; worktree_cache="$(worktree_cache_kb)"
  free_gib=$((free / 1073741824)); growth_gib=$((growth / 1073741824))
  docker_gib=$((docker_cache / 1048576)); docker_warn_kb=$((DOCKER_WARN_GIB * 1048576)); verdict="ok"; reason="within-bounds"; action="none"
  if (( free_gib < CRIT_FREE_GIB )); then
    verdict="critical"; reason="free-below-critical"
  elif (( free_gib < WARN_FREE_GIB )); then
    verdict="warning"; reason="free-below-warning"
  elif (( growth_gib >= GROWTH_WARN_GIB )); then
    verdict="warning"; reason="rapid-growth"
  elif (( docker_cache >= docker_warn_kb )); then
    verdict="warning"; reason="docker-build-cache"
  elif (( worktree_keys > WORKTREE_CACHE_KEEP )); then
    verdict="warning"; reason="worktree-cache-overflow"
  fi
  if [[ "$verdict" != "ok" ]]; then
    if [[ "$active" == "1" || "$docker_running" == "1" ]]; then
      action="deferred-active-build"
    elif [[ "$active" != "0" || "$docker_running" != "0" ]]; then
      action="deferred-process-observation"
    else
      if (( worktree_keys > WORKTREE_CACHE_KEEP )); then
        if acquire_build_lock_nonblocking; then
          evict_worktree_caches; action="evict-worktree-cache"
        else
          action="deferred-build-lock"
        fi
      fi
      if [[ "$action" == "none" ]]; then
        evict_keyed_caches; action="evict-old-ios-cache"
      elif [[ "$action" == "evict-worktree-cache" ]]; then
        # Keep the existing pressure cleanup in the same guarded turn.
        if (( free_gib < WARN_FREE_GIB )); then
          evict_keyed_caches
          action="evict-worktree-cache-and-ios-cache"
        fi
      fi
      if (( docker_cache >= docker_warn_kb )); then
        prune_docker_cache; action="evict-old-ios-cache-and-docker-build-cache"
      fi
      if (( free_gib < CRIT_FREE_GIB )); then
        evict_old_app_derived_data; action="evict-old-ios-cache-and-derived-data"
      fi
    fi
  fi
  # Known launchd logs are capped every tick, even while disk pressure is healthy.
  # Otherwise a quiet disk can still accumulate a multi-GB service log between alerts.
  trim_logs
  write_state "$free" "$prev" "$growth" "$active" "$cache" "$docker_cache" "$docker_running" "$worktree_cache" "$worktree_keys" "$verdict" "$reason" "$action"
  logger -t kg-disk-guard "verdict=$verdict freeGiB=$free_gib growthGiB=$growth_gib activeBuild=$active dockerCacheGiB=$docker_gib dockerActive=$docker_running cacheKB=$cache worktreeCacheKB=$worktree_cache worktreeKeys=$worktree_keys action=$action" 2>/dev/null || true
}

main "$@"
