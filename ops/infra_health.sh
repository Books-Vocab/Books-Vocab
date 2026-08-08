#!/usr/bin/env bash
# infra_health.sh — KG 生產 host 層唯讀健康聚合器
# =============================================================================
# 補上 ops-cli 的觀測盲區：ops-cli 讀「業務資料庫」，本工具讀「機器本身」。
# 一次 SSH 收集 host 層指標 + 本地 openssl 探 TLS 憑證 + 本地 curl 探 HTTPS 端點
# （皆 client 真實視角），套閾值判 ok/warn/crit，吐人讀文字或 --json 機讀。
#
# 全唯讀（macOS-native 探針，prod = standby/felix = macOS+OrbStack+CF Tunnel）：
#   df / vm_stat+sysctl(記憶體/swap) / docker inspect / docker stats /
#   pgrep cloudflared(對外入口) / docker logs grep / du。
# 不改機器狀態（但仍經 safe wrapper 的 preflight）。
# 設計定案：macOS-native，不做 dual-OS 偵測（Lightsail 已 terminate）。若日後
#   再遷 Linux host 須補回 free/systemctl 分支或加 OS 偵測。
#
# 用法：
#   ./ops/infra_health.sh            # 人讀
#   ./ops/infra_health.sh --json     # 機讀（stdout 純 JSON，診斷走 stderr）
#
# JSON 契約：{"overall":"ok|warn|crit","domain":..,"metrics":[
#   {"key","label","value"(人讀字串),"raw"(數值或 null,供二次判斷),"status"}]}
# exit code：0=ok 1=warn 2=crit（供 cron/alert：`if ! cmd; then alert; fi`）
#
# 閾值可由 env 覆寫（cron 調靈敏度免改腳本）：
#   KG_HEALTH_DISK_WARN/CRIT  INODE_WARN/CRIT  MEM_WARN/CRIT
#   KG_HEALTH_CERT_WARN/CRIT  ERR_WARN/CRIT  SWAP_WARN/CRIT  RESTART_WARN
#
# Seam（測試用）：
#   KG_BASE                 取代 ./devops.sh（攔截 `run "<bundle>"`）
#   KG_HEALTH_CERT_ENDDATE  注入憑證 notAfter 字串，繞過 openssl
#   KG_HEALTH_HTTP_CODE     注入 HTTPS 探針 http_code，繞過 curl
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${KG_BASE:-$ROOT/devops.sh}"
DOMAIN="${KG_DOMAIN:-wordnexus.lol}"
PUBLIC_WEB_BASE_URL="${KG_PUBLIC_WEB_BASE_URL:-https://${DOMAIN}}"
CONTAINER="${KG_CONTAINER:-knowledge-graph-api}"
DATA_DIR="${KG_DATA_DIR:-/Users/chenliangyu/kg-data}"
PROBE_URL="${KG_HEALTH_PROBE_URL:-${PUBLIC_WEB_BASE_URL}/api/system/info}"

JSON=0
[[ "${1:-}" == "--json" ]] && JSON=1

# ── 閾值（env 可覆寫；單一真相）──────────────────────────────────────────────
DISK_WARN="${KG_HEALTH_DISK_WARN:-80}";   DISK_CRIT="${KG_HEALTH_DISK_CRIT:-90}"
INODE_WARN="${KG_HEALTH_INODE_WARN:-80}"; INODE_CRIT="${KG_HEALTH_INODE_CRIT:-90}"
MEM_WARN="${KG_HEALTH_MEM_WARN:-15}";     MEM_CRIT="${KG_HEALTH_MEM_CRIT:-8}"   # 可用%，低於告警
CERT_WARN="${KG_HEALTH_CERT_WARN:-14}";   CERT_CRIT="${KG_HEALTH_CERT_CRIT:-3}" # 剩餘天數
ERR_WARN="${KG_HEALTH_ERR_WARN:-20}";     ERR_CRIT="${KG_HEALTH_ERR_CRIT:-100}" # 近1h錯誤行
# swap 使用%。macOS 動態 swap + 壓縮記憶體：中度 swap 是常態（惰性換頁），swap-used
# 高 ≠ OOM 前兆（真實記憶體壓力看 mem_avail_pct）。故閾值比 Linux 寬鬆，swap 僅當粗略
# 旁證信號，避免 RAM 健康時假 crit。Linux 舊值 warn20/crit50 不適用 macOS。
SWAP_WARN="${KG_HEALTH_SWAP_WARN:-70}";   SWAP_CRIT="${KG_HEALTH_SWAP_CRIT:-90}"
RESTART_WARN="${KG_HEALTH_RESTART_WARN:-1}"

