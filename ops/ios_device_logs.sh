#!/bin/bash
# ios_device_logs.sh — 真機 runtime log / crash report 取證（pymobiledevice3 包裝）。
#
# 動機（2026-06-11 observability gap audit）：
# - `ios_ops.sh logs` 非 sim 路徑讀的是 Mac 本機 unified log（Catalyst 用），
#   真機 log 撈不到；debug 級訊息更是不持久化、事後必空。
# - Xcode debugger 不在場時 crash 落 .ips 在裝置上，過去無拉取管線
#   （devicectl 這版無 crash log surface；lldb 管線只蓋 debugger 在場的 crash）。
# 本工具固化 pymobiledevice3（經 uvx，免安裝）為單一入口。
#
# 用法：
#   ops/ios_device_logs.sh syslog [--proc <name>] [--duration <sec>] [--match <expr>] [--out <file>]
#                                                          # 真機 live log 串流（含 debug 級/stdout）
#   ops/ios_device_logs.sh collect [--out <dir>] [--age-limit <days>]
#                                                          # 拉 .logarchive（事後用 log show --archive 讀）
#   ops/ios_device_logs.sh crashes [--match <regex>]       # 列裝置上 .ips crash report
#   ops/ios_device_logs.sh pull-crashes [--out <dir>] [--match <regex>] [--parse]
#                                                          # 拉 .ips（預設只拉本 app），--parse 順手符號化
#   ops/ios_device_logs.sh parse <remote.ips>              # 直接解析裝置上單一 .ips
#
# 通用旗標：
#   --udid <udid>     多裝置時指定（預設 pymobiledevice3 自選唯一裝置）
#   --dry-run         只印命令不執行（測試用）
set -uo pipefail

DEFAULT_PROC="BooksAndVocab"
UDID=""
DRY_RUN=0

usage() { sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'; }

run_cmd() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "DRY-RUN: $*"
        return 0
    fi
    "$@"
}

cmd_syslog() {
    local proc="$DEFAULT_PROC" duration=30 out="" match=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --proc) proc="$2"; shift 2 ;;
            --duration) duration="$2"; shift 2 ;;
            --match) match="$2"; shift 2 ;;
            --out) out="$2"; shift 2 ;;
            *) echo "ERROR: syslog 不認得參數 $1" >&2; return 64 ;;
        esac
    done
    case "$duration" in
        ''|*[!0-9]*) echo "ERROR: --duration 需要非負整數秒數，收到 '$duration'" >&2; return 64 ;;
    esac
    local args=(syslog live -pn "$proc")
    [ -n "$match" ] && args+=(-m "$match")
    [ -n "$out" ] && args+=(-o "$out")
    [ -n "$UDID" ] && args+=(--udid "$UDID")
    if [ "$duration" -gt 0 ]; then
        # timeout 到點屬正常收束（exit 124 不視為失敗）
        run_cmd timeout "$duration" uvx pymobiledevice3 "${args[@]}"
        local rc=$?
        [ "$rc" -eq 124 ] && rc=0
        return "$rc"
    fi
    run_cmd uvx pymobiledevice3 "${args[@]}"
}

cmd_collect() {
    local out="/tmp/kg_device_logarchive" age=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --out) out="$2"; shift 2 ;;
            --age-limit) age="$2"; shift 2 ;;
            *) echo "ERROR: collect 不認得參數 $1" >&2; return 64 ;;
        esac
    done
    # pymobiledevice3 把 archive 內容直接攤進給定目錄（目錄本身就是 bundle）；
    # 沒有 .logarchive 副檔名時 log show / Console.app 一律拒讀
    out="${out%/}"
    case "$out" in *.logarchive) ;; *) out="$out.logarchive" ;; esac
    [ "$DRY_RUN" = "1" ] || mkdir -p "$out"
    local args=(syslog collect "$out")
    [ -n "$age" ] && args+=(--age-limit "$age")
    [ -n "$UDID" ] && args+=(--udid "$UDID")
    run_cmd uvx pymobiledevice3 "${args[@]}" || return 1
    [ "$DRY_RUN" = "1" ] && return 0
    echo "logarchive 已拉到 $out；讀法（log 是 zsh builtin，必須用絕對路徑）："
    echo "  /usr/bin/log show --archive $out --predicate 'process == \"BooksAndVocab\"' --info --debug --last 1h"
}

