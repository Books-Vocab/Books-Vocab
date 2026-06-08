#!/usr/bin/env bash
# Upload podcast workspace assets to S3 (Lightsail Object Storage,
# S3-compatible). Track B replaced SSH/rsync — no more ssh key handling here.
# Usage: ./ops/podcast_upload.sh <workspace_path> [--dry-run]
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

# ── Machine-local config (gap-fill) ──────────────────────────────────────────
# The monitor does NOT load .env, and a launching shell / cron may not export
# the bucket or AWS profile — both used to fall through to the default AWS
# identity, which is read-only on kg-podcasts-prod (Lightsail Object Storage in
# a separate account) → PutObject AccessDenied. Pull AWS_*/PODCAST_* from
# lab/podcast/.env for any key the caller did NOT already set (caller env wins).
# `aws` and boto3 both honor AWS_PROFILE from the environment automatically.
_ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lab/podcast/.env"
if [[ -f "$_ENV_FILE" ]]; then
  while IFS='=' read -r _k _v || [[ -n "$_k" ]]; do
    if [[ ! "$_k" =~ ^(AWS|PODCAST)_[A-Za-z0-9_]*$ ]]; then continue; fi
    if [[ -n "${!_k:-}" ]]; then continue; fi  # caller-provided env wins
    export "$_k=${_v%$'\r'}"
  done < "$_ENV_FILE"
fi

# Python entrypoint — go through uv (project rule: never invoke bare python3;
# the host python3 lacks boto3 and uv guarantees a consistent interpreter).
UV_BIN="$(command -v uv || echo "$HOME/.local/bin/uv")"
[[ -x "$UV_BIN" ]] || { echo "✗ uv not found: $UV_BIN" >&2; exit 1; }

# Clean up temp files on ANY exit (incl. set -e abort mid-metadata/index build).
trap 'rm -f "${EXISTING_META_TMP:-}" "${INDEX_TMP:-}"' EXIT

# ── Config ───────────────────────────────────────────────────────────────────
BUCKET="${PODCAST_BUCKET:?PODCAST_BUCKET not set (e.g. kg-podcasts-prod)}"
REGION="${PODCAST_BUCKET_REGION:-ap-northeast-1}"
# Lightsail Object Storage uses Lightsail-specific endpoint, but aws cli auto-
# derives it from region when --endpoint-url isn't passed AND the bucket lives
# in standard S3 namespace (Lightsail Object Storage does). Override here only
# if AWS_ENDPOINT_URL is exported.
S3_PREFIX="s3://$BUCKET"

# ── Helpers ──────────────────────────────────────────────────────────────────
info()  { echo "▶ $*"; }
ok()    { echo "✓ $*"; }
err()   { echo "✗ $*" >&2; exit 1; }
# Wrapper so --endpoint-url is injected only when AWS_ENDPOINT_URL is set.
# Avoids the bash 3.x set -u + empty-array expansion bug on macOS.
run_aws() { [[ -n "${AWS_ENDPOINT_URL:-}" ]] && aws --endpoint-url "$AWS_ENDPOINT_URL" "$@" || aws "$@"; }

# ── Free-tier preview clip ───────────────────────────────────────────────────
# The free tier streams a *separate* preview asset (see backend podcast_access.py
# FREE_PREVIEW_EP_NUM / PREVIEW_AUDIO_STEM). It must be a self-contained file
# whose own moov advertises ~PREVIEW_SECONDS — a byte-truncated copy of the full
# progressive MP4 would make AVPlayer error instead of stopping cleanly. We cut
# it with `-c copy` (stream copy: no re-encode, near-instant, lossless) so the
# container/codec match the full audio and the backend's audioFormat resolution
# applies unchanged. Only episode 1 is previewable, so only ep_01 gets one.
PREVIEW_SECONDS=180

make_preview() {
  local src="$1" dst="$2" ext="$3"
  local movflags=()
  [[ "$ext" == "m4a" ]] && movflags=(-movflags +faststart)  # faststart is mp4-only
  ffmpeg -nostdin -v error -y -i "$src" -t "$PREVIEW_SECONDS" -c copy "${movflags[@]}" "$dst" \
    || err "ffmpeg failed to generate free-tier preview from $src (full audio publishes but free tier would 404)"
}

