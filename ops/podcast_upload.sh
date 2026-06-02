#!/usr/bin/env bash
# Upload podcast workspace assets to S3 (Lightsail Object Storage,
# S3-compatible). Track B replaced SSH/rsync — no more ssh key handling here.
# Usage: ./ops/podcast_upload.sh <workspace_path> [--dry-run]
set -euo pipefail

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

  srt="$WORKSPACE/scripts/ep_${ep_num}_${suffix}.srt"
  [[ -f "$srt" ]] && cp "$srt" "$STAGING/$ep_dir/subtitle.srt"

  script="$WORKSPACE/scripts/ep_${ep_num}_script.md"
  [[ -f "$script" ]] && cp "$script" "$STAGING/$ep_dir/script.md"

  EP_COUNT=$((EP_COUNT + 1))
done

[[ $EP_COUNT -gt 0 ]] \
  || err "No ep_*_{pro,flash}.{m4a,mp3} files found in scripts/"
ok "Staged $EP_COUNT episodes (format: $AUDIO_EXT)"

# ── Fetch existing remote metadata (for createdAt preservation) ──────────────
EXISTING_META=""
if [[ $DRY_RUN -eq 0 ]]; then
  EXISTING_META="$(run_aws s3 cp \
    --region "$REGION" \
    "$S3_PREFIX/$SERIES_ID/metadata.json" - 2>/dev/null || true)"
fi

# ── Generate metadata.json ───────────────────────────────────────────────────
OVERVIEW="$WORKSPACE/plan/overview.md"

python3 - "$OVERVIEW" "$STAGING" "$SERIES_ID" "$AUDIO_EXT" "$EXISTING_META" <<'PYEOF'
import sys, json, os, re, subprocess

overview_path, staging_dir, series_id, audio_ext = sys.argv[1:5]
existing_meta_raw = sys.argv[5] if len(sys.argv) > 5 else ""

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

    episodes.append({
        "episodeNumber": ep_num,
        "title": ep_title,
        "durationSec": duration_sec,
        "audioAvailable": os.path.isfile(audio_path),
        "subtitleAvailable": subtitle_content is not None,
        "subtitleContent": subtitle_content,
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

metadata = {
    "id": series_id,
    "title": title,
    "author": author,
    "hostNames": host_names,
    "color": "#5B8C5A",
    "coverPattern": "waves",
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

# ── Dry-run: show tree and exit ──────────────────────────────────────────────
if [[ $DRY_RUN -eq 1 ]]; then
  info "Dry-run — staging directory:"
  find "$STAGING" -type f | sort | while read -r f; do
    size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo "?")
    echo "  $(echo "$f" | sed "s|$STAGING/||")  ($size bytes)"
  done
  info "Would: aws s3 sync $STAGING/ $S3_PREFIX/$SERIES_ID/ --region $REGION --delete"
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
    *)      echo "application/octet-stream" ;;
  esac
}

info "Syncing to $S3_PREFIX/$SERIES_ID/ ..."
# Sync everything in one pass (multipart upload for large files is automatic).
# --delete removes server-side artifacts that no longer exist locally — same
# semantics as the previous rsync invocation.
# We then loop again to fix Content-Type per file because `aws s3 sync` only
# accepts ONE --content-type and we have heterogeneous extensions. Copy-in-
# place is the documented way to alter metadata.
run_aws s3 sync \
  --region "$REGION" \
  --delete \
  --no-progress \
  "$STAGING/" "$S3_PREFIX/$SERIES_ID/"

info "Fixing Content-Type per file ..."
find "$STAGING" -type f | while read -r f; do
  rel="${f#$STAGING/}"
  ct="$(content_type_for "$f")"
  run_aws s3 cp \
    --region "$REGION" \
    --no-progress \
    --metadata-directive REPLACE \
    --content-type "$ct" \
    "$S3_PREFIX/$SERIES_ID/$rel" "$S3_PREFIX/$SERIES_ID/$rel" >/dev/null
done
ok "Upload complete"

# ── Rebuild index.json locally (no remote flock needed — last writer wins) ───
# Multiple concurrent uploads racing the index.json swap is still possible,
# but the race window is small (a few seconds) and the conflict is recoverable
# (next upload of either series fixes it). The previous SSH+flock did not buy
# us anything stronger on object storage.
info "Rebuilding index.json from bucket listing..."
INDEX_TMP="$(mktemp)"
python3 - "$BUCKET" "$REGION" "${AWS_ENDPOINT_URL:-}" "$INDEX_TMP" <<'PYEOF'
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
        if sid and sid != "index.json":
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
