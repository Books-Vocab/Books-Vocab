#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPEN=1

usage() {
  cat <<'EOF'
Usage:
  ./start.sh              refresh and open UITest UIreview.html
  ./start.sh --print      refresh and print the resolved path only
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --print|--no-open) OPEN=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "start.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

"$ROOT/ops/uitest_review_workspace.py" --json >/dev/null
review_html="$ROOT/build/snapshots/uitest-runs/UIreview.html"
if [[ ! -f "$review_html" ]]; then
  cat >&2 <<'EOF'
start.sh: failed to build UITest UIreview.html.

Expected workspace:
  build/snapshots/uitest-runs/UIreview.html
EOF
  exit 1
fi

printf 'mode=uitest path=%s\n' "$review_html"
if [[ "$OPEN" -eq 1 ]]; then
  open "$review_html"
fi