DRY_RUN=0

# ── Parse args ───────────────────────────────────────────────────────────────
WORKSPACE=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)         WORKSPACE="$arg" ;;
  esac
done

[[ -n "$WORKSPACE" ]] || err "Usage: $0 <workspace_path> [--dry-run]"

# Resolve to absolute path
WORKSPACE="$(cd "$WORKSPACE" && pwd)"

# ── Validate workspace ───────────────────────────────────────────────────────
[[ -f "$WORKSPACE/plan/overview.md" ]] || err "Missing plan/overview.md in $WORKSPACE"
[[ -d "$WORKSPACE/scripts" ]]          || err "Missing scripts/ dir in $WORKSPACE"

SERIES_ID="$(basename "$WORKSPACE")"
# Must match backend _SERIES_ID_RE in routers/podcast.py — otherwise upload
# succeeds but every API call returns 404.
[[ "$SERIES_ID" =~ ^[a-z0-9_]+$ ]] \
  || err "Invalid series_id '$SERIES_ID' — must match ^[a-z0-9_]+\$ (lowercase, digits, underscore)"
info "Series: $SERIES_ID"
info "Bucket: $S3_PREFIX (region $REGION)"

# ── Create staging dir ───────────────────────────────────────────────────────
STAGING="/tmp/podcast_upload_${SERIES_ID}"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# ── Reorganize files into ep_NN/ dirs ────────────────────────────────────────
# Post-Track-B default is .m4a (AAC). .mp3 still accepted for legacy series.
# Prefer _pro if both pro and flash exist for the same episode (poor-man's set
# using space-delimited string).
EP_COUNT=0
SEEN_EPS=" "
AUDIO_EXT=""  # detected from the chosen source file (mp3 or m4a)
for src in \
    "$WORKSPACE/scripts"/ep_*_pro.m4a \
    "$WORKSPACE/scripts"/ep_*_pro.mp3 \
    "$WORKSPACE/scripts"/ep_*_flash.m4a \
    "$WORKSPACE/scripts"/ep_*_flash.mp3; do
  [[ -f "$src" ]] || continue
  fname="$(basename "$src")"
  ep_num="${fname#ep_}"
  ep_num="${ep_num%%_*}"
  case "$SEEN_EPS" in *" $ep_num "*) continue ;; esac
  SEEN_EPS="$SEEN_EPS$ep_num "

  ext="${fname##*.}"
  AUDIO_EXT="$ext"  # all eps in a series share the same format
  suffix="${fname%.*}"
  suffix="${suffix##*_}"  # pro / flash
  ep_dir="$(printf "ep_%02d" "$ep_num")"

  mkdir -p "$STAGING/$ep_dir"
  cp "$src" "$STAGING/$ep_dir/audio.$ext"

  # Free-tier preview: only episode 1 is free-previewable (10# forces base-10
  # so a leading-zero ep_num like "01" isn't parsed as octal).
  if (( 10#$ep_num == 1 )); then
    make_preview "$STAGING/$ep_dir/audio.$ext" "$STAGING/$ep_dir/preview.$ext" "$ext"
  fi

  srt="$WORKSPACE/scripts/ep_${ep_num}_${suffix}.srt"
  [[ -f "$srt" ]] && cp "$srt" "$STAGING/$ep_dir/subtitle.srt"

  script="$WORKSPACE/scripts/ep_${ep_num}_script.md"
  [[ -f "$script" ]] && cp "$script" "$STAGING/$ep_dir/script.md"

  EP_COUNT=$((EP_COUNT + 1))
done

[[ $EP_COUNT -gt 0 ]] \
  || err "No ep_*_{pro,flash}.{m4a,mp3} files found in scripts/"
ok "Staged $EP_COUNT episodes (format: $AUDIO_EXT)"

# ── Stage series cover (cover stage output, optional) ────────────────────────
# plan/cover.png → <staging>/cover.png; the sync loop uploads it to
# <sid>/cover.png and the metadata block sets coverImageURL when present.
if [[ -f "$WORKSPACE/plan/cover.png" ]]; then
  cp "$WORKSPACE/plan/cover.png" "$STAGING/cover.png"
  ok "Staged series cover"
fi

# ── Fetch existing remote metadata (for createdAt preservation) ──────────────
EXISTING_META=""
if [[ $DRY_RUN -eq 0 ]]; then
  EXISTING_META="$(run_aws s3 cp \
    --region "$REGION" \
    "$S3_PREFIX/$SERIES_ID/metadata.json" - 2>/dev/null || true)"
fi

# ── Generate metadata.json ───────────────────────────────────────────────────
OVERVIEW="$WORKSPACE/plan/overview.md"

# Pass existing metadata via a temp FILE, not argv: it now embeds full inline
# subtitle text per episode (~1 MB for a long series), which overflows ARG_MAX
# ("Argument list too long") when passed as a command-line argument.
EXISTING_META_TMP="$(mktemp)"
printf '%s' "$EXISTING_META" > "$EXISTING_META_TMP"

"$UV_BIN" run python - "$OVERVIEW" "$STAGING" "$SERIES_ID" "$AUDIO_EXT" "$EXISTING_META_TMP" <<'PYEOF'
import sys, json, os, re, subprocess, hashlib

overview_path, staging_dir, series_id, audio_ext = sys.argv[1:5]
existing_meta_path = sys.argv[5] if len(sys.argv) > 5 else ""
existing_meta_raw = ""
if existing_meta_path and os.path.isfile(existing_meta_path):
    with open(existing_meta_path, "r", encoding="utf-8") as mf:
        existing_meta_raw = mf.read()

with open(overview_path, "r") as f:
    text = f.read()

title_m = re.search(r'^#\s+(.+)', text, re.MULTILINE)
title = title_m.group(1).strip() if title_m else series_id

author_m = re.search(r'\*\*Type\*\*:\s*(.+)', text)
author = author_m.group(1).strip() if author_m else ""

voice_map_re = re.compile(r"\*\*([^*()]+?)\s*\(([^)]+)\)\*\*:\s*(Speaker[12])")
host_names = [m.group(1).strip() for m in voice_map_re.finditer(text)]
if not host_names:
    print(
        "⚠ no Voice Mapping section found in overview.md — hostNames left empty "
        "(pre-tts-prep workspace, e.g. legacy flow_*)",
        file=sys.stderr,
    )

episodes = []
for m in re.finditer(
    r'\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*~?(\d+)\s*min\s*\|',
    text
):
    ep_num = int(m.group(1))
    ep_title = m.group(2).strip()
    ep_dir = os.path.join(staging_dir, f"ep_{ep_num:02d}")
    audio_path = os.path.join(ep_dir, f"audio.{audio_ext}")

    duration_sec = 0
    if os.path.isfile(audio_path):
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                duration_sec = int(float(result.stdout.strip()))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    subtitle_path = os.path.join(ep_dir, "subtitle.srt")
    subtitle_content = None
    if os.path.isfile(subtitle_path):
        try:
            with open(subtitle_path, "r", encoding="utf-8") as srt_f:
                subtitle_content = srt_f.read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"⚠ ep_{ep_num}: subtitle read failed ({exc}); inline skipped")

    # Free-tier preview (ep_01 only — see make_preview / backend podcast_access).
    # previewDurationSec lets the client show "N-min preview" + an upgrade CTA
    # at clip end without probing the asset itself.
    preview_path = os.path.join(ep_dir, f"preview.{audio_ext}")
    preview_available = os.path.isfile(preview_path)
    preview_duration_sec = 0
    if preview_available:
        try:
            pr = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "csv=p=0", preview_path],
                capture_output=True, text=True, timeout=10
            )
            if pr.returncode == 0 and pr.stdout.strip():
                preview_duration_sec = int(float(pr.stdout.strip()))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    episodes.append({
        "episodeNumber": ep_num,
        "title": ep_title,
        "durationSec": duration_sec,
        "audioAvailable": os.path.isfile(audio_path),
        "subtitleAvailable": subtitle_content is not None,
        "subtitleContent": subtitle_content,
        "previewAvailable": preview_available,
        "previewDurationSec": preview_duration_sec,
    })

