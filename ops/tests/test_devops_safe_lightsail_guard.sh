#!/usr/bin/env bash
# test_devops_safe_lightsail_guard.sh — Lightsail 遷移防呆 guard 單元測試
#
# 2026-06-15 正式站從 Lightsail 遷到家用 standby（Cloudflare Tunnel）。
# devops_kg_safe.sh 的變更型子命令（deploy/restart/migrate/backup/backup-s3-test）
# 仍寫死打向已停的 Lightsail = footgun：
#   - deploy 把程式碼 rsync 到錯主機（已停的舊站）
#   - backup / backup-s3-test 會用 Lightsail 凍結舊資料覆蓋 standby 今天的好備份
#
# Guard 契約：這些子命令預設被擋（exit≠0、BASE 不被呼叫、訊息指向 standby 程序）；
# 真要對 Lightsail 操作（rollback 情境）才設 KG_ALLOW_LIGHTSAIL=1 放行。
# 唯讀子命令（status/logs/health…）不受影響。

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

# run_wrap <allow 0|1> <args...> → stdout 含 BASE 呼叫；stderr 落 $TMPDIR/err；回傳 wrapper rc
run_wrap() {
  local allow="$1"; shift
  if [[ "$allow" == "1" ]]; then
    KG_ALLOW_LIGHTSAIL=1 KG_DEVOPS_BASE="$STUB" "$WRAP" "$@" 2>"$TMPDIR/err"
  else
    KG_DEVOPS_BASE="$STUB" "$WRAP" "$@" 2>"$TMPDIR/err"
  fi
}

echo "── 變更型指令預設被擋（exit≠0 且 BASE 不被呼叫）──"
for sub in deploy restart migrate backup backup-s3-test; do
  out="$(run_wrap 0 "$sub")"; rc=$?
  if [[ $rc -ne 0 ]] && ! grep -q "BASE_CALLED" <<<"$out"; then
    ok "$sub 被擋 (rc=$rc)"
  else
    no "$sub 應被擋但沒有 (rc=$rc out=[$out])"
  fi
done

echo "── 擋訊息指向 standby 程序 ──"
run_wrap 0 deploy >/dev/null
if grep -qiE "standby|kg-backend-deployment" "$TMPDIR/err"; then
  ok "訊息含 standby 指引"
else
  no "訊息缺 standby 指引 (err=[$(cat "$TMPDIR/err")])"
fi

echo "── KG_ALLOW_LIGHTSAIL=1 放行（BASE 被呼叫，供 rollback）──"
for sub in deploy backup; do
  out="$(run_wrap 1 "$sub")"; rc=$?
  if grep -q "BASE_CALLED:$sub" <<<"$out"; then
    ok "$sub 放行"
  else
    no "$sub 應放行但沒透傳 (rc=$rc out=[$out])"
  fi
done

echo "── 唯讀指令不受影響（status 仍透傳給 BASE）──"
out="$(run_wrap 0 status)"
if grep -q "BASE_CALLED:status" <<<"$out"; then
  ok "status 透傳"
else
  no "status 不該被擋 (out=[$out])"
fi

echo ""
echo "pass=$pass fail=$fail"
[[ $fail -eq 0 ]]
