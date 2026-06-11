#!/bin/bash
# 安裝 KG crash forensics 到 ~/.lldbinit（idempotent）。
# 之後所有 lldb session（含 Xcode debug session）自動載入 stop-hook：
# 真機/sim crash 時全量取證自動落 /tmp/kg_lldb_forensics/，agent 直接讀檔。
#
# 用法：ops/install_lldb_forensics.sh [--uninstall]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MODULE="$REPO/ops/lldb_crash_forensics.py"
INIT="$HOME/.lldbinit"
MARKER_BEGIN="# >>> kg-crash-forensics >>>"
MARKER_END="# <<< kg-crash-forensics <<<"

[ -f "$MODULE" ] || { echo "ERROR: module 不存在: $MODULE"; exit 1; }

remove_block() {
    [ -f "$INIT" ] || return 0
    if grep -qF "$MARKER_BEGIN" "$INIT"; then
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
