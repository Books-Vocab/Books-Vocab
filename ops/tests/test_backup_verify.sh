#!/usr/bin/env bash
# test_backup_verify.sh — backup_verify.sh 單元測試
#
# 透過 KG_BACKUP_DIR 注入 mock backup 目錄，覆蓋情境：
#   1. 健康 backup → exit 0
#   2. 顯式路徑參數 → exit 0
#   3. 解壓失敗（非 gzip 內容）→ exit 1
#   4. 缺 users.json → exit 1
#   5. SQLite 損毀 → exit 1
#   6. 缺 pipeline_runs 表 → exit 1
#   7. 缺 judge_log 表 → exit 1
#   8. pipeline_runs/judge_log rows=0 → exit 0 + warning
#   9. 找不到 backup → exit 1（die）
#  10. 缺 cards.db → exit 0 + warning（無用戶情境）

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$WORKTREE/ops/backup_verify.sh"
TMPDIR="$(mktemp -d -t kg_bv_test_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "✗ test 需要 $1，未安裝" >&2; exit 1; }
}
require_cmd sqlite3
require_cmd tar

# ── 建一份「健康」mock backup tarball 到指定目錄 ────────────────────────────
# 用法：build_backup <out_dir> <stamp> [opt:root=<name>|skip_users_json|corrupt_cards|skip_pipeline_table|skip_judge_table|empty_logs|skip_cards]
build_backup() {
  local out_dir="$1" stamp="$2"
  shift 2
  local opts=("$@")
  mkdir -p "$out_dir"
  local stage="$TMPDIR/stage_$RANDOM"
  local root_name="data_$stamp"
  local opt
  for opt in "${opts[@]}"; do
    [[ "$opt" == root=* ]] && root_name="${opt#root=}"
  done
  local root="$stage/$root_name"
  mkdir -p "$root/users/u1"

  # users.json
  if ! printf '%s\n' "${opts[@]}" | grep -qx skip_users_json; then
    echo '[{"id":"u1","email":"a@b"}]' > "$root/users.json"
  fi

  # pipeline_runs.db
  if ! printf '%s\n' "${opts[@]}" | grep -qx skip_pipeline_table; then
    sqlite3 "$root/pipeline_runs.db" \
      "CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, run_id TEXT);"
    if ! printf '%s\n' "${opts[@]}" | grep -qx empty_logs; then
      sqlite3 "$root/pipeline_runs.db" "INSERT INTO pipeline_runs (run_id) VALUES ('r1'),('r2');"
    fi
  else
    sqlite3 "$root/pipeline_runs.db" "CREATE TABLE other (id INTEGER);"
  fi

  # judge_log.db
  if ! printf '%s\n' "${opts[@]}" | grep -qx skip_judge_table; then
    sqlite3 "$root/judge_log.db" \
      "CREATE TABLE judge_log (id INTEGER PRIMARY KEY, verdict TEXT);"
    if ! printf '%s\n' "${opts[@]}" | grep -qx empty_logs; then
      sqlite3 "$root/judge_log.db" "INSERT INTO judge_log (verdict) VALUES ('accept');"
    fi
  else
    sqlite3 "$root/judge_log.db" "CREATE TABLE other (id INTEGER);"
  fi

  # users/u1/cards.db
  if ! printf '%s\n' "${opts[@]}" | grep -qx skip_cards; then
    sqlite3 "$root/users/u1/cards.db" \
      "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT);"
    sqlite3 "$root/users/u1/cards.db" \
      "INSERT INTO card (id, content) VALUES ('c1','hello'),('c2','world');"
  fi

  local tarball="$out_dir/data_${stamp}.tar.gz"
  tar -czf "$tarball" -C "$stage" "$root_name"

  # corrupt_cards：解壓後將 cards.db 改成亂碼 → 重新打包
  if printf '%s\n' "${opts[@]}" | grep -qx corrupt_cards; then
    # 直接寫一份亂掉的 .db 重打
    printf 'CORRUPTED\x00BADDATA' > "$root/users/u1/cards.db"
    tar -czf "$tarball" -C "$stage" "$root_name"
  fi

  echo "$tarball"
}

