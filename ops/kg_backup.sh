#!/usr/bin/env bash
# Stream-backup KG production data to AWS S3.
#
# Pipeline:
#   stage data/ (SQLite online snapshots + hardlinks)
#     →  tar -czf - data/  →  tee fifo(sha256sum)  →  tee fifo(wc -c)  →  aws s3 cp - s3://...
# Writes a one-line audit log per run (path from $KG_BACKUP_LOG):
#   <timestamp> exit=<rc> bytes=<size> sha256=<hash> key=<s3 key>
# A run that stops before the upload, or whose bytes/sha256 are empty or
# malformed, logs `exit=<rc> <reason>` (non-zero) instead; exit=0 is never logged
# without bytes=<digits> and a 64-hex sha256.
#
# The archive itself is never written locally: avoids filling the data disk and
# removes the "backup tarball deleted by same incident" risk. The only local
# intermediate copy is the staging tree: one online snapshot per *.db (non-DB
# files are hardlinked, or copied with cp -p across filesystems). The trap
# removes it on every exit path, including INT/TERM/HUP.
#
# Portable across the two prod hosts (paths come from env, not hardcoded):
#   - standby (current prod, macOS/OrbStack): invoked by the LaunchAgent
#     ops/launchd/com.kg.backup.plist as user chenliangyu, with
#     KG_DATA_DIR=~/kg-data (moved out of git worktree 2026-06-16), KG_BACKUP_LOG=~/Library/Logs/kg_backup.log.
#     Uses /sbin/sha256sum + bsdtar (both present on macOS).
#   - Lightsail (Linux): historical host, instance terminated 2026-06-19. Was
#     /usr/local/bin/kg_backup.sh run by /etc/cron.d/kg-backup as root. No longer
#     a live target; kept here only for reference (see ops/cron/kg-backup.cron).
#
# Defaults below are host-agnostic fallbacks only; prod always provides
# KG_DATA_DIR / KG_BACKUP_LOG via env (launchd plist), so they don't get hit.
set -euo pipefail

BUCKET="${KG_BACKUP_BUCKET:-kg-backups-prod-967512079054}"
REGION="${KG_BACKUP_REGION:-ap-northeast-1}"
DATA_DIR="${KG_DATA_DIR:-$HOME/kg-data}"
LOG="${KG_BACKUP_LOG:-$HOME/kg_backup.log}"

DATE="$(date -u +%Y-%m-%d)"
KEY="data/${DATE}.tar.gz"
S3_URI="s3://${BUCKET}/${KEY}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG"; }
die() { local rc="$1"; shift; log "exit=$rc $*"; exit "$rc"; }

STAGE=""
SHA_PID=""; SIZE_PID=""
cleanup() {
  # A consumer still blocked opening its FIFO (no writer ever came) would orphan.
  [[ -z "$SHA_PID" ]] || kill "$SHA_PID" 2>/dev/null || true
  [[ -z "$SIZE_PID" ]] || kill "$SIZE_PID" 2>/dev/null || true
  if [[ -n "$STAGE" ]]; then rm -rf "$STAGE"; fi
}
on_signal() { log "exit=$1 interrupted by signal"; exit "$1"; }
trap cleanup EXIT
trap 'on_signal 129' HUP
trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'rc=$?; log "exit=$rc (unexpected)"; exit $rc' ERR

[[ -d "$DATA_DIR" ]] || die 2 "missing data dir: $DATA_DIR"
command -v sqlite3 >/dev/null 2>&1 || die 3 "sqlite3 missing"
DATA_ABS="$(cd "$DATA_DIR" && pwd)" || die 3 "cannot enter data dir: $DATA_DIR"
ROOT="$(basename "$DATA_ABS")"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/kg_backup_stage.XXXXXX")" || die 3 "cannot create staging dir"

# The backend keeps every DB open in WAL mode, so committed rows can live only
# in <db>-wal until a checkpoint. Tarring the live files would drop them, and a
# concurrent checkpoint could tear the main file (Issue #2250). Each *.db is
# therefore captured with SQLite's online backup API: a consistent copy that
# includes committed WAL content. The snapshots are self-contained, so -wal/-shm
# and any -journal (a hot one would roll a consistent snapshot back on open)
# stay out of the archive, as do macOS AppleDouble/Finder droppings.
#
# The source is opened as file:...?mode=rw (never creates a vanished DB) with
# no_ckpt_on_close (never checkpoints or writes the live DB; at most it leaves
# empty -wal/-shm sidecars). Not -readonly: macOS /usr/bin/sqlite3 refuses a
# read-only open of a WAL DB whose sidecars are absent, which is the normal
# state of every DB the backend has closed. CLI exit codes are not trusted
# (sqlite 3.53 exits 0 having skipped .backup under some flag mixes), so the
# setting echo, a non-empty snapshot and quick_check=ok are all required.
uri_path() { local p="${1//%/%25}"; p="${p//\?/%3F}"; printf '%s' "${p//\#/%23}"; }
snapshot_db() {  # <src> <dst>
  local snap="$STAGE/.snap.db" out check
  rm -f "$snap" "$snap-journal" "$snap-wal" "$snap-shm"
  # .backup takes a fixed relative name, so no path is ever quoted for the CLI.
  out="$(cd "$STAGE" && sqlite3 -cmd '.timeout 30000' -cmd '.dbconfig no_ckpt_on_close on' \
    "file:$(uri_path "$1")?mode=rw" '.backup .snap.db' </dev/null)" || return 1
  [[ "$out" == *"no_ckpt_on_close on"* && -s "$snap" ]] || return 1
  check="$(sqlite3 "$snap" 'PRAGMA quick_check' </dev/null)" || return 1
  [[ "$check" == ok ]] || return 1
  mv "$snap" "$2"
}

