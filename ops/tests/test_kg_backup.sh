#!/usr/bin/env bash
# test_kg_backup.sh — kg_backup.sh 回歸測試（Issue #2250）
#
# aws 以 PATH stub 取代（上傳串流寫成本地檔），不碰 S3、不碰正式資料。情境：
#   1. WAL 模式 DB 的已提交 rows 只在 -wal（holder 連線持有、auto-checkpoint 關閉）
#      → 還原後 rows 全在且 integrity_check=ok；已關閉且無 -wal/-shm 的 DB（Linux
#      backend 關閉後的常態）也能快照；live 主檔不被 checkpoint；非 DB 檔／symlink／
#      空目錄保留；archive 無 -wal/-shm/-journal/._*/.DS_Store；log 的 bytes/sha256
#      = 實際上傳；staging 清空
#   1b. writer 被 kill -9 留下孤兒 WAL → 快照含其 rows，live 主檔仍不被 checkpoint
#   2. 非空亂碼 *.db → exit≠0、aws 未被呼叫、log exit=<非零> 指名該檔、staging 清空
#   3. 走訪失敗（不可讀子目錄）→ 同樣 fail-closed（root 執行時跳過）
#   4. sqlite3 不在 PATH → exit=3、aws 未被呼叫
#   5. 上傳中收到 TERM → log exit=143、staging 清空

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$WORKTREE/ops/kg_backup.sh"
STATUS="$WORKTREE/ops/backup_status.sh"
T="$(mktemp -d -t kg_backup_test_XXXXXX)"
HOLDER_PID=""

cleanup() {
  if [[ -n "$HOLDER_PID" ]]; then
    exec 3>&-
    kill "$HOLDER_PID" 2>/dev/null
    wait "$HOLDER_PID" 2>/dev/null
  fi
  chmod -R u+rwx "$T" 2>/dev/null
  rm -rf "$T"
}
trap cleanup EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
check()  { local name="$1"; shift; if "$@"; then ok "$name"; else fail_t "$name"; fi; }
section(){ echo ""; echo "── $* ──"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "✗ test 需要 $1，未安裝" >&2; exit 1; }
}
require_cmd sqlite3
require_cmd tar
require_cmd mkfifo

# launchd plist 以 /bin/bash 執行（macOS 上是 3.2）；照實用同一支直譯器。
BASH_BIN=/bin/bash
[[ -x "$BASH_BIN" ]] || BASH_BIN="$(command -v bash)"

mkdir -p "$T/bin" "$T/tmp"
if ! command -v sha256sum >/dev/null 2>&1; then
  require_cmd shasum
  printf '#!/bin/sh\nexec shasum -a 256 "$@"\n' >"$T/bin/sha256sum"
  chmod +x "$T/bin/sha256sum"
fi
# aws stub：記錄參數、把上傳串流寫成 upload.tgz。設 AWS_STUB_GATE 時先留下
# started 記號，讀完串流後等到 gate 檔出現才結束（讓 TERM 落在上傳期間）。
cat >"$T/bin/aws" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >>"$T/aws.calls"
if [ -n "\${AWS_STUB_GATE:-}" ]; then : >"\$AWS_STUB_GATE.started"; fi
cat >"$T/upload.tgz"
if [ -n "\${AWS_STUB_GATE:-}" ]; then
  i=0
  while [ ! -e "\$AWS_STUB_GATE" ] && [ \$i -lt 300 ]; do sleep 0.1; i=\$((i+1)); done
fi
EOF
chmod +x "$T/bin/aws"
PATH="$T/bin:$PATH"; export PATH

