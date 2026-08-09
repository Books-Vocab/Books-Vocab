#!/usr/bin/env bash
# 在本機用 docker 重跑 `ops-suite` workflow 的三個 step。
#
# 為什麼需要這支：`LINUX_GROUPS`（`ops/tests/test_ops_ci_coverage.sh`）的成員資格是
# 一句**關於 linux 的斷言**，而開發機是 macOS。少了它，唯一的驗法是推上去等 CI——
# 於是 2026-08-04 有三個 group 被收進 CI 才被發現在 linux 必紅（IMP-0058）。
#
# 誠實邊界（不要拿它當「CI 一定綠」的證明）：
#   * 架構不同。本機多半是 arm64，GitHub runner 是 x86_64。
#   * 這裡是 ubuntu:24.04 + workflow 自己裝的套件；ubuntu-latest runner image 另外
#     預裝了數百個工具，**兩個方向都會咬人**：
#       - 這裡紅、CI 綠 → 那個 group 依賴一個 workflow 沒明講的預裝工具。修 workflow。
#       - 這裡綠、CI 紅 → runner 多裝的東西改變了行為。**實際發生過**：runner 有 swift
#         但沒有 xcodebuild，而證偽器的「未遮蔽 baseline」原本只要求任一命令存在就開跑，
#         於是 ios-ops / lldb-forensics 在 CI 兩條都紅。本機容器沒裝 swift，看不出來。
#     所以本腳本綠**不等於** CI 綠；它排除的是可在 linux 上重現的那一類問題。
#   * 網路可達性、runner 的 secrets、GITHUB_* env 都不在這裡。
#
# Usage:
#   ./ops/ci_linux_repro.sh              # 跑目前工作樹（含未 commit 的改動）
#   ./ops/ci_linux_repro.sh --head       # 只跑 HEAD，忽略未 commit 的改動
#   ./ops/ci_linux_repro.sh --keep       # 保留暫存 clone 與完整 log 供事後翻查
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WORKSPACE"

WF=".github/workflows/ops-suite.yml"
IMAGE="kg-ci-linux"
USE_HEAD=0
KEEP=0
for a in "$@"; do
  case "$a" in
    --head) USE_HEAD=1 ;;
    --keep) KEEP=1 ;;
    # 先判「還在註解區嗎」再做 sub——反過來的話 sub 已經把開頭的 # 拿掉，
    # 結束條件會在第一行就成立，help 只印得出一行（實測過）。
    -h|--help) awk '/^# Usage:/{f=1} f{if(!/^#/)exit; sub(/^# ?/,""); print}' "$0"; exit 0 ;;
    *) echo "unknown option: $a （--help 看用法）" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "需要 docker，未安裝" >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "docker daemon 沒在跑" >&2; exit 2; }

# 套件清單只有一份真相：workflow 自己的 apt-get 那行。手抄一份在這裡，
# 就是再造一次「兩個平面對同一件事各有意見」——本檔存在的理由正是那個病。
# 全部的 apt-get install 都收，不是只收第一行——拆成兩個 step 是很自然的編輯，
# 而「只讀第一行」會安靜地少裝東西，然後把結果當成 linux 的事實。
PKGS="$(grep -oE 'apt-get install -y [^&|]*' "$WF" | sed 's/apt-get install -y //' | tr -d '\r' | tr '\n' ' ' | xargs || true)"
[[ -n "$PKGS" ]] || { echo "解析不到 $WF 的 apt-get install 清單——探針壞了，不是 workflow" >&2; exit 2; }
echo "workflow 宣告要裝的套件：$PKGS"

TMP="$(mktemp -d)"
cleanup() { (( KEEP )) && echo "保留：$TMP" || rm -rf "$TMP"; }
trap cleanup EXIT

cat > "$TMP/Dockerfile" <<EOF
FROM ubuntu:24.04
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \\
      git curl ca-certificates $PKGS && rm -rf /var/lib/apt/lists/*
# runner 不是 root：root 讀得動 chmod 000 的檔，會讓「檔案不可讀」那類測試假綠。
RUN useradd -m -u $(id -u) runner
USER runner
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH=/home/runner/.local/bin:\$PATH
EOF

echo "── 建 image（第一次約 60s，之後走 layer cache）──"
docker build -q -t "$IMAGE" "$TMP" >/dev/null

# 全新 clone：直接掛工作樹會讓容器在裡面留下 root 產物（實測踩過：一次 root 跑留下的
# backend/.venv 讓後續非 root 跑冒出兩個假紅）。
echo "── 準備乾淨的 tree ──"
git clone -q --local --no-hardlinks "$WORKSPACE" "$TMP/repo"
git -C "$TMP/repo" checkout -q "$(git rev-parse HEAD)"
if (( ! USE_HEAD )) && ! git diff --quiet; then
  git diff > "$TMP/wt.patch"
  git -C "$TMP/repo" apply "$TMP/wt.patch"
  echo "已套用未 commit 的改動（--head 可跳過）"
fi

cat > "$TMP/run.sh" <<'EOF'
set -uo pipefail
cd /w
git config --global --add safe.directory /w
echo "whoami=$(whoami) uid=$(id -u) arch=$(uname -m) bash=${BASH_VERSION}"
echo "── step 1: assert every group is classified ──"
./ops/tests/test_ops_ci_coverage.sh; s1=$?
echo "STEP1_RC=$s1"
echo "── step 2: run platform-independent ops groups ──"
./ops/test_ops.sh $(./ops/tests/test_ops_ci_coverage.sh --print-linux-groups); s2=$?
echo "STEP2_RC=$s2"
echo "── step 3: falsify the exclusions (expected-fail) ──"
./ops/ci_expected_fail_exclusions.sh; s3=$?
echo "STEP3_RC=$s3"
(( s1 == 0 && s2 == 0 && s3 == 0 ))
EOF

echo "── 跑 workflow 的三個 step（約 10 分鐘）──"
rc=0
docker run --rm -v "$TMP/repo:/w" -v "$TMP/run.sh:/run.sh:ro" "$IMAGE" \
  bash /run.sh 2>&1 | tee "$TMP/full.log" || rc=$?

echo ""
echo "════════ ci_linux_repro ════════"
grep -E '^(STEP._RC|passed groups:|failed groups:|failed:|elapsed:)' "$TMP/full.log" || true
(( KEEP )) && echo "完整 log：$TMP/full.log"
exit "$rc"
