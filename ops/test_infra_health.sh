#!/usr/bin/env bash
# test_infra_health.sh — infra_health.sh 結構與行為驗證（離線，靠 seam 注入）
#
# Seam:
#   KG_BASE                  指向 stub，取代 ./devops.sh，攔截 `run "<bundle>"`，吐 canned 指標
#   KG_HEALTH_CERT_ENDDATE   注入憑證 notAfter（繞過 openssl 網路呼叫）
#   KG_HEALTH_HTTP_CODE      注入 HTTPS 探針 http_code（繞過 curl）
#
# 注意：stub 直接吐 canned tab 指標（忽略 REMOTE_BUNDLE），故 macOS-native 探針
#   （vm_stat/sysctl 記憶體·swap、cloudflared ingress、date StartedAt 解析）的真實
#   解析行為無法在此 stub 行使，須靠 standby 實機 `health --json` 驗證（見 receipt）。
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
printf 'container_uptime_s\t%s\n' "${KG_TEST_UPTIME:-93600}"
printf 'cpu_pct\t4.2\n'; printf 'mem_pct\t38.0\n'
printf 'ingress\t%s\n' "${KG_TEST_INGRESS:-active}"
printf 'log_errors_1h\t%s\n' "${KG_TEST_ERRS:-0}"
printf 'data_dir_mb\t393\n'
EOF
chmod +x "$STUB"
trap 'rm -f "$STUB"' EXIT

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