LOG="$T/backup.log"
backup_env() { env KG_DATA_DIR="$1" KG_BACKUP_LOG="$LOG" KG_BACKUP_BUCKET=test TMPDIR="$T/tmp" "${@:2}"; }
reset_run()  { rm -rf "$T/aws.calls" "$T/upload.tgz" "$LOG" "$T/restore" "$T/run.out"; }
# run_backup <data dir> [VAR=value...]
run_backup() { backup_env "$@" "$BASH_BIN" "$SCRIPT" >"$T/run.out" 2>&1; }
last_log()   { tail -n 1 "$LOG" 2>/dev/null; }
tmp_empty()  { [[ -d "$T/tmp" && -z "$(ls -A "$T/tmp")" ]]; }
no_upload()  { [[ ! -e "$T/aws.calls" && ! -e "$T/upload.tgz" ]]; }
show_run()   { sed 's/^/    | /' "$T/run.out" 2>/dev/null; echo "    | log: $(last_log)"; }
aws_called_once() {
  [[ "$(wc -l <"$T/aws.calls" 2>/dev/null | tr -d ' ')" == 1 ]] &&
    grep -Eqx 's3 cp - s3://test/data/[0-9]{4}-[0-9]{2}-[0-9]{2}\.tar\.gz --region ap-northeast-1 --expected-size 2000000000 --no-progress' "$T/aws.calls"
}
# log_field <name> <value>：最後一筆紀錄含 " <name>=<value> "（value 不可為空）。
log_field()  { [[ -n "$2" && " $(last_log) " == *" $1=$2 "* ]]; }
status_healthy() { "$STATUS" --log "$LOG" --job-state loaded >/dev/null; }
# failure_logged [substring]：最後一筆是 exit=<非零> 紀錄，且 backup_status 判為不健康。
failure_logged() {
  local rec re='^[0-9T:-]+Z exit=[1-9][0-9]* '
  rec="$(last_log)"
  [[ "$rec" =~ $re ]] || return 1
  [[ -z "${1:-}" || "$rec" == *"$1"* ]] || return 1
  ! status_healthy 2>/dev/null
}
listing_rooted() { [[ -s "$T/listing" ]] && ! grep -qv '^kg-data/' "$T/listing"; }
listing_clean()  { ! grep -Eq '(-wal|-shm|-journal)/?$|(^|/)\._|(^|/)\.DS_Store/?$' "$T/listing"; }
same_file()      { cmp -s "$DATA/$1" "$R/$1"; }
symlink_kept()   { [[ -L "$R/current" && "$(readlink "$R/current")" == podcasts/s1 ]]; }
sql_is()         { [[ "$(sqlite3 "$1" "$2" 2>/dev/null)" == "$3" ]]; }
main_untouched() { cmp -s "$DB" "$T/main.before"; }
extract_upload() {
  rm -rf "$T/restore"; mkdir -p "$T/restore"
  tar -xzf "$T/upload.tgz" -C "$T/restore" 2>/dev/null
}

# ── fixture ────────────────────────────────────────────────────────────
DATA="$T/kg-data"
DB="$DATA/users/u1/cards.db"
EV="$DATA/users/u1/review_events.db"
R="$T/restore/kg-data"
N=50
mkdir -p "$DATA/users/u1" "$DATA/podcasts/s1" "$DATA/empty"
printf '[{"id":"u1"}]\n' >"$DATA/users.json"
printf '{"title":"s1"}\n' >"$DATA/podcasts/s1/meta.json"
ln -s podcasts/s1 "$DATA/current"
printf 'appledouble' >"$DATA/._junk"
printf 'finder' >"$DATA/.DS_Store"
printf 'stale rollback journal' >"$DATA/stray.db-journal"
sqlite3 "$DB" "PRAGMA journal_mode=WAL; CREATE TABLE card (id INTEGER PRIMARY KEY, content TEXT); INSERT INTO card (content) VALUES ('baseline');" >/dev/null
# 已關閉的 WAL DB：Linux backend 關閉最後一條連線會刪 -wal/-shm（Apple 版 sqlite3
# 會留著），照前者處理；macOS /usr/bin/sqlite3 的 -readonly 開不了這種檔。
sqlite3 "$EV" "PRAGMA journal_mode=WAL; CREATE TABLE ev (id INTEGER PRIMARY KEY, kind TEXT); INSERT INTO ev (kind) VALUES ('a'), ('b');" >/dev/null
rm -f "$EV-wal" "$EV-shm"