# 建立只應在 member policy 階段被拒絕的 archive。-P 保留絕對/父層路徑，-s
# 讓 bsdtar 能在不經過檔案系統解析的情況下加入逃逸 member。
build_policy_archive() {
  local out_dir="$1" stamp="$2" policy="$3"
  local stage="$TMPDIR/policy_stage_$RANDOM"
  local root_name="data_$stamp"
  local root="$stage/$root_name"
  local plain="$TMPDIR/policy_$RANDOM.tar"
  local outside="$TMPDIR/policy_outside_$RANDOM"
  mkdir -p "$out_dir" "$root"
  POLICY_SENTINEL=""

  case "$policy" in
    sibling)
      mkdir -p "$stage/sibling"
      printf 'SIBLING\n' > "$stage/sibling/payload"
      tar -P -cf "$plain" -C "$stage" "$root_name" sibling
      ;;
    parent)
      printf 'ESCAPE\n' > "$stage/payload"
      tar -P -cf "$plain" -C "$stage" "$root_name"
      tar -P -rf "$plain" -C "$stage" -s "#^payload\$#${root_name}/../outside#" payload
      ;;
    absolute)
      printf 'ESCAPE\n' > "$stage/payload"
      tar -P -cf "$plain" -C "$stage" "$root_name"
      tar -P -rf "$plain" -C "$stage" -s "#^payload\$#/tmp/kg_backup_verify_escape_$RANDOM#" payload
      ;;
    external-symlink)
      mkdir -p "$outside"
      POLICY_SENTINEL="$outside/sentinel"
      printf 'KEEP\n' > "$POLICY_SENTINEL"
      ln -s "$outside" "$root/escape"
      printf 'PAYLOAD\n' > "$stage/payload"
      tar -P -cf "$plain" -C "$stage" "$root_name"
      tar -P -rf "$plain" -C "$stage" -s "#^payload\$#${root_name}/escape/payload#" payload
      ;;
    external-hardlink)
      mkdir -p "$stage/sibling"
      POLICY_SENTINEL="$stage/sibling/sentinel"
      printf 'KEEP\n' > "$POLICY_SENTINEL"
      ln "$POLICY_SENTINEL" "$root/external_hard"
      tar -P -cf "$plain" -C "$stage" "$root_name" sibling
      ;;
    *)
      echo "unknown policy fixture: $policy" >&2
      return 1
      ;;
  esac

  local tarball="$out_dir/data_${stamp}_${policy}.tar.gz"
  gzip -c "$plain" > "$tarball"
  echo "$tarball"
}

# 跑一次 verify，回傳 rc，輸出存到 logfile
run_verify() {
  local backup_dir="$1"
  local arg="${2:-}"
  local logfile="$TMPDIR/log_$RANDOM.txt"
  if [[ -n "$arg" ]]; then
    KG_BACKUP_DIR="$backup_dir" KG_VERIFY_QUIET=0 "$SCRIPT" "$arg" >"$logfile" 2>&1
  else
    KG_BACKUP_DIR="$backup_dir" KG_VERIFY_QUIET=0 "$SCRIPT" >"$logfile" 2>&1
  fi
  local rc=$?
  echo "$rc|$logfile"
}

run_help() {
  local logfile="$TMPDIR/log_$RANDOM.txt"
  "$SCRIPT" --help >"$logfile" 2>&1
  local rc=$?
  echo "$rc|$logfile"
}

assert_rc() {
  local name="$1" expected="$2" got="$3" logfile="$4"
  if [[ "$got" == "$expected" ]]; then
    ok "$name (rc=$got)"
  else
    fail_t "$name expect rc=$expected got rc=$got"
    sed 's/^/      /' "$logfile" >&2
  fi
}

assert_log_contains() {
  local name="$1" needle="$2" logfile="$3"
  if grep -q -- "$needle" "$logfile"; then
    ok "$name contains \"$needle\""
  else
    fail_t "$name missing \"$needle\""
    sed 's/^/      /' "$logfile" >&2
  fi
}

assert_log_not_contains() {
  local name="$1" needle="$2" logfile="$3"
  if grep -q -- "$needle" "$logfile"; then
    fail_t "$name unexpectedly contains \"$needle\""
    sed 's/^/      /' "$logfile" >&2
  else
    ok "$name excludes \"$needle\""
  fi
}

# ── Syntax 先過 ────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$SCRIPT" && ok "backup_verify.sh syntax" || fail_t "backup_verify.sh syntax"

section "help surface"
out=$(run_help); rc="${out%%|*}"; log="${out##*|}"
assert_rc "help exits 0" 0 "$rc" "$log"
assert_log_contains "help has usage" "Usage:" "$log"

