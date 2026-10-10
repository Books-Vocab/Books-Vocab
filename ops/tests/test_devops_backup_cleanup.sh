#!/usr/bin/env bash
# cleanup_old_backups：保留最新 10 份 data_<date>/ 快照目錄（連同其 .tar.gz／.sha256），
# 且清掉沒有對應目錄的孤兒 tar.gz／sha256。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../lib/hermetic_ops_test.sh
source "$ROOT/ops/lib/hermetic_ops_test.sh"
hermetic_ops_test_init "$ROOT"
pass() { printf '✓ %s\n' "$*"; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 在子 shell 載入 devops.sh（source-only seam），對指定 BACKUP_DIR 跑 cleanup。
run_cleanup() {
  ROOT="$ROOT" TARGET="$1" DEVOPS_SOURCE_ONLY=1 KG_SSH_CMD=/usr/bin/true bash -c '
    source "$ROOT/devops.sh"
    BACKUP_DIR="$TARGET"
    cleanup_old_backups
  ' >/dev/null
}

make_runs() { # dir count
  local dir="$1" n="$2" i d
  for ((i = 1; i <= n; i++)); do
    d="data_202601$(printf "%02d" "$i")_000000"
    mkdir -p "$dir/$d"
    : >"$dir/$d/f"
    : >"$dir/$d.tar.gz"
    : >"$dir/$d.tar.gz.sha256"
  done
}

# 12 份 → 剩最新 10 份，各自完整
B1="$TMP/b1"; mkdir -p "$B1"; make_runs "$B1" 12
run_cleanup "$B1"
dirs=$(ls -1d "$B1"/data_*/ | wc -l | tr -d ' ')
[[ "$dirs" == 10 ]] || fail "expected 10 dirs, got $dirs"
for i in 01 02; do
  [[ ! -e "$B1/data_202601${i}_000000" && ! -e "$B1/data_202601${i}_000000.tar.gz" && ! -e "$B1/data_202601${i}_000000.tar.gz.sha256" ]] \
    || fail "oldest run $i not fully removed"
done
for i in 03 04 05 06 07 08 09 10 11 12; do
  p="$B1/data_202601${i}_000000"
  [[ -d "$p" && -f "$p.tar.gz" && -f "$p.tar.gz.sha256" ]] || fail "run $i lost a component"
done
pass "12 runs prune to newest 10 with tar.gz and sha256 intact"

# 10 份 → 不刪
B2="$TMP/b2"; mkdir -p "$B2"; make_runs "$B2" 10
run_cleanup "$B2"
[[ "$(ls -1 "$B2" | wc -l | tr -d ' ')" == 30 ]] || fail "10 runs must not be deleted"
pass "10 runs delete nothing"

# 既有孤兒 → 清掉，完整 run 不動
B3="$TMP/b3"; mkdir -p "$B3"; make_runs "$B3" 3
: >"$B3/data_20250101_000000.tar.gz"
: >"$B3/data_20250101_000000.tar.gz.sha256"
: >"$B3/data_20250102_000000.tar.gz.sha256"
run_cleanup "$B3"
ls "$B3" | grep -q '^data_2025' && fail "orphans remain"
[[ "$(ls -1 "$B3" | wc -l | tr -d ' ')" == 9 ]] || fail "complete runs were disturbed"
pass "orphan tar.gz and sha256 are swept"

# .INCOMPLETE 目錄不占 keep 額度（否則殘缺快照會把好備份擠掉），且一併清掉
B4="$TMP/b4"; mkdir -p "$B4"; make_runs "$B4" 10
mkdir -p "$B4/data_20260199_000000"; : >"$B4/data_20260199_000000/.INCOMPLETE"
run_cleanup "$B4"
for i in 01 02 03 04 05 06 07 08 09 10; do
  [[ -d "$B4/data_202601${i}_000000" ]] || fail "complete run $i evicted by an INCOMPLETE dir"
done
[[ ! -e "$B4/data_20260199_000000" ]] || fail "INCOMPLETE dir not swept"
pass "INCOMPLETE dirs neither evict good runs nor linger"
