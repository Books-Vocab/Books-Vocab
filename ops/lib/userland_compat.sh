#!/usr/bin/env bash
# userland_compat.sh — BSD(macOS) / GNU(linux) userland 差異的單一收斂點（sourced library）。
#
# 探針為什麼是 `--version` 而不是「先試 BSD 旗標、失敗再試 GNU」（ops/release.sh:264 的
# `stat -f '%Lp' || stat -c '%a'` 那個範式）：GNU 的 `stat -f` 是 --file-system 而不是
# format，餵它 '%m' 不會乾脆失敗，只會去 stat 一個不存在的檔案系統；呼叫端若再帶
# `2>/dev/null`（ops/lib/ios_cache_evict.sh 兩處都帶），順序 fallback 會**安靜地**走錯分支，
# 產出空清單而不是報錯。`--version` 在 GNU rc=0、BSD rc=1，是唯一不含糊的判別式。
#
# 可測性：判別式走 PATH 上的 `stat`/`date`，所以 ops/tests/test_userland_portability.sh
# 能用 PATH 前置的 GNU shim 在 macOS 上扮演 linux——這條相容層若改成讀 `uname`，那支
# 守衛測試就只剩空話。

kg_userland_stat_is_gnu() { stat --version >/dev/null 2>&1; }
kg_userland_date_is_gnu() { date --version >/dev/null 2>&1; }

# kg_stat_mtime <path> — 印出 mtime(epoch)。
# 注意：兩個分支都必須維持「旗標、格式、path」三個參數的呼叫形狀，且必須呼叫裸 `stat`
# （不可寫 command stat）——ops/tests/test_ios_cache_evict.sh:183-189 的 stat shadow 用
# "${3:-}" 認 path，改形狀會讓 case 12 假綠或假紅。
kg_stat_mtime() {
  if kg_userland_stat_is_gnu; then
    stat -c '%Y' "$1"
  else
    stat -f '%m' "$1"
  fi
}

# kg_stat_batch_mtime_name — stdin 收 NUL 分隔的路徑，逐行印 "<mtime> <path>"。
# 批次形式的存在理由是避免每條目 fork 一次 stat（呼叫端在 find | xargs 管線裡用）。
kg_stat_batch_mtime_name() {
  if kg_userland_stat_is_gnu; then
    xargs -0 stat -c '%Y %n'
  else
    xargs -0 stat -f '%m %N'
  fi
}

# kg_date_hours_ago <hours> <+fmt> — 印出 N 小時前的時間。
kg_date_hours_ago() {
  if kg_userland_date_is_gnu; then
    date -d "-${1} hours" "$2"
  else
    date -v "-${1}H" "$2"
  fi
}
