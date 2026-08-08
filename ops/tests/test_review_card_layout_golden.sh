#!/usr/bin/env bash
# test_review_card_layout_golden.sh — prove the golden comparator has a red path.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi

GOLDEN="ios/BooksAndVocabTests/Golden/review_card_layout.json"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/kg_review_card_golden.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

if [[ ! -f "$GOLDEN" ]]; then
  echo "review-card-golden: missing $GOLDEN" >&2
  exit 1
fi

compare() {
  "$UV_BIN" run --no-project --python 3.13 python - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    left = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    right = json.load(handle)
if left != right:
    print("review-card-golden: mismatch detected", file=sys.stderr)
    sys.exit(1)
PY
}

same="$TMP/same.json"
changed="$TMP/changed.json"
cp "$GOLDEN" "$same"
cp "$GOLDEN" "$changed"

if compare "$GOLDEN" "$same"; then
  echo "  ✓ identical golden data is accepted"
else
  echo "  ✗ identical golden data was rejected" >&2
  exit 1
fi

sed -i.bak 's/"frontHeight": 404/"frontHeight": 405/' "$changed"
if compare "$GOLDEN" "$changed"; then
  echo "  ✗ changed golden data was accepted — comparator cannot fail"
  exit 1
else
  echo "  ✓ changed golden data is rejected"
fi

echo "review-card-golden: 2 passed, 0 failed"
