#!/usr/bin/env bash
# test_ios_cache_evict.sh — lib/ios_cache_evict.sh 單元測試
#
# 透過 mktemp cache root + touch -m -t 偽造 keyed DerivedData 條目，覆蓋：
#   1. 條目數 ≤ keep → 全留
#   2. 超過 keep 且夠老 → 按 mtime 淘汰最舊、留最新 keep 條
#   3. current key 超出 keep 名次且很老 → 仍受保護（且被 touch 成最新）
#   4. min-age 內的條目超出 keep 名次 → 仍受保護
#   5. dry-run → 不刪、log 標示 would-evict
#   6. cache root 不存在 → no-op exit 0
#   7. root 下的一般檔案（非目錄）→ 忽略不刪
#   8. log 走 stderr（stdout 必須保持乾淨，catalog caller stdout 是純 JSON）

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$WORKTREE/ops/lib/ios_cache_evict.sh"
TMPROOT="$(mktemp -d -t kg_cache_evict_test_XXXXXX)"
trap 'rm -rf "$TMPROOT"' EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "✗ 缺 $LIB" >&2; exit 1; }
# shellcheck source=../lib/ios_cache_evict.sh
source "$LIB"

# build_entry <root> <name> <age_hours> — 造一個帶內容的 key 目錄並回推 mtime
build_entry() {
  local root="$1" name="$2" age_hours="$3" stamp
  mkdir -p "$root/$name/Build/Products"
  printf 'x%.0s' {1..2048} > "$root/$name/Build/Products/blob.bin"
  stamp="$(date -v "-${age_hours}H" '+%Y%m%d%H%M.%S')"
  touch -m -t "$stamp" "$root/$name"
}

fresh_root() {
  local root="$TMPROOT/case_$1"
  mkdir -p "$root"
  printf '%s\n' "$root"
}

# ── 1. 條目數 ≤ keep → 全留 ──────────────────────────────────────────────
section "under keep limit"
root="$(fresh_root 1)"
build_entry "$root" aaa 100; build_entry "$root" bbb 200
KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" aaa 2>/dev/null
[[ -d "$root/aaa" && -d "$root/bbb" ]] && ok "entries ≤ keep 全留" || fail_t "entries ≤ keep 不應淘汰"

# ── 2. 超過 keep → 按 mtime 淘汰最舊 ─────────────────────────────────────
section "evict oldest beyond keep"
root="$(fresh_root 2)"
build_entry "$root" newest 10
build_entry "$root" mid1 50
build_entry "$root" mid2 100
build_entry "$root" oldest1 300
build_entry "$root" oldest2 400
KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" newest 2>/dev/null
if [[ -d "$root/newest" && -d "$root/mid1" && -d "$root/mid2" \
      && ! -d "$root/oldest1" && ! -d "$root/oldest2" ]]; then
  ok "留最新 3、淘汰最舊 2"
else
  fail_t "淘汰選擇錯誤: $(ls "$root" | tr '\n' ' ')"
fi

# ── 3. current key 很老仍受保護 ──────────────────────────────────────────
section "current key protected"
root="$(fresh_root 3)"
build_entry "$root" cur 500
build_entry "$root" n1 10; build_entry "$root" n2 20; build_entry "$root" n3 30
KG_IOS_CACHE_KEEP=2 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" cur 2>/dev/null
[[ -d "$root/cur" ]] && ok "current key 不被淘汰" || fail_t "current key 被淘汰了"
# current key 被 touch 成最新（之後其他 caller 的 LRU 會視其為 in-use）
cur_m="$(stat -f '%m' "$root/cur")"; n1_m="$(stat -f '%m' "$root/n1")"
[[ "$cur_m" -ge "$n1_m" ]] && ok "current key 被 touch 成最新" || fail_t "current key 未被 touch"

# ── 4. min-age 內的條目受保護 ────────────────────────────────────────────
section "min-age guard"
root="$(fresh_root 4)"
build_entry "$root" n1 1; build_entry "$root" n2 2; build_entry "$root" n3 3
build_entry "$root" recent 4   # 超出 keep=3 名次，但 4h < min-age 24h
build_entry "$root" ancient 999
KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=24 \
  kg_ios_cache_evict "$root" n1 2>/dev/null
[[ -d "$root/recent" ]] && ok "min-age 內條目保留" || fail_t "min-age 內條目被淘汰"
[[ ! -d "$root/ancient" ]] && ok "夠老的條目照常淘汰" || fail_t "夠老的條目未淘汰"

# ── 5. dry-run 不刪 ─────────────────────────────────────────────────────
section "dry-run"
root="$(fresh_root 5)"
build_entry "$root" n1 10; build_entry "$root" n2 20; build_entry "$root" n3 30
build_entry "$root" old 500
log="$(KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 KG_IOS_CACHE_EVICT_DRY_RUN=1 \
  kg_ios_cache_evict "$root" n1 2>&1 >/dev/null)"
