#!/usr/bin/env bash
# test_lib_sourcing.sh — 每個 ops/ 入口腳本用到的 ops/lib/*.sh 函式，都必須真的（可經
# 轉包）source 到那個 lib。
#
# 為什麼需要這條：ops/ios_build.sh 呼叫 start_build_monitor / count_compile_events，卻從未
# source lib/ios_build_progress.sh。它不會炸，因為兩個呼叫點都在 `set +e` 區段內——於是
# `ios_ops.sh build` 全程沒有 heartbeat，收尾印出空的 `( compile events)`，progress
# baseline 也永遠寫不進去。錯得無聲，正是最貴的那種；而它旁邊的 ios_test.sh 有 source，
# 兩者長得夠像，肉眼 review 不會發現。
#
# 這條之所以值得存在，是因為 CLAUDE.md 把鐵律 5（長時操作不可靜默）標成 [machine]，
# 宣稱有工具強制。標註在本 repo 是可稽核的事實；build 這條路徑上它曾經是死的。
#
# 只掃**入口腳本**（ops/*.sh）。ops/lib/*.sh 之間互相呼叫是合法的組合模式——由入口
# 一次 source 一組 sibling lib（ios_ops.sh 就是這樣組 ios_ops_*.sh），要求每個 lib 自我
# 完備會產出大量假陽性，而假陽性會讓人關掉這條測試。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# 「這個腳本有沒有接上這個 lib」用**全檔是否提到該 lib 路徑**判定，而不是逐行解析
# source 語句。理由是實際寫法五花八門且都合法：`source "$PROGRESS_LIB"`（路徑存在變數
# 裡）、在 `bash -lc '…'` 字串內 source（探針測試）、經另一個 lib 轉包。逐行解析會把這
# 些判成缺 source，而假陽性多到一定程度，這條測試就會被關掉。
# 代價是「只在註解裡提到」也會被放行——換來的是它對真正的失效模式仍然靈敏：
# ios_build.sh 從頭到尾沒有出現過 ios_build_progress.sh 這個字串。
mentions_lib() {  # $1=腳本  $2=lib 檔名
  grep -qE "lib/$2" "$1"
}

call_re() { printf '(^|[;&|(`]|\\$\\()[[:space:]]*%s([[:space:]]|$)' "$1"; }

fail=0
hits=""
checked=0

for lib in ops/lib/*.sh; do
  libname="$(basename "$lib")"
  fns="$(grep -oE '^[a-z_][a-z0-9_]*\(\)' "$lib" | sed 's/()$//' || true)"
  [[ -n "$fns" ]] || continue

  for script in ops/*.sh; do
    mentions_lib "$script" "$libname" && continue
    for fn in $fns; do
      grep -qE "^${fn}\(\)" "$script" && continue      # 自己定義了同名函式
      checked=$((checked + 1))
      # `type fn >/dev/null 2>&1 && fn …` 是明示的選擇性依賴（缺了就跳過該功能），
      # 不是漏 source。它自己就說清楚了，所以放行。
      hits="$(grep -nE "$(call_re "$fn")" "$script" | grep -vE "type[[:space:]]+${fn}[[:space:]]*>" || true)"
      if [[ -n "$hits" ]]; then
        echo "✗ ${script} 呼叫 ${fn}()，但全檔沒有提到 ops/lib/${libname}"
        printf '%s\n' "$hits" | head -3 | sed 's/^/    /'
        fail=$((fail + 1))
      fi
    done
  done
done

# 負控：守衛本身不得被掏空。植入一個明顯缺 source 的呼叫必須被抓到，
# 而同一個檔案補上 source 之後必須不再被抓到（雙向都驗，否則規則可能是恆真或恆假）。
probe="$(mktemp -d)"; trap 'rm -rf "$probe"' EXIT
printf '#!/usr/bin/env bash\nset +e\nkg_probe_fn arg\n' > "$probe/missing.sh"
printf '#!/usr/bin/env bash\nsource "$D/lib/kg_probe_lib.sh"\nkg_probe_fn arg\n' > "$probe/present.sh"
probe_ok=1
grep -qE "$(call_re kg_probe_fn)" "$probe/missing.sh" || probe_ok=0
mentions_lib "$probe/missing.sh" kg_probe_lib.sh && probe_ok=0
mentions_lib "$probe/present.sh" kg_probe_lib.sh || probe_ok=0
if [[ "$probe_ok" -ne 1 ]]; then
  echo "✗ 負控失敗：偵測規則無法同時區分「缺 source」與「已 source」，這條測試沒有在測東西"
  fail=$((fail + 1))
fi

if [[ "$fail" -ne 0 ]]; then
  echo "✗ test_lib_sourcing: ${fail} 處未 source 的 lib 函式呼叫"
  exit 1
fi
echo "✓ test_lib_sourcing: ${checked} 組 (entrypoint, lib fn) 檢查通過，負控雙向有效"
