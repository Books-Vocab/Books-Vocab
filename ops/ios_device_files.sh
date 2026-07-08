#!/bin/bash
# ios_device_files.sh — 真機 app 容器檔案取證（devicectl 包裝）。
#
# 動機（2026-06-11 書庫消失調查）：devicectl 原生介面摩擦大 ——
# `info files` 用 --username、`copy from` 用 --user（旗標不一致）、每次輸出夾
# provisioning 噪音、SwiftData store 三件套（.store/.store-shm/.store-wal）要
# 手動迴圈拉。本工具固化為單一入口。
#
# 用法：
#   ops/ios_device_files.sh list [--sub <subdir>]          # 列容器檔案
#   ops/ios_device_files.sh pull <remote-path> [local]     # 拉單檔
#   ops/ios_device_files.sh pull-store [--out <dir>]       # 拉 CloudStore+LocalStore 三件套
#   ops/ios_device_files.sh devices                        # 列出 connected 裝置
#
# 通用旗標：
#   --device <coredevice-id>   預設自動選唯一 connected 裝置（sim 模式 = sim udid，預設 booted）
#   --app <bundle-id>          預設 com.Max0228.BooksBrowser
#   --simulator                改查 simulator 容器（simctl get_app_container + 本地 ls/cp）
#   --dry-run                  只印 devicectl/simctl 命令不執行（測試用）
set -uo pipefail

DEFAULT_APP="com.Max0228.BooksBrowser"
APP="$DEFAULT_APP"
DEVICE=""
SIMULATOR=0
DRY_RUN=0

usage() { sed -n '3,19p' "$0" | sed 's/^# \{0,1\}//'; }

resolve_device() {
    [ -n "$DEVICE" ] && return 0
    local rows
    rows="$(xcrun devicectl list devices 2>/dev/null | awk 'NR>2 && / connected /')"
    local count
    count="$(printf '%s' "$rows" | grep -c . || true)"
    if [ "$count" -eq 0 ]; then
        echo "ERROR: 無 connected 裝置（xcrun devicectl list devices）" >&2
        return 1
    fi
    if [ "$count" -gt 1 ]; then
        echo "ERROR: 多台 connected 裝置，請用 --device 指定：" >&2
        printf '%s\n' "$rows" >&2
        return 1
    fi
    # Identifier 欄為第一個 UUID 樣式 token（裝置名可能含空白，不能按欄位數抓）
    DEVICE="$(printf '%s' "$rows" | grep -oE '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}' | head -1)"
    [ -n "$DEVICE" ] || { echo "ERROR: 無法從 devicectl 輸出解析裝置 id" >&2; return 1; }
}

run_devicectl() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "DRY-RUN: xcrun devicectl $*"
        return 0
    fi
    # devicectl 把 provisioning 噪音與進度印在 stderr/stdout 混流；保留 stdout
    # 表格，濾掉已知噪音行。
    xcrun devicectl "$@" 2>&1 | grep -vE "provisioning paramter|devicectl manage create|Acquired tunnel|Enabling developer disk|Acquired usage assertion"
}

# sim 模式：解析 app data 容器路徑到 ${CONTAINER}（dry-run 用 <container> 佔位，離線可測）
sim_container() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "DRY-RUN: xcrun simctl get_app_container ${DEVICE:-booted} $APP data"
        CONTAINER="<container>"
        return 0
    fi
    CONTAINER="$(xcrun simctl get_app_container "${DEVICE:-booted}" "$APP" data)" || {
        echo "ERROR: simctl get_app_container 失敗（sim 未開機或 app 未安裝？）" >&2
        return 1
    }
}

run_local() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "DRY-RUN: $*"
        return 0
    fi
    "$@"
}

cmd_devices() {
    if [ "$SIMULATOR" = "1" ]; then
        xcrun simctl list devices booted
        return
    fi
    xcrun devicectl list devices 2>/dev/null | awk 'NR<=2 || / connected /'
}

