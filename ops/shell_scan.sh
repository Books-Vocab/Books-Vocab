#!/usr/bin/env bash
# shell_scan.sh — repo 級的跨檔 shell 掃描器（cutover gate 的 `ops-shell-scan`）。
#
# 為什麼要有這支獨立入口（IMP-20260808-3bbfa2）：
# 下面這道守衛原本長在 ops/tests/test_script_help.sh 裡面。它正確、帶正控、一跑就精準
# 指出違規的檔名與行號——但**沒有任何 gate 會在可能違反它的 diff 上跑它**。cutover 的
# `ops/**.sh` 路由只做三件事：`bash -n`、跑「該腳本自己的同名測試」、解析不到就具名 warn。
# 跨檔掃描器不屬於任何**單一**腳本，所以它永遠不會被任何 diff 觸發，只有有人整組跑
# `./ops/test_ops.sh script-help` 時才會執行。2026-08-08 因此讓 `devops.sh:669` 一路
# 撐到 land，診斷花掉約 30 分鐘。
#
# 缺口在**路由**，不在守衛。所以修法是「路由 + 一個共用入口」，而不是在 orchestrator
# 裡重造一份掃描邏輯——兩份實作就是兩份會各自漂移的判準。
# test_script_help.sh 現在改成呼叫本檔，兩個入口共用同一份實作。

set -o pipefail

