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
grep -q 'KG_SCP_CMD' "$KG"    && ok "KG SCP test seam"     || fail_t "KG SCP test seam missing"
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

# ── 9. ops-edit transport quoting（空白 content / notebook 名原封不動）──────
section "ops-edit transport quoting"
STUB="$(mktemp)"
cat > "$STUB" <<'STUBEOF'
#!/usr/bin/env bash
arg="$*"
case "$arg" in
  *"docker inspect"*) echo true ;;
  *) printf '%s\n' "$arg" ;;
esac
STUBEOF
chmod +x "$STUB"

remote_cmd=$(KG_SSH_CMD="$STUB" bash "$KG" ops-edit card-move u1 "file in" --to-notebook "Turns of Phrase" --commit --json 2>/dev/null | tail -1)
eval "argv=( $remote_cmd )"
expect=(card-move u1 "file in" --to-notebook "Turns of Phrase" --commit --json)
for i in "${!expect[@]}"; do
  [[ "${argv[$((5 + i))]}" == "${expect[$i]}" ]] \
    && ok "ops-edit arg[$i] preserved: ${expect[$i]}" \
    || fail_t "ops-edit arg[$i] mangled: got [${argv[$((5 + i))]}] want [${expect[$i]}]"
done
rm -f "$STUB"

# ── 10. ops-edit-batch wrapper（單次 upload + docker exec）─────────────────
section "ops-edit-batch wrapper"
SSH_STUB="$(mktemp)"
SCP_STUB="$(mktemp)"
cat > "$SSH_STUB" <<'STUBEOF'
#!/usr/bin/env bash
arg="$*"
case "$arg" in
  *"docker inspect"*) echo true ;;
  *) printf '%s\n' "$arg" ;;
esac
STUBEOF
cat > "$SCP_STUB" <<'STUBEOF'
#!/usr/bin/env bash
printf 'scp:%s\n' "$*"
STUBEOF
chmod +x "$SSH_STUB" "$SCP_STUB"
PLAN="$(mktemp)"
printf '{"schema":"kg.ops_edit_batch.v1","ops":[["world-snapshot","--json"]]}\n' > "$PLAN"
batch_out=$(KG_SSH_CMD="$SSH_STUB" KG_SCP_CMD="$SCP_STUB" bash "$KG" ops-edit-batch "$PLAN" 2>/dev/null || true)
echo "$batch_out" | grep -q 'docker exec knowledge-graph-api python3 /tmp/ops_edit_batch' \
  && ok "ops-edit-batch docker exec runner" \
  || fail_t "ops-edit-batch missing runner docker exec"
echo "$batch_out" | grep -q '/tmp/ops_edit_batch_plan' \
  && ok "ops-edit-batch passes uploaded plan path" \
  || fail_t "ops-edit-batch missing uploaded plan path"
rm -f "$SSH_STUB" "$SCP_STUB" "$PLAN"

# ── 11. validate_uid（Apple uid 含點；traversal 仍須擋）─────────────────────
# 根因:Apple Sign-in user_id 含 '.'（如 000287.<hex>.0228），舊白名單
# [A-Za-z0-9_-] 把真實生產 uid 全擋，導致 user-info/ops-cli 查不了任何 Apple
# 帳號。修法:放行 '.'，但以「禁 '..' / 禁前導 '.'」對齊後端 _safe_user_dir
# (admin_wiring.py) 的 resolve()+commonpath path-traversal 防護語意。
section "validate_uid (Apple uid with dots; traversal still blocked)"
# devops.sh 底部的 dispatch 會在 source 時直接執行（跑 help 後結束），
# 導致 source 後的 validate_uid 永遠不會執行。改為提取函式到 tmp 腳本獨立跑。
vuid() {
  local tmpf=$(mktemp)
  {
    sed -n '/^err()/,/^}$/p' "$KG"
    sed -n '/^validate_uid()/,/^}$/p' "$KG"
    echo 'validate_uid "$1"'
  } > "$tmpf"
  bash "$tmpf" "$1"
  local rc=$?
  rm -f "$tmpf"
  return $rc
}

vuid '000287.04e254024c2f4341849278a933743257.0228' >/dev/null 2>&1 \
  && ok "accepts Apple uid with dots" \
  || fail_t "rejected legit Apple uid with dots"
vuid 'abc_123-XYZ' >/dev/null 2>&1 \
  && ok "accepts plain alnum/_/-" \
  || fail_t "rejected plain alnum uid"

# 負控:traversal / metachar / 邊界 必須續擋
LONG65=$(printf 'x%.0s' $(seq 1 65))
for bad in '..' '../etc' 'a..b' '.hidden' 'a/b' 'a b' 'a;rm' '' "$LONG65"; do
  _out=$(vuid "$bad" 2>&1) || true
  echo "$_out" | grep -q '非法\|不可' \
    && ok "blocks bad uid: '${bad:0:24}'" \
    || fail_t "did NOT block bad uid: '$bad'"
done

