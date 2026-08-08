#!/usr/bin/env bash
# test_infra_health.sh — infra_health.sh 結構與行為驗證（離線，靠 seam 注入）
#
# Seam:
#   KG_BASE                  指向 stub，取代 ./devops.sh，攔截 `run "<bundle>"`，吐 canned 指標
#   KG_HEALTH_CERT_ENDDATE   注入憑證 notAfter（繞過 openssl 網路呼叫）
#   KG_HEALTH_HTTP_CODE      注入 HTTPS 探針 http_code（繞過 curl）
#
# 注意：stub 直接吐 canned tab 指標（忽略 REMOTE_BUNDLE），故 macOS-native 探針
#   （vm_stat/sysctl 記憶體·swap、cloudflared ingress）的真實解析行為無法在此 stub
#   行使，須靠 standby 實機 `health --json` 驗證（見 receipt）。
#   **例外：StartedAt 的 uptime 計算已有覆蓋**，走的是第二條 seam——把 REMOTE_BUNDLE
#   裡那一行原封抽出來直接 eval（見「Uptime：StartedAt 是 UTC」段），繞過 stub。要為
#   其餘 bundle 內的解析補真實覆蓋，照抄那個模式即可，不必再擴充 stub。
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$WORKSPACE/ops/infra_health.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }
py() { python3 -c "$@"; }  # 純測試斷言用（非 backend env）

# stub：吃 `run "<bundle>"`，無視 bundle，吐固定 tab-separated 指標
STUB="$(mktemp)"
cat >"$STUB" <<'EOF'
#!/usr/bin/env bash
[ -n "${KG_TEST_EMPTY:-}" ] && exit 0   # 模擬 SSH 逾時：完全無輸出
printf 'disk_pct\t%s\n' "${KG_TEST_DISK:-27}"
printf 'disk_used_gb\t16\n'; printf 'disk_total_gb\t58\n'; printf 'inode_pct\t3\n'
printf 'mem_total_mb\t1896\n'; printf 'mem_avail_mb\t%s\n' "${KG_TEST_MEM_AVAIL:-900}"
printf 'swap_total_mb\t%s\n' "${KG_TEST_SWAP_TOTAL:-2048}"
printf 'swap_used_mb\t%s\n' "${KG_TEST_SWAP_USED:-100}"
printf 'container_health\t%s\n' "${KG_TEST_HEALTH:-healthy}"
printf 'container_status\trunning\n'
printf 'container_restarts\t%s\n' "${KG_TEST_RESTARTS:-0}"
if [ -n "${KG_TEST_UPTIME_PARSE_FAIL:-}" ]; then
  printf 'container_uptime_parse\tfailed\n'
else
  printf 'container_uptime_s\t%s\n' "${KG_TEST_UPTIME:-93600}"
fi
printf 'cpu_pct\t4.2\n'; printf 'mem_pct\t38.0\n'
printf 'ingress\t%s\n' "${KG_TEST_INGRESS:-active}"
printf 'log_errors_1h\t%s\n' "${KG_TEST_ERRS:-0}"
printf 'data_dir_mb\t393\n'
EOF
chmod +x "$STUB"

# 假 date：**只**攔「取現在時刻」(`date +%s`)，給 uptime 算式一個可注入的時間源，讓
# 期望值是常數而非「執行當下算出來的東西」。解析呼叫（`date -j -f …`）一律 exec 回真
# date——那正是受測邏輯，替身接手就等於把待測的失效模式從模型裡刪掉。
FAKEBIN="$(mktemp -d)"
cat >"$FAKEBIN/date" <<'EOF'
#!/usr/bin/env bash
if [[ "$#" -eq 1 && "$1" == "+%s" ]]; then
  printf '%s\n' "${KG_TEST_FAKE_NOW:?fake date 被呼叫但 KG_TEST_FAKE_NOW 未設}"; exit 0
fi
exec /bin/date "$@"
EOF
chmod +x "$FAKEBIN/date"
trap 'rm -f "$STUB"; rm -rf "$FAKEBIN"' EXIT

# openssl notAfter 一律英文月名（如 "Sep 13 .. 2026 GMT"）；fixture 須 LC_ALL=C
# 才不會被系統 locale 換成本地月名（如 "7月"），否則無法行使真實解析路徑。
FUTURE_CERT="$(LC_ALL=C date -u -v+30d '+%b %e %T %Y GMT' 2>/dev/null || LC_ALL=C date -u -d '+30 days' '+%b %e %T %Y GMT')"

