#!/usr/bin/env bash
# test_ui_quality_plane.sh — behavior tests for ops/ui_quality_plane.py.
#
# Covers: validate (schema + entrypoint/docs existence + enum + dup id),
# list --json, impact --files trigger matching (dir prefix / glob / !exclude),
# and the real plane file staying valid.
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
PLANE=("$UV_BIN" run --no-project --python 3.13 python ops/ui_quality_plane.py)

pass=0
fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/kg_ui_plane_test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

write_fixture() {
  # $1 = path; stdin = yml body
  cat >"$1"
}

section "Real plane validates"
if "${PLANE[@]}" validate >/dev/null 2>&1; then
  ok "ops/ui_quality_plane.yml validate exit 0"
else
  fail_t "ops/ui_quality_plane.yml failed validate"
fi

section "list --json on real plane"
LIST_JSON="$("${PLANE[@]}" list --json 2>/dev/null || true)"
# Self-maintaining count: every `- id:` declared in the yml must survive the
# parser — a silent parse drop is exactly the failure this guards against.
DECLARED="$(grep -c '^  - id:' ops/ui_quality_plane.yml)"
if jq -e --argjson n "$DECLARED" 'type == "array" and length == $n' <<<"$LIST_JSON" >/dev/null 2>&1; then
  ok "list --json carries all $DECLARED declared mechanisms"
else
  fail_t "list --json count != declared $DECLARED: $LIST_JSON"
fi
if jq -e 'all(.[]; has("id") and has("layer") and has("entrypoint") and has("gate"))' <<<"$LIST_JSON" >/dev/null 2>&1; then
  ok "every mechanism has id/layer/entrypoint/gate"
else
  fail_t "mechanism entries missing required keys"
fi

section "validate catches broken fixtures"
# Reject = non-zero exit AND a diagnostic on stderr; a parser crash (traceback,
# no ERROR: line) must not pass as a rejection.
expect_reject() {
  local fixture="$1" label="$2" err rc
  err="$(KG_UI_PLANE_FILE="$fixture" "${PLANE[@]}" validate 2>&1 >/dev/null)"; rc=$?
  if [[ "$rc" -ne 0 && "$err" == *"ERROR:"* ]]; then
    ok "validate rejects $label with diagnostic"
  else
    fail_t "validate $label: rc=$rc stderr=$err"
  fi
}

write_fixture "$TMP/missing_entrypoint.yml" <<'YML'
version: 1
mechanisms:
  - id: fake.tool
    layer: static-code
    entrypoint: ops/does_not_exist_anywhere.sh
    gate: manual
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
expect_reject "$TMP/missing_entrypoint.yml" "missing entrypoint"

write_fixture "$TMP/dup_id.yml" <<'YML'
version: 1
mechanisms:
  - id: dup.tool
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: manual
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
  - id: dup.tool
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: manual
    triggers:
      - backend/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
expect_reject "$TMP/dup_id.yml" "duplicate id"

write_fixture "$TMP/bad_enum.yml" <<'YML'
version: 1
mechanisms:
  - id: enum.tool
    layer: not-a-layer
    entrypoint: ops/test_ops.sh
    gate: manual
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
expect_reject "$TMP/bad_enum.yml" "unknown layer enum"

write_fixture "$TMP/bad_gate.yml" <<'YML'
version: 1
mechanisms:
  - id: gate.tool
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: vibes
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
expect_reject "$TMP/bad_gate.yml" "unknown gate enum"

write_fixture "$TMP/unknown_key.yml" <<'YML'
version: 1
mechanisms:
  - id: key.tool
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: manual
    severity: high
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
expect_reject "$TMP/unknown_key.yml" "unknown key"

write_fixture "$TMP/empty_triggers.yml" <<'YML'
version: 1
mechanisms:
  - id: trig.tool
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: manual
    triggers:
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
expect_reject "$TMP/empty_triggers.yml" "empty triggers list"

write_fixture "$TMP/missing_doc.yml" <<'YML'
version: 1
mechanisms:
  - id: doc.tool
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: manual
    triggers:
      - ios/
    verdict: "exit code"
    docs:
      - docs/sop/never_written.md
