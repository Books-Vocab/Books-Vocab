#!/usr/bin/env bash
# test_devops.sh — devops 腳本結構與行為驗證
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
KG="$WORKSPACE/devops.sh"
QBANK="$WORKSPACE/../qbank/ops/devops_qbank.sh"

pass=0; fail=0

ok()      { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t()  { echo "  ✗ $*"; fail=$((fail+1)); }

section() { echo ""; echo "── $* ──"; }

# ── 1. Syntax ──────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$KG"    && ok "KG syntax"    || fail_t "KG syntax"
bash -n "$QBANK" && ok "QBank syntax" || fail_t "QBank syntax"

# ── 2. SSH array 結構 ──────────────────────────────────────────────────────
section "SSH array (no string concatenation)"
grep -q 'SSH_OPTS=(' "$KG"    && ok "KG SSH_OPTS array"    || fail_t "KG SSH_OPTS array"
grep -q 'SSH_OPTS=(' "$QBANK" && ok "QBank SSH_OPTS array" || fail_t "QBank SSH_OPTS array"
grep -q 'SSH_CMD=('  "$KG"    && ok "KG SSH_CMD array"     || fail_t "KG SSH_CMD array"
grep -q 'SSH_CMD=('  "$QBANK" && ok "QBank SSH_CMD array"  || fail_t "QBank SSH_CMD array"
grep -q 'SCP_CMD=('  "$KG"    && ok "KG SCP_CMD array"     || fail_t "KG SCP_CMD array"
grep -q 'SCP_CMD=('  "$QBANK" && ok "QBank SCP_CMD array"  || fail_t "QBank SCP_CMD array"
! grep -qE '^SSH_CMD="' "$KG"    && ok "KG no bare SSH_CMD string"    || fail_t "KG bare SSH_CMD string found"
! grep -qE '^SSH_CMD="' "$QBANK" && ok "QBank no bare SSH_CMD string" || fail_t "QBank bare SSH_CMD string found"

# ── 3. 函式名稱一致 ────────────────────────────────────────────────────────
section "Function naming consistency"
grep -q 'run_remote()' "$KG"             && ok "KG run_remote()"             || fail_t "KG run_remote() missing"
grep -q 'run_remote()' "$QBANK"          && ok "QBank run_remote()"          || fail_t "QBank run_remote() missing"
grep -q 'preflight()'  "$KG"             && ok "KG preflight()"              || fail_t "KG preflight() missing"
grep -q 'preflight()'  "$QBANK"          && ok "QBank preflight()"           || fail_t "QBank preflight() missing"
grep -q 'require_local_files()' "$KG"    && ok "KG require_local_files()"    || fail_t "KG require_local_files() missing"
grep -q 'require_local_files()' "$QBANK" && ok "QBank require_local_files()" || fail_t "QBank require_local_files() missing"
! grep -q 'rssh'            "$KG" && ok "KG no legacy rssh"            || fail_t "KG legacy rssh found"
! grep -q 'preflight_check' "$KG" && ok "KG no legacy preflight_check" || fail_t "KG legacy preflight_check found"

# ── 4. Deploy pipeline 結構 ────────────────────────────────────────────────
section "Deploy pipeline"
grep -q 'cmd_backup'       "$KG"    && ok "KG deploy calls cmd_backup"    || fail_t "KG deploy missing cmd_backup"
grep -q 'cmd_backup'       "$QBANK" && ok "QBank deploy calls cmd_backup" || fail_t "QBank deploy missing cmd_backup"
grep -q 'for i in 1 2 3 4 5' "$KG"    && ok "KG health retry loop"    || fail_t "KG health retry loop missing"
grep -q 'for i in 1 2 3 4 5' "$QBANK" && ok "QBank health retry loop" || fail_t "QBank health retry loop missing"
grep -q 'local http_code'  "$KG"    && ok "KG http_code variable"    || fail_t "KG http_code variable missing"
grep -q 'local http_code'  "$QBANK" && ok "QBank http_code variable" || fail_t "QBank http_code variable missing"

# ── 5. Blocklist 行為 ──────────────────────────────────────────────────────
section "Blocklist (dangerous commands blocked)"
output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" run "docker system prune -af" 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "KG safe wrapper blocks docker system prune" || fail_t "KG safe wrapper did NOT block docker system prune"

output=$(bash "$WORKSPACE/ops/devops_kg_safe.sh" setup 2>&1 || true)
echo "$output" | grep -q "blocked" && ok "KG safe wrapper blocks setup" || fail_t "KG safe wrapper did NOT block setup"

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

# ── 結果 ──────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