cmd_list() {
    local sub=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --sub) sub="$2"; shift 2 ;;
            *) echo "ERROR: list 不認得參數 $1" >&2; return 64 ;;
        esac
    done
    if [ "$SIMULATOR" = "1" ]; then
        sim_container || return 1
        if [ -n "$sub" ]; then
            run_local ls -la "$CONTAINER/$sub"
        else
            run_local ls -la "$CONTAINER"
        fi
        return
    fi
    resolve_device || return 1
    # 注意：info files 的使用者旗標是 --username（copy from 是 --user）
    if [ -n "$sub" ]; then
        run_devicectl device info files --device "$DEVICE" --username mobile \
            --domain-type appDataContainer --domain-identifier "$APP" --subdirectory "$sub"
    else
        run_devicectl device info files --device "$DEVICE" --username mobile \
            --domain-type appDataContainer --domain-identifier "$APP"
    fi
}

cmd_pull() {
    [ $# -ge 1 ] || { echo "ERROR: pull 需要 <remote-path>" >&2; return 64; }
    local remote="$1"
    local local_path="${2:-$(basename "$remote")}"
    if [ "$SIMULATOR" = "1" ]; then
        sim_container || return 1
        run_local cp "$CONTAINER/$remote" "$local_path"
        return
    fi
    resolve_device || return 1
    run_devicectl device copy from --device "$DEVICE" --user mobile \
        --domain-type appDataContainer --domain-identifier "$APP" \
        --source "$remote" --destination "$local_path"
}

cmd_pull_store() {
    local out="/tmp/kg_device_store"
    while [ $# -gt 0 ]; do
        case "$1" in
            --out) out="$2"; shift 2 ;;
            *) echo "ERROR: pull-store 不認得參數 $1" >&2; return 64 ;;
        esac
    done
    local failed=0
    if [ "$SIMULATOR" = "1" ]; then
        sim_container || return 1
        [ "$DRY_RUN" = "1" ] || mkdir -p "$out"
        for store in CloudStore.store LocalStore.store; do
            for suffix in "" "-shm" "-wal"; do
                local f="$store$suffix"
                if ! run_local cp "$CONTAINER/Library/Application Support/$f" "$out/$f"; then
                    echo "WARN: 拉取失敗 ${f}（store 可能無 wal/shm，屬正常）" >&2
                    failed=$((failed+1))
                fi
            done
        done
        echo "store 三件套已拉到 ${out}（失敗 $failed 個，wal/shm 缺檔屬正常）"
        [ "$DRY_RUN" = "1" ] || ls -la "$out"
        return 0
    fi
    resolve_device || return 1
    mkdir -p "$out"
    for store in CloudStore.store LocalStore.store; do
        for suffix in "" "-shm" "-wal"; do
            local f="$store$suffix"
            if ! run_devicectl device copy from --device "$DEVICE" --user mobile \
                --domain-type appDataContainer --domain-identifier "$APP" \
                --source "Library/Application Support/$f" --destination "$out/$f"; then
                echo "WARN: 拉取失敗 ${f}（store 可能無 wal/shm，屬正常）" >&2
                failed=$((failed+1))
            fi
        done
    done
    echo "store 三件套已拉到 ${out}（失敗 $failed 個，wal/shm 缺檔屬正常）"
    ls -la "$out"
}

# --- main ---
[ $# -ge 1 ] || { usage; exit 64; }
SUBCMD="$1"; shift

# 全域旗標可放子命令後（簡化呼叫），先抽出
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --device) DEVICE="$2"; shift 2 ;;
        --app) APP="$2"; shift 2 ;;
        --simulator) SIMULATOR=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

case "$SUBCMD" in
    devices)    cmd_devices ;;
    list)       cmd_list "${ARGS[@]+"${ARGS[@]}"}" ;;
    pull)       cmd_pull "${ARGS[@]+"${ARGS[@]}"}" ;;
    pull-store) cmd_pull_store "${ARGS[@]+"${ARGS[@]}"}" ;;
    -h|--help|help) usage ;;
    *) echo "ERROR: 未知子命令 $SUBCMD"; usage; exit 64 ;;
esac
