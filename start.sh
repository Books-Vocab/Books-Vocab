#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPEN=1
MODE="uitest"

usage() {
  cat <<'EOF'
Usage:
  ./start.sh              refresh and open UITest UIreview.html
  ./start.sh --print      refresh and print the resolved path only
  ./start.sh --catalog    explicitly open latest catalog UIreview.html

No silent fallback: catalog artifacts are opened only with --catalog.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --print|--no-open)
      OPEN=0
      shift
      ;;
    --catalog)
      MODE="catalog"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "start.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

resolve_uitest_review_html() {
  local review_html="$ROOT/build/snapshots/uitest-runs/UIreview.html"
  [[ -f "$review_html" ]] || return 1
  printf '%s\n' "$review_html"
}

resolve_catalog_review_html() {
  local candidate
  candidate="$(
    find "$ROOT/build/snapshots" \
      -mindepth 2 -maxdepth 2 -path '*/catalog-full-*/UIreview.html' -type f -print 2>/dev/null \
      | sort \
      | tail -n 1
  )"
  if [[ -n "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  candidate="$(
    find "$ROOT/build/snapshots" \
      -mindepth 2 -maxdepth 2 -path '*/catalog-full-*/review.html' -type f -print 2>/dev/null \
      | sort \
      | tail -n 1
  )"
  if [[ -n "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  return 1
}

if [[ "$MODE" == "catalog" ]]; then
  review_html="$(resolve_catalog_review_html)" || {
    echo "start.sh: no catalog UIreview.html found." >&2
    exit 1
  }
else
  "$ROOT/ops/uitest_review_workspace.py" --json >/dev/null
  review_html="$(resolve_uitest_review_html)" || {
    cat >&2 <<'EOF'
start.sh: failed to build UITest UIreview.html. Refusing to fall back to catalog.

Expected workspace:
  build/snapshots/uitest-runs/UIreview.html

If you intentionally want the catalog gallery, run:
  ./start.sh --catalog
EOF
    exit 1
  }
fi

printf 'mode=%s path=%s\n' "$MODE" "$review_html"

if [[ "$OPEN" -eq 1 ]]; then
  open "$review_html"
fi