usage() {
  cat <<'EOF'
Usage: ops/shell_scan.sh [<repo-root>]
       ops/shell_scan.sh --help

Repo-wide shell scanner: the cross-file checks that belong to no single script,
so nothing routes them per-file. Run once per diff that touches any *.sh.

Checks:
  1. A $VAR abutting ANY non-ASCII character inside a double-quoted string.
     bash under a UTF-8 LC_CTYPE reads that character's first byte as part of
     the variable name, so `set -u` kills the script — and every known hit sat
     on an error path, i.e. it fires exactly when something has already gone
     wrong and the message is the only thing left. The fix is always braces.
     Not just punctuation: `$sha中`, `$sha—`, `$sha…` and `$shaＡ` all die,
     measured under C.UTF-8 and en_US.UTF-8. Named exemption: put
     `fw-allow: <reason>` in a comment on the line.

Arguments:
  <repo-root>   tree to scan (default: this script's own repository)

Exit: 0 clean, 1 violation found or the probe itself is broken.
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if ! git -C "${ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
  echo "✗ not a git tree: ${ROOT}" >&2
  exit 1
fi

TMP="$(mktemp -d -t kg_shell_scan_XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }

# ── $VAR 緊接任何非 ASCII 字元 = 定時炸彈 ──────────────────────────────────
# bash 在 **UTF-8 LC_CTYPE** 下會把下一個字元的首個 byte 吃進變數名（下一個 byte
# ≥ 0x80 就吃，**與是不是標點無關**——漢字最常見，見 :78-90 的實測矩陣）：
#   echo "已回到 $sha，但…"   →   `sha\xEF: unbound variable`  →  set -u 當場殺掉腳本
#   echo "已回到 $sha中文"     →   同上（原本的十個全形標點清單抓不到這個形狀）
# C locale 下同一行完全正常，所以**開發機測不出來、跑起來才炸**。實測矩陣：
#   Bash tool（LC_CTYPE unset）→ 過；gate runner（LC_CTYPE=C.UTF-8）→ 死；
#   felix launchd（未設 locale）→ 過；人在 Terminal.app（UTF-8）→ **死**。
# 2026-08-08 起 gate 的 child locale 已由 ops/lib/streaming_command.py 明確固定成
# C.UTF-8（CHILD_LC_CTYPE），也就是**嚴格的那一邊**——所以這道掃描守的正是 gate 真正
# 會走的解析路徑，不再是「某些人某些時候」的路徑。
# 這個 repo 的字串大量是中文，而命中的 9 處**全部落在錯誤路徑**——也就是它只在
# 「已經出事了、正要印出原因」的那一刻引爆，把診斷訊息換成一行 unbound variable。
# 2026-08-04 它讓 kg_reconcile.sh 的回滾告警整個吞掉 verdict（IMP-0062）。
# 修法一律是 `${VAR}`。frozen/ 具名排除：刻意冷凍、不執行。
echo "── no \$VAR abuts a non-ASCII character (UTF-8 locale time bomb) ──"
# 不用 `grep -P`：macOS 的 BSD grep 沒有這個旗標，而這段第一版正是 `-P` + `2>/dev/null`
# ——每個檔案都 "invalid option" 失敗、輸出全空、掃描器報 ✓。**沉默被當成沒有違規**，
# 這正是它要防的那類假綠。
#
# 這裡比對的是**位元組類 \200-\377**，不是一份標點清單。理由是量出來的
# （2026-08-08，`LC_ALL=<loc> bash -c 'set -u; sha=abc; echo "x $sha<C>y"'`）：
#   C          → 六個字元全部 rc=0，正常輸出
#   C.UTF-8    → 中 — … 《 ， Ａ **六個全部** rc=127 `sha<?>: unbound variable`
#   en_US.UTF-8→ 同上
# 也就是說 bash 吃掉的是「下一個 byte 是不是 ≥ 0x80」，跟那個字元是不是標點無關。
# 原本的十個全形標點是危害的**嚴格子集**，而這個 repo 的訊息幾乎全是中文——
# `$VAR` 後面直接接漢字（`$sha中文`）才是最可能出現的形狀，卻整整不在偵測範圍內。
# 由 round2 批次整合的 code review 具名交回，本檔自行複驗（掃描範圍的兩個已知邊界
# 另見 IMP-20260808-2f4203：只掃雙引號內、只認 `*.sh` 副檔名）。
#
# `LC_ALL=C` 必須明確釘住：在 UTF-8 locale 下 `[\200-\377]` 是不合法的多位元組序列，
# grep 會拒絕整條 pattern —— 又一次「沉默被當成沒有違規」。C locale 下它就是位元組範圍。
FW_HI="$(printf '[\200-\377]')"
FW_RE="\"[^\"]*[$][a-zA-Z_][a-zA-Z0-9_]*${FW_HI}"

# 正控：先證明掃描器抓得到已知的違規，否則下面的「沒有命中」與「掃描器壞了」無法區分。
fw_fixture="${TMP}/fw_fixture.sh"
# 四行、兩對。每一對都是「危險形 vs 同一個字元的加括號安全形」，所以「抓到」與
# 「不誤抓」由同一個字元作證，而不是拿標點的命中去替漢字背書。
printf 'echo "已回到 $sha，但…"\necho "safe ${sha}，braced"\necho "hanabuts $sha中文"\necho "safehan ${sha}中文"\n' > "${fw_fixture}"  # fw-allow: 這是正控 fixture 本身，單引號內不展開
fw_probe="$(LC_ALL=C grep -nE "$FW_RE" "${fw_fixture}" 2>&1 || true)"
if [[ "${fw_probe}" != *'已回到'* ]]; then
  fail_t "non-ASCII scanner cannot flag a known punctuation violation — probe broken, not the tree: ${fw_probe:-<no output>}"
elif [[ "${fw_probe}" != *hanabuts* ]]; then
  # 標點只是危害的子集。實測（2026-08-08）C.UTF-8 / en_US.UTF-8 下，`$sha中`、`$sha—`、
  # `$sha…`、`$sha《`、`$shaＡ` 全部同樣 unbound variable。在一個訊息幾乎全是中文的
  # repo 裡，「$VAR 後面直接接漢字」才是最可能出現的形狀，而它曾經完全不在偵測範圍內。
  fail_t "non-ASCII scanner misses \$VAR abutting a Han character — the likeliest form in this repo: ${fw_probe:-<no output>}"
elif [[ "${fw_probe}" == *braced* || "${fw_probe}" == *safehan* ]]; then
  fail_t "non-ASCII scanner also flags the braced (safe) form — pattern too broad"
else
  ok "non-ASCII scanner flags both bad forms and spares \${VAR} (positive control)"
fi

fw_hits="$(
  git -C "${ROOT}" ls-files '*.sh' \
    | grep -v '^frozen/' \
    | while read -r f; do
        # 註解行 shell 不展開 → 真的無害；`# fw-allow: <理由>` 是具名豁免（需寫理由）。
        LC_ALL=C grep -nE "$FW_RE" "${ROOT}/${f}" 2>/dev/null \
          | grep -v '^[0-9][0-9]*: *#' | grep -v 'fw-allow' | sed "s|^|${f}:|"
      done
)"
scanned="$(git -C "${ROOT}" ls-files '*.sh' | grep -cv '^frozen/')"
if (( scanned < 10 )); then
  fail_t "only scanned ${scanned} shell script(s) — the probe is broken, not the tree"
elif [[ -n "${fw_hits}" ]]; then
  fail_t "\$VAR abuts a non-ASCII character (use \${VAR}); dies under UTF-8 LC_CTYPE:"
  printf '%s\n' "${fw_hits}" | sed 's/^/      /'
else
  ok "no \$VAR abuts a non-ASCII character across ${scanned} tracked shell script(s)"
fi

echo ""
echo "══════════════════════════════"
echo "  passed: ${pass}  failed: ${fail}"
echo "══════════════════════════════"
[[ ${fail} -eq 0 ]]