log() { echo "$@" >&2; }

# ── 1. host 層指標：單發 SSH 收集，吐 tab-separated key<TAB>value ───────────
# 全段為單引號字串（內含的 " 與 $(...) 皆原封送遠端執行，不在本地展開）。
REMOTE_BUNDLE='
set -e
C='"$CONTAINER"'
D='"$DATA_DIR"'
df -P / | awk "NR==2{gsub(/%/,\"\",\$5); printf \"disk_pct\t%s\n\", \$5; printf \"disk_used_gb\t%d\n\", \$3/1048576; printf \"disk_total_gb\t%d\n\", \$2/1048576}"
df -Pi / | awk "NR==2{gsub(/%/,\"\",\$5); printf \"inode_pct\t%s\n\", \$5}"
# macOS 記憶體：total=sysctl hw.memsize；available=(free+inactive+speculative 頁)×頁大小。
# 頁大小由 vm_stat header 動態讀（felix 為 16384，非 4096）。BSD awk 無 match() array，
# 故 header 用欄位掃描取「size N bytes」的 N。
TB=$(sysctl -n hw.memsize)
vm_stat | awk -v tb="$TB" "NR==1{for(i=1;i<=NF;i++)if(\$i==\"size\"){ps=\$(i+2);sub(/[^0-9].*/,\"\",ps)}} /Pages free/{gsub(/\./,\"\",\$3);f=\$3} /Pages inactive/{gsub(/\./,\"\",\$3);ia=\$3} /Pages speculative/{gsub(/\./,\"\",\$3);sp=\$3} END{printf \"mem_total_mb\t%d\n\",tb/1048576;printf \"mem_avail_mb\t%d\n\",(f+ia+sp)*ps/1048576}"
# macOS swap：vm.swapusage = "total = N.NNM  used = N.NNM  free = ..."；取 total/used 的 M 值。
sysctl -n vm.swapusage | awk "{for(i=1;i<=NF;i++){if(\$i==\"total\"){v=\$(i+2);gsub(/M/,\"\",v);t=v}if(\$i==\"used\"){v=\$(i+2);gsub(/M/,\"\",v);u=v}}printf \"swap_total_mb\t%d\n\",t;printf \"swap_used_mb\t%d\n\",u}"
docker inspect -f "container_health	{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}
container_status	{{.State.Status}}
container_restarts	{{.RestartCount}}" "$C" 2>/dev/null || printf "container_status\tmissing\n"
S=$(docker inspect -f "{{.State.StartedAt}}" "$C" 2>/dev/null || echo "")
# docker 的 State.StartedAt 是 **UTC**，故解析必須釘 TZ=UTC（與 :107 憑證解析同一寫法）。
# 少了它，BSD date -j -f 依本機時區解讀 → 秒數被灌水本機 UTC 偏移（CST 即 +8h），剛起來的
# 容器看起來已經跑了大半天——而 operator 最需要這條讀數的時刻正是部署後那幾分鐘
# （IMP-20260806-e4988a）。解析失敗亦不再代入 NOW 假裝成功（那會顯示 0，與「剛起來」無法
# 區分＝把壞掉的解析偽裝成健康讀數），改印獨立 key 讓下游判讀段出聲。
if [ -n "$S" ]; then NOW=$(date +%s); SP=${S%.*}; ST=$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%S" "$SP" +%s 2>/dev/null || echo ""); if [ -n "$ST" ]; then printf "container_uptime_s\t%s\n" "$(( NOW - ST ))"; else printf "container_uptime_parse\tfailed\n"; fi; fi
docker stats --no-stream --format "cpu_pct	{{.CPUPerc}}\nmem_pct	{{.MemPerc}}" "$C" 2>/dev/null | tr -d "%" || true
# 對外入口 = Cloudflare Tunnel 連接器（macOS 無 Caddy/systemctl）。
printf "ingress\t%s\n" "$(pgrep -f "cloudflared.*tunnel" >/dev/null 2>&1 && echo active || echo inactive)"
printf "log_errors_1h\t%s\n" "$(docker logs "$C" --since 1h 2>&1 | grep -ciE "error|exception|traceback|critical" || true)"
printf "data_dir_mb\t%s\n" "$(du -sm "$D" 2>/dev/null | cut -f1 || echo 0)"
'

