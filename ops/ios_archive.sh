#!/usr/bin/env bash
# ios_archive.sh — inspect local Xcode Organizer archives for BooksAndVocab.
#
# Usage:
#   ./ops/ios_archive.sh list [--json] [--root <ArchivesDir>]
#   ./ops/ios_archive.sh latest [--json] [--root <ArchivesDir>]
#   ./ops/ios_archive.sh inspect <archive-path> [--json]
#
# Read-only. Does not delete, export, or upload archives.

set -euo pipefail

ROOT="$HOME/Library/Developer/Xcode/Archives"
JSON=0

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }
need_val() { [[ -n "${2:-}" && "${2:-}" != -* ]] || { echo "✗ $1 需要一個值" >&2; exit 1; }; }

json_escape() {
  local s="${1:-}"
  s=${s//\\/\\\\}; s=${s//\"/\\\"}; s=${s//$'\n'/\\n}
  printf '%s' "$s"
}

plist_value() {
  local plist="$1" key="$2"
  /usr/libexec/PlistBuddy -c "Print :$key" "$plist" 2>/dev/null || printf -- "-"
}

archive_row() {
  local archive="$1" plist name bundle version build created
  plist="$archive/Info.plist"
  [[ -f "$plist" ]] || return 0
  name="$(plist_value "$plist" "Name")"
  bundle="$(plist_value "$plist" "ApplicationProperties:CFBundleIdentifier")"
  version="$(plist_value "$plist" "ApplicationProperties:CFBundleShortVersionString")"
  build="$(plist_value "$plist" "ApplicationProperties:CFBundleVersion")"
  created="$(plist_value "$plist" "CreationDate")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$created" "$name" "$bundle" "$version" "$build" "$archive"
}

list_rows() {
  find "$ROOT" -maxdepth 3 -name 'BooksAndVocab*.xcarchive' -print 2>/dev/null \
    | sort \
    | while IFS= read -r archive; do archive_row "$archive"; done
}

emit_text() {
  printf 'created_at\tname\tbundle_id\tversion\tbuild\tarchive\n'
  cat
}

emit_json() {
  local first=1 line created name bundle version build archive
  printf '{"schema":"kg.ios.archives.v1","archives":['
  while IFS=$'\t' read -r created name bundle version build archive; do
    [[ -n "${archive:-}" ]] || continue
    if [[ "$first" -eq 0 ]]; then printf ','; fi
    first=0
    printf '{"createdAt":"%s","name":"%s","bundleId":"%s","version":"%s","build":"%s","archive":"%s"}' \
      "$(json_escape "$created")" "$(json_escape "$name")" "$(json_escape "$bundle")" \
      "$(json_escape "$version")" "$(json_escape "$build")" "$(json_escape "$archive")"
  done
  printf ']}\n'
}

cmd="${1:-}"
[[ -n "$cmd" ]] || { usage; exit 0; }
shift || true

archive_arg=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON=1; shift ;;
    --root) need_val --root "${2:-}"; ROOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) archive_arg="$1"; shift ;;
  esac
done

case "$cmd" in
  list)
    if [[ "$JSON" -eq 1 ]]; then list_rows | emit_json; else list_rows | emit_text; fi
    ;;
  latest)
    rows="$(list_rows)"
    latest="$(printf '%s\n' "$rows" | tail -1)"
    if [[ "$JSON" -eq 1 ]]; then printf '%s\n' "$latest" | emit_json; else printf '%s\n' "$latest" | emit_text; fi
    ;;
  inspect)
    [[ -n "$archive_arg" ]] || { echo "✗ inspect 需要 archive path" >&2; exit 1; }
    if [[ "$JSON" -eq 1 ]]; then archive_row "$archive_arg" | emit_json; else archive_row "$archive_arg" | emit_text; fi
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "✗ unknown subcommand: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
