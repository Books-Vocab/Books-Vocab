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
# 2026-06-15 遷 standby 起 deploy 不再自動備份（備份走 launchd com.kg.backup 自己的
# 排程，見 docs/sop/deploy.md §標準部署流程）。這裡原本斷言「deploy calls cmd_backup」，
# 而它是被 devops.sh:594 的**函式定義**滿足的——全檔 grep 分不出定義與呼叫，所以語意
# 整個反轉之後它照樣是綠的。改成對 cmd_deploy 函式範圍的斷言，兩個方向才都測得到。
awk '/^cmd_deploy\(\)/,/^}$/' "$KG" | grep -q 'cmd_backup' \
  && fail_t "KG deploy runs a backup inline — that moved to the com.kg.backup schedule" \
  || ok "KG deploy does not back up inline (scheduled separately)"
grep -q 'for i in $(seq 1' "$KG"    && ok "KG health retry loop"    || fail_t "KG health retry loop missing"
grep -q 'local http_code'  "$KG"    && ok "KG http_code variable"    || fail_t "KG http_code variable missing"
grep -q -- "--exclude='_ops_backups/'" "$KG" \
  && grep -q -- "--exclude='_ops_world_backups/'" "$KG" \
  && ok "KG backup excludes nested ops backup trees" \
  || fail_t "KG backup should exclude nested ops backup trees"
# 這裡原本是對 "$KG" 的**全檔** grep --info=progress2 / --human-readable。加了 rsync
# flavor 分流之後那兩個字面值仍然出現在 devops.sh（在 rsync_progress_flags 的 printf
# 那行），所以舊斷言不會轉紅——它會靜靜變成空話，不再證明備份呼叫點會顯示進度。失敗
# 模式同 :37-43 的註解。改成「注入 version 字串 → 純函式輸出」的行為斷言 + 對
# cmd_backup 函式範圍的呼叫點斷言。
# 不可 `source devops.sh`——它有頂層 case dispatch 且 set -euo pipefail，source 會直接
# 執行（理由同 ops/kg_reconcile.sh:24-25 的註解），故用 awk 抽函式再丟給子 bash。
rsync_flags() {
  local tmpf; tmpf=$(mktemp)
  {
    awk '/^rsync_progress_flags\(\)/,/^}$/' "$KG"
    echo 'rsync_progress_flags "$1"'
  } > "$tmpf"
  bash "$tmpf" "$1"
  rm -f "$tmpf"
}
[[ "$(rsync_flags 'openrsync: protocol version 29')" == '--progress' ]] \
  && ok "KG backup picks --progress on openrsync" \
  || fail_t "KG backup picks --progress on openrsync"
[[ "$(rsync_flags 'rsync  version 3.3.0  protocol version 31' | tr '\n' '|')" == '--info=progress2|--human-readable|' ]] \
  && ok "KG backup picks --info=progress2 --human-readable on GNU rsync" \
  || fail_t "KG backup picks --info=progress2 --human-readable on GNU rsync"
_backup_body=$(awk '/^cmd_backup\(\)/,/^}$/' "$KG")
# grep -c 零命中時 exit 1，而本檔 :3 是 set -euo pipefail → 兩處 || true 不可省。
# 兩半缺一不可：只驗「不含 --info=progress2」會在 cmd_backup 被改名或刪掉時假綠，
# progress_flags[@] 那半是正控，證明看的是真的新呼叫點。
if [[ "$(printf '%s' "$_backup_body" | grep -c -- 'progress_flags\[@\]' || true)" == 1 \
   && "$(printf '%s' "$_backup_body" | grep -c -- '--info=progress2' || true)" == 0 ]]; then
  ok "KG backup call site no longer hardcodes rsync progress flags"
else
  fail_t "KG backup call site no longer hardcodes rsync progress flags"