log "[infra-health] 收集 host 指標 ($DOMAIN)…"
RAW="$("$BASE" run "$REMOTE_BUNDLE" 2>/dev/null || true)"

# bash 3.2（macOS 預設）無 associative array；用 awk 依 key 取值，取第一筆。
getm() { printf '%s\n' "$RAW" | awk -F'\t' -v k="$1" '$1==k{print $2; exit}'; }

# ── 2. TLS 憑證到期（本地 openssl 探 live endpoint = client 真實視角）──────
cert_enddate() {
  if [[ -n "${KG_HEALTH_CERT_ENDDATE:-}" ]]; then echo "$KG_HEALTH_CERT_ENDDATE"; return; fi
  echo | openssl s_client -connect "${DOMAIN}:443" -servername "$DOMAIN" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | sed 's/notAfter=//'
}
# macOS date：須 LC_ALL=C（locale 會讓 %b/%e 解析失敗）+ 分解 %T 成 %H:%M:%S
# （此版 BSD date 對 %T 挑剔），TZ=UTC 對應 openssl 輸出的 GMT。openssl notAfter
# 格式：「Sep 13 11:00:13 2026 GMT」（單/雙位日皆 %e 容納）。GNU date 分支留作後援。
to_epoch() { date -d "$1" +%s 2>/dev/null \
  || LC_ALL=C TZ=UTC date -j -f "%b %e %H:%M:%S %Y %Z" "$1" +%s 2>/dev/null \
  || echo ""; }
CERT_RAW="$(cert_enddate || true)"; CERT_DAYS=""
if [[ -n "$CERT_RAW" ]]; then
  ep="$(to_epoch "$CERT_RAW")"
  [[ -n "$ep" ]] && CERT_DAYS=$(( (ep - $(date +%s)) / 86400 ))
fi

# ── 3. HTTPS 端點探針（本地 curl，一次驗 DNS+TLS+Caddy+FastAPI）────────────
log "[infra-health] 探 HTTPS $PROBE_URL …"
if [[ -n "${KG_HEALTH_HTTP_CODE:-}" ]]; then
  HTTP_CODE="$KG_HEALTH_HTTP_CODE"
else
  HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$PROBE_URL" 2>/dev/null || echo 000)"
fi

# ── 4. 套閾值 → status ─────────────────────────────────────────────────────
# 每筆 = key|label|value(人讀)|status|raw(數值或空)
ROWS=(); overall="ok"
# 嚴重度只升不降：ok < unknown(→warn) < warn < crit。
# 「量不到」絕不等於「健康」——unknown 至少降到 warn，避免 SSH/探針失敗時假綠。
bump() { case "$1" in
  crit) overall="crit";;
  warn|unknown) [[ "$overall" == "ok" ]] && overall="warn";;