cmd_crashes() {
    local match=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --match) match="$2"; shift 2 ;;
            *) echo "ERROR: crashes 不認得參數 $1" >&2; return 64 ;;
        esac
    done
    # depth 2：iOS 會把已讀取的 .ips retire 進 /Retired/，depth 1 會誤判「沒有 crash」
    local args=(crash ls -d 2)
    [ -n "$UDID" ] && args+=(--udid "$UDID")
    # --match 為本地 grep 後處理（crash ls 無 server-side 過濾）；
    # 注意真跑時「無匹配」與「工具失敗」共用非零 exit。
    if [ -n "$match" ] && [ "$DRY_RUN" != "1" ]; then
        run_cmd uvx pymobiledevice3 "${args[@]}" | grep -E "$match"
    else
        run_cmd uvx pymobiledevice3 "${args[@]}"
    fi
}

cmd_pull_crashes() {
    local out="/tmp/kg_device_crashes" match="$DEFAULT_PROC" do_parse=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --out) out="$2"; shift 2 ;;
            --match) match="$2"; shift 2 ;;
            --parse) do_parse=1; shift ;;
            *) echo "ERROR: pull-crashes 不認得參數 $1" >&2; return 64 ;;
        esac
    done
    [ "$DRY_RUN" = "1" ] || mkdir -p "$out"
    # pull/parse-latest 的 enumerate 都不遞迴：新鮮 crash 在 top-level，
    # 已讀過的會被 iOS retire 進 /Retired/，兩處都要掃。
    local args=(crash pull "$out" --match "$match")
    [ -n "$UDID" ] && args+=(--udid "$UDID")
    run_cmd uvx pymobiledevice3 "${args[@]}" || return 1
    local retired_args=(crash pull "$out" --remote-file /Retired --match "$match")
    [ -n "$UDID" ] && retired_args+=(--udid "$UDID")
    run_cmd uvx pymobiledevice3 "${retired_args[@]}" \
        || echo "WARN: /Retired 拉取失敗（無 retired report 屬正常；若上方有連線錯誤則需重查）" >&2
    if [ "$do_parse" = "1" ]; then
        # parse-latest 是 remote afc 操作（吃裝置路徑不吃本地目錄），用 --match 對齊；
        # top-level 無匹配時 fallback /Retired
        local parse_args=(crash parse-latest --match "$match")
        [ -n "$UDID" ] && parse_args+=(--udid "$UDID")
        if ! run_cmd uvx pymobiledevice3 "${parse_args[@]}"; then
            local parse_retired=(crash parse-latest /Retired --match "$match")
            [ -n "$UDID" ] && parse_retired+=(--udid "$UDID")
            run_cmd uvx pymobiledevice3 "${parse_retired[@]}" || return 1
        fi
    fi
    [ "$DRY_RUN" = "1" ] && return 0
    echo "crash report 已拉到 $out（match=$match）"
    ls -la "$out" 2>/dev/null || true
}

cmd_parse() {
    [ $# -ge 1 ] || { echo "ERROR: parse 需要 <remote.ips>" >&2; return 64; }
    local remote="$1"; shift
    [ $# -eq 0 ] || { echo "ERROR: parse 不認得參數 $1" >&2; return 64; }
    local args=(crash parse "$remote")
    [ -n "$UDID" ] && args+=(--udid "$UDID")
    run_cmd uvx pymobiledevice3 "${args[@]}"
}

# --- main ---
[ $# -ge 1 ] || { usage; exit 64; }
SUBCMD="$1"; shift

# 全域旗標可放子命令後（簡化呼叫），先抽出
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --udid) UDID="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

case "$SUBCMD" in
    syslog)       cmd_syslog "${ARGS[@]+"${ARGS[@]}"}" ;;
    collect)      cmd_collect "${ARGS[@]+"${ARGS[@]}"}" ;;
    crashes)      cmd_crashes "${ARGS[@]+"${ARGS[@]}"}" ;;
    pull-crashes) cmd_pull_crashes "${ARGS[@]+"${ARGS[@]}"}" ;;
    parse)        cmd_parse "${ARGS[@]+"${ARGS[@]}"}" ;;
    -h|--help|help) usage ;;
    *) echo "ERROR: 未知子命令 $SUBCMD"; usage; exit 64 ;;
esac
