#!/usr/bin/env bash
# Every ops/test_ops.sh group must be explicitly classified as CI-runnable or
# not, with a reason.
#
# 沒有這條，`.github/workflows/ops-suite.yml` 的覆蓋面會靜默腐爛：新增一個 group、
# 忘了加進 CI 清單，那個 group 就永遠只在有人手動跑的時候存在。ops 套件在
# 2026-08-03 之前完全沒有 CI 執行面，代價是 test_ui_quality_gate.sh 紅了數週、
# ui-quality-gate 空轉兩個月，都沒有任何東西發聲。
#
# Usage:
#   ./ops/tests/test_ops_ci_coverage.sh                     # assert classification is total
#   ./ops/tests/test_ops_ci_coverage.sh --print-linux-groups # emit the CI group list
#
# ── 為什麼理由要帶 token（IMP-0054，2026-08-04）────────────────────────────────
# 原本每筆排除只帶一段散文理由。「required reason」讓排除看起來被稽核過，但**沒有任何
# 東西查過理由是否為真**，於是理由描述的是「被測工具」而不是「這支測試」——工具打 ssh，
# 測試卻是注入 seam 的離線 stub。排除從 27 筆降到 14 筆，**收回 13 個 group**；
# `ops/test_devops.sh` 就在其中一個裡紅了 6.5 週沒人知道（IMP-0052）。收回的依據不是
# 讀理由，是在 runner 等價容器裡實跑（`ops/ci_linux_repro.sh`）：23/23 全綠。
#
# 所以理由現在必須挑一個 token，而 `bin-*` token 是**可證偽的**：把它宣稱的命令換成
# exit 127 的 stub 再跑一次那個 group，還能綠 = 這個相依不存在 = 契約紅。`data-*` /
# `net-external` 這幾個本質上無法用 PATH 證偽（相依的是磁碟上的資產或外部服務），
# 它們是這條檢查的**逃生口**——所以字彙表是封閉清單：要新增逃生口得動這張表，那是一次
# 看得見、會被 review 的編輯，不是一句誰都能寫的散文。

# 這支在 macOS 上約 130 秒：`bin-*` 的證偽對每個 group 要先跑一次未遮蔽的 baseline
# 再跑一次遮蔽的，而 ios-ops 單趟就近一分鐘。不是卡住。
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"   # cd 之前先釘死，供源碼自檢用
cd "$WORKSPACE"

# 這些 group 在 linux runner 上只需要 workflow 明講會裝的東西：
# git / curl / uv（python）＋ `.github/workflows/ops-suite.yml` 的 apt 清單
# （ripgrep、jq、sqlite3、python3、openssh-client）。**清單要跟 workflow 對齊**——
# 這裡寫一份、workflow 裝另一份，就是再造一次「兩個平面各有意見」。
LINUX_GROUPS=(
  lint-baselines
  injection-lint
  ops-ci-coverage
  ui-token
  plain-deadzone
  ui-quality-plane
  python-entrypoints
  capability-matrix
  worktree-orchestrator
  script-help
  lib-sourcing
  backlog
  gen-ios-baseline
  ios-signal-traps
  # ── 以下 13 筆原本被排除，理由經證偽實測不成立後收進來（IMP-0054）──
  # 共通形狀：測試本身是注入 seam 的離線 stub，散文理由描述的是它所測的那支工具。
  backup-verify
  devops
  deploy-smoke
  infra-health
  reconcile
  branch-audit
  review-audit
  log-assert
  ios-release
  ios-run-verdict
  ios-device-files
  ios-device-logs
  review-flip-probe
  # ── IMP-0038：排除理由是「anchor 指向從未進 origin 的 pre-squash commit，只能從
  #    本地 dangling object 解析」。2026-08-06 收攏後 179 顆 commit 已 sync 到
  #    origin/main，且逐份實測全部 active doc 的 verified_against 都能從 origin/main
  #    可達 —— 那個理由現在是假的，所以收進來。
  docs-lint
  # 純 Python：讀 ops/fixtures/ui_worlds/marketing_demo.json 與兩支 Debug scene
  # 的原始碼字面量做對帳，不需要模擬器（那正是它存在的理由——Swift 端的
  # precondition 只有跑得動 simulator 時才會講話）。
  catalog-scene-expectations
  # ── IMP-20260805-947062 收編的 4 個 group ──────────────────────────────────
  # 全都跑在 --no-project sandbox（stdlib + pytest），逐支在 macOS 實測過。
  streaming-command
  app-review
  demo-data
  # catalog-render 的 linux 判決**未實測**：本機沒有 docker，跑不了
  # ops/ci_linux_repro.sh。放這裡是因為手上證據不支持排除——它讀的三個資產
  # （iphone_frame.png/.json、sources/iphone-framed/01_vocab_list.png）都是 tracked，
  # 拿的 pillow 走 `uv run --with pillow`，而 CI 既然跑得動 `uv run --with pytest`
  # 就有同一條 PyPI 路徑；四支測試都沒有 /System/Library、字型、sips、xcrun 之類的
  # macOS 專屬相依（實際 grep 過）。
  # 刻意**不**借 data-catalog-png 排除：那個 token 的意思是「只有模擬器跑得出來的
  # PNG」，這裡的是 tracked 資產，借用等於寫一個假理由——正是 IMP-0054 砍掉 13 個
  # group 的那種病。真在 runner 上紅了，帶著實測訊息移進 EXCLUDED_GROUPS 或補一個
  # 誠實的新 token，那是一行的距離。
  catalog-render
)