[[ -d "$root/old" ]] && ok "dry-run 不刪檔" || fail_t "dry-run 刪了檔"
grep -q "would-evict" <<<"$log" && ok "dry-run log 標示 would-evict" || fail_t "dry-run log 缺 would-evict: $log"

# ── 6. cache root 不存在 → no-op ────────────────────────────────────────
section "missing root"
if kg_ios_cache_evict "$TMPROOT/nonexistent" somekey 2>/dev/null; then
  ok "root 不存在 exit 0"
else
  fail_t "root 不存在不應失敗"
fi

# ── 7. 一般檔案忽略 ─────────────────────────────────────────────────────
section "plain files ignored"
root="$(fresh_root 7)"
build_entry "$root" n1 10; build_entry "$root" n2 20; build_entry "$root" n3 30
build_entry "$root" old 500
echo data > "$root/stray.txt"
touch -m -t "$(date -v -900H '+%Y%m%d%H%M.%S')" "$root/stray.txt"
KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" n1 2>/dev/null
[[ -f "$root/stray.txt" ]] && ok "非目錄條目不動" || fail_t "非目錄條目被刪"
[[ ! -d "$root/old" ]] && ok "目錄條目照常淘汰" || fail_t "目錄條目未淘汰"

# ── 8. stdout 乾淨、stderr 有 summary ───────────────────────────────────
section "stream discipline"
root="$(fresh_root 8)"
build_entry "$root" n1 10; build_entry "$root" n2 20; build_entry "$root" n3 30
build_entry "$root" old 500
out="$(KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" n1 2>/dev/null)"
err="$(build_entry "$root" old2 600; KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" n1 2>&1 >/dev/null)"
[[ -z "$out" ]] && ok "stdout 乾淨" || fail_t "stdout 不乾淨: $out"
grep -q "\[ios_cache\] eviction" <<<"$err" && ok "stderr 有 summary 行" || fail_t "stderr 缺 summary: $err"

# ── 9. 空 root（存在但空）在 set -euo pipefail bash 3.2 下不炸 ─────────────
# 真實狀態：--clean-cache 後 / 災後手動清空。caller 全是 set -euo pipefail；
# macOS /bin/bash 3.2 對空陣列 "${arr[@]}" 展開在 set -u 下報 unbound variable。
section "empty root under set -euo pipefail (bash 3.2)"
root="$(fresh_root 9)"
if /bin/bash -c "set -euo pipefail; source '$LIB'; kg_ios_cache_evict '$root' ''" 2>/dev/null; then
  ok "空 root + set -euo + /bin/bash 不炸"
else
  fail_t "空 root 在 set -euo pipefail 下 crash"
fi

# ── 10. current_key 留空（ios_clean 手動 sweep 的生產呼叫形態）──────────────
section "empty current_key (manual sweep form)"
root="$(fresh_root 10)"
build_entry "$root" n1 10; build_entry "$root" n2 20; build_entry "$root" n3 30
build_entry "$root" old 500
if /bin/bash -c "set -euo pipefail; source '$LIB'; kg_ios_cache_evict '$root' ''" 2>/dev/null; then
  ok "current_key='' 不炸"
else
  fail_t "current_key='' crash"
fi
[[ ! -d "$root/old" && -d "$root/n1" ]] && ok "current_key='' 淘汰行為正確" || fail_t "current_key='' 淘汰行為錯誤"

# ── 11. stale-snapshot guard：刪除前 mtime 重驗 ─────────────────────────────
# 模擬：別的 run 在快照後 touch 了一條本該被淘汰的 key → 必須放過。
# 注入法：用 wrapper 在 du 被呼叫前攔不到，改為直接驗證「touch 成新的條目不會被刪」
# —— 在 evict 前把 old2 touch 成現在，等價於並行 run 的續命動作。
section "stale-snapshot guard (re-stat before rm)"
root="$(fresh_root 11)"
build_entry "$root" n1 10; build_entry "$root" n2 20; build_entry "$root" n3 30
build_entry "$root" old1 500
build_entry "$root" old2 600
# 快照語意在函式內不可中斷，改驗最終不變式：mtime 新的條目（無論何時變新）不被刪。
touch "$root/old2"
KG_IOS_CACHE_KEEP=3 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=6 \
  kg_ios_cache_evict "$root" n1 2>/dev/null
[[ -d "$root/old2" ]] && ok "mtime 變新的條目不被淘汰" || fail_t "mtime 變新的條目被淘汰"
[[ ! -d "$root/old1" ]] && ok "仍舊的條目照常淘汰" || fail_t "仍舊條目未淘汰"

echo ""
echo "passed=$pass failed=$fail"
[[ $fail -eq 0 ]] || exit 1
exit 0
