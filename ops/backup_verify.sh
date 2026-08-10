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
# shellcheck source=lib/signal_traps.sh
source "$SCRIPT_DIR/lib/signal_traps.sh"

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
kg_install_signal_traps cleanup backup_verify

# ── 3. archive member policy（必須先於任何解壓） ─────────────────────────────
ARCHIVE_ROOT=""
ARCHIVE_MEMBERS=()
ARCHIVE_LINK_MEMBERS=()
ARCHIVE_LINK_TARGETS=()
ARCHIVE_LINK_TYPES=()
ARCHIVE_RESOLVED=""
ARCHIVE_LINK_INDEX=-1

archive_policy_die() {
  die "archive member policy 拒絕：$*"
}

archive_member_exists() {
  local wanted="$1"
  local member
  ((${#ARCHIVE_MEMBERS[@]} > 0)) || return 1
  for member in "${ARCHIVE_MEMBERS[@]}"; do
    [[ "$member" == "$wanted" ]] && return 0
  done
  return 1
}

archive_validate_member() {
  local raw_member="$1"
  local member="$raw_member"
  local remainder component root

  [[ "$member" != *//* ]] || archive_policy_die "拒絕空 path component：$raw_member"
  [[ "$member" == */ ]] && member="${member%/}"
  [[ -n "$member" ]] || archive_policy_die "空 member"
  [[ "$member" != /* ]] || archive_policy_die "拒絕絕對路徑：$raw_member"
  case "$member" in
    *[[:space:]]*) archive_policy_die "拒絕含空白的 member（無法安全解析 type）：$raw_member" ;;
  esac

  remainder="$member"
  while :; do
    if [[ "$remainder" == */* ]]; then
      component="${remainder%%/*}"
      remainder="${remainder#*/}"
    else
      component="$remainder"
      remainder=""
    fi
    [[ -n "$component" ]] || archive_policy_die "拒絕空 path component：$raw_member"
    [[ "$component" != "." && "$component" != ".." ]] || \
      archive_policy_die "拒絕 . / .. path component：$raw_member"
    [[ -n "$remainder" ]] || break
  done

  root="${member%%/*}"
  if [[ -z "$ARCHIVE_ROOT" ]]; then
    ARCHIVE_ROOT="$root"
  elif [[ "$root" != "$ARCHIVE_ROOT" ]]; then
    archive_policy_die "拒絕額外 top-level sibling：${root}（資料根應唯一為 ${ARCHIVE_ROOT}）"
  fi

  archive_member_exists "$member" && \
    archive_policy_die "拒絕重複 member：$member"
  ARCHIVE_MEMBERS+=("$member")
  printf '%s\n' "$member" >> "$ARCHIVE_CANONICAL_FILE"
}

archive_find_link() {
  local wanted="$1"
  local i
  ARCHIVE_LINK_INDEX=-1
  for ((i=0; i<${#ARCHIVE_LINK_MEMBERS[@]}; i++)); do
    if [[ "${ARCHIVE_LINK_MEMBERS[$i]}" == "$wanted" ]]; then
      ARCHIVE_LINK_INDEX=$i
      return 0
    fi
  done
  return 1
}

# 將 archive path 以 lexical path resolution + 已知 symlink graph 展開。
# 只要有一段穿出唯一資料根，或 symlink cycle / 絕對 target，就 fail closed。
archive_resolve_path() {
  local path="$1"
  local component candidate target
  local i hops=0
  local -a pending=()
  # path 本身會帶著唯一 root；從空 stack 開始才能正確識別 root/link。
  local -a stack=()
  local -a target_parts=()

  [[ "$path" != /* && -n "$path" ]] || return 1
  [[ "$path" != *"//"* ]] || return 1
  IFS='/' read -r -a pending <<< "$path"

  while ((${#pending[@]} > 0)); do
    component="${pending[0]}"
    pending=("${pending[@]:1}")
    [[ -n "$component" ]] || return 1
    if [[ "$component" == "." ]]; then
      continue
    elif [[ "$component" == ".." ]]; then
      ((${#stack[@]} > 1)) || return 1
      local stack_last=$(( ${#stack[@]} - 1 ))
      unset "stack[$stack_last]"
      continue
    fi

    if ((${#stack[@]} == 0)); then
      candidate="$component"
    else
      candidate="${stack[0]}"
      for ((i=1; i<${#stack[@]}; i++)); do
        candidate="$candidate/${stack[$i]}"
      done
      candidate="$candidate/$component"
    fi

    if archive_find_link "$candidate"; then
      hops=$((hops+1))
      ((hops <= 40)) || return 1
      target="${ARCHIVE_LINK_TARGETS[$ARCHIVE_LINK_INDEX]}"
      [[ -n "$target" && "$target" != /* && "$target" != *"//"* ]] || return 1
      IFS='/' read -r -a target_parts <<< "$target"
      if ((${#pending[@]} > 0)); then
        pending=("${target_parts[@]}" "${pending[@]}")
      else
        pending=("${target_parts[@]}")
      fi
      continue
    fi

    stack+=("$component")
  done

  local IFS=/
  ARCHIVE_RESOLVED="${stack[*]}"
}

archive_validate_links_and_members() {
  local i member target hard_path

  for ((i=0; i<${#ARCHIVE_LINK_MEMBERS[@]}; i++)); do
    member="${ARCHIVE_LINK_MEMBERS[$i]}"
    target="${ARCHIVE_LINK_TARGETS[$i]}"
    if [[ "${ARCHIVE_LINK_TYPES[$i]}" == "h" ]]; then
      [[ "$target" != /* && -n "$target" ]] || \
        archive_policy_die "拒絕外指 hardlink：$member -> $target"
      if [[ "$target" == "$ARCHIVE_ROOT" || "$target" == "$ARCHIVE_ROOT/"* ]]; then
        hard_path="$target"
      else
        hard_path="$ARCHIVE_ROOT/$target"
      fi
      archive_resolve_path "$hard_path" || \
        archive_policy_die "拒絕外指 hardlink：$member -> $target"
      archive_member_exists "$hard_path" || \
        archive_policy_die "拒絕指向不存在 member 的 hardlink：$member -> $target"
    fi
  done

  # 不只檢查 link target；每一個後續 member 也必須在展開 symlink graph 後仍留在根內。
  for member in "${ARCHIVE_MEMBERS[@]}"; do
    archive_resolve_path "$member" || \
      archive_policy_die "拒絕可穿出資料根的 symlink/path：$member"
  done
}

section "archive member policy"
ARCHIVE_LIST_FILE="$TMPDIR_BV/.archive_members"
ARCHIVE_DETAIL_FILE="$TMPDIR_BV/.archive_details"
ARCHIVE_CANONICAL_FILE="$TMPDIR_BV/.archive_canonical"
ARCHIVE_TAR_ERR="$TMPDIR_BV/.archive_tar_err"
: > "$ARCHIVE_CANONICAL_FILE"

if ! tar -P -tzf "$BACKUP_FILE" >"$ARCHIVE_LIST_FILE" 2>"$ARCHIVE_TAR_ERR"; then
  archive_policy_die "無法列舉 archive members（解壓失敗前置檢查）"
fi
if ! tar -P -tvzf "$BACKUP_FILE" >"$ARCHIVE_DETAIL_FILE" 2>>"$ARCHIVE_TAR_ERR"; then
  archive_policy_die "無法讀取 archive member type（解壓失敗前置檢查）"
fi

while IFS= read -r archive_member || [[ -n "$archive_member" ]]; do
  archive_validate_member "$archive_member"
done < "$ARCHIVE_LIST_FILE"

[[ -n "$ARCHIVE_ROOT" ]] || archive_policy_die "archive 沒有任何 member"
if [[ ! "$ARCHIVE_ROOT" =~ ^data_[0-9]{8}_[0-9]{4}$ && "$ARCHIVE_ROOT" != "kg-data" ]]; then
  archive_policy_die "拒絕不合法資料根名稱：${ARCHIVE_ROOT}（只接受 data_YYYYMMDD_HHMM 或 kg-data）"
fi

duplicate_member="$(LC_ALL=C sort "$ARCHIVE_CANONICAL_FILE" | LC_ALL=C uniq -d | head -n 1)"
[[ -z "$duplicate_member" ]] || archive_policy_die "拒絕重複 member：$duplicate_member"

while IFS= read -r archive_detail || [[ -n "$archive_detail" ]]; do
  archive_type="${archive_detail:0:1}"
  case "$archive_type" in
    d|-)
      ;;
    l|h)
      if [[ "$archive_type" == "l" ]]; then
        archive_marker=" -> "
      else
        archive_marker=" link to "
      fi
      [[ "$archive_detail" == *"$archive_marker"* ]] || \
        archive_policy_die "無法解析 link member：$archive_detail"
      archive_prefix="${archive_detail%%$archive_marker*}"
      archive_link_member="${archive_prefix##* }"
      archive_link_target="${archive_detail##*$archive_marker}"
      archive_member_exists "$archive_link_member" || \
        archive_policy_die "type listing 找不到 member：$archive_link_member"
      [[ -n "$archive_link_target" && "$archive_link_target" != *[[:space:]]* ]] || \
        archive_policy_die "拒絕不合法 link target：$archive_link_member -> $archive_link_target"
      ARCHIVE_LINK_MEMBERS+=("$archive_link_member")
      ARCHIVE_LINK_TARGETS+=("$archive_link_target")
      ARCHIVE_LINK_TYPES+=("$archive_type")
      ;;
    b|c|p|s|*)
      archive_policy_die "拒絕特殊 archive member type '$archive_type'：$archive_detail"
      ;;
  esac
done < "$ARCHIVE_DETAIL_FILE"

archive_validate_links_and_members
ok "archive members 合法（root=${ARCHIVE_ROOT}，members=${#ARCHIVE_MEMBERS[@]}）"

# ── 4. 解壓 backup ──────────────────────────────────────────────────────────
section "解壓 backup"
info "解壓到 $TMPDIR_BV"
tar_err="$TMPDIR_BV/.tar_err"
if ! tar -xzf "$BACKUP_FILE" -C "$TMPDIR_BV" 2>"$tar_err"; then
  echo "✗ 解壓失敗：${BACKUP_FILE}（tar -xzf 失敗）" >&2
  [[ -s "$tar_err" ]] && sed 's/^/    /' "$tar_err" >&2
  exit 1
fi
ok "解壓成功"

DATA_ROOT="$TMPDIR_BV/$ARCHIVE_ROOT"
[[ -d "$DATA_ROOT" ]] || die "backup 結構異常：找不到合法資料根目錄 $ARCHIVE_ROOT"
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