run_health() {  # 預設健康全綠的環境
  KG_BASE="$STUB" KG_HEALTH_CERT_ENDDATE="${KG_HEALTH_CERT_ENDDATE:-$FUTURE_CERT}" \
  KG_HEALTH_HTTP_CODE="${KG_HEALTH_HTTP_CODE:-200}" \
    bash "$SCRIPT" "$@"
}

section "Syntax"
bash -n "$SCRIPT" && ok "infra_health syntax" || fail_t "infra_health syntax"

section "Text mode：健康全綠"
out="$(run_health 2>&1 || true)"
echo "$out" | grep -q "OK" && ok "text 含整體 OK" || fail_t "text 無整體 OK"
echo "$out" | grep -q "27%" && ok "text 顯示磁碟 27%" || fail_t "text 無磁碟值"
echo "$out" | grep -q "HTTPS 端點" && ok "text 含 HTTPS 探針" || fail_t "text 無 HTTPS 探針"

section "JSON mode：結構契約 + overall=ok"
js="$(run_health --json 2>/dev/null || true)"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);assert "overall" in d and isinstance(d["metrics"],list)' \
  && ok "JSON overall + metrics[]" || fail_t "JSON 結構不符"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);assert d["overall"]=="ok",d["overall"]' \
  && ok "全綠 overall=ok" || fail_t "全綠 overall 非 ok"

section "JSON：raw 數值欄（B agent 回饋）"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);m={x["key"]:x for x in d["metrics"]};assert m["disk_pct"]["raw"]==27,m["disk_pct"];assert isinstance(m["disk_pct"]["raw"],(int,float))' \
  && ok "disk_pct.raw 為純數值 27" || fail_t "disk_pct.raw 非數值"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);m={x["key"]:x for x in d["metrics"]};assert m["ingress"]["raw"] is None,m["ingress"]' \
  && ok "非數值 metric raw=null" || fail_t "ingress.raw 非 null"

section "Cloudflare Tunnel ingress：active → ok"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);g=[m for m in d["metrics"] if m["key"]=="ingress"][0];assert g["status"]=="ok" and g["value"]=="active",g' \
  && ok "ingress active → ok" || fail_t "ingress active 未 ok"

section "Cloudflare Tunnel ingress：inactive → crit"
echo "$(KG_TEST_INGRESS=inactive run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);g=[m for m in d["metrics"] if m["key"]=="ingress"][0];assert g["status"]=="crit",g;assert d["overall"]=="crit",d["overall"]' \
  && ok "ingress inactive → crit" || fail_t "ingress inactive 未 crit"

section "閾值：磁碟 92% → crit"
echo "$(KG_TEST_DISK=92 run_health --json 2>/dev/null)" | py 'import sys,json;assert json.load(sys.stdin)["overall"]=="crit"' \
  && ok "磁碟 92% crit" || fail_t "磁碟 92% 未 crit"

section "閾值：容器 unhealthy → crit"
echo "$(KG_TEST_HEALTH=unhealthy run_health --json 2>/dev/null)" | py 'import sys,json;assert json.load(sys.stdin)["overall"]=="crit"' \
  && ok "容器 unhealthy crit" || fail_t "容器 unhealthy 未 crit"

section "閾值：憑證 2 天 → crit"
SOON="$(LC_ALL=C date -u -v+2d '+%b %e %T %Y GMT' 2>/dev/null || LC_ALL=C date -u -d '+2 days' '+%b %e %T %Y GMT')"
echo "$(KG_HEALTH_CERT_ENDDATE="$SOON" run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);c=[m for m in d["metrics"] if m["key"]=="cert_days_left"][0];assert c["status"]=="crit",c' \
  && ok "憑證 2 天 crit" || fail_t "憑證 2 天 未 crit"

section "HTTPS 探針：503 → crit"
echo "$(KG_HEALTH_HTTP_CODE=503 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);h=[m for m in d["metrics"] if m["key"]=="http_probe"][0];assert h["status"]=="crit",h;assert d["overall"]=="crit"' \
  && ok "HTTPS 503 crit" || fail_t "HTTPS 503 未 crit"