esac; return 0; }  # 必回 0：否則 && 短路時非零會在 set -e 下中斷呼叫端
add() { ROWS+=("$1|$2|$3|$4|${5:-}"); bump "$4"; }
th_high() { local v="$1" w="$2" c="$3"; [[ -z "$v" ]] && { echo unknown; return; }
  (( v >= c )) && { echo crit; return; }; (( v >= w )) && { echo warn; return; }; echo ok; }
th_low()  { local v="$1" w="$2" c="$3"; [[ -z "$v" ]] && { echo unknown; return; }
  (( v <= c )) && { echo crit; return; }; (( v <= w )) && { echo warn; return; }; echo ok; }

# Host 指標收集成功與否（降級守門）：container_status 一定會被遠端印出（含 "missing"），
# disk_pct 來自 df。兩者皆空 = SSH 整段沒回應（逾時/斷線）→ 所有 host 指標其實是「未知」，
# 此時直接判 crit，不讓底下一堆 "?" 靜默成 ok。本地探針（cert/http）仍照常評估。
if [[ -z "$(getm container_status)" && -z "$(getm disk_pct)" ]]; then
  add host_collect "Host 指標收集" "失敗（SSH 無回應）" crit ""
else
  add host_collect "Host 指標收集" "成功" ok ""
fi

disk="$(getm disk_pct)"
add disk_pct "磁碟使用率" "${disk:-?}%" "$(th_high "${disk:-}" $DISK_WARN $DISK_CRIT)" "$disk"
inode="$(getm inode_pct)"
add inode_pct "inode 使用率" "${inode:-?}%" "$(th_high "${inode:-}" $INODE_WARN $INODE_CRIT)" "$inode"

mt="$(getm mem_total_mb)"; ma="$(getm mem_avail_mb)"; mem_pct_avail=""
[[ -n "$mt" && -n "$ma" && "$mt" -gt 0 ]] && mem_pct_avail=$(( ma * 100 / mt ))
add mem_avail_pct "可用記憶體" "${ma:-?}MB / ${mt:-?}MB (${mem_pct_avail:-?}%)" "$(th_low "${mem_pct_avail:-}" $MEM_WARN $MEM_CRIT)" "$mem_pct_avail"

# Swap：用量高代表記憶體吃緊（OOM 前兆）
swt="$(getm swap_total_mb)"; swu="$(getm swap_used_mb)"; swap_pct=""
if [[ -n "$swt" && "$swt" -gt 0 ]]; then swap_pct=$(( swu * 100 / swt )); else swap_pct=0; fi
add swap_used_pct "Swap 使用率" "${swu:-?}MB / ${swt:-?}MB (${swap_pct}%)" "$(th_high "$swap_pct" $SWAP_WARN $SWAP_CRIT)" "$swap_pct"

# 容器健康
ch="$(getm container_health)"; ch="${ch:-none}"
cs="$(getm container_status)"; cs="${cs:-missing}"
cr="$(getm container_restarts)"; cr="${cr:-0}"
if [[ "$cs" == "missing" ]]; then add container "容器" "缺失" crit ""
elif [[ "$cs" != "running" ]]; then add container "容器" "$cs" crit ""
elif [[ "$ch" == "unhealthy" ]]; then add container "容器" "running/unhealthy" crit ""
elif [[ "$ch" == "starting" ]]; then add container "容器" "running/starting" warn ""
else add container "容器" "running/${ch}" ok ""; fi
rst="ok"; [[ "${cr:-0}" -ge "$RESTART_WARN" ]] && rst="warn"
add container_restarts "容器重啟次數" "$cr" "$rst" "$cr"

# 容器 uptime（資訊性；可佐證「重啟 0 次但剛起來」的判讀）
up="$(getm container_uptime_s)"
up_parse="$(getm container_uptime_parse)"
if [[ -n "$up" ]]; then
  if   (( up >= 86400 )); then upd="$(( up/86400 ))d $(( (up%86400)/3600 ))h"
  elif (( up >= 3600 ));  then upd="$(( up/3600 ))h $(( (up%3600)/60 ))m"
  else upd="$(( up/60 ))m"; fi
  add container_uptime "容器運行時長" "$upd" ok "$up"