# Walk in the foreground so a find error fails the run instead of silently
# dropping files; never fall back to copying a live DB.
(cd "$DATA_ABS" && find . \( -name '._*' -o -name '.DS_Store' -o -name '*-wal' -o -name '*-shm' -o -name '*-journal' \) -prune \
  -o \( -type d -o -type f -o -type l \) -print0) >"$STAGE/.list" || die 3 "file walk failed: $DATA_DIR"

while IFS= read -r -d '' path; do
  rel="${path#./}"
  src="$DATA_ABS/$rel"
  dst="$STAGE/$ROOT/$rel"
  if [[ -L "$src" ]]; then
    target="$(readlink "$src")" && ln -s "$target" "$dst" || die 3 "stage symlink failed: $rel"
  elif [[ -d "$src" ]]; then
    mkdir -p "$dst" || die 3 "stage mkdir failed: $rel"
  elif [[ "$rel" == *.db ]]; then
    snapshot_db "$src" "$dst" || die 3 "snapshot failed: $rel"
  else
    ln "$src" "$dst" 2>/dev/null || cp -p "$src" "$dst" || die 3 "stage copy failed: $rel"
  fi
done <"$STAGE/.list"

# sha256 and byte count are computed by two consumers fed through FIFOs rather
# than `tee >(...)`: bash 3.2 (the launchd /bin/bash on macOS) does not set `$!`
# for process substitution, so those children could not be waited on by PID.
# Both consumers are started first (each opens its FIFO for reading) so the
# writers in the pipeline never deadlock on open order, and the record is read
# only after `wait`ing on each named PID. Their output is normalized (BSD wc
# left-pads the count) and validated before an exit=0 record is allowed.
mkfifo "$STAGE/.sha.fifo" "$STAGE/.size.fifo" || die 3 "cannot create fifos"
{ sha256sum <"$STAGE/.sha.fifo" | awk '{print $1}' >"$STAGE/.sha"; } &
SHA_PID=$!
{ wc -c <"$STAGE/.size.fifo" >"$STAGE/.size"; } &
SIZE_PID=$!

ps=(0 0 0 0)
set +e
tar -C "$STAGE" \
    --exclude='._*' \
    --exclude='.DS_Store' \
    --exclude='*-wal' \
    --exclude='*-shm' \
    --exclude='*-journal' \
    -czf - "$ROOT" \
  | tee "$STAGE/.sha.fifo" \
  | tee "$STAGE/.size.fifo" \
  | aws s3 cp - "$S3_URI" \
      --region "$REGION" \
      --expected-size 2000000000 \
      --no-progress || ps=("${PIPESTATUS[@]}")
# `|| ps=(...)` also keeps the ERR trap from pre-empting the record on a failed
# stage. The upload (aws) status wins; otherwise any earlier stage (tar, tee)
# failing must still fail the run: a clean upload of a broken archive is not a backup.
rc=${ps[3]}
note=""
if [[ "$rc" -eq 0 ]]; then
  if [[ "${ps[0]}" -ne 0 ]]; then rc=${ps[0]}; note=" tar exited ${ps[0]}"
  elif [[ "${ps[1]}" -ne 0 || "${ps[2]}" -ne 0 ]]; then rc=${ps[1]}; [[ "$rc" -ne 0 ]] || rc=${ps[2]}; note=" tee exited $rc"; fi
fi
wait "$SHA_PID"
wait "$SIZE_PID"
SHA_PID=""; SIZE_PID=""
set -e

SHA="$(tr -cd '0-9A-Fa-f' <"$STAGE/.sha")"
SIZE="$(tr -cd '0-9' <"$STAGE/.size")"
if [[ -z "$SIZE" || ! "$SHA" =~ ^[0-9A-Fa-f]{64}$ ]]; then
  if [[ "$rc" -eq 0 ]]; then
    die 3 "backup record incomplete: empty or invalid bytes/sha256 (upload may have succeeded)"
  fi
  die "$rc" "backup record incomplete: empty or invalid bytes/sha256"
fi
log "exit=$rc bytes=$SIZE sha256=$SHA key=$KEY$note"
exit "$rc"
