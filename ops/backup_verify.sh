#!/usr/bin/env bash
# backup_verify.sh — 驗證 backup tarball 可解壓 + SQLite 完整性 + 必要表存在 + row 數
#
# Usage:
#   ./ops/backup_verify.sh                       # 自動找最近一份 backup
#   ./ops/backup_verify.sh path/to/backup.tar.gz # 驗指定檔
#
# Backup 由 devops.sh cmd_backup 寫入：
#   <repo>/backups/data_YYYYMMDD_HHMM.tar.gz
#   內部結構：
#     data_YYYYMMDD_HHMM/
#       users.json
#       pipeline_runs.db        (table: pipeline_runs)
#       judge_log.db            (table: judge_log)
#       users/<uid>/cards.db    (table: card)
#
# Exit:
#   0 — 全部 PASS（warning 不算 fail）
#   1 — 任一 fatal 失敗（解壓失敗 / integrity 損毀 / 必要表缺失）
#
# Env override:
#   KG_BACKUP_DIR   — 覆寫 backup 目錄（預設 <repo>/backups）
#   KG_VERIFY_QUIET — 1 = 只印摘要

set -euo pipefail

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

# ── 路徑解析 ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${KG_BACKUP_DIR:-$REPO_ROOT/backups}"

QUIET="${KG_VERIFY_QUIET:-0}"

# ── 輸出 helper ─────────────────────────────────────────────────────────────
info()    { [[ "$QUIET" == "1" ]] || echo "▶ $*"; }
ok()      { [[ "$QUIET" == "1" ]] || echo "  ✓ $*"; }
warn()    { echo "  ! $*" >&2; }
fail()    { echo "  ✗ $*" >&2; }
section() { [[ "$QUIET" == "1" ]] || { echo ""; echo "── $* ──"; }; }
die()     { echo "✗ $*" >&2; exit 1; }

# ── 計數器 ──────────────────────────────────────────────────────────────────
FATAL=0
WARNINGS=0

mark_fatal()   { FATAL=$((FATAL+1)); fail "$*"; }
mark_warning() { WARNINGS=$((WARNINGS+1)); warn "$*"; }

# ── 依賴檢查 ────────────────────────────────────────────────────────────────
require() {
  command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1"
}
require tar
require sqlite3
require find

# ── 1. 找 backup ────────────────────────────────────────────────────────────
find_latest_backup() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  # 用 ls -t 取 mtime 最新（兼容 macOS / Linux，不依賴 find -printf）
  local latest
  latest=$(ls -1t "$dir"/data_*.tar.gz 2>/dev/null | head -n1)
  [[ -n "$latest" ]] || return 1
  echo "$latest"
}

BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" ]]; then
  info "未指定 backup，搜尋 $BACKUP_DIR/data_*.tar.gz"
  BACKUP_FILE="$(find_latest_backup "$BACKUP_DIR")" || die "找不到任何 backup（$BACKUP_DIR/data_*.tar.gz）"
  info "選用最近一份：$BACKUP_FILE"
fi

[[ -f "$BACKUP_FILE" ]] || die "backup 檔不存在：$BACKUP_FILE"

# ── 2. 臨時目錄 + 退場清理 ──────────────────────────────────────────────────
TMPDIR_BV="$(mktemp -d -t kg_backup_verify_XXXXXX)"
cleanup() {
  if [[ -n "${TMPDIR_BV:-}" && -d "$TMPDIR_BV" ]]; then
    rm -rf "$TMPDIR_BV"
  fi
}
trap cleanup EXIT INT TERM

section "解壓 backup"
info "解壓到 $TMPDIR_BV"
tar_err="$TMPDIR_BV/.tar_err"
if ! tar -xzf "$BACKUP_FILE" -C "$TMPDIR_BV" 2>"$tar_err"; then
  echo "✗ 解壓失敗：${BACKUP_FILE}（tar -xzf 失敗）" >&2
  [[ -s "$tar_err" ]] && sed 's/^/    /' "$tar_err" >&2
  exit 1
fi
ok "解壓成功"

# 取頂層 data_* 目錄
DATA_ROOT="$(find "$TMPDIR_BV" -mindepth 1 -maxdepth 1 -type d -name 'data_*' | head -n1)"
if [[ -z "$DATA_ROOT" ]]; then
  # 容錯：可能沒包 data_ prefix，直接用 tmpdir 第一層唯一目錄
  DATA_ROOT="$(find "$TMPDIR_BV" -mindepth 1 -maxdepth 1 -type d | head -n1)"
fi
[[ -n "$DATA_ROOT" && -d "$DATA_ROOT" ]] || die "backup 結構異常：找不到頂層 data_ 目錄"
ok "data root: $(basename "$DATA_ROOT")"