from datetime import datetime, timezone
total_duration = sum(e["durationSec"] for e in episodes)
now = datetime.now(timezone.utc).isoformat(timespec="seconds")

created_at = now
if existing_meta_raw.strip():
    try:
        prev = json.loads(existing_meta_raw)
        if isinstance(prev.get("createdAt"), str) and prev["createdAt"]:
            created_at = prev["createdAt"]
    except json.JSONDecodeError:
        pass

# Cover stage output (staged as <staging>/cover.png → S3 <sid>/cover.png).
# coverImageURL is the backend proxy path the client fetches; null when the
# cover stage hasn't produced one (legacy / pre-cover series → procedural cover).
cover_path = os.path.join(staging_dir, "cover.png")
cover_image_url = None
if os.path.isfile(cover_path):
    with open(cover_path, "rb") as cover_f:
        cover_version = hashlib.sha256(cover_f.read()).hexdigest()[:16]
    cover_image_url = f"/api/podcasts/{series_id}/cover?v={cover_version}"

metadata = {
    "id": series_id,
    "title": title,
    "author": author,
    "hostNames": host_names,
    "color": "#5B8C5A",
    "coverPattern": "waves",
    "coverImageURL": cover_image_url,
    "totalDurationSec": total_duration,
    # Record format on the series so the backend can content-type-route
    # without sniffing the bucket every request. m4a → "audio/mp4".
    "audioFormat": audio_ext,
    "episodes": episodes,
    "createdAt": created_at,
    "updatedAt": now,
}

