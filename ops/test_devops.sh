#!/usr/bin/env bash
# test_devops.sh — devops 腳本結構與行為驗證
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
KG="$WORKSPACE/devops.sh"

pass=0; fail=0

ok()      { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t()  { echo "  ✗ $*"; fail=$((fail+1)); }

section() { echo ""; echo "── $* ──"; }

# ── 1. Syntax ──────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$KG"    && ok "KG syntax"    || fail_t "KG syntax"

# ── 2. SSH array 結構 ──────────────────────────────────────────────────────
section "SSH array (no string concatenation)"
grep -q 'SSH_OPTS=(' "$KG"    && ok "KG SSH_OPTS array"    || fail_t "KG SSH_OPTS array"
grep -q 'SSH_CMD=('  "$KG"    && ok "KG SSH_CMD array"     || fail_t "KG SSH_CMD array"
grep -q 'SCP_CMD=('  "$KG"    && ok "KG SCP_CMD array"     || fail_t "KG SCP_CMD array"
! grep -qE '^SSH_CMD="' "$KG"    && ok "KG no bare SSH_CMD string"    || fail_t "KG bare SSH_CMD string found"

# ── 3. 函式名稱一致 ────────────────────────────────────────────────────────
section "Function naming consistency"
grep -q 'run_remote()' "$KG"             && ok "KG run_remote()"             || fail_t "KG run_remote() missing"
grep -q 'preflight()'  "$KG"             && ok "KG preflight()"              || fail_t "KG preflight() missing"
grep -q 'require_local_files()' "$KG"    && ok "KG require_local_files()"    || fail_t "KG require_local_files() missing"
! grep -q 'rssh'            "$KG" && ok "KG no legacy rssh"            || fail_t "KG legacy rssh found"
! grep -q 'preflight_check' "$KG" && ok "KG no legacy preflight_check" || fail_t "KG legacy preflight_check found"

# ── 4. Deploy pipeline 結構 ────────────────────────────────────────────────
section "Deploy pipeline"
grep -q 'cmd_backup'       "$KG"    && ok "KG deploy calls cmd_backup"    || fail_t "KG deploy missing cmd_backup"
grep -q 'for i in $(seq 1' "$KG"    && ok "KG health retry loop"    || fail_t "KG health retry loop missing"
grep -q 'local http_code'  "$KG"    && ok "KG http_code variable"    || fail_t "KG http_code variable missing"

# ── 5. Blocklist 行為 ──────────────────────────────────────────────────────
section "Blocklist (dangerous commands blocked)"
output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "docker system prune -af" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "KG safe wrapper blocks docker system prune" || fail_t "KG safe wrapper did NOT block docker system prune"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" setup 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "KG safe wrapper blocks setup" || fail_t "KG safe wrapper did NOT block setup"

# Flag/case variants that the original literal-byte regex let slip through.
output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "docker compose down -v" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "blocks 'compose down -v'" || fail_t "did NOT block 'compose down -v'"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "docker compose down --volumes" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "blocks 'down --volumes' long form" || fail_t "did NOT block 'down --volumes'"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "rm -fr /home/ubuntu" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "blocks 'rm -fr' swapped flags" || fail_t "did NOT block 'rm -fr /home/ubuntu'"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "rm -r -f /" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "blocks 'rm -r -f /' split flags" || fail_t "did NOT block 'rm -r -f /'"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "rm --recursive --force ~" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "blocks 'rm --recursive --force ~' long form" || fail_t "did NOT block long-form rm"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "RM -RF /home/ubuntu" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "blocks upper-case 'RM -RF'" || fail_t "did NOT block upper-case rm"

# Adversarial bypass variants (negative controls — must stay BLOCKED so a future
# regex regression can't silently reopen them).
declare -a BYPASS=(
  'rm -rf "/home/ubuntu"@quoted path'
  "rm -rf '/'@quoted root"
  'rm -rf /home/ubuntu;@trailing semicolon'
  'rm -rf /*@root glob wipe'
  'rm -rf /.@root dot wipe'
  'find /* -delete@find root glob'
  'echo x > /*@redirect root glob'
  'echo x | tee /app/data/db@tee clobber'
  'rm -rf /home//ubuntu@double slash'
  'rm -rf ${HOME}@brace HOME'
  '/bin/rm -rf /home/ubuntu@absolute rm path'
  'find / -delete@find -delete root'
  'find /home/ubuntu -delete@find -delete home'
  'cat foo > /home/ubuntu/data.db@redirect clobber'
  'truncate -s0 /home/ubuntu/x@truncate clobber'
  'docker volume rm knowledge-graph-api_data@docker volume rm'
  'docker volume prune -f@docker volume prune'
  'docker compose -f x.yml down -v@compose -f down -v'
)
for entry in "${BYPASS[@]}"; do
  cmd="${entry%%@*}"; label="${entry##*@}"
  output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "$cmd" 2>&1 || true)
  echo "$output" | grep -q "blocked" && ok "blocks bypass: $label" || fail_t "BYPASS NOT BLOCKED: $label ($cmd)"