# ── 3. SQLite integrity_check ──────────────────────────────────────────────
section "SQLite integrity_check"
DB_COUNT=0
while IFS= read -r -d '' db; do
  DB_COUNT=$((DB_COUNT+1))
  rel="${db#$DATA_ROOT/}"
  # `|| true`：db 損毀時 sqlite3 回非零(如 26 NOTADB),在 set -e 下命令
  # 替換賦值會直接 exit,跳過下方 integrity 損毀 的 fatal 標記。吞掉碼讓
  # 錯誤文字落入 result,由 == "ok" 分支判定。
  result=$(sqlite3 "$db" "PRAGMA integrity_check;" 2>&1 || true)
  if [[ "$result" == "ok" ]]; then
    ok "integrity ok: $rel"
  else
    mark_fatal "integrity 損毀: $rel"
    echo "      $result" >&2
  fi
done < <(find "$DATA_ROOT" -name "*.db" -print0)

if [[ "$DB_COUNT" -eq 0 ]]; then
  mark_warning "backup 內未找到任何 .db 檔"
fi

# ── 4. 必要表存在性 ────────────────────────────────────────────────────────
section "必要表 / 資料源檢查"

# users — 存於 users.json（非 SQLite）
USERS_JSON="$DATA_ROOT/users.json"
if [[ -f "$USERS_JSON" ]]; then
  ok "users.json 存在"
else
  mark_fatal "缺少 users.json"
fi

# 在指定 db 內檢查單一 table 是否存在；回傳 0=存在 / 1=不在 / 2=db 缺
check_table() {
  local db="$1" table="$2"
  [[ -f "$db" ]] || return 2
  local found
  found=$(sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name='$table' LIMIT 1;" 2>/dev/null || true)
  [[ "$found" == "$table" ]]
}

# row count（fail-soft：db/table 不在則回 -1）
row_count() {
  local db="$1" table="$2"
  [[ -f "$db" ]] || { echo -1; return; }
  local n
  n=$(sqlite3 "$db" "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo -1)
  echo "${n:--1}"
}

# pipeline_runs
PR_DB="$DATA_ROOT/pipeline_runs.db"
if check_table "$PR_DB" "pipeline_runs"; then
  n=$(row_count "$PR_DB" "pipeline_runs")
  if [[ "$n" -gt 0 ]]; then
    ok "table pipeline_runs (rows=$n)"
  else
    mark_warning "table pipeline_runs 存在但 rows=0"
  fi
else
  mark_fatal "缺少 pipeline_runs 表（檔: pipeline_runs.db）"
fi

# judge_log
JL_DB="$DATA_ROOT/judge_log.db"
if check_table "$JL_DB" "judge_log"; then
  n=$(row_count "$JL_DB" "judge_log")
  if [[ "$n" -gt 0 ]]; then
    ok "table judge_log (rows=$n)"
  else
    mark_warning "table judge_log 存在但 rows=0"
  fi
else
  mark_fatal "缺少 judge_log 表（檔: judge_log.db）"
fi

# vocabulary cards — 至少一份 users/<uid>/cards.db 含 table card
CARD_DBS=()
if [[ -d "$DATA_ROOT/users" ]]; then
  while IFS= read -r -d '' cdb; do
    CARD_DBS+=("$cdb")
  done < <(find "$DATA_ROOT/users" -mindepth 2 -maxdepth 2 -name 'cards.db' -print0)
fi

if [[ "${#CARD_DBS[@]}" -eq 0 ]]; then
  mark_warning "未找到任何 users/<uid>/cards.db（可能尚無用戶）"
else
  cards_table_ok=0
  total_cards=0
  for cdb in "${CARD_DBS[@]}"; do
    if check_table "$cdb" "card"; then
      cards_table_ok=$((cards_table_ok+1))
      n=$(row_count "$cdb" "card")
      [[ "$n" -gt 0 ]] && total_cards=$((total_cards+n))
    fi
  done
  if [[ "$cards_table_ok" -gt 0 ]]; then
    ok "table card: ${cards_table_ok}/${#CARD_DBS[@]} 份 cards.db OK（total rows=${total_cards}）"
    if [[ "$total_cards" -eq 0 ]]; then
      mark_warning "所有 cards.db 都是空的（rows=0）"
    fi
  else
    mark_fatal "${#CARD_DBS[@]} 份 cards.db 內皆無 card 表"
  fi
fi

# ── 5. 摘要 ────────────────────────────────────────────────────────────────
section "摘要"
echo "  backup file : $BACKUP_FILE"
echo "  size        : $(ls -lh "$BACKUP_FILE" 2>/dev/null | awk '{print $5}')"
echo "  databases   : $DB_COUNT"
echo "  card dbs    : ${#CARD_DBS[@]}"
echo "  warnings    : $WARNINGS"
echo "  fatal       : $FATAL"

if [[ "$FATAL" -gt 0 ]]; then
  echo ""
  echo "✗ backup verify FAILED ($FATAL fatal, $WARNINGS warnings)"
  exit 1
fi

echo ""
if [[ "$WARNINGS" -gt 0 ]]; then
  echo "✓ backup verify PASSED with $WARNINGS warnings"
else
  echo "✓ backup verify PASSED (clean)"
fi
exit 0
