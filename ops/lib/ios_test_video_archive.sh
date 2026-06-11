#!/usr/bin/env bash
# ios_test_video_archive.sh — persist UITest run recordings beyond the tmp dir.
#
# `ios_test.sh --ui` records the simulator into a mktemp dir that the OS
# reclaims, so the verdict's artifacts.uiVideo went stale within hours. This
# lib moves the finalized mp4 into build/snapshots/uitest-videos/ with a
# timestamped name, maintains index.json (kg.ios.uitest-videos.v1, newest
# first), and prunes to KG_UITEST_VIDEO_KEEP (default 10) so the archive
# can't grow unbounded. catalog_review_sync.py reads index.json and mirrors
# the recordings into each review root for the UIreview.html gallery.

# uitest_video_archive <video_path> <dest_root> <scope> <caller> [timestamp]
# Echoes the archived path. Missing/empty recording is a silent no-op (the
# recorder legitimately skips when no explicit simulator udid exists).
uitest_video_archive() {
  local video="$1" dest_root="$2" scope="$3" caller="$4" stamp="${5:-}"
  local keep="${KG_UITEST_VIDEO_KEEP:-10}"
  # Guard the knob: 0 would prune the file we just archived while still
  # echoing its path, and a non-numeric value would poison the jq slice.
  [[ "$keep" =~ ^[0-9]+$ && "$keep" -ge 1 ]] || keep=10
  keep=$((10#$keep))  # "010" passes the regex but is not valid JSON for --argjson
  [[ -s "$video" ]] || return 0
  [[ -n "$stamp" ]] || stamp="$(date -u +%Y%m%d-%H%M%S)"
  mkdir -p "$dest_root" || return 1

  local base="$stamp-$scope" name suffix=1
  name="$base.mp4"
  while [[ -e "$dest_root/$name" ]]; do
    suffix=$((suffix + 1))
    name="$base-$suffix.mp4"
  done
  # The function body runs inside an if-condition command substitution, so
  # set -e is suppressed: a failed mv must return explicitly or the caller
  # would log "archived <path>" for a file that does not exist.
  mv "$video" "$dest_root/$name" || return 1

  local size recorded_at index="$dest_root/index.json" tmp_index
  size="$(wc -c <"$dest_root/$name" | tr -d ' ')"
  recorded_at="$(printf '%s' "$stamp" | sed -E 's/^([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})$/\1-\2-\3T\4:\5:\6Z/')"
  [[ -s "$index" ]] || printf '{"schema":"kg.ios.uitest-videos.v1","videos":[]}\n' >"$index"
  tmp_index="$(mktemp)"
  if jq \
      --arg file "$name" \
      --arg recordedAtUtc "$recorded_at" \
      --arg scope "$scope" \
      --arg caller "$caller" \
      --argjson sizeBytes "$size" \
      --argjson keep "$keep" \
      '.videos = ([{file:$file, recordedAtUtc:$recordedAtUtc, scope:$scope, caller:$caller, sizeBytes:$sizeBytes}] + .videos)
       | {schema:"kg.ios.uitest-videos.v1", pruned:(.videos[$keep:] | map(.file)), videos:.videos[:$keep]}' \
      "$index" >"$tmp_index"; then
    local pruned_file
    while IFS= read -r pruned_file; do
      [[ -n "$pruned_file" ]] && rm -f "$dest_root/$pruned_file"
    done < <(jq -r '.pruned[]?' "$tmp_index")
    jq 'del(.pruned)' "$tmp_index" >"$index"
  else
    echo "[ios_test][ui-video] warning: failed to update $index" >&2
  fi
  rm -f "$tmp_index"
  printf '%s\n' "$dest_root/$name"
}
