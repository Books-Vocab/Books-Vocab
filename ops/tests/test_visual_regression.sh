#!/usr/bin/env bash
# test_visual_regression.sh — behavior tests for ops/visual_regression.py.
#
# Builds two fixture catalog roots (light + dark device dirs) with ImageMagick
# and exercises: identical roots, perceptual change, added/removed scenarios,
# dimension mismatch, --threshold, --only, --json schema, --auto root pairing.
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
VR=("$UV_BIN" run --no-project --python 3.13 python ops/visual_regression.py)

command -v magick >/dev/null 2>&1 || { echo "✗ test 需要 ImageMagick (magick)" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "✗ test 需要 jq" >&2; exit 1; }

pass=0
fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/kg_visreg_test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

# shape A / shape B render clearly different pHash; A twice = 0.
draw_a() { magick -size 100x200 xc:white -fill black -draw "rectangle 10,10 50,50" "$1"; }
draw_b() { magick -size 100x200 xc:white -fill black -draw "rectangle 40,120 90,180" "$1"; }
draw_wide_a() { magick -size 120x200 xc:white -fill black -draw "rectangle 10,10 50,50" "$1"; }

make_root() {
  # $1 = root dir
  mkdir -p "$1/Dev portrait/Surface_One" "$1/Dev portrait (dark)/Surface_One"
  printf '{"totalImages": 4}' >"$1/review_manifest.json"
}

BASE="$TMP/catalog-full-20260101-000000"
CURR="$TMP/catalog-full-20260201-000000"
make_root "$BASE"; make_root "$CURR"
draw_a "$BASE/Dev portrait/Surface_One/Same.png";    draw_a "$CURR/Dev portrait/Surface_One/Same.png"
draw_a "$BASE/Dev portrait/Surface_One/Changed.png"; draw_b "$CURR/Dev portrait/Surface_One/Changed.png"
draw_a "$BASE/Dev portrait/Surface_One/Removed.png"
draw_b "$CURR/Dev portrait/Surface_One/Added.png"
draw_a "$BASE/Dev portrait (dark)/Surface_One/Same.png"; draw_a "$CURR/Dev portrait (dark)/Surface_One/Same.png"
draw_a "$BASE/Dev portrait/Surface_One/Resized.png";  draw_wide_a "$CURR/Dev portrait/Surface_One/Resized.png"

section "Diff detection"
OUT="$("${VR[@]}" --baseline "$BASE" --current "$CURR" --json 2>/dev/null)"; RC=$?
if [[ "$RC" == "1" ]]; then
  ok "changed/removed present → exit 1"
else
  fail_t "expected exit 1, got $RC"
fi
if jq -e '.changed | map(.path) | index("Dev portrait/Surface_One/Changed.png") != null' <<<"$OUT" >/dev/null 2>&1; then
  ok "perceptual change detected"
else
  fail_t "Changed.png not flagged: $OUT"
fi
if jq -e '.changed | map(.path) | index("Dev portrait/Surface_One/Resized.png") != null' <<<"$OUT" >/dev/null 2>&1; then
  ok "dimension mismatch flagged as changed"
else
  fail_t "Resized.png not flagged: $OUT"
fi
if jq -e '.removed == ["Dev portrait/Surface_One/Removed.png"] and .added == ["Dev portrait/Surface_One/Added.png"]' <<<"$OUT" >/dev/null 2>&1; then
  ok "added/removed listed"
else
  fail_t "added/removed wrong: $OUT"
fi
if jq -e '.changed | map(.path) | index("Dev portrait/Surface_One/Same.png") == null' <<<"$OUT" >/dev/null 2>&1; then
  ok "identical png not flagged"
else
  fail_t "Same.png falsely flagged"
fi
if jq -e '.unchanged == 2' <<<"$OUT" >/dev/null 2>&1; then
  ok "unchanged count covers light+dark Same.png"
else
  fail_t "unchanged count wrong: $OUT"
fi

section "Identical roots"
if "${VR[@]}" --baseline "$BASE" --current "$BASE" >/dev/null 2>&1; then
  ok "self-compare exits 0"
else
  fail_t "self-compare should exit 0"
fi

section "Threshold + filter"
OUT="$("${VR[@]}" --baseline "$BASE" --current "$CURR" --threshold 99999 --only Changed --json 2>/dev/null)"; RC=$?
if [[ "$RC" == "0" ]] && jq -e '.changed == []' <<<"$OUT" >/dev/null 2>&1; then
  ok "huge threshold suppresses perceptual change"
else
  fail_t "threshold not honored (rc=$RC): $OUT"
fi
OUT="$("${VR[@]}" --baseline "$BASE" --current "$CURR" --only Removed --json 2>/dev/null)"; RC=$?
if [[ "$RC" == "1" ]] && jq -e '(.removed | length == 1) and (.changed == []) and (.added == [])' <<<"$OUT" >/dev/null 2>&1; then
  ok "--only filters pair universe"
else
  fail_t "--only filter wrong (rc=$RC): $OUT"
fi

section "--auto root pairing"
# usable manifest + lexicographically after catalog-full-*: must NOT be paired.
make_root "$TMP/gallery-admin-preview"
draw_a "$TMP/gallery-admin-preview/Dev portrait/Surface_One/Same.png"
OUT="$(KG_VISREG_SNAPSHOTS="$TMP" "${VR[@]}" --auto --json 2>/dev/null)"
if jq -e '.baseline | endswith("catalog-full-20260101-000000")' <<<"$OUT" >/dev/null 2>&1 \
  && jq -e '.current | endswith("catalog-full-20260201-000000")' <<<"$OUT" >/dev/null 2>&1; then
  ok "--auto pairs newest catalog-full as current, skipping side artifacts"
else
  fail_t "--auto pairing wrong: $OUT"
fi
if KG_VISREG_SNAPSHOTS="$TMP/nonexistent" "${VR[@]}" --auto >/dev/null 2>&1; then
  fail_t "--auto with no roots should fail"
else
  ok "--auto without two usable roots exits non-zero"
fi

echo ""
echo "visual-regression: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
