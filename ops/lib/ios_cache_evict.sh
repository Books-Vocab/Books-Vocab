#!/usr/bin/env bash
# ios_cache_evict.sh — keyed DerivedData cache 的 LRU eviction（sourced library）。
#
# 背景：ios_test.sh 與 ios_ops catalog 的 DerivedData 以 config hash 為 key，
# 每個 key 一份完整 DerivedData（數 GB）。source 一改 key 就換，舊 key 永遠
# 不會被重用也從未被清理 — 2026-06-10 累積 94G+31G 兩度塞爆磁碟
# （xcodebuild exit=73 No space left on device）。
#
# 介面：
#   kg_ios_cache_evict <cache_root> <current_key>
#
# 環境變數：
#   KG_IOS_CACHE_KEEP                 保留最新幾條（default 3）
#   KG_IOS_CACHE_EVICT_MIN_AGE_HOURS  幾小時內用過的條目永不淘汰（default 6）
#   KG_IOS_CACHE_EVICT_DRY_RUN        1 = 只報告不刪（default 0）
#
# 行為契約：
#   - current_key 永不淘汰，且在進場時 touch 成最新（標記 in-use，讓其他
#     caller 的 LRU 視其為熱條目）。
#   - 只動 cache_root 第一層的「目錄」；一般檔案（sentinel/log）不碰。
#   - 淘汰順序 = mtime 最舊優先；保留 = 最新 KEEP 條 ∪ current ∪ min-age 內。
#   - 所有 log 走 stderr — catalog caller 的 stdout 是純 JSON，不可污染。
#   - 任何單一條目刪除失敗不中斷整體（best-effort，回報但續行）。
#
# 並發注意：ios_test.sh 在 build lock 內呼叫；catalog 無共用鎖，靠
# 「resolve 即 touch + min-age 視窗」保護仍在跑的並行 run。

# kg_ios_cache_evict <cache_root> <current_key>
kg_ios_cache_evict() {
  local cache_root="$1"
  local current_key="$2"
  local keep="${KG_IOS_CACHE_KEEP:-3}"
  local min_age_hours="${KG_IOS_CACHE_EVICT_MIN_AGE_HOURS:-6}"
  local dry_run="${KG_IOS_CACHE_EVICT_DRY_RUN:-0}"

  [[ -d "$cache_root" ]] || return 0

  # 標記現用 key 為最新（即使本輪是 cache hit 也要續命）。
  [[ -n "$current_key" && -d "$cache_root/$current_key" ]] \
    && touch "$cache_root/$current_key" 2>/dev/null

  local now min_age_secs
  now="$(date +%s)"
  min_age_secs=$(( min_age_hours * 3600 ))

  # mtime 由新到舊列出第一層目錄（stat 一次拿 mtime+path，避免逐條 fork）。
  local entries=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && entries+=("$line")
  done < <(
    find "$cache_root" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null \
      | xargs -0 stat -f '%m %N' 2>/dev/null \
      | sort -rn
  )

  local kept=0 evicted=0 freed_kb=0
  local rank=0 mtime path name age_secs age_h size_kb verb
  for line in "${entries[@]}"; do
    mtime="${line%% *}"
    path="${line#* }"
    name="$(basename "$path")"
    rank=$(( rank + 1 ))
    age_secs=$(( now - mtime ))

    if [[ "$name" == "$current_key" ]] || (( rank <= keep )) || (( age_secs < min_age_secs )); then
      kept=$(( kept + 1 ))
      continue
    fi

    size_kb="$(du -sk "$path" 2>/dev/null | cut -f1)"
    [[ -n "$size_kb" ]] || size_kb=0
    age_h=$(( age_secs / 3600 ))
    if [[ "$dry_run" == "1" ]]; then
      verb="would-evict"
    else
      verb="evicted"
      if ! rm -rf "$path" 2>/dev/null; then
        echo "[ios_cache] evict-failed key=$name (continuing)" >&2
        kept=$(( kept + 1 ))
        continue
      fi
    fi
    echo "[ios_cache] $verb key=$name sizeKB=$size_kb ageH=$age_h" >&2
    evicted=$(( evicted + 1 ))
    freed_kb=$(( freed_kb + size_kb ))
  done

  if (( evicted > 0 )); then
    echo "[ios_cache] eviction root=$cache_root keep=$keep minAgeH=$min_age_hours kept=$kept $( [[ "$dry_run" == "1" ]] && echo would-free || echo freed )KB=$freed_kb evicted=$evicted" >&2
  fi
  return 0
}