fi
# IMP-20260806-02bf8d：rsync 失敗過去只留下 rsync 自己印的 usage，前兩行 preflight 與
# 「▶ 本地冷快照」看起來像開始工作了，很容易被讀成「跑完了」。備份指令不得用「印出
# usage」當失敗訊號 → 呼叫點必須守住 rsync 的非零退出，並具名指向 standby 的每日 S3
# 備份（launchd com.kg.backup）。正控 = 守衛存在；指向性 = 訊息點名那條替代路徑。
# 指向性檢查必須**限縮在守衛區塊內**：cmd_backup 開頭本來就有一句提到 com.kg.backup
# 的註解，對整個函式範圍 grep 會被那句既有註解滿足——守衛留著但把訊息全刪掉照樣綠。
# 那正是本檔上方剛換掉的空話斷言換個位置復發。
# 再往下濾一層到「真的印給人看的行」（去註解 + 必須有 >&2），原因有二：
#   a) 註解同樣能滿足 grep（守衛裡新寫一句提到 com.kg.backup 的註解就假綠）；
#   b) $dest 若對整個守衛範圍 grep 會是**恆真式**——awk 範圍必然含 rsync 的目的地引數
#      那行 `"$SERVER:$REMOTE_DATA_DIR/" "$dest/"; then`，它已被第一個 conjunct 蘊含，
#      discriminating power 為零。濾掉不含 >&2 的行才真的在鎖「訊息點出了殘留目錄」。
_guard=$(printf '%s\n' "$_backup_body" | awk '/if ! rsync -az/,/^  fi$/')
_guard_msg=$(printf '%s\n' "$_guard" | grep -v '^[[:space:]]*#' | grep -F -- '>&2' || true)
if [[ "$(printf '%s' "$_backup_body" | grep -c -- 'if ! rsync -az' || true)" == 1 \
   && "$(printf '%s' "$_guard_msg" | grep -c -- 'com\.kg\.backup' || true)" -ge 1 \
   && "$(printf '%s' "$_guard_msg" | grep -c -- '\$dest' || true)" -ge 1 ]]; then
  ok "KG backup names its own failure and points at the S3 daily backup"
else
  fail_t "KG backup names its own failure and points at the S3 daily backup"
fi
# 上面三條都是「注入 version 字串 → mapper 輸出」，沒有一條走**無參數**路徑，而那是
# 生產唯一的呼叫方式（cmd_backup 不帶參數呼叫 helper）。這條蓋住 probe 本身：無論本機
# 是哪種 flavor，都必須吐出非空旗標，否則 cmd_backup 會拿到空陣列。
[[ -n "$(rsync_flags '')" ]] \
  && ok "KG backup rsync flavor probe yields flags on this host" \
  || fail_t "KG backup rsync flavor probe yields flags on this host"
# 以上全是 grep-on-source，擋不住「訊息一字不動、只把結尾的 err 換成 echo」——那之後
# cmd_backup 會對空目錄繼續跑 integrity check + tar 然後 exit 0，正是 IMP-20260806-
# 02bf8d 的病本身（拿印訊息當失敗訊號）換皮。這條用 stub rsync 實跑一次失敗路徑，
# 斷 exit code 與磁碟產物，不看原始碼長相。全程本機離線，不碰生產。
_bk_sandbox=$(mktemp -d)
mkdir -p "$_bk_sandbox/bin" "$_bk_sandbox/backups"
cat > "$_bk_sandbox/bin/rsync" <<'STUB'
#!/bin/bash
[[ "${1:-}" == "--version" ]] && { echo "openrsync: protocol version 29"; exit 0; }
echo "rsync: unrecognized option --info=progress2" >&2
exit 1
STUB
chmod +x "$_bk_sandbox/bin/rsync"
{
  echo 'set -euo pipefail'
  grep -E '^(info|ok|err|section)\(\)' "$KG"
  awk '/^rsync_progress_flags\(\)/,/^}$/' "$KG"
  awk '/^cmd_backup\(\)/,/^}$/' "$KG"
  echo "BACKUP_DIR='$_bk_sandbox/backups'; SERVER=stub-host; REMOTE_DATA_DIR=/stub"
  echo 'cmd_backup'
} > "$_bk_sandbox/run.sh"
_bk_rc=0
PATH="$_bk_sandbox/bin:$PATH" bash "$_bk_sandbox/run.sh" > "$_bk_sandbox/out" 2>&1 || _bk_rc=$?
if [[ "$_bk_rc" -ne 0 ]] \
   && grep -qF 'com.kg.backup' "$_bk_sandbox/out" \
   && [[ -z "$(find "$_bk_sandbox/backups" -name '*.tar.gz' 2>/dev/null)" ]] \
   && [[ -n "$(find "$_bk_sandbox/backups" -name '.INCOMPLETE' 2>/dev/null)" ]]; then
  ok "KG backup really exits non-zero on rsync failure, leaving no fake artifact"