# ── 12. 診斷噪音須走 stderr，讓 --json 的 stdout 可被機器 parse ─────────────
# 根因:dogfooding 發現 preflight banner + info "▶ 執行 argv" 印到 stdout,
# 害每個 ops-cli --json 都 json.loads 失敗。診斷訊息一律 stderr,stdout 只留 payload。
section "Diagnostics to stderr (clean --json stdout)"
# 10a. wrapper preflight banner 不可出現在 stdout
_pf_stdout=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" preflight 2>/dev/null)
[[ -z "$_pf_stdout" ]] \
  && ok "preflight banner not on stdout" \
  || fail_t "preflight banner leaked to stdout: $_pf_stdout"
# 10b. wrapper preflight banner 必須出現在 stderr
_pf_stderr=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" preflight 2>&1 >/dev/null)
echo "$_pf_stderr" | grep -q '\[Preflight\]' \
  && ok "preflight banner on stderr" \
  || fail_t "preflight banner missing from stderr"
# 10c. devops.sh info() 須導向 stderr（progress 非 payload）
grep -qE '^info\(\)[[:space:]]*\{[[:space:]]*echo "▶ \$\*" >&2;' "$KG" \
  && ok "info() routed to stderr" \
  || fail_t "info() not routed to stderr (would pollute --json stdout)"

# ── 13. status_all 相容入口不得繞過 safe wrapper ─────────────────────────
section "status_all delegates to safe wrapper"
STATUS_ALL="$WORKSPACE/ops/status_all.sh"
bash -n "$STATUS_ALL" \
  && ok "status_all syntax" \
  || fail_t "status_all syntax"
grep -q 'devops_kg_safe.sh' "$STATUS_ALL" \
  && ok "status_all calls devops_kg_safe.sh" \
  || fail_t "status_all does not call safe wrapper"
grep -q '"$SAFE" status' "$STATUS_ALL" && grep -q '"$SAFE" health' "$STATUS_ALL" \
  && ok "status_all delegates status + health" \
  || fail_t "status_all missing status/health delegation"
grep -qE '(^|[[:space:]])ssh([[:space:]]|$)|run_remote\(\)' "$STATUS_ALL" \
  && fail_t "status_all still has raw ssh/run_remote bypass" \
  || ok "status_all has no raw ssh/run_remote bypass"

# ── 12. typed read-only debug surfaces（縮 raw run surface）──────────────────
section "Typed read-only debug surfaces"
SAFE_KG="$WORKSPACE/ops/devops_kg_safe.sh"
grep -q 'caddy-status' "$SAFE_KG" && grep -q 'caddyfile' "$SAFE_KG" \
  && grep -q 'docker-ps' "$SAFE_KG" && grep -q 'docker-logs' "$SAFE_KG" \
  && grep -q 'disk-usage' "$SAFE_KG" && grep -q 'memory-usage' "$SAFE_KG" \
  && grep -q 'docker-stats' "$SAFE_KG" \
  && ok "safe wrapper exposes typed debug commands" \
  || fail_t "safe wrapper missing typed debug commands"

STUB_BASE="$(mktemp)"
cat > "$STUB_BASE" <<'STUBEOF'
#!/usr/bin/env bash
printf '%s\n' "$*"
STUBEOF
chmod +x "$STUB_BASE"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" caddy-status 2>/dev/null | tail -1)
[[ "$typed_out" == 'run sudo systemctl status caddy' ]] \
  && ok "caddy-status maps to fixed readonly command" \
  || fail_t "caddy-status mapping drifted: $typed_out"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" caddyfile 2>/dev/null | tail -1)
[[ "$typed_out" == 'run cat /etc/caddy/Caddyfile' ]] \
  && ok "caddyfile maps to fixed readonly command" \
  || fail_t "caddyfile mapping drifted: $typed_out"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" docker-ps 2>/dev/null | tail -1)
[[ "$typed_out" == 'run docker ps' ]] \
  && ok "docker-ps maps to fixed readonly command" \
  || fail_t "docker-ps mapping drifted: $typed_out"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" docker-logs 25 2>/dev/null | tail -1)
[[ "$typed_out" == 'run docker logs knowledge-graph-api -n 25' ]] \
  && ok "docker-logs maps to container log tail" \
  || fail_t "docker-logs mapping drifted: $typed_out"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" disk-usage 2>/dev/null | tail -1)
[[ "$typed_out" == 'run df -h' ]] \
  && ok "disk-usage maps to df -h" \
  || fail_t "disk-usage mapping drifted: $typed_out"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" memory-usage 2>/dev/null | tail -1)
[[ "$typed_out" == 'run free -m' ]] \
  && ok "memory-usage maps to free -m" \
  || fail_t "memory-usage mapping drifted: $typed_out"

typed_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" docker-stats 2>/dev/null | tail -1)
[[ "$typed_out" == 'run docker stats --no-stream' ]] \
  && ok "docker-stats maps to non-streaming stats" \
  || fail_t "docker-stats mapping drifted: $typed_out"

typed_out=$(bash "$SAFE_KG" run "docker ps" 2>&1 || true)
echo "$typed_out" | grep -q 'use typed command: docker-ps' \
  && ok "raw docker ps redirected to typed command" \
  || fail_t "raw docker ps was not redirected"

typed_out=$(bash "$SAFE_KG" run "sudo systemctl status caddy" 2>&1 || true)
echo "$typed_out" | grep -q 'use typed command: caddy-status' \
  && ok "raw caddy status redirected to typed command" \
  || fail_t "raw caddy status was not redirected"
rm -f "$STUB_BASE"

# ── 結果 ──────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