done

# False-positive controls — legitimate commands must pass the guard. Stub BASE
# with /usr/bin/true so the wrapper does not invoke the real remote.
declare -a SAFE=(
  'rm -rf ./build@relative build dir'
  'rm -rf /tmp/foo@tmp path'
  'rm -rf node_modules@relative no-slash'
  'rm -f /home/ubuntu/single.log@non-recursive single file'
  'ls -la /home/ubuntu@listing prod dir'
  'tar czf x.tgz /home/ubuntu@backup read of prod dir'
  'grep -r foo /home/ubuntu@recursive grep read'
)
for entry in "${SAFE[@]}"; do
  cmd="${entry%%@*}"; label="${entry##*@}"
  output=$(KG_DEVOPS_BASE=/usr/bin/true bash "$WORKSPACE/ops/devops_kg_safe.sh" run "$cmd" 2>&1 || true)
  echo "$output" | grep -q "blocked" && fail_t "FALSE POSITIVE blocked safe cmd: $label ($cmd)" || ok "allows safe: $label"
done

# ── 6. Preflight 檔案驗證（靜態） ─────────────────────────────────────────
section "Preflight file validation (static)"
awk '/^preflight\(\)/,/^}/' "$KG" | grep -q 'require_local_files' \
  && ok "KG preflight() calls require_local_files" \
  || fail_t "KG preflight() does not call require_local_files"
awk '/^require_local_files\(\)/,/^}/' "$KG" | grep -q 'Dockerfile' \
  && ok "KG require_local_files checks Dockerfile" \
  || fail_t "KG require_local_files missing Dockerfile check"
awk '/^require_local_files\(\)/,/^}/' "$KG" | grep -q 'docker-compose.yml' \
  && ok "KG require_local_files checks docker-compose.yml" \
  || fail_t "KG require_local_files missing docker-compose.yml check"

# ── 7. 部署版本追蹤 ──────────────────────────────────────────────────────
section "Deploy version tracking"
grep -q 'git rev-parse --short HEAD' "$KG" \
  && ok "KG deploy stamps git SHA" \
  || fail_t "KG deploy missing git SHA stamp"
grep -q 'VERSION' "$KG" \
  && ok "KG writes VERSION file" \
  || fail_t "KG missing VERSION file write"
grep -q 'deploy.log' "$KG" \
  && ok "KG appends deploy log" \
  || fail_t "KG missing deploy log"
awk '/^cmd_status\(\)/,/^}/' "$KG" | grep -q 'VERSION' \
  && ok "KG status shows deployed version" \
  || fail_t "KG status missing version display"

# ── 8. ops-cli transport quoting（argv 安全序列化）──────────────────────────
# 根因回歸:ops-cli 的 SQL 過去用 $* 扁平化 + 遠端 bash 二次解析,引號/括號/% 全毀。
# 用 KG_SSH_CMD stub 攔截最終遠端指令字串,確認任意特殊字元的 SQL 原封不動穿越。
section "ops-cli transport quoting"
STUB="$(mktemp)"
cat > "$STUB" <<'STUBEOF'
#!/usr/bin/env bash
# fake ssh: docker-inspect 探活回 true;其餘把遠端指令字串原樣印出
arg="$*"
case "$arg" in
  *"docker inspect"*) echo true ;;
  *) printf '%s\n' "$arg" ;;
esac
STUBEOF
chmod +x "$STUB"

# argv 佈局:docker(0) exec(1) container(2) python3(3) ops_cli.py(4) db-query(5) uid(6) SQL...(7+)
SQL="SELECT id FROM card WHERE content LIKE '%a(b)%' COLLATE NOCASE"
remote_cmd=$(KG_SSH_CMD="$STUB" bash "$KG" ops-cli db-query u1 "$SQL" 2>/dev/null | tail -1)
# 遠端 bash 重新解析該字串後,還原出的 argv 自第 7 元素起應 == 原始 SQL（一字不差）
eval "argv=( $remote_cmd )"
got="${argv[*]:7}"
[[ "$got" == "$SQL" ]] \
  && ok "ops-cli SQL survives transport (quotes/parens/% intact)" \
  || fail_t "ops-cli SQL mangled: got [$got] want [$SQL]"

# REMAINDER 多 token:遠端 bash 解析後須還原出 count(*)，不被當 subshell 破壞
remote_cmd=$(KG_SSH_CMD="$STUB" bash "$KG" ops-cli db-query u1 SELECT count'(*)' FROM card 2>/dev/null | tail -1)
eval "argv=( $remote_cmd )"
[[ "${argv[*]:7}" == "SELECT count(*) FROM card" ]] \
  && ok "ops-cli preserves 'count(*)' across hop" \
  || fail_t "ops-cli lost 'count(*)': [${argv[*]:7}]"
rm -f "$STUB"

# ── 結果 ──────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