# token|要從 PATH 拿掉的命令|功能探針（皆空 = 這個 token 無法用 PATH 證偽）
#
# 封閉字彙表。空 denial set 的 token 是逃生口，新增前先問：真正的相依是磁碟資產、
# 外部服務，還是其實只是一支沒人跑過的離線測試？
#
# **第三欄存在是因為「在 PATH 上」不等於「能用」。** 只裝了 Command Line Tools 的
# macOS 上，xcode-select 的 shim 讓 xcodebuild/xcrun/swift/swiftc 四個名字全都
# resolve 得到，但 `xcodebuild -version` 會吐
# 「requires Xcode, but active developer directory is a CLT instance」。fleet 裡的
# felix 正是這種機器：只看 command -v 的話，這裡會判定工具鏈齊全、跑一次注定失敗的
# baseline，然後指控兩個其實健康的 group「已經紅了，先去修」。探針空 = 只驗存在。
#
# 曾經有過 bin-lldb（給 lldb-forensics 用）。證偽器當場否決：那支測試從不直接呼叫 lldb，
# 它靠的是 xcrun。這段故事留成註解，不留成沒人用的活 token。
DEP_TOKENS=(
  "bin-xcode|xcodebuild xcrun swift swiftc|xcodebuild -version"
  "bin-ssh|ssh scp rsync|ssh -V"
  "data-indexstore||"
  "data-ui-world||"
  "data-catalog-png||"
  "data-git-history||"
  "bsd-userland||"
  "net-external||"
)

# 自我檢驗 fixture 用的 token。它是唯一允許「沒有任何排除引用」的 token——因為引用它的
# 是下面那兩個合成 fixture。具名例外，不是通則。
FIXTURE_TOKEN="bin-ssh"

# group|token|reason —— reason 說明「為什麼這個 token 擋住了 linux runner」。
EXCLUDED_GROUPS=(
  "gate-can-fail|data-ui-world|its ui-quality-fast proof needs the same UI World assets as ui-quality-gate"
  "ui-quality-gate|data-ui-world|its --dataset assertions load a UI World whose assets are absolute local paths (lab/podcast workspaces)"
  "release|data-git-history|drives ops/release.sh against local tags and the iOS pbxproj"
  "ios-ops|bin-xcode|shells out to the Xcode toolchain for real (swift 2x) — dies with it denied"
  "lldb-forensics|bin-xcode|shells out to xcrun 4x for real — dies with it denied. Tokened bin-lldb first; the falsifier rejected that on the spot (it never invokes lldb directly)"
  "ui-deadcode|data-indexstore|reads an IndexStore that only an Xcode build produces; the xcodebuild binary itself is never invoked"
  "ui-graph|data-indexstore|reads an IndexStore that only an Xcode build produces; the xcodebuild binary itself is never invoked"
  "visual-regression|data-catalog-png|compares rendered catalog PNGs that only a simulator run produces"
  "catalog-review|data-catalog-png|compares rendered catalog PNGs that only a simulator run produces"
  "podcast-ops|net-external|lab/podcast toolchain + network TTS"
  # ── 以下三筆是我先收進 CI、再被 ubuntu 容器實跑打回來的（review 提供 runner 等價環境）──
  # 「二進位不缺」不等於「跑得起來」：前兩筆缺的是 GNU/BSD 語意差，第三筆缺的是資產。
  "ios-cache-evict|bsd-userland|BSD-only date/stat: date -v -900H (test_ios_cache_evict.sh:35,117) and stat -f %m (:79). On GNU both fail, every mtime collapses to one instant and the LRU ordering under test evaporates — measured 10 passed / 10 failed on ubuntu (IMP-0058)"
  "ios-test-discovery|bsd-userland|a grep piped into head -1 at test_ios_test_discovery.sh:312 — GNU grep dies on SIGPIPE and pipefail propagates 141, killing the script. 5/5 rc=141 on ubuntu vs 5/5 rc=0 on macOS (IMP-0058)"
  "review-probe|data-ui-world|case 14 (test_review_probe.sh:133-145) resolves ops/fixtures/ui_worlds/marketing_demo.json:58, an absolute path to an UNTRACKED 16MB .m4a — the very dependency this table already excludes ui-quality-gate for. Admitting it while excluding ui-quality-gate was self-contradictory"
)

