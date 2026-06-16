#!/usr/bin/env bash
# Stream-backup KG production data to AWS S3.
#
# Pipeline:
#   tar -czf - data/  →  tee >(sha256sum)  →  aws s3 cp - s3://...
# Writes a one-line audit log to /var/log/kg_backup.log per run:
#   <timestamp> exit=<rc> bytes=<size> sha256=<hash> key=<s3 key>
#
# Intentionally NO local intermediate file: avoids filling the data disk and
# removes the "backup tarball deleted by same incident" risk.
#
# Portable across the two prod hosts (paths come from env, not hardcoded):
#   - standby (current prod, macOS/OrbStack): invoked by the LaunchAgent
#     ops/launchd/com.kg.backup.plist as user chenliangyu, with
#     KG_DATA_DIR=~/kg-data (moved out of git worktree 2026-06-16), KG_BACKUP_LOG=~/Library/Logs/kg_backup.log.
#     Uses /sbin/sha256sum + bsdtar (both present on macOS).
#   - Lightsail (stopped rollback, Linux): was /usr/local/bin/kg_backup.sh run by
#     /etc/cron.d/kg-backup as root (cron now disabled; see ops/cron/kg-backup.cron).
set -euo pipefail

BUCKET="${KG_BACKUP_BUCKET:-kg-backups-prod-967512079054}"
REGION="${KG_BACKUP_REGION:-ap-northeast-1}"
DATA_DIR="${KG_DATA_DIR:-/home/ubuntu/knowledge_graph_api/data}"
LOG="${KG_BACKUP_LOG:-/var/log/kg_backup.log}"

DATE="$(date -u +%Y-%m-%d)"
KEY="data/${DATE}.tar.gz"
S3_URI="s3://${BUCKET}/${KEY}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG"; }

trap 'rc=$?; log "exit=$rc (unexpected)"; exit $rc' ERR

if [[ ! -d "$DATA_DIR" ]]; then
  log "exit=2 missing data dir: $DATA_DIR"
  exit 2
fi

# Exclude macOS AppleDouble droppings (from prior local-restore round-trips)
# and SQLite WAL/SHM journal sidecars. WAL/SHM are not needed: SQLite at next
# open will replay WAL into the main DB. Including them would either error
# (WAL referencing missing main) or restore inconsistent state.
TMP_SHA="$(mktemp)"
TMP_SIZE="$(mktemp)"
trap 'rm -f "$TMP_SHA" "$TMP_SIZE"' EXIT

set +e
tar -C "$(dirname "$DATA_DIR")" \
    --exclude='._*' \
    --exclude='.DS_Store' \
    --exclude='*-wal' \
    --exclude='*-shm' \
    -czf - "$(basename "$DATA_DIR")" \
  | tee >(sha256sum | awk '{print $1}' >"$TMP_SHA") \
  | tee >(wc -c >"$TMP_SIZE") \
  | aws s3 cp - "$S3_URI" \
      --region "$REGION" \
      --expected-size 2000000000 \
      --no-progress
rc=${PIPESTATUS[3]}
set -e

# Ensure the `tee >(...)` process-substitution children have finished writing
# TMP_SHA / TMP_SIZE before we read them. Without this the read races the async
# subshells; it happens to win under the current aws consumer but that's luck,
# not contract.
wait

SHA="$(cat "$TMP_SHA")"
SIZE="$(cat "$TMP_SIZE")"
log "exit=$rc bytes=$SIZE sha256=$SHA key=$KEY"
exit "$rc"
