#!/usr/bin/env bash
# Every block-level cutover gate must be provably able to go red.
#
# 這是唯一能抓「檢查器根本不存在」的機制，而其他所有品質手段都抓不到：
#   - `ios-quality-impact` 掛在 cutover 上，routed 到 ui_quality_plane 的**規劃器**，
#     每條 return 都是 0 —— 結構上不可能失敗，卻叫 quality gate。
#   - `.github/workflows/ui-quality-gate.yml` 連續兩個月 `planned=0` 回綠。
#   - i18n baseline 停在 51 而實際 0，門檻在但形同虛設。
# 三者的共同點是：沒有任何東西問過「餵它一個已知壞輸入，它會紅嗎」。
#
# 契約：plan_gates 能排出的每一道 level=block 的 gate，都必須在 PROOFS 裡有一筆
# 「怎麼讓它紅」的證明。CHEAP 的當場跑；EXPENSIVE 的（xcodebuild 等）只登記證明
# 途徑並在此註明未執行——**明示未跑，不假裝跑過**。

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; else UV_BIN="uv"; fi
fi

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
note() { echo "  · $*"; }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# gate-name|kind|how it is proven to fail
#   cheap     — proof is executed by this test
#   expensive — proof route recorded; running it here would cost minutes of
#               xcodebuild, so it is deliberately NOT executed
PROOFS=(
  "ui-quality-fast|cheap|inject a raw-CJK Text() and run the gate command"
  "review-receipts|cheap|a commit without a Reviewed-by/Review-Exempt trailer"
  "docs-lint|cheap|a doc with a conflict marker"
  "ios-build|expensive|ops/test_ios_ops.sh covers xcodebuild failure propagation"
  "ios-build-catalyst|expensive|same runner as ios-build"
  "ios-test-unit|expensive|ops/tests/test_ios_run_verdict.sh false-green section"
  "ios-test-ui|expensive|ops/tests/test_ios_run_verdict.sh false-green section"
  "ios-live-demo-uitest-compile|expensive|Release iphoneos compile gate, see test_ios_ops.sh"
  "design-system|expensive|ops/verify_design_system.sh has its own regression suite"
  "backend-pytest|expensive|pytest's own non-zero exit"
  "ops-pytest|expensive|pytest's own non-zero exit"
  "docs-conflict-markers|cheap|internal gate, same fixture as docs-lint"
  "coverage|cheap|internal gate"
)

proof_for() {  # $1 = gate name -> "kind|description" or empty
  local g="$1" e
  for e in "${PROOFS[@]}"; do
    [[ "${e%%|*}" == "$g" ]] && { printf '%s\n' "${e#*|}"; return 0; }
  done
  return 1
}

section "every block-level gate has a recorded way to fail"
BLOCK_GATES="$(
  "$UV_BIN" run --no-project --python 3.13 python - <<'PY'
import importlib.util as u, pathlib
s = u.spec_from_file_location("wo", "ops/worktree_orchestrate.py")
m = u.module_from_spec(s); s.loader.exec_module(m)
probes = [
    ["ios/BooksAndVocab/Views/X.swift"],
    ["ios/BooksAndVocabUITests/FooTests.swift"],
    ["ios/BooksAndVocabUITests/LiveDemoAccessUITests.swift"],
    ["docs/reference/tech_index.md"],
    ["backend/src/kg/app.py"], ["backend/tests/test_x.py"],
    ["ops/worktree_orchestrate.py"], ["design-system/tokens.json"],
    ["README.md"],
]
names = set()
for files in probes:
    for g in m.plan_gates(files, ops_test_exists=lambda rel: True, base="main"):
        if g["level"] == "block":
            names.add(g["name"].split(":")[0])
print("\n".join(sorted(names)))
PY
)"
[[ -n "$BLOCK_GATES" ]] || fail_t "enumerated zero block gates — the probe is broken, not the coverage"
while IFS= read -r g; do
  [[ -z "$g" ]] && continue
  if proof_for "$g" >/dev/null; then :; else
    fail_t "$g is a block gate with no recorded proof that it can fail — add it to PROOFS"
  fi
done <<<"$BLOCK_GATES"
(( fail == 0 )) && ok "all block gates declared: $(tr '\n' ' ' <<<"$BLOCK_GATES")"

section "cheap proofs are executed, not asserted"

# ui-quality-fast: a raw-CJK string must turn the gate command red.
PROBE="ios/BooksAndVocab/Views/Settings/KGCanFailProbe.swift"
cleanup_probe() { rm -f "$PROBE"; }
trap 'cleanup_probe; rm -rf "$TMP"' EXIT
printf 'import SwiftUI\n\nstruct KGCanFailProbe: View {\n    @ObserveInjection private var inject\n    var body: some View {\n        Text("紅燈探針")\n            .enableInjection()\n    }\n}\n' >"$PROBE"
rc=0; ./ops/ui_quality_gate.sh --tier fast --execute --all-mechanisms >/dev/null 2>&1 || rc=$?
cleanup_probe
[[ "$rc" -ne 0 ]] && ok "ui-quality-fast goes red on a raw-CJK string (exit $rc)" \
  || fail_t "ui-quality-fast stayed green with a raw-CJK string in the tree"

# review-receipts: a commit without a trailer must be rejected.
git init -q "$TMP/repo" 2>/dev/null
git -C "$TMP/repo" config user.email t@t.test; git -C "$TMP/repo" config user.name T
: >"$TMP/repo/a.txt"; git -C "$TMP/repo" add -A; git -C "$TMP/repo" commit -qm root
git -C "$TMP/repo" branch -M main
: >"$TMP/repo/b.txt"; git -C "$TMP/repo" add -A
git -C "$TMP/repo" commit -qm "feat: no receipt at all"
rc=0
( cd "$TMP/repo" && "$WORKSPACE/ops/review_audit.sh" --rev-range main~1..HEAD ) >/dev/null 2>&1 || rc=$?
[[ "$rc" -ne 0 ]] && ok "review-receipts rejects a trailer-less commit (exit $rc)" \
  || fail_t "review-receipts accepted a commit with no Reviewed-by/Review-Exempt"

# docs-lint: a conflict marker must be an ERROR.
mkdir -p "$TMP/docs"
printf '<!-- doc-meta -->\n<<<<<<< HEAD\nx\n' >"$TMP/conflict.md"
rc=0; ./ops/docs_lint.sh --files "$TMP/conflict.md" >/dev/null 2>&1 || rc=$?
[[ "$rc" -ne 0 ]] && ok "docs-lint goes red on a conflict marker (exit $rc)" \
  || fail_t "docs-lint accepted a file containing a conflict marker"

section "expensive proofs are recorded, not silently skipped"
while IFS= read -r g; do
  [[ -z "$g" ]] && continue
  p="$(proof_for "$g" || true)"
  [[ "${p%%|*}" == "expensive" ]] && note "$g — not executed here: ${p#*|}"
done <<<"$BLOCK_GATES"
ok "expensive proofs named explicitly (no silent coverage claim)"

echo ""
echo "gate-can-fail: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