YML
expect_reject "$TMP/missing_doc.yml" "missing doc path"

section "impact --files trigger matching"
write_fixture "$TMP/impact.yml" <<'YML'
version: 1
mechanisms:
  - id: swift.gate
    layer: static-code
    entrypoint: ops/test_ops.sh
    gate: test_ops
    triggers:
      - ios/BooksAndVocab/
      - "!ios/BooksAndVocab/Debug/"
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
  - id: exact.gate
    layer: static-value
    entrypoint: ops/test_ops.sh
    gate: ci
    triggers:
      - design-system/tokens.json
    verdict: "exit code"
    docs:
      - docs/sop/ios.md
YML
IMPACT() { KG_UI_PLANE_FILE="$TMP/impact.yml" "${PLANE[@]}" impact --json --files "$@" 2>/dev/null; }

OUT="$(IMPACT ios/BooksAndVocab/Views/Foo.swift)"
if jq -e 'map(.id) == ["swift.gate"]' <<<"$OUT" >/dev/null 2>&1; then
  ok "dir-prefix trigger matches"
else
  fail_t "dir-prefix trigger failed: $OUT"
fi

OUT="$(IMPACT ios/BooksAndVocab/Debug/CatalogScene.swift)"
if jq -e 'length == 0' <<<"$OUT" >/dev/null 2>&1; then
  ok "!exclude suppresses broad dir match"
else
  fail_t "!exclude not honored: $OUT"
fi

OUT="$(IMPACT design-system/tokens.json backend/src/kg/main.py)"
if jq -e 'map(.id) == ["exact.gate"]' <<<"$OUT" >/dev/null 2>&1; then
  ok "exact trigger matches; unrelated file matches nothing"
else
  fail_t "exact trigger failed: $OUT"
fi

OUT="$(IMPACT docs/sop/debug.md)"
if jq -e 'length == 0' <<<"$OUT" >/dev/null 2>&1; then
  ok "no-match file yields empty impact (exit 0)"
else
  fail_t "no-match file produced impact: $OUT"
fi

OUT="$(KG_UI_PLANE_FILE="$TMP/impact.yml" "${PLANE[@]}" impact --files ios/BooksAndVocab/Views/Foo.swift 2>/dev/null)"
if grep -q "swift.gate" <<<"$OUT" && grep -q "ops/test_ops.sh" <<<"$OUT"; then
  ok "human impact output names mechanism + entrypoint"
else
  fail_t "human impact output incomplete: $OUT"
fi

section "Real plane impact sanity"
OUT="$("${PLANE[@]}" impact --json --files ios/BooksAndVocab/Views/Vocabulary/Components/VocabCalendarGrid.swift 2>/dev/null)"
if jq -e 'map(.id) | index("static.plain_deadzone") != null and index("static.ui_token") != null' <<<"$OUT" >/dev/null 2>&1; then
  ok "iOS view change maps to plain_deadzone + ui_token gates"
else
  fail_t "real plane misses iOS view gates: $OUT"
fi
# App-root Swift files live directly under ios/BooksAndVocab/ — `**/` globs
# alone miss them (fnmatch needs >=1 subdir level); regression for that hole.
OUT="$("${PLANE[@]}" impact --json --files ios/BooksAndVocab/ContentView.swift 2>/dev/null)"
if jq -e 'map(.id) | index("static.ui_token") != null and index("static.i18n") != null' <<<"$OUT" >/dev/null 2>&1; then
  ok "app-root Swift file still triggers the swift lints"
else
  fail_t "app-root Swift file misses swift lints: $OUT"
fi
OUT="$("${PLANE[@]}" impact --json --files design-system/tokens.json 2>/dev/null)"
if jq -e 'map(.id) | index("value.design_system") != null' <<<"$OUT" >/dev/null 2>&1; then
  ok "tokens.json change maps to design-system verify"
else
  fail_t "real plane misses design-system verify: $OUT"
fi

echo ""
echo "ui-quality-plane: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