out_path = os.path.join(staging_dir, "metadata.json")
with open(out_path, "w") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)

print(f"✓ metadata.json: {len(episodes)} episodes")
PYEOF
rm -f "$EXISTING_META_TMP"

# ── Dry-run: show tree and exit ──────────────────────────────────────────────
if [[ $DRY_RUN -eq 1 ]]; then
  info "Dry-run — staging directory:"
  find "$STAGING" -type f | sort | while read -r f; do
    size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo "?")
    echo "  $(echo "$f" | sed "s|$STAGING/||")  ($size bytes)"
  done
  info "Would: per-file 'aws s3 cp --content-type' each file into $S3_PREFIX/$SERIES_ID/ (metadata.json last), then prune remote orphans"
  rm -rf "$STAGING"
  exit 0
fi

# ── Sync to S3 ───────────────────────────────────────────────────────────────
# Content-Type per extension. Without these, S3 defaults to
# binary/octet-stream and AVPlayer rejects the stream.
content_type_for() {
  case "$1" in
    *.m4a)  echo "audio/mp4" ;;
    *.mp3)  echo "audio/mpeg" ;;
    *.srt)  echo "text/plain; charset=utf-8" ;;
    *.json) echo "application/json; charset=utf-8" ;;
    *.md)   echo "text/markdown; charset=utf-8" ;;
    *.png)  echo "image/png" ;;
    *)      echo "application/octet-stream" ;;
  esac
}

info "Uploading to $S3_PREFIX/$SERIES_ID/ ..."
# Single-pass per-file `cp --content-type`: every object lands with its correct
# Content-Type from the very first byte. The old "sync (octet-stream) then
# fixup loop" left a window where audio was already PUT as binary/octet-stream
# — AVPlayer rejects that. If the upload aborted in that window, iOS still saw
# audioAvailable:true (metadata.json had been written by sync) pointing at
# broken audio. Per-file cp eliminates the window entirely.
#
# Ordering invariant: upload metadata.json LAST. It is the "ready" signal —
# audioAvailable:true must never be visible before the audio it describes is
# fully present with a playable Content-Type.
find "$STAGING" -type f ! -name metadata.json | while read -r f; do
  rel="${f#$STAGING/}"
  ct="$(content_type_for "$f")"
  run_aws s3 cp \
    --region "$REGION" \
    --no-progress \
    --content-type "$ct" \
    "$f" "$S3_PREFIX/$SERIES_ID/$rel" >/dev/null
done

# metadata.json LAST — the ready signal (see ordering invariant above).
if [[ -f "$STAGING/metadata.json" ]]; then
  run_aws s3 cp \
    --region "$REGION" \
    --no-progress \
    --content-type "$(content_type_for "$STAGING/metadata.json")" \
    "$STAGING/metadata.json" "$S3_PREFIX/$SERIES_ID/metadata.json" >/dev/null