section "HTTPS 探針：200 → ok + raw=200"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);h=[m for m in d["metrics"] if m["key"]=="http_probe"][0];assert h["status"]=="ok" and h["raw"]==200,h' \
  && ok "HTTPS 200 ok + raw=200" || fail_t "HTTPS 200 未 ok"

section "Swap：使用 63% → ok（macOS 門檻 warn70/crit90；中度 swap 為常態）"
echo "$(KG_TEST_SWAP_USED=1300 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);s=[m for m in d["metrics"] if m["key"]=="swap_used_pct"][0];assert s["status"]=="ok",s' \
  && ok "swap 63% ok" || fail_t "swap 63% 未 ok"
section "Swap：使用 78% → warn（門檻 warn70/crit90）"
echo "$(KG_TEST_SWAP_USED=1600 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);s=[m for m in d["metrics"] if m["key"]=="swap_used_pct"][0];assert s["status"]=="warn",s' \
  && ok "swap 78% warn" || fail_t "swap 78% 未 warn"
section "Swap：使用 93% → crit"
echo "$(KG_TEST_SWAP_USED=1900 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);s=[m for m in d["metrics"] if m["key"]=="swap_used_pct"][0];assert s["status"]=="crit",s' \
  && ok "swap 93% crit" || fail_t "swap 93% 未 crit"

section "Uptime：93600s → 1d 2h + raw 秒數"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);u=[m for m in d["metrics"] if m["key"]=="container_uptime"][0];assert u["raw"]==93600,u;assert "1d" in u["value"] and "2h" in u["value"],u' \
  && ok "uptime 1d 2h + raw=93600" || fail_t "uptime 格式/raw 不符"

section "Uptime：StartedAt 是 UTC，本機時區不得改變秒數"
# 這幾條斷言碰到的字串**由 ops/infra_health.sh 自己產生**：從 REMOTE_BUNDLE 把那一行原封
# 抽出來 eval（與 backlog acceptance 同一個抽法），不是在測試裡另寫一份等價算式（那只會
# 證明測試自己會算術）。抽錯行的話斷言會被一個不相干的字串滿足，故先立 provenance 守衛。
UPLINE_NO="$(grep -n 'container_uptime_s' "$SCRIPT" | head -1 | cut -d: -f1)"
UPSNIP="$(sed -n "${UPLINE_NO}p" "$SCRIPT")"
# 守衛要求同一行**同時**具備「日期解析」與「印出 uptime key」兩個特徵。只認前者的話，
# 一句同時提到這兩個 token 的註解就能通過守衛（實測過），守衛就只是裝飾——真正擋住誘餌的
# 會變成下游那幾條值斷言，而那不是守衛存在的理由。
# 日期解析認 `date -j -f` 與 `date -u -j -f` 兩種寫法：ticket 的 plan 兩種都認可，只綁
# 其中一種會讓「另一個正確實作」變成一條指著錯誤原因的假紅。
if printf '%s' "$UPSNIP" | grep -qE 'date (-u )?-j -f' \
   && printf '%s' "$UPSNIP" | grep -qF 'printf "container_uptime_s'; then
  ok "抽到的是 uptime 計算行（provenance 守衛，行號 $UPLINE_NO）"
else
  fail_t "抽到的不是 uptime 計算行（行號 $UPLINE_NO）：$UPSNIP"
fi

# StartedAt 與 NOW 都釘死 → 期望值是常數 90，不隨執行時刻漂移，也不靠「兩邊一致」蒙混
# （兩邊同時錯成 0 也會一致；故三條斷言各自釘絕對值）。
# 用**生產形狀**的字串（docker 的 StartedAt 帶奈秒），否則 `${S%.*}` 的剝除是 no-op、
# 那條路徑從未被行使，而尾隨的 Z 只是靠 BSD date 的「忽略多餘字元」容忍度矇混過去。
STARTED_AT="2026-08-06T03:40:51.123456789Z"   # State.StartedAt 語意為 UTC；epoch 1785987651
FAKE_NOW=1785987741                 # = StartedAt + 90s
eval_upsnip() {  # $1 = TZ
  ( export PATH="$FAKEBIN:$PATH" KG_TEST_FAKE_NOW="$FAKE_NOW" TZ="$1" S="$STARTED_AT"
    eval "$UPSNIP" ) 2>/dev/null | cut -f2
}
UP_UTC="$(eval_upsnip UTC || true)"
UP_TPE="$(eval_upsnip Asia/Taipei || true)"
[[ "$UP_UTC" == "90" ]] && ok "TZ=UTC 下 uptime=90s" \
  || fail_t "TZ=UTC 下 uptime=${UP_UTC:-<空>}，期望 90"