else
  fail_t "KG backup really exits non-zero on rsync failure, leaving no fake artifact (rc=$_bk_rc)"
fi
rm -rf "$_bk_sandbox"

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
# 函式範圍 + 剝註解，兩者缺一不可。全檔 grep 會被兩種東西滿足：把正確命令寫進**註解**
# （devops.sh:418-427 現在就有一整段在談這條命令），以及旗標搬到 cmd_restart 之類的
# **別的函式**。回補旗標的那個 commit 順手加了註解，若沿用全檔 grep，等於一邊修回歸
# 一邊為下一次同樣的回歸鋪好綠燈。
awk '/^cmd_deploy\(\)/,/^}$/' "$KG" | grep -v '^[[:space:]]*#' \
  | grep -q -- 'docker compose up -d --build --force-recreate' \
  && ok "KG deploy force-recreates container so VERSION is re-read" \
  || fail_t "KG deploy should force-recreate container after stamping VERSION"
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

VIEW_LOGS="$WORKSPACE/backend/view_logs.sh"
bash -n "$VIEW_LOGS" \
  && ok "view_logs syntax" \
  || fail_t "view_logs syntax"
grep -q 'devops_kg_safe.sh' "$VIEW_LOGS" \
  && ok "view_logs calls devops_kg_safe.sh" \
  || fail_t "view_logs does not call safe wrapper"
grep -Eq '(^|[[:space:]])ssh([[:space:]]|$)|docker compose logs' "$VIEW_LOGS" \
  && fail_t "view_logs still has raw ssh/docker logs bypass" \
  || ok "view_logs has no raw ssh/docker logs bypass"

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

# set -o pipefail 下 `$(wrapper ... | tail -1)` 的狀態是 **wrapper** 的狀態——tail 遮不住。
# 某個 arm 一被刪掉，wrapper 就落到 usage 分支非零退出，賦值失敗，set -e 在下面的斷言
# 之前殺掉整支腳本：輸出裡一個 ✗ 都沒有、後面的斷言連跑都沒跑，而那正是最需要診斷的
# 時刻。
#
# 但 rc 不能只是「抓進來然後不看」——那是把大聲難看的偵測換成安靜的漏放（實測：arm 印出
# 正確命令後 exit 3，整組全綠；改版前那個 mutant 反而是紅的）。非零一律回傳 `EXIT-<rc>`，
# 六條 `==` 比較全部判紅，且 exit code 直接出現在診斷字串裡。
#
# 也不 `tail -1`：這六個 arm 的 stdout 恰好一行，比對**完整 stdout** 才釘得住「這個 typed
# 命令只碰得到什麼」——只看最後一行的話，在正確命令之前多送一條 `run cat /etc/shadow`
# 是綠的，而「縮 raw run surface」正是本段存在的理由。
typed_all() {
  local out rc=0
  out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" "$@" 2>/dev/null) || rc=$?
  (( rc == 0 )) || { printf 'EXIT-%d' "$rc"; return 0; }
  printf '%s' "$out"
}

# caddy-status / caddyfile 保留舊名（agent 肌肉記憶 + docs/sop/debug.md 仍這樣寫），
# 但 standby 遷 felix + Cloudflare Tunnel 後底下已無 Caddy：前者改探 cloudflared，
# 後者根本沒有本地檔可讀（ingress 是 CF remotely-managed）。這兩條斷言在 2026-06-15
# 之後就描述著一個不存在的世界，紅到 2026-08-04 才被看見（IMP-0053）。
# 這是六條裡唯一用**前綴**比對的（fallback 訊息會變動，不宜整串釘死）。`!= *$'\n'*`
# 不可省：`tail -1` 還在的時候，結尾那個 `*` 只吃得掉同一行的其餘部分；改成比對完整
# stdout 之後，它吃掉的是**整個剩餘輸出含換行**——於是往這條 arm 後面追加任意遠端命令
# 完全隱形，而那正是拿掉 tail -1 要修的東西（實測：改版前紅、改版後綠）。契約要講完整：
# 這條 typed surface 只發**一條**遠端命令，且它以 pgrep cloudflared 開頭。
typed_out=$(typed_all caddy-status)
if [[ "$typed_out" == "run pgrep -lf 'cloudflared.*tunnel'"* \
   && "$typed_out" != *caddy* && "$typed_out" != *$'\n'* ]]; then
  ok "caddy-status probes the cloudflared tunnel (no Caddy on standby)"