fi
ok "Upload complete"

# ── Reconcile (replaces `aws s3 sync --delete`) ──────────────────────────────
# Per-file cp does not prune server-side orphans, so we delete any remote key
# under this series prefix that no longer exists in staging — preserving the
# previous --delete semantics. Done AFTER metadata.json upload: pruning a stale
# orphan never affects the ready signal, and deleting before would not help.
info "Reconciling remote (pruning orphans) ..."
"$UV_BIN" run --with boto3 python - \
  "$BUCKET" "$REGION" "${AWS_ENDPOINT_URL:-}" "$SERIES_ID" "$STAGING" <<'PYEOF'
import sys, os, boto3
bucket, region, endpoint, series_id, staging = sys.argv[1:6]
kwargs = {"region_name": region}
if endpoint:
    kwargs["endpoint_url"] = endpoint
s3 = boto3.client("s3", **kwargs)

# Relative keys present locally (what we just uploaded).
local = set()
for root, _dirs, files in os.walk(staging):
    for fn in files:
        rel = os.path.relpath(os.path.join(root, fn), staging)
        local.add(rel.replace(os.sep, "/"))

prefix = f"{series_id}/"
paginator = s3.get_paginator("list_objects_v2")
orphans = []
for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for obj in page.get("Contents", []) or []:
        rel = obj["Key"][len(prefix):]
        if rel and rel not in local:
            orphans.append(obj["Key"])

for i in range(0, len(orphans), 1000):
    batch = orphans[i:i + 1000]
    s3.delete_objects(
        Bucket=bucket,
        Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
    )
print(f"reconcile: pruned {len(orphans)} orphan object(s)")
PYEOF

# ── Rebuild index.json locally (no remote flock needed — last writer wins) ───
# Multiple concurrent uploads racing the index.json swap is still possible,
# but the race window is small (a few seconds) and the conflict is recoverable
# (next upload of either series fixes it). The previous SSH+flock did not buy
# us anything stronger on object storage.
info "Rebuilding index.json from bucket listing..."
INDEX_TMP="$(mktemp)"
# Run through uv so boto3 is guaranteed present — the host `python3` (homebrew)
# has no boto3, which silently left index.json stale after a successful upload.
"$UV_BIN" run --with boto3 python - "$BUCKET" "$REGION" "${AWS_ENDPOINT_URL:-}" "$INDEX_TMP" <<'PYEOF'
import sys, json, boto3
bucket, region, endpoint, out_path = sys.argv[1:5]
kwargs = {"region_name": region}
if endpoint:
    kwargs["endpoint_url"] = endpoint
s3 = boto3.client("s3", **kwargs)

# List one level deep — every series is a top-level "directory" in the bucket.
paginator = s3.get_paginator("list_objects_v2")
series_ids = set()
for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
    for p in page.get("CommonPrefixes", []) or []:
        sid = p["Prefix"].rstrip("/")
        if sid:
            series_ids.add(sid)

entries = []
for sid in sorted(series_ids):
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"{sid}/metadata.json")
        meta = json.loads(obj["Body"].read())
    except Exception as exc:  # noqa: BLE001
        print(f"⚠ {sid}: metadata.json missing/unreadable ({exc}); skipped",
              file=sys.stderr)
        continue
    entry = {k: v for k, v in meta.items() if k != "episodes"}
    entry["episodeCount"] = len(meta.get("episodes", []))
    entries.append(entry)

with open(out_path, "w") as f:
    json.dump(entries, f, indent=2, ensure_ascii=False)
print(f"index.json: {len(entries)} series")
PYEOF

run_aws s3 cp \
  --region "$REGION" \
  --no-progress \
  --content-type "application/json; charset=utf-8" \
  "$INDEX_TMP" "$S3_PREFIX/index.json"
rm -f "$INDEX_TMP"
ok "index.json rebuilt"

# ── Cleanup ──────────────────────────────────────────────────────────────────
rm -rf "$STAGING"
ok "Done — $SERIES_ID uploaded with $EP_COUNT episodes"