# holder：持有 WAL 連線、關閉 auto-checkpoint，提交 N rows 後回報可見 row 數。
# 它活著時不會 checkpoint，所以 case 1 的斷言必須在它結束前跑完。
mkfifo "$T/holder.in"
sqlite3 "$DB" <"$T/holder.in" >"$T/holder.out" 2>&1 &
HOLDER_PID=$!
exec 3>"$T/holder.in"
{
  echo "PRAGMA wal_autocheckpoint=0;"
  echo "BEGIN;"
  i=1
  while [[ $i -le $N ]]; do echo "INSERT INTO card (content) VALUES ('wal-$i');"; i=$((i+1)); done
  echo "COMMIT;"
  echo ".once '$T/READY'"
  echo "SELECT count(*) FROM card;"
} >&3
i=0
while [[ "$(cat "$T/READY" 2>/dev/null)" != "$((N+1))" && $i -lt 100 ]]; do sleep 0.1; i=$((i+1)); done

section "fixture: committed rows live only in the WAL"
check "holder sees $((N+1)) rows" [ "$(cat "$T/READY" 2>/dev/null)" = "$((N+1))" ]
check "cards.db-wal is non-empty" [ -s "$DB-wal" ]
cp "$DB" "$T/main.before"
cp "$DB" "$T/probe.db"
check "main .db file alone holds only the baseline row" sql_is "$T/probe.db" 'SELECT count(*) FROM card;' 1
check "closed review_events.db has no -wal/-shm" [ ! -e "$EV-wal" -a ! -e "$EV-shm" ]

# ── 1. 成功路徑 ────────────────────────────────────────────────────────
section "case 1: online snapshot captures WAL-only rows"
reset_run
run_backup "$DATA"; rc=$?
if [[ $rc -eq 0 ]]; then ok "exit 0"; else fail_t "exit=$rc"; show_run; fi
check "aws called once with the S3 target" aws_called_once
check "backup_status accepts the log record" status_healthy
up_bytes="$(wc -c <"$T/upload.tgz" 2>/dev/null | tr -d ' ')"
up_sha="$(sha256sum "$T/upload.tgz" 2>/dev/null | awk '{print $1}')"
check "logged bytes match the upload" log_field bytes "$up_bytes"
check "logged sha256 matches the upload" log_field sha256 "$up_sha"

tar -tzf "$T/upload.tgz" >"$T/listing" 2>/dev/null
check "archive root stays kg-data/" listing_rooted
check "no -wal/-shm/-journal/._*/.DS_Store entries" listing_clean

extract_upload
check "restored cards.db has all $((N+1)) committed rows" \
  sql_is "$R/users/u1/cards.db" 'SELECT count(*) FROM card;' "$((N+1))"
check "restored cards.db integrity_check = ok" sql_is "$R/users/u1/cards.db" 'PRAGMA integrity_check;' ok
check "restored closed review_events.db has its 2 rows" sql_is "$R/users/u1/review_events.db" 'SELECT count(*) FROM ev;' 2
check "live cards.db main file not checkpointed" main_untouched
check "users.json byte-identical" same_file users.json
check "podcasts/s1/meta.json byte-identical" same_file podcasts/s1/meta.json
check "symlink recreated with its target" symlink_kept
check "empty directory recreated" [ -d "$R/empty" ]
check "staging removed" tmp_empty

# ── 1b. 孤兒 WAL ───────────────────────────────────────────────────────
# kill -9 不給 holder 關閉時 checkpoint 的機會：WAL 留著已提交 frames、無人持有。
# 一般 read-write 連線最後關閉時會把它 checkpoint 進 live 主檔；備份不得如此。
section "case 1b: orphaned WAL (writer killed) is captured, live DB not checkpointed"
kill -9 "$HOLDER_PID" 2>/dev/null
wait "$HOLDER_PID" 2>/dev/null
exec 3>&-
HOLDER_PID=""
check "cards.db-wal still holds the committed frames" [ -s "$DB-wal" ]
reset_run
run_backup "$DATA"; rc=$?
if [[ $rc -eq 0 ]]; then ok "exit 0"; else fail_t "exit=$rc"; show_run; fi
extract_upload
check "restored cards.db has all $((N+1)) committed rows" \
  sql_is "$R/users/u1/cards.db" 'SELECT count(*) FROM card;' "$((N+1))"
