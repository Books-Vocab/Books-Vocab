#!/usr/bin/env bash
# Upload podcast workspace assets to server
# Usage: ./ops/podcast_upload.sh <workspace_path> [--dry-run]
set -euo pipefail

# ── Config (mirrors devops.sh) ──────────────────────────────────────────────
SSH_KEY="$HOME/.ssh/lightsail_default.pem"
SERVER="ubuntu@13.193.212.134"
REMOTE_PODCAST_DIR="~/knowledge_graph_api/data/podcasts"

SSH_OPTS=( -T -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes )
SSH_CMD=( ssh "${SSH_OPTS[@]}" "$SERVER" )

# ── Helpers ──────────────────────────────────────────────────────────────────
info()  { echo "▶ $*"; }
ok()    { echo "✓ $*"; }
err()   { echo "✗ $*" >&2; exit 1; }

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

# ── Create staging dir ───────────────────────────────────────────────────────
STAGING="/tmp/podcast_upload_${SERIES_ID}"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# ── Reorganize files into ep_NN/ dirs ────────────────────────────────────────
# Accept either _pro.mp3 (Vertex Pro TTS) or _flash.mp3 (Vertex Flash TTS).
# Prefer _pro if both exist (looped first; space-separated list used as poor-man's set).
EP_COUNT=0
SEEN_EPS=" "
for mp3 in "$WORKSPACE/scripts"/ep_*_pro.mp3 "$WORKSPACE/scripts"/ep_*_flash.mp3; do
  [[ -f "$mp3" ]] || continue
  fname="$(basename "$mp3")"
  ep_num="${fname#ep_}"
  ep_num="${ep_num%%_*}"
  # Skip if we already processed this episode number
  case "$SEEN_EPS" in *" $ep_num "*) continue ;; esac
  SEEN_EPS="$SEEN_EPS$ep_num "

  # Derive suffix (pro / flash) from filename for SRT pairing
  suffix="${fname%.mp3}"
  suffix="${suffix##*_}"
  ep_dir="$(printf "ep_%02d" "$ep_num")"

  mkdir -p "$STAGING/$ep_dir"
  cp "$mp3" "$STAGING/$ep_dir/audio.mp3"

  srt="$WORKSPACE/scripts/ep_${ep_num}_${suffix}.srt"
  [[ -f "$srt" ]] && cp "$srt" "$STAGING/$ep_dir/subtitle.srt"

  script="$WORKSPACE/scripts/ep_${ep_num}_script.md"
  [[ -f "$script" ]] && cp "$script" "$STAGING/$ep_dir/script.md"

  EP_COUNT=$((EP_COUNT + 1))
done

[[ $EP_COUNT -gt 0 ]] || err "No ep_*_{pro,flash}.mp3 files found in scripts/"
ok "Staged $EP_COUNT episodes"

# ── Fetch existing remote metadata (for createdAt preservation) ──────────────
EXISTING_META=""
if [[ $DRY_RUN -eq 0 ]]; then
  EXISTING_META="$("${SSH_CMD[@]}" "cat $REMOTE_PODCAST_DIR/$SERIES_ID/metadata.json 2>/dev/null || true")"
fi

# ── Generate metadata.json ───────────────────────────────────────────────────
OVERVIEW="$WORKSPACE/plan/overview.md"

python3 - "$OVERVIEW" "$STAGING" "$SERIES_ID" "$EXISTING_META" <<'PYEOF'
import sys, json, os, re, subprocess

overview_path, staging_dir, series_id = sys.argv[1], sys.argv[2], sys.argv[3]
existing_meta_raw = sys.argv[4] if len(sys.argv) > 4 else ""

with open(overview_path, "r") as f:
    text = f.read()

# Title from H1
title_m = re.search(r'^#\s+(.+)', text, re.MULTILINE)
title = title_m.group(1).strip() if title_m else series_id

# Author from Book Analysis section — look for Type line to find the book topic
# The "author" here is the book author implied by the series
author_m = re.search(r'\*\*Type\*\*:\s*(.+)', text)
author = author_m.group(1).strip() if author_m else ""

# Host names from Host A / Host B sections
host_a_m = re.search(r'###\s+Host\s+A:\s*(\w+)', text)
host_b_m = re.search(r'###\s+Host\s+B:\s*(\w+)', text)
host_names = []
if host_a_m:
    host_names.append(host_a_m.group(1))
if host_b_m:
    host_names.append(host_b_m.group(1))

# Parse episode map table
episodes = []
for m in re.finditer(
    r'\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d+)\s*min\s*\|',
    text
):
    ep_num = int(m.group(1))
    ep_title = m.group(2).strip()
    ep_dir = os.path.join(staging_dir, f"ep_{ep_num:02d}")
    audio_path = os.path.join(ep_dir, "audio.mp3")

    # Try ffprobe for duration
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

    episodes.append({
        "episodeNumber": ep_num,
        "title": ep_title,
        "durationSec": duration_sec,
        "audioAvailable": os.path.isfile(os.path.join(ep_dir, "audio.mp3")),
        "subtitleAvailable": os.path.isfile(os.path.join(ep_dir, "subtitle.srt")),
    })

from datetime import datetime, timezone
total_duration = sum(e["durationSec"] for e in episodes)
now = datetime.now(timezone.utc).isoformat(timespec="seconds")

# Preserve createdAt from existing remote metadata (idempotent re-upload
# must not reset series creation time).
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
  info "Would rsync to: $SERVER:$REMOTE_PODCAST_DIR/$SERIES_ID/"
  rm -rf "$STAGING"
  exit 0
fi

# ── rsync to server ──────────────────────────────────────────────────────────
# --partial + --delay-updates: interrupted transfers leave a .tmp partial
# instead of corrupting the final file; finalized files swap in atomically
# at the end. Prevents half-uploaded mp3 being served mid-transfer.
info "Uploading to $SERVER:$REMOTE_PODCAST_DIR/$SERIES_ID/ ..."
rsync -avz --partial --partial-dir=.rsync-partial --delay-updates \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
  "$STAGING/" \
  "$SERVER:$REMOTE_PODCAST_DIR/$SERIES_ID/"
ok "Upload complete"

# ── Rebuild index.json on remote (flock-serialized) ──────────────────────────
# flock prevents concurrent uploads from racing the index rebuild
# (reader may observe other series' metadata mid-swap otherwise).
info "Rebuilding index.json on server..."
"${SSH_CMD[@]}" flock /tmp/podcast_index.lock python3 - "$REMOTE_PODCAST_DIR" <<'REMOTE_PY'
import sys, json, os, glob

podcast_dir = os.path.expanduser(sys.argv[1])
index = []
for meta_path in sorted(glob.glob(os.path.join(podcast_dir, "*/metadata.json"))):
    with open(meta_path) as f:
        meta = json.load(f)
    entry = {k: v for k, v in meta.items() if k != "episodes"}
    entry["episodeCount"] = len(meta.get("episodes", []))
    index.append(entry)

out = os.path.join(podcast_dir, "index.json")
tmp = out + ".tmp"
with open(tmp, "w") as f:
    json.dump(index, f, indent=2, ensure_ascii=False)
os.replace(tmp, out)  # atomic swap — reader never sees truncated JSON
print(f"index.json: {len(index)} series")
REMOTE_PY
ok "index.json rebuilt"

# ── Cleanup ──────────────────────────────────────────────────────────────────
rm -rf "$STAGING"
ok "Done — $SERIES_ID uploaded with $EP_COUNT episodes"
