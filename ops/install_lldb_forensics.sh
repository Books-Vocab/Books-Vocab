#!/bin/bash
# 安裝 KG crash forensics 到 ~/.lldbinit（idempotent）。
# 之後所有 lldb session（含 Xcode debug session）自動載入 stop-hook：
# 真機/sim crash 時全量取證自動落 /tmp/kg_lldb_forensics/，agent 直接讀檔。
#
# 用法：ops/install_lldb_forensics.sh [--uninstall]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# ~/.lldbinit 是全機長壽設定：必須指向 main repo，不能指向 worktree
# （worktree 被 converge 清掉後，每個 lldb session 啟動都會報 import error）。
if COMMON_DIR="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    MAIN_ROOT="$(dirname "$COMMON_DIR")"
    [ -f "$MAIN_ROOT/ops/lldb_crash_forensics.py" ] && REPO="$MAIN_ROOT"
fi
MODULE="$REPO/ops/lldb_crash_forensics.py"
INIT="$HOME/.lldbinit"
MARKER_BEGIN="# >>> kg-crash-forensics >>>"
MARKER_END="# <<< kg-crash-forensics <<<"

[ -f "$MODULE" ] || { echo "ERROR: module 不存在: $MODULE"; exit 1; }

remove_block() {
    [ -f "$INIT" ] || return 0
    if grep -qF "$MARKER_BEGIN" "$INIT"; then
        # END marker 遺失時 awk 的 skip 永不復位，會把 BEGIN 之後的使用者
        # 設定全部靜默刪掉 —— 寧可中止要求人工處理。
        if ! grep -qF "$MARKER_END" "$INIT"; then
            echo "ERROR: $INIT 有 BEGIN marker 但無 END marker，拒絕自動改寫（請人工修復 marker block）"
            exit 1
        fi
        tmp="$(mktemp)"
        awk -v b="$MARKER_BEGIN" -v e="$MARKER_END" '
            $0 == b {skip=1; next}
            $0 == e {skip=0; next}
            !skip {print}
        ' "$INIT" > "$tmp"
        mv "$tmp" "$INIT"
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    remove_block
    echo "kg-crash-forensics 已自 $INIT 移除"
    exit 0
fi

remove_block
{
    echo "$MARKER_BEGIN"
    echo "command script import $MODULE"
    echo "$MARKER_END"
} >> "$INIT"

echo "已安裝到 $INIT："
echo "  command script import $MODULE"
echo "驗證：xcrun lldb -b -o quit 2>&1 | grep kg-forensics"
