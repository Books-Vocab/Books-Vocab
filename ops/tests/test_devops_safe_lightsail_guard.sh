#!/usr/bin/env bash
# test_devops_safe_lightsail_guard.sh — devops_kg_safe.sh transport retarget 契約測試
#
# 歷史：2026-06-15 正式站從 Lightsail 遷到家用 standby（CF Tunnel），當時 wrapper
# transport 仍寫死 Lightsail，故對變更型子命令加「Lightsail 防呆」（預設擋下）。
# 2026-06-19 transport 已 retarget 到 standby（felix），那道防呆語意失效並移除：
#   - deploy/restart/migrate/backup 現對 standby 生效 = 正式站，預設透傳給 BASE。
#   - backup-s3-test 改成唯讀驗證 standby launchd com.kg.backup（不透傳變更型 BASE 動作）。
#   - 破壞性 run 命令仍由 is_blocked_run 守護（另見其他測試）。
#   - 唯讀子命令（status/logs/health…）一律透傳。

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
WRAP="$WORKTREE/ops/devops_kg_safe.sh"
TMPDIR="$(mktemp -d -t kg_ls_guard_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

# stub BASE：記錄是否被呼叫（透過 KG_DEVOPS_BASE test seam 注入）
STUB="$TMPDIR/stub_base.sh"
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
echo "BASE_CALLED:$*"
exit 0
EOF
chmod +x "$STUB"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
no() { echo "  ✗ $*"; fail=$((fail+1)); }

run_wrap() {
  KG_DEVOPS_BASE="$STUB" "$WRAP" "$@" 2>"$TMPDIR/err"
}

echo "── 變更型指令透傳給 BASE（standby = 正式站，不再被 Lightsail 防呆擋）──"
for sub in deploy restart migrate backup; do
  out="$(run_wrap "$sub")"; rc=$?
  if grep -q "BASE_CALLED:$sub" <<<"$out"; then
    ok "$sub 透傳給 BASE"
  else
    no "$sub 應透傳但沒有 (rc=$rc out=[$out] err=[$(cat "$TMPDIR/err")])"
  fi
done

echo "── 不再殘留 Lightsail 防呆語意（err 不得叫人設 KG_ALLOW_LIGHTSAIL）──"
run_wrap deploy >/dev/null
if ! grep -qi "KG_ALLOW_LIGHTSAIL" "$TMPDIR/err"; then
  ok "deploy 不再要求 KG_ALLOW_LIGHTSAIL"
else
  no "deploy 仍殘留 Lightsail 防呆 (err=[$(cat "$TMPDIR/err")])"
fi

echo "── preflight banner 指向 standby（非 Lightsail IP）──"
run_wrap preflight >/dev/null
if grep -qi "standby" "$TMPDIR/err" && ! grep -q "13.193.212.134" "$TMPDIR/err"; then
  ok "preflight 指向 standby、無 Lightsail IP"
else
  no "preflight banner 未對齊 standby (err=[$(cat "$TMPDIR/err")])"
fi

echo "── 唯讀指令透傳（status 仍給 BASE）──"
out="$(run_wrap status)"
if grep -q "BASE_CALLED:status" <<<"$out"; then
  ok "status 透傳"
else
  no "status 不該被擋 (out=[$out])"
fi

echo "── 真破壞性 run 仍被 is_blocked_run 擋（rm -rf /app/data）──"
out="$(run_wrap run "rm -rf /app/data")"; rc=$?
if [[ $rc -ne 0 ]] && ! grep -q "BASE_CALLED" <<<"$out"; then
  ok "破壞性 run 被擋 (rc=$rc)"
else
  no "破壞性 run 應被擋 (rc=$rc out=[$out])"
fi

echo ""
echo "pass=$pass fail=$fail"
[[ $fail -eq 0 ]]