# path|reason —— tracked test files that intentionally belong to no group.
#
# 只有兩欄，不是三欄。EXCLUDED_GROUPS 的 token 欄之所以存在，是因為 `bin-*` 可以用 PATH
# 證偽；「這個檔不是測試」沒有任何對應的證偽器，加一欄 token 只會讓豁免**看起來**被稽核過
# 而其實沒有——那正是 header（14-25 行）記載的 IMP-0054 罪狀。這張表的機器可查性來自
# 下面那段的 stale / overlap 斷言：名字必須是 tracked 檔，且不得同時被某個 group 跑到。
#
# 「它紅了所以豁免」不是這張表的用途。那是本表要殺的靜默綠本身。
UNGROUPED_TESTS=(
  "ops/test_ops.sh|the aggregate dispatcher itself, not a test — ops/worktree_orchestrate.py:OPS_SHELL_UNROUTABLE_TESTS states the same exemption for the cutover plane"
)

if [[ "${1:-}" == "--print-linux-groups" ]]; then
  printf '%s\n' "${LINUX_GROUPS[@]}"
  exit 0
fi

pass=0; fail=0; skipped=0; SEC_BASE=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; SEC_BASE=$fail; }
# 收尾摘要必須看**本段**有沒有失敗，不是全域計數器。用全域的話，前面任何一段紅了之後，
# 後面每一段都只印標題不印任何結論——「這段全過」與「這段根本沒跑」在輸出上一模一樣。
ok_if_clean() { (( fail == SEC_BASE )) && ok "$*" || true; }

# DEFAULT_TESTS is the SoT for what the suite contains.
#
# 註解要剝掉再讀。原版直接把陣列裡的每一行當 group 名，於是在 DEFAULT_TESTS 裡寫一行
# 註解說明「這批 group 為什麼存在」會讓那行**變成一個假 group**，然後被下一段指控
# 未分類——實測過：4 行註解 = 4 筆 unclassified。這等於用工具行為禁止在唯一的 group
# SoT 旁邊留下理由，而下一個註冊 group 的人正需要那個位置。group 名不含 '#'，所以
# 從 '#' 砍到行尾對整行註解與行尾註解都成立。
DECLARED=()
while IFS= read -r line; do DECLARED+=("$line"); done < <(
  awk '/^DEFAULT_TESTS=\(/{flag=1;next} /^\)/{flag=0} flag {sub(/#.*/,"");gsub(/[[:space:]]/,"");if($0!="")print}' ops/test_ops.sh
)

section "DEFAULT_TESTS is readable"
if [[ "${#DECLARED[@]}" -gt 0 ]]; then
  ok "parsed ${#DECLARED[@]} group(s) from ops/test_ops.sh"
else
  fail_t "parsed 0 groups — the probe is broken, not the classification"
fi

section "every declared group is classified exactly once"
for g in "${DECLARED[@]}"; do
  in_linux=0
  for l in "${LINUX_GROUPS[@]}"; do [[ "$l" == "$g" ]] && in_linux=1; done
  in_excluded=0
  for e in "${EXCLUDED_GROUPS[@]}"; do [[ "${e%%|*}" == "$g" ]] && in_excluded=1; done
  if (( in_linux + in_excluded == 1 )); then
    :
  elif (( in_linux + in_excluded == 0 )); then
    fail_t "$g is unclassified — add it to LINUX_GROUPS or give it an EXCLUDED_GROUPS reason"
  else
    fail_t "$g is in both LINUX_GROUPS and EXCLUDED_GROUPS"
  fi
done
ok_if_clean "all ${#DECLARED[@]} group(s) classified"