else
  fail_t "caddy-status mapping drifted: $typed_out"
fi

# caddyfile 是唯一「不打遠端」的 typed 指令：CF ingress 存在 Cloudflare 端，沒有本地
# 檔案可 cat。契約因此是**不得發出任何 remote 命令**，並在 stderr 指向 ingress 正本。
#
# 兩者必須綁成一條，順序不可反：空 stdout 本身是**假證據**——arm 被刪掉、subcommand
# 打錯、腳本提早 exit，stdout 一樣是空的。先用 stderr 的 SoT 指標證明這條 arm 真的跑過，
# 「它沒發出遠端命令」才是關於被測路徑的斷言而非關於「什麼都沒發生」的同義反覆。
# rc 要顯式接住：這是本組唯一不以 `| tail -1` 收尾的捕捉，而管線最後一段的 tail 恆 0，
# 正是其他每一條被 set -e 放過的原因。少了 `|| rc=$?`，arm 一被刪掉 wrapper 就落到
# usage 分支非零退出，`set -e` 在下面的 if 判斷**之前**就殺掉整支腳本——診斷訊息永遠
# 印不出來，後面 8 條斷言連跑都沒跑，而且輸出裡一個 ✗ 都沒有。
caddyfile_err_file="$(mktemp)"
caddyfile_rc=0
caddyfile_out=$(KG_DEVOPS_BASE="$STUB_BASE" bash "$SAFE_KG" caddyfile 2>"$caddyfile_err_file") \
  || caddyfile_rc=$?
caddyfile_err=$(cat "$caddyfile_err_file"); rm -f "$caddyfile_err_file"
if (( caddyfile_rc != 0 )); then
  fail_t "caddyfile exited $caddyfile_rc — the arm is gone or broken: ${caddyfile_err:-(no stderr)}"
elif [[ "$caddyfile_err" != *kg-backend-deployment.md* ]]; then
  fail_t "caddyfile stopped naming the ingress SoT: $caddyfile_err"
elif [[ "$caddyfile_err" == *'[Preflight]'* ]]; then
  # 正面證據勝過「stdout 是空的」：只有 run_fixed_remote 會印 preflight banner，所以
  # 把遠端輸出重導掉也逃不過——空 stdout 本身無法區分「沒打遠端」與「打了但沒回顯」。
  fail_t "caddyfile reached the host — preflight banner present, so a remote command ran"
elif [[ -n "$caddyfile_out" ]]; then
  fail_t "caddyfile stdout must be empty, got: $caddyfile_out"
else
  ok "caddyfile issues no remote command, names the ingress SoT, and never preflights"
fi

typed_out=$(typed_all docker-ps)
[[ "$typed_out" == 'run docker ps' ]] \
  && ok "docker-ps maps to fixed readonly command" \
  || fail_t "docker-ps mapping drifted: $typed_out"

# 餵 7 而不是 25：預設是 100，但「寫死成 25」與「透傳 25」在只測 25 時無法區分——
# 挑一個沒人會寫死的值，再補一條不帶參數的呼叫把預設本身釘住。
typed_out=$(typed_all docker-logs 7)
[[ "$typed_out" == 'run docker logs knowledge-graph-api -n 7' ]] \
  && ok "docker-logs passes the caller's line count through" \
  || fail_t "docker-logs mapping drifted: $typed_out"

typed_out=$(typed_all docker-logs)
[[ "$typed_out" == 'run docker logs knowledge-graph-api -n 100' ]] \
  && ok "docker-logs defaults to 100 lines" \
  || fail_t "docker-logs default drifted: $typed_out"

typed_out=$(typed_all disk-usage)
[[ "$typed_out" == 'run df -h' ]] \
  && ok "disk-usage maps to df -h" \
  || fail_t "disk-usage mapping drifted: $typed_out"

typed_out=$(typed_all memory-usage)
[[ "$typed_out" == 'run free -m' ]] \
  && ok "memory-usage maps to free -m" \
  || fail_t "memory-usage mapping drifted: $typed_out"

typed_out=$(typed_all docker-stats)
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