# ── 1. 健康 backup（auto-find）→ pass ──────────────────────────────────────
section "case 1: healthy backup, auto-find"
D1="$TMPDIR/c1"
build_backup "$D1" 20260101_0100 >/dev/null
out=$(run_verify "$D1"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "auto-find healthy" 0 "$rc" "$log"
assert_log_contains "auto-find healthy" "backup verify PASSED" "$log"

# ── 1b. 現役 production root 名稱 → pass ────────────────────────────────────
section "case 1b: kg-data root is accepted"
D1B="$TMPDIR/c1b"
build_backup "$D1B" 20260101_0130 root=kg-data >/dev/null
out=$(run_verify "$D1B"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "kg-data root" 0 "$rc" "$log"
assert_log_contains "kg-data root" "kg-data" "$log"

# ── 2. 顯式路徑參數 → pass ────────────────────────────────────────────────
section "case 2: explicit path arg"
D2="$TMPDIR/c2"
TB2=$(build_backup "$D2" 20260101_0200)
out=$(run_verify "$D2" "$TB2"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "explicit path" 0 "$rc" "$log"

# ── 3. 多份 backup，挑最新 ───────────────────────────────────────────────
section "case 3: pick latest among multiple"
D3="$TMPDIR/c3"
build_backup "$D3" 20260101_0100 >/dev/null
sleep 1
TB3_NEW=$(build_backup "$D3" 20260102_0100)
out=$(run_verify "$D3"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "pick latest" 0 "$rc" "$log"
assert_log_contains "pick latest" "data_20260102_0100" "$log"

# ── 3b. archive member policy：所有案例都應在解壓前拒絕 ─────────────────────
for policy in sibling parent absolute external-symlink external-hardlink; do
  section "case 3${policy}: archive member policy rejects before extraction"
  DP="$TMPDIR/policy_$policy"
  TBP=$(build_policy_archive "$DP" "20260102_${RANDOM}" "$policy")
  out=$(run_verify "$DP" "$TBP"); rc="${out%%|*}"; log="${out##*|}"
  assert_rc "$policy rejected" 1 "$rc" "$log"
  assert_log_contains "$policy policy refusal" "archive member policy" "$log"
  assert_log_not_contains "$policy pre-extraction refusal" "解壓到" "$log"
  if [[ -n "$POLICY_SENTINEL" ]]; then
    if grep -qx 'KEEP' "$POLICY_SENTINEL"; then
      ok "$policy sentinel unchanged"
    else
      fail_t "$policy sentinel changed"
    fi
  fi
done

# ── 4. 解壓失敗 ─────────────────────────────────────────────────────────
section "case 4: tar corrupt → fatal"
D4="$TMPDIR/c4"
mkdir -p "$D4"
printf 'NOT A TAR GZ' > "$D4/data_20260103_0100.tar.gz"
out=$(run_verify "$D4"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "tar corrupt" 1 "$rc" "$log"
assert_log_contains "tar corrupt" "解壓失敗" "$log"

# ── 5. 缺 users.json → fatal ───────────────────────────────────────────
section "case 5: missing users.json → fatal"
D5="$TMPDIR/c5"
build_backup "$D5" 20260104_0100 skip_users_json >/dev/null
out=$(run_verify "$D5"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "missing users.json" 1 "$rc" "$log"
assert_log_contains "missing users.json" "缺少 users.json" "$log"

# ── 6. SQLite 損毀 → fatal ─────────────────────────────────────────────
section "case 6: sqlite corrupt → fatal"
D6="$TMPDIR/c6"
build_backup "$D6" 20260105_0100 corrupt_cards >/dev/null
out=$(run_verify "$D6"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "sqlite corrupt" 1 "$rc" "$log"
assert_log_contains "sqlite corrupt" "integrity 損毀" "$log"

# ── 7. 缺 pipeline_runs 表 → fatal ────────────────────────────────────
section "case 7: missing pipeline_runs table → fatal"
D7="$TMPDIR/c7"
build_backup "$D7" 20260106_0100 skip_pipeline_table >/dev/null
out=$(run_verify "$D7"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "missing pipeline_runs" 1 "$rc" "$log"
assert_log_contains "missing pipeline_runs" "缺少 pipeline_runs" "$log"

# ── 8. 缺 judge_log 表 → fatal ────────────────────────────────────────
section "case 8: missing judge_log table → fatal"
D8="$TMPDIR/c8"
build_backup "$D8" 20260107_0100 skip_judge_table >/dev/null
out=$(run_verify "$D8"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "missing judge_log" 1 "$rc" "$log"
assert_log_contains "missing judge_log" "缺少 judge_log" "$log"

# ── 9. logs rows=0 → pass + warning ───────────────────────────────────
section "case 9: pipeline/judge rows=0 → warning, exit 0"
D9="$TMPDIR/c9"
build_backup "$D9" 20260108_0100 empty_logs >/dev/null
out=$(run_verify "$D9"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "empty logs warning" 0 "$rc" "$log"
assert_log_contains "empty logs warning" "rows=0" "$log"
assert_log_contains "empty logs warning" "PASSED with" "$log"

# ── 10. 找不到 backup → exit 1 ─────────────────────────────────────────
section "case 10: no backup found → die"
D10="$TMPDIR/c10_empty"
mkdir -p "$D10"
out=$(run_verify "$D10"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "no backup found" 1 "$rc" "$log"
assert_log_contains "no backup found" "找不到任何 backup" "$log"

# ── 11. 缺 cards.db（無用戶）→ pass + warning ─────────────────────────
section "case 11: no cards.db → warning, exit 0"
D11="$TMPDIR/c11"
build_backup "$D11" 20260109_0100 skip_cards >/dev/null
out=$(run_verify "$D11"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "no cards.db" 0 "$rc" "$log"
assert_log_contains "no cards.db" "未找到任何 users" "$log"

# ── 結果 ───────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