elif [[ -n "$up_parse" ]]; then
  # StartedAt 解析失敗（docker 換格式 / date 行為變了）。判 warn 而非靜默略過：這條指標
  # 的存在理由是「重啟 0 次但剛起來」的判讀，量不到就等於那個判讀失去佐證，與本檔 :127
  # 「量不到絕不等於健康」同一原則。不 crit——它不 gate 任何東西，只是觀測性降級。
  add container_uptime "容器運行時長" "StartedAt 解析失敗" warn ""
fi

cpu="$(getm cpu_pct)"; add cpu "CPU" "${cpu:-?}%" ok "$cpu"
mp="$(getm mem_pct)";  add mem_pct "容器記憶體佔比" "${mp:-?}%" ok "$mp"

# Cloudflare Tunnel（對外入口）：active 才綠，否則 crit（公網打不進來）。
ing="$(getm ingress)"; ing="${ing:-unknown}"
ist="ok"; [[ "$ing" != "active" ]] && ist="crit"
add ingress "Cloudflare Tunnel" "$ing" "$ist" ""

# HTTPS 端點（200 才綠；其餘皆 crit —— client 真的打不到）
hst="crit"; [[ "$HTTP_CODE" == "200" ]] && hst="ok"
add http_probe "HTTPS 端點" "$HTTP_CODE" "$hst" "$HTTP_CODE"

# 近期錯誤
errs="$(getm log_errors_1h)"
add log_errors_1h "近1h log 錯誤行" "${errs:-?}" "$(th_high "${errs:-}" $ERR_WARN $ERR_CRIT)" "$errs"

# 憑證
add cert_days_left "TLS 憑證剩餘" "${CERT_DAYS:-?} 天" "$(th_low "${CERT_DAYS:-}" $CERT_WARN $CERT_CRIT)" "$CERT_DAYS"

ddir="$(getm data_dir_mb)"; add data_dir_mb "資料目錄大小" "${ddir:-?}MB" ok "$ddir"

# ── 5. 輸出 ────────────────────────────────────────────────────────────────
is_num() { [[ "$1" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; }
if [[ "$JSON" -eq 1 ]]; then
  printf '{"overall":"%s","domain":"%s","metrics":[' "$overall" "$DOMAIN"
  first=1
  for r in "${ROWS[@]}"; do
    IFS='|' read -r k label value status raw <<< "$r"
    [[ $first -eq 0 ]] && printf ','; first=0
    v_esc="${value//\\/\\\\}"; v_esc="${v_esc//\"/\\\"}"
    if is_num "$raw"; then raw_json="$raw"; else raw_json="null"; fi
    printf '{"key":"%s","label":"%s","value":"%s","raw":%s,"status":"%s"}' \
      "$k" "$label" "$v_esc" "$raw_json" "$status"
  done
  printf ']}\n'
else
  icon() { case "$1" in ok) echo "✓";; warn) echo "⚠";; crit) echo "✗";; *) echo "?";; esac; }
  echo ""; echo "══ KG 生產健康 ($DOMAIN) ══"
  for r in "${ROWS[@]}"; do
    IFS='|' read -r k label value status raw <<< "$r"
    printf "  %s  %-14s %s\n" "$(icon "$status")" "$label" "$value"
  done
  echo ""
  case "$overall" in
    ok)   echo "整體：✓ OK（全部正常）";;
    warn) echo "整體：⚠ WARN（有指標逼近門檻，需留意）";;
    crit) echo "整體：✗ CRIT（有指標越線，需立即處理）";;
  esac
fi

case "$overall" in ok) exit 0;; warn) exit 1;; crit) exit 2;; esac