[[ "$UP_TPE" == "90" ]] && ok "TZ=Asia/Taipei 下 uptime 同為 90s（時區不污染）" \
  || fail_t "TZ=Asia/Taipei 下 uptime=${UP_TPE:-<空>}，期望 90（差 28800 = 把 UTC 時戳當本地時間讀）"

section "Uptime：StartedAt 解析失敗 → 不得靜默消失"
# 舊 fallback 代入 NOW → uptime 顯示 0，與「容器剛起來」長得一模一樣：一個解析壞掉被
# 偽裝成一個健康讀數。
#
# **兩端各釘一次，producer 端不可省**：stub 是直接偽造 container_uptime_parse 這個 key
# 的，注入的是失效的**結果**而不是失效本身。只釘消費端的話，把 bundle 那行的
# `|| echo ""` 改回 `|| echo "$NOW"`（＝把整個 bug 放回去）測試照樣全綠——實測過。
# 這正是本檔 TZ 段自己寫下的判準（替身接手＝把待測的失效模式從模型裡刪掉），這裡補上。
UP_BAD="$( ( export PATH="$FAKEBIN:$PATH" KG_TEST_FAKE_NOW="$FAKE_NOW" TZ=UTC S="not-a-timestamp"
             eval "$UPSNIP" ) 2>/dev/null || true )"
[[ "$UP_BAD" == "container_uptime_parse"$'\t'"failed" ]] \
  && ok "producer：StartedAt 真解析不了時，bundle 印出 container_uptime_parse" \
  || fail_t "producer：解析失敗未留痕跡（實得：${UP_BAD:-<空>}）"
# consumer：key 送達後不得被判讀段吞掉
echo "$(KG_TEST_UPTIME_PARSE_FAIL=1 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);u=[m for m in d["metrics"] if m["key"]=="container_uptime"];assert u,"container_uptime metric 整個不見了（靜默降級）";assert u[0]["status"]!="ok",u[0];assert d["overall"]!="ok",d["overall"]' \
  && ok "uptime 解析失敗 → metric 仍在且非 ok" || fail_t "uptime 解析失敗被靜默吞掉"

section "閾值 env 覆寫：磁碟 70% + DISK_WARN=65 → warn"
echo "$(KG_TEST_DISK=70 KG_HEALTH_DISK_WARN=65 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);assert d["overall"]=="warn",d["overall"]' \
  && ok "env 覆寫 DISK_WARN 生效" || fail_t "env 覆寫 DISK_WARN 無效"

section "閾值：容器重啟 3 次 → warn"
echo "$(KG_TEST_RESTARTS=3 run_health --json 2>/dev/null)" | py 'import sys,json;d=json.load(sys.stdin);r=[m for m in d["metrics"] if m["key"]=="container_restarts"][0];assert r["status"]=="warn" and d["overall"]=="warn",r' \
  && ok "重啟 3 次 warn" || fail_t "重啟 3 次 未 warn"

section "降級：SSH 收集失敗（空 RAW）→ host_collect crit + overall crit"
js="$(KG_TEST_EMPTY=1 run_health --json 2>/dev/null || true)"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);h=[m for m in d["metrics"] if m["key"]=="host_collect"][0];assert h["status"]=="crit",h;assert d["overall"]=="crit",d["overall"]' \
  && ok "空 RAW → crit（不假綠）" || fail_t "空 RAW 未判 crit"

section "降級：憑證量不到（openssl 失敗）→ unknown → overall warn"
js="$(KG_HEALTH_CERT_ENDDATE="garbage-not-a-date" run_health --json 2>/dev/null || true)"
echo "$js" | py 'import sys,json;d=json.load(sys.stdin);c=[m for m in d["metrics"] if m["key"]=="cert_days_left"][0];assert c["status"]=="unknown",c;assert d["overall"]=="warn",d["overall"]' \
  && ok "cert 量不到 → unknown→warn" || fail_t "cert 量不到 未 warn"

echo ""
echo "═══ infra_health v2: $pass passed, $fail failed ═══"
[[ $fail -eq 0 ]]