section "no classification refers to a group that no longer exists"
for g in "${LINUX_GROUPS[@]}" "${EXCLUDED_GROUPS[@]%%|*}"; do
  found=0
  for d in "${DECLARED[@]}"; do [[ "$d" == "$g" ]] && found=1; done
  (( found == 1 )) || fail_t "$g is classified but not in DEFAULT_TESTS — stale entry"
done
ok_if_clean "classification contains no stale entries"

# ── file→group 反向覆蓋 ──────────────────────────────────────────────────────
# 上面三段驗的全是 group→分類：每個 group 都被分類、沒有分類指向死 group。**沒有一段
# 列舉過檔案**，所以「測試檔存在但沒有任何 group 跑得到」在結構上偵測不到，這正是
# IMP-20260805-947062：19 支 tracked 測試檔對每個 group 都不可達，其中
# test_streaming_command.py 是鐵律 5 heartbeat 契約唯一的 `[machine]` 守衛、
# test_app_review_gate.py 守送審。**從不執行的守衛跟永遠通過的守衛在輸出上無法區分。**
section "every tracked test file is reachable from some group"
# run_one 是「某個 group 實際 EXECUTE 什麼」的 SoT。先剝註解再比對：在註解裡提到一個
# 路徑不是執行，少了這道 sed，任何人都能靠寫一行註解讓這條檢查閉嘴。
REACHABLE=(); TRACKED=()
while IFS= read -r l; do REACHABLE+=("$l"); done < <(
  awk '/^run_one\(\) \{/{f=1} f{print} f&&/^\}/{exit}' ops/test_ops.sh \
    | sed 's/[[:space:]]*#.*$//' \
    | grep -oE 'ops/(tests/)?test_[A-Za-z0-9_]+\.(sh|py)' | sort -u
)
while IFS= read -r l; do TRACKED+=("$l"); done < <(git ls-files 'ops/tests/test_*' 'ops/test_*' | sort -u)