check "live cards.db main file not checkpointed" main_untouched
check "staging removed" tmp_empty

# ── 2. 快照失敗 ────────────────────────────────────────────────────────
section "case 2: garbage *.db fails closed before upload"
mkdir -p "$DATA/users/u2"
printf 'this is not an sqlite database, only garbage bytes\n' >"$DATA/users/u2/bad.db"
reset_run
run_backup "$DATA"; rc=$?
if [[ $rc -ne 0 ]]; then ok "exit $rc"; else fail_t "exit 0 on a garbage db"; show_run; fi
check "aws never called, nothing uploaded" no_upload
check "log records exit=<nonzero> naming users/u2/bad.db" failure_logged "users/u2/bad.db"
check "staging removed" tmp_empty
rm -rf "$DATA/users/u2"

# ── 3. 走訪失敗 ────────────────────────────────────────────────────────
section "case 3: unreadable subdirectory fails the walk"
if [[ "$(id -u)" -eq 0 ]]; then
  ok "skipped (root ignores directory permissions)"
else
  WALK="$T/walk-data"
  mkdir -p "$WALK/locked"
  printf 'x' >"$WALK/readable.json"
  chmod 000 "$WALK/locked"
  reset_run
  run_backup "$WALK"; rc=$?
  chmod 700 "$WALK/locked"
  if [[ $rc -ne 0 ]]; then ok "exit $rc"; else fail_t "exit 0 with an unreadable subdirectory"; show_run; fi
  check "aws never called, nothing uploaded" no_upload
  check "log records exit=<nonzero>" failure_logged
  check "staging removed" tmp_empty
fi

# ── 4. sqlite3 缺席 ────────────────────────────────────────────────────
section "case 4: missing sqlite3 fails closed"
mkdir -p "$T/minbin"
ln -s "$T/bin/aws" "$T/minbin/aws"
for tool in date mktemp dirname basename find mkdir ln cp readlink rm mv tar gzip tee sha256sum awk wc cat sleep; do
  p="$(command -v "$tool")" && ln -s "$p" "$T/minbin/$tool"
done
reset_run
run_backup "$DATA" PATH="$T/minbin"; rc=$?
if [[ $rc -eq 3 ]]; then ok "exit 3"; else fail_t "exit=$rc (want 3)"; show_run; fi
check "aws never called, nothing uploaded" no_upload
check "log records exit=3 sqlite3 missing" failure_logged "exit=3 sqlite3 missing"
check "staging removed" tmp_empty

# ── 5. 訊號 ────────────────────────────────────────────────────────────
section "case 5: TERM during upload records exit=143 and removes staging"
reset_run
GATE="$T/gate"
# 直接背景執行 env（不經 shell function，否則 $! 是包一層的 subshell）：
# env exec 成 bash，所以 $! 就是受測 script 本身。
env KG_DATA_DIR="$DATA" KG_BACKUP_LOG="$LOG" KG_BACKUP_BUCKET=test TMPDIR="$T/tmp" \
  AWS_STUB_GATE="$GATE" "$BASH_BIN" "$SCRIPT" >"$T/run.out" 2>&1 &
pid=$!
i=0
while [[ ! -e "$GATE.started" && $i -lt 100 ]]; do sleep 0.1; i=$((i+1)); done
check "upload reached the aws stub" [ -e "$GATE.started" ]
kill -TERM "$pid" 2>/dev/null
: >"$GATE"
wait "$pid"; rc=$?
if [[ $rc -eq 143 ]]; then ok "exit 143"; else fail_t "exit=$rc (want 143)"; show_run; fi
check "log records exit=143" failure_logged "exit=143"
check "staging removed" tmp_empty

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