# 兩道探針自檢，比照 192 / 199 行：少了它們，改個名字就能讓整段恆真地綠。
# bash 3.2 配 set -u 展開空陣列是 crash 不是空迴圈，所以筆數要先看再展開。
if (( ${#TRACKED[@]} == 0 )); then
  fail_t "git ls-files found no tracked ops test file — the probe is broken, not the suite"
elif (( ${#REACHABLE[@]} == 0 )); then
  fail_t "parsed 0 test paths out of run_one — the probe is broken, not the dispatcher"
else
  for f in "${TRACKED[@]}"; do
    reach=0
    for r in "${REACHABLE[@]}"; do [[ "$r" == "$f" ]] && reach=1; done
    exempt=0
    for u in "${UNGROUPED_TESTS[@]}"; do [[ "${u%%|*}" == "$f" ]] && exempt=1; done
    if (( reach + exempt == 0 )); then
      fail_t "$f is reachable from no group — register it in ops/test_ops.sh run_one, or name it in UNGROUPED_TESTS with a reason"
    elif (( reach + exempt == 2 )); then
      fail_t "$f is both run by a group and named exempt — pick one"
    fi
  done
  # 反向 stale，比照 164-170 行：改名後留下的豁免是一支永久的消音器。
  for u in "${UNGROUPED_TESTS[@]}"; do
    p="${u%%|*}"; found=0
    for f in "${TRACKED[@]}"; do [[ "$f" == "$p" ]] && found=1; done
    (( found == 1 )) || fail_t "$p is named exempt but is not a tracked test file — stale entry"
  done
  ok_if_clean "all ${#TRACKED[@]} tracked test file(s) are reachable or named-exempt"
fi

# ── CI 觸發面 vs cutover 路由面 ──────────────────────────────────────────────
# 兩個平面對同一個檔案必須有相同意見。cutover 的路由條件是「`.sh` 且（在 ops/ 下
# 或在 repo root）」（worktree_orchestrate.py:plan_gates）；workflow 的 `ops/**`
# 一條就涵蓋前半，後半沒有共同前綴，只能逐條列——所以它是會漂的那一半。
# 漏一條的後果就是 IMP-0052 本身：本機 gate 擋得住、CI 完全看不到那支腳本。
WF=".github/workflows/ops-suite.yml"
section "the workflow triggers on every root script cutover routes"
wf_paths=()
while IFS= read -r pat; do wf_paths+=("$pat"); done < <(
  awk '/paths: &ops_paths/,/^  pull_request:/' "$WF" \
    | grep -oE "^ *- '[^']+'" | sed "s/^ *- '//;s/'\$//"
)
# 自測：解析不到 `ops/**` 就代表 awk 抓錯區塊，下面整段迴圈會變成恆真。
# 先看筆數再展開——bash 3.2 配 `set -u` 展開空陣列是**crash** 不是空迴圈，
# 那會讓這條「偵測探針壞掉」的檢查自己死在報告之前，並帶走後面所有 section。
wf_has_ops=0
if (( ${#wf_paths[@]} > 0 )); then
  for p in "${wf_paths[@]}"; do [[ "$p" == 'ops/**' ]] && wf_has_ops=1; done
fi
if (( wf_has_ops == 0 )); then
  fail_t "could not parse the paths anchor out of $WF (got ${#wf_paths[@]} entry/entries, none of them 'ops/**') — the probe is broken, not the workflow"
else
  root_sh=()
  while IFS= read -r f; do root_sh+=("$f"); done < <(git ls-files '*.sh' | grep -v '/')
  if (( ${#root_sh[@]} == 0 )); then
    # 空清單會讓下面的迴圈零圈跑完然後印 ✓——「沒有東西違規」與「沒有東西被檢查」
    # 在輸出上長得一模一樣。這是本輪反覆出現的那種假綠，明確擋掉。
    fail_t "git ls-files found no tracked root shell script — the probe is broken (devops.sh at minimum should be there)"
  else
    missing=""
    for f in "${root_sh[@]}"; do
      listed=0
      for p in "${wf_paths[@]}"; do [[ "$p" == "$f" ]] && listed=1; done
      (( listed == 1 )) || missing="${missing:+$missing }$f"
    done
    if [[ -n "$missing" ]]; then
      fail_t "cutover routes these root script(s) but $WF does not trigger on them: $missing"
    else
      ok "all ${#root_sh[@]} tracked root script(s) are in the workflow paths anchor"
    fi
  fi
  # 反向：列了但檔案不存在 = 早已改名/刪除的死條目，會讓上面的檢查看起來很健康。
  stale=""
  for p in "${wf_paths[@]}"; do
    [[ "$p" == *'*'* || "$p" == */* ]] && continue   # glob 與帶目錄的條目不在本檢查範圍
    [[ -f "$p" ]] || stale="${stale:+$stale }$p"
  done
  if [[ -n "$stale" ]]; then
    fail_t "$WF lists root path(s) that no longer exist: $stale"
  else
    ok "the workflow lists no root path that has disappeared"
  fi
fi

# ── token 字彙 + 證偽 ────────────────────────────────────────────────────────

token_denials() {  # token → denial set（第 2 欄）；未知 token 回 __UNKNOWN__
  local want="$1" t rest
  for t in "${DEP_TOKENS[@]}"; do
    if [[ "${t%%|*}" == "$want" ]]; then rest="${t#*|}"; printf '%s' "${rest%%|*}"; return 0; fi
  done
  printf '__UNKNOWN__'
}

token_probe() {  # token → 功能探針（第 3 欄，可為空）
  local want="$1" t rest
  for t in "${DEP_TOKENS[@]}"; do
    if [[ "${t%%|*}" == "$want" ]]; then rest="${t#*|}"; printf '%s' "${rest#*|}"; return 0; fi
  done
  printf ''
}

# token 指名的工具鏈在這台機器上「真的能用」嗎？名字 resolve 得到不算數（見 DEP_TOKENS
# 註解的 CLT shim）。回 0 = 可用；回非 0 時把原因寫進 ${TOOLCHAIN_WHY}。
TOOLCHAIN_WHY=""
toolchain_usable() {
  local tok="$1" denials probe b missing=""
  denials="$(token_denials "$tok")"
  for b in $denials; do command -v "$b" >/dev/null 2>&1 || missing="${missing:+$missing }$b"; done
  if [[ -n "$missing" ]]; then TOOLCHAIN_WHY="[$missing] absent"; return 1; fi
  probe="$(token_probe "$tok")"
  if [[ -n "$probe" ]] && ! $probe >/dev/null 2>&1; then
    TOOLCHAIN_WHY="[$denials] all resolve but \`$probe\` fails — present in name only"
    return 1
  fi
  TOOLCHAIN_WHY=""
  return 0
}

# 用 exit 127 的 stub 遮蔽 <denied> 裡的命令，再跑 <cmd...>，回傳它的 exit code。
# 遮蔽靠 PATH 前置，所以只擋得住「靠 PATH 解析」的呼叫；絕對路徑呼叫（/usr/bin/log）
# 穿得過去——這個缺口**沒有補**，見下面 falsify 段的註解。
#
# GH_TOKEN/GITHUB_TOKEN 只在 denial set 含 gh 時才清：先前無條件清空，等於夾帶一道
# 沒有任何 token 宣告的額外 denial，一個標 bin-xcode 的 group 若其實是死在缺 token，
# 會被認證成 xcode 相依。
run_denied() {
  local denied="$1"; shift
  local shim rc=0 b
  shim="$(mktemp -d)"
  for b in $denied; do
    printf '#!/bin/sh\necho "DENIED: %s" >&2\nexit 127\n' "$b" >"$shim/$b"
    chmod +x "$shim/$b"
  done
  # 目前**走不到**：唯二的 denial set 是 xcode 那組與 ssh 那組，都不含 gh。留著是因為
  # 一旦有人加 `bin-gh`，少了這段，shim 會被一個仍然有效的 token 繞過去而假綠。
  # 它是未來的保險，不是現在生效的保護——不要把它讀成後者。
  if [[ " $denied " == *" gh "* ]]; then
    PATH="$shim:$PATH" GH_TOKEN="" GITHUB_TOKEN="" "$@" >/dev/null 2>&1 || rc=$?
  else
    PATH="$shim:$PATH" "$@" >/dev/null 2>&1 || rc=$?
  fi
  rm -rf "$shim"
  return "$rc"
}

run_plain() { "$@" >/dev/null 2>&1; }

section "every exclusion carries a token from the closed vocabulary"
for e in "${EXCLUDED_GROUPS[@]}"; do
  g="${e%%|*}"; rest="${e#*|}"; tok="${rest%%|*}"; why="${rest#*|}"
  if [[ "$tok" == "$rest" || -z "$why" || "$why" == "$tok" ]]; then
    fail_t "$g: expected group|token|reason, got '$e'"
  elif [[ "$(token_denials "$tok")" == "__UNKNOWN__" ]]; then
    fail_t "$g: token '$tok' is not in DEP_TOKENS — add it there (a visible edit) or pick an existing one"
  elif [[ "$tok" == bin-* && -z "$(token_denials "$tok")" ]]; then
    # `bin-*` 意思就是「這個相依是一支可以從 PATH 拿掉的命令」，denial set 空掉就自相矛盾。
    # 擋在這裡是因為往下走會很難看：空 denial 讓 skip 條件不成立 → baseline 綠 → 遮蔽是
    # 空的 no-op → 「survived denial」→ 指控一個健康的 group 理由造假。今天走不到（兩個
    # bin-* token 都非空），但 DEP_TOKENS 的註解正好在鼓勵用空 denial 當逃生口。
    fail_t "$g: token '$tok' is bin-* but names no command — a PATH-falsifiable token with an empty denial set is a contradiction; give it commands or use a data-*/net-* token"
  fi
done
ok_if_clean "all ${#EXCLUDED_GROUPS[@]} exclusion(s) carry a known token and a reason"

# 這張表是**資料**，不該執行。反引號寫進雙引號陣列元素會被 bash 做命令替換：本檔第一版
# 的理由裡引用了那條有問題的 grep 當例證，結果它真的被執行、真的吃到 SIGPIPE，
# 整支腳本以 rc=141 死掉且一個字都沒印——正是那條理由描述的 bug。
#
# 檢查的對象必須是**原始碼文字**，不是陣列元素的值。`ARR=( "..." )` 是雙引號賦值，
# bash 在**賦值當下**就做完命令替換，等迴圈讀到元素時反引號早被輸出取代——所以
# 「檢查元素值」的版本對危險寫法永遠不會紅，只會對單引號（本來就無害）那種紅，
# 極性是反的。這是 reviewer 用注入實測打掉的：注入的命令跑了，檢查照樣印 ✓。
section "reason strings are inert data"
danger=0
while IFS= read -r srcline; do
  if [[ "$srcline" == *'`'* || "$srcline" == *'$('* ]]; then
    fail_t "table source executes at parse time (backtick or \$( ): ${srcline#"${srcline%%[![:space:]]*}"}"
    danger=1
  fi
done < <(awk '/^(EXCLUDED_GROUPS|DEP_TOKENS|UNGROUPED_TESTS)=\(/{f=1;next} f&&/^\)/{f=0} f' "$SELF")
# 自測：解析不到表就代表 awk 抓錯範圍，上面的迴圈零圈跑完會長得像「沒有危險寫法」。
tbl_lines="$(awk '/^(EXCLUDED_GROUPS|DEP_TOKENS|UNGROUPED_TESTS)=\(/{f=1;next} f&&/^\)/{f=0} f' "$SELF" | grep -c . || true)"
if (( tbl_lines < 10 )); then
  fail_t "only parsed $tbl_lines line(s) of the table literals out of $SELF — the probe is broken, not the table"
elif (( danger == 0 )); then
  ok "no line of the table literals ($tbl_lines) contains a backtick or \$("
fi

section "every token in the vocabulary is actually referenced"
for t in "${DEP_TOKENS[@]}"; do
  tok="${t%%|*}"; used=0
  for e in "${EXCLUDED_GROUPS[@]}"; do
    rest="${e#*|}"; [[ "${rest%%|*}" == "$tok" ]] && used=1
  done
  [[ "$tok" == "$FIXTURE_TOKEN" ]] && used=1   # 具名例外：自我檢驗 fixture 的 token
  (( used == 1 )) || fail_t "token '$tok' is in DEP_TOKENS but no exclusion uses it — an unused escape hatch nobody reviews"
done
ok_if_clean "all ${#DEP_TOKENS[@]} token(s) are in use"

# 證偽器自己也會壞，而且壞法是「永遠說相依存在」——那正好是靜悄悄放行所有假理由。
# 先用合成 fixture 把兩個方向都釘住，再拿它去判真的 group。
#
# baseline 這一維不可省：只斷言「denial 下非零」分不出「shim 擋住了 ssh」與「這台機器
# 根本沒有 ssh」。實測——把 PATH 前置改成後綴（denial 完全失效），在有 ssh 的機器上會被
# 抓到，但把 /usr/bin/ssh 移走之後整支回 8 passed / 0 failed。
section "the falsifier can tell a real dependency from a claimed one"
fx="$(mktemp -d)"
printf '#!/bin/sh\nexit 0\n' >"$fx/liar.sh"                    # 宣稱要 ssh，其實碰都沒碰
printf '#!/bin/sh\nssh -V >/dev/null 2>&1\n' >"$fx/honest.sh"  # 真的靠 ssh
chmod +x "$fx/liar.sh" "$fx/honest.sh"
fixture_denials="$(token_denials "$FIXTURE_TOKEN")"
# 這台機器上，下面那段證偽真的會跑到嗎？沒有任何 bin-* token 的命令存在（linux runner
# 就是這樣：沒有 xcodebuild）→ 證偽整章都會 declared-skip，自我檢驗守的是空氣。
# 那種情況下缺 ssh 只是「fixture 跑不動」，不該把整個 ops-ci-coverage 判紅——它同時是
# 分類 gate，而分類 gate 跟 ssh 一點關係都沒有。相反地，只要有任何一個 bin-* 相依真的
# 存在、證偽即將實跑，自我檢驗失效就是致命的，必須紅。
# 判準必須跟下面那段的 skip 條件**同一個函式**，不是「長得像」。兩處判準不一致的話，
# 這裡會宣告「證偽要跑了」而下面其實整段跳過——自我檢驗就白紅一場（reviewer 實測過
# 這個分岔：把本段改回只看存在，就會在兩個 group 都跳過的機器上硬紅）。
falsify_will_run=0
for e in "${EXCLUDED_GROUPS[@]}"; do
  rest="${e#*|}"; tok="${rest%%|*}"
  [[ "$tok" == bin-* ]] || continue
  [[ "${e%%|*}" == "ops-ci-coverage" ]] && continue   # 與下面的自指守衛對齊
  [[ "$(token_denials "$tok")" == "__UNKNOWN__" ]] && continue
  toolchain_usable "$tok" && falsify_will_run=1
done
if ! run_plain "$fx/honest.sh"; then
  if (( falsify_will_run == 0 )); then
    echo "  · self-test skipped: no [$fixture_denials] on this host, and no bin-* dependency exists here either — nothing to falsify" >&2
    ok "self-test declared-skipped (no falsification will run on this host)"
  else
    fail_t "this host cannot prove denial works: honest.sh fails even undenied (missing [$fixture_denials]?) — yet a real bin-* falsification is about to run, so every verdict below would be vacuous"
  fi
else
  ok "baseline: the ssh fixture passes when nothing is denied"
  if run_denied "$fixture_denials" "$fx/liar.sh"; then
    ok "a group that survives denial is detected (would be flagged)"
  else
    fail_t "falsifier reported a dependency for a script that never calls ssh — it would flag nothing"
  fi
  if run_denied "$fixture_denials" "$fx/honest.sh"; then
    fail_t "falsifier let a genuinely ssh-dependent script through as surviving — denial is not taking effect"
  else
    ok "a group that genuinely needs the binary still dies under denial"
  fi
fi
rm -rf "$fx"

# 已知未補的缺口，明寫出來而不是假裝有守：絕對路徑呼叫（ops/lib/ios_ops_logs.sh 的
# /usr/bin/log 就是一例）穿得過 PATH 遮蔽。先前這裡有一條 grep 守衛，但它掃的是
# ops/test_ops.sh——那只是 dispatcher，對任何 binary 都零命中，是一條寫著卻永遠不會響的
# 檢查，比沒有更危險。要補得掃出 group 的真實命令鏈，屬 IMP-0059。
section "no bin-* exclusion survives losing the binary it names"
for e in "${EXCLUDED_GROUPS[@]}"; do
  g="${e%%|*}"; rest="${e#*|}"; tok="${rest%%|*}"
  [[ "$tok" == bin-* ]] || continue
  # 自己不能證偽自己：下面是 `./ops/test_ops.sh "$g"`，$g 是本 group 就無限遞迴。
  # 今天走不到（ops-ci-coverage 在 LINUX_GROUPS 裡），但那是一個單字的距離。
  [[ "$g" == "ops-ci-coverage" ]] && { fail_t "$g cannot falsify itself — the falsifier would re-invoke this script forever"; continue; }
  denials="$(token_denials "$tok")"
  [[ "$denials" == "__UNKNOWN__" ]] && continue
  # 前提是工具鏈**整組都在且真的能用**，不是任一個名字 resolve 得到。這條實驗的第一腿
  # 是「未遮蔽必須綠」，而那只有在這台機器跑得動整組工具時才是公平的測試。少一件就不
  # 公平：group 會因為缺的那件而紅，而「未遮蔽卻紅」會把它讀成「group 壞了，先修好」。
  #
  # 兩次都不是假想，兩次都是實測打出來的：
  #   * GitHub 的 ubuntu runner **有 swift、沒有 xcodebuild**。舊版「任一個在就開跑」
  #     讓 ios-ops / lldb-forensics 在 CI 兩條都紅，還叫人去修兩個好好的 group。
  #   * 只裝 CLT 的 macOS（felix）四個名字**全都** resolve，`xcodebuild -version` 卻
  #     報 CLT-instance 錯。只看 command -v 的版本在那台會犯一模一樣的錯。
  # 半套工具鏈比完全沒有更會騙人：全都沒有時它至少誠實宣告跳過。
  if ! toolchain_usable "$tok"; then
    echo "  · $g: skipped — $TOOLCHAIN_WHY, so the undenied baseline cannot be a fair test here" >&2
    ok "$g: falsification skipped on this host (declared, not silently passed)"
    skipped=$((skipped+1))
    continue
  fi
  echo "  … $g: baseline run (undenied)…" >&2
  if ! run_plain ./ops/test_ops.sh "$g"; then
    # 「非零」不等於「因為被 deny 而非零」。少了這一腿，一個壞掉的 group 會被永久認證成
    # 合法排除、永遠不進 CI——IMP-0052 原封不動搬到上一層。
    fail_t "$g is already red WITHOUT denial, so its death proves nothing about '$tok' — fix the group first"
    continue
  fi
  echo "  … $g: falsifying (denying:$denials)…" >&2
  if run_denied "$denials" ./ops/test_ops.sh "$g"; then
    fail_t "$g claims '$tok' but passed with [$denials] denied — the reason is false; move it to LINUX_GROUPS or state the real dependency"
  else
    ok "$g passes undenied and dies without [$denials]"
  fi
done

echo ""
# skip 要有自己的計數器。它被記成 pass，所以「整段跳過」與「整段真的驗過」收尾行一模一樣，
# 而一次被繳械的跑，分數還會**比**一次抓到問題的跑高（reviewer 實測 14 passed 對 13 passed
# 1 failed）。CI 上這個數字現在是 2/2——linux 沒有 Xcode，兩條 bin-* 排除都跳過，
# **CI 實際證偽的排除數是 0**，唯一真的執行點是開發者本機的 macOS。IMP-0059 提的
# expected-fail CI step 因此比當初寫下時更值得做。
echo "ops-ci-coverage: $pass passed, $fail failed, $skipped falsification(s) skipped"
[[ "$fail" -eq 0 ]]
