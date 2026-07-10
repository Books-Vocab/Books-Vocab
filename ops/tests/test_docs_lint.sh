#!/usr/bin/env bash
# Regression tests for docs_lint gate/audit split and registry checks.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

dump_file() {
  file="$1"
  echo "---- $file (tail) ----" >&2
  if [ -f "$file" ]; then
    tail -80 "$file" >&2
  else
    echo "(missing)" >&2
  fi
}

run_capture() {
  out="$1"
  shift
  set +e
  "$@" >"$out" 2>&1
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "command failed rc=$rc: $*" >&2
    dump_file "$out"
    exit "$rc"
  fi
}

require_grep() {
  pattern="$1"
  file="$2"
  if ! grep -q "$pattern" "$file"; then
    echo "missing pattern '$pattern' in $file" >&2
    dump_file "$file"
    exit 1
  fi
}

grep -q "docs/registry.yml" CLAUDE.md
grep -q "ops/docs_impact.py" CLAUDE.md
grep -q "ops/docs_lint.sh" CLAUDE.md
grep -q "ops/docs_registry_coverage.py" CLAUDE.md
grep -q "cd backend && uv run python ops_cli.py" CLAUDE.md
grep -q "cd backend && uv run python ops_cli.py" AGENTS.md
grep -q "uv run python scripts/cli.py" CLAUDE.md
grep -q "uv run python scripts/cli.py" AGENTS.md
if grep -q "uv run ops/ops_cli.py" CLAUDE.md AGENTS.md; then
  echo "startup docs still reference missing ops/ops_cli.py" >&2
  exit 1
fi
if grep -q "uv run backend/ops_cli.py" CLAUDE.md AGENTS.md; then
  echo "startup docs still reference root-relative backend/ops_cli.py without backend project context" >&2
  exit 1
fi
if grep -q "uv run lab/llm_eval/cli.py" CLAUDE.md AGENTS.md; then
  echo "startup docs still reference missing lab/llm_eval/cli.py" >&2
  exit 1
fi
if grep -q "uv run llm-eval" CLAUDE.md AGENTS.md .claude/skills/kg-router/SKILL.md ops/capability_matrix.py; then
  echo "startup docs still reference unavailable llm-eval console script" >&2
  exit 1
fi

./ops/docs_lint.sh --help > /tmp/kg_docs_lint_help.out
if grep -q '^!/usr/bin/env bash' /tmp/kg_docs_lint_help.out; then
  echo "docs_lint --help should not expose the shebang line" >&2
  dump_file /tmp/kg_docs_lint_help.out
  exit 1
fi
require_grep "docs_lint.sh — docs gate / audit / registry checks" /tmp/kg_docs_lint_help.out

run_capture /tmp/kg_docs_lint_files.out ./ops/docs_lint.sh --files docs/reference/tech_index.md docs/sop/architecture.md
require_grep "ERROR: 0" /tmp/kg_docs_lint_files.out

run_capture /tmp/kg_docs_lint_default.out ./ops/docs_lint.sh
require_grep "mode=gate" /tmp/kg_docs_lint_default.out
if grep -q "docs_lint: mode=audit" /tmp/kg_docs_lint_default.out; then
  echo "docs_lint default mode should stay in gate mode, not silently flip to audit" >&2
  dump_file /tmp/kg_docs_lint_default.out
  exit 1
fi

run_capture /tmp/kg_docs_lint_audit.out ./ops/docs_lint.sh --audit
require_grep "mode=audit" /tmp/kg_docs_lint_audit.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_audit.out

run_capture /tmp/kg_docs_lint_all.out ./ops/docs_lint.sh --all
require_grep "mode=audit" /tmp/kg_docs_lint_all.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_all.out

run_capture /tmp/kg_docs_lint_registry.out ./ops/docs_lint.sh --registry
require_grep "REGISTRY OK" /tmp/kg_docs_lint_registry.out
require_grep "OK:    1" /tmp/kg_docs_lint_registry.out

run_capture /tmp/kg_docs_lint_since_head.out ./ops/docs_lint.sh --since HEAD
if ! grep -q "docs_lint: no docs selected" /tmp/kg_docs_lint_since_head.out; then
  require_grep "ERROR: 0" /tmp/kg_docs_lint_since_head.out
fi

impact_probe="ops/.docs_lint_impact_probe"
trap 'rm -f "$impact_probe"' EXIT
printf 'probe\n' >"$impact_probe"
run_capture /tmp/kg_docs_lint_impact.out ./ops/docs_lint.sh --since HEAD
require_grep "docs_lint: current checkout impact hints" /tmp/kg_docs_lint_impact.out
require_grep "reference.tech_index" /tmp/kg_docs_lint_impact.out
require_grep "docs_lint: inspect suppression with ./ops/docs_impact.py --since HEAD --explain" /tmp/kg_docs_lint_impact.out
require_grep "docs_lint: frontmatter checks below only cover docs changed in the current checkout; use the impact hints above to judge non-doc changes" /tmp/kg_docs_lint_impact.out
require_grep "docs_lint: next-step heuristic -> impact hints are sync candidates, not auto-required; STALE means freshness risk, not automatic doc-sync for this change" /tmp/kg_docs_lint_impact.out
rm -f "$impact_probe"
trap - EXIT

if ./ops/docs_lint.sh --definitely-not-a-real-flag >/tmp/kg_docs_lint_bad.out 2>&1; then
  echo "docs_lint accepted an unknown flag" >&2
  exit 1
fi
grep -q "Unknown arg" /tmp/kg_docs_lint_bad.out

if ./ops/docs_lint.sh --files docs/reference/does-not-exist.md >/tmp/kg_docs_lint_missing.out 2>&1; then
  echo "docs_lint accepted a missing --files path" >&2
  exit 1
fi
grep -q "路徑不存在" /tmp/kg_docs_lint_missing.out

run_capture /tmp/kg_docs_lint_positional.out ./ops/docs_lint.sh docs/reference/tech_index.md docs/sop/architecture.md
require_grep "ERROR: 0" /tmp/kg_docs_lint_positional.out

if ./ops/docs_lint.sh --files README.md >/tmp/kg_docs_lint_nondoc.out 2>&1; then
  echo "docs_lint accepted a non-doc --files path" >&2
  exit 1
fi
grep -q "只接受 docs/.*\\.md" /tmp/kg_docs_lint_nondoc.out

# --- IMP-0015: git 衝突標記殘留必須被 gate 攔截 ---
# 事故 92da32e64: rebase 解衝突未完成,衝突標記進 main 而 docs_lint 全綠。
# 衝突標記 <<<<<<< / >>>>>>> 在正常 doc 無合法用途,應 ERROR。
conflict_fixture="docs/.lint_test_conflict_marker.md"
cleanup_conflict() { rm -f "$conflict_fixture"; }
trap cleanup_conflict EXIT
cat > "$conflict_fixture" <<'CONFLICT_EOF'
<!-- doc-meta
tier: reference
authority: SoT
update_trigger: manual
scope:
  - ops/docs_lint.sh
verified_against: HEAD
-->
# Conflict fixture

<<<<<<< HEAD
ours line
=======
theirs line
>>>>>>> some-branch
CONFLICT_EOF
if ./ops/docs_lint.sh --files "$conflict_fixture" >/tmp/kg_docs_lint_conflict.out 2>&1; then
  echo "docs_lint 未攔截 git 衝突標記殘留(--files)" >&2
  dump_file /tmp/kg_docs_lint_conflict.out
  exit 1
fi
require_grep "衝突標記" /tmp/kg_docs_lint_conflict.out
# setext H1 底線(===)不得被誤判為衝突標記
setext_fixture="docs/.lint_test_setext.md"
cleanup_setext() { rm -f "$conflict_fixture" "$setext_fixture"; }
trap cleanup_setext EXIT
cat > "$setext_fixture" <<'SETEXT_EOF'
<!-- doc-meta
tier: reference
authority: SoT
update_trigger: manual
scope:
  - ops/docs_lint.sh
verified_against: HEAD
-->
Setext Heading
=======
內文,不該被當成衝突標記。
SETEXT_EOF
run_capture /tmp/kg_docs_lint_setext.out ./ops/docs_lint.sh --files "$setext_fixture"
require_grep "ERROR: 0" /tmp/kg_docs_lint_setext.out
cleanup_setext
trap - EXIT

# --- verified_against 可達性(anchor reachability) ---
# 實戰事故:doc-sync 在 rebase 前 branch 取 anchor,rebase 後 hash 成 orphan,
# gate 照綠(rev-parse 只驗 object 存在,不驗 HEAD 可達)。
# 不變式 = reachable-from-HEAD(放行 worktree pre-cutover 指自身 branch commit 的合法情境)。
anchor_fixture="docs/.lint_test_anchor.md"
cleanup_anchor() { rm -f "$anchor_fixture"; }
trap cleanup_anchor EXIT

write_anchor_fixture() {
  cat > "$anchor_fixture" <<ANCHOR_EOF
<!-- doc-meta
tier: reference
authority: SoT
update_trigger: manual
scope:
  - ops/docs_lint.sh
verified_against: $1
-->
# Anchor reachability fixture
ANCHOR_EOF
}

# 1) orphan anchor:object 存在但不在 HEAD 祖先鏈 → 必須紅
orphan_sha="$(git commit-tree "HEAD^{tree}" -m "docs_lint orphan anchor fixture")"
if git merge-base --is-ancestor "$orphan_sha" HEAD; then
  echo "fixture bug: orphan commit 竟然可達 HEAD: $orphan_sha" >&2
  exit 1
fi
write_anchor_fixture "$orphan_sha"
if ./ops/docs_lint.sh --files "$anchor_fixture" >/tmp/kg_docs_lint_orphan.out 2>&1; then
  echo "docs_lint 未攔截 orphan verified_against(存在但 HEAD 不可達)" >&2
  dump_file /tmp/kg_docs_lint_orphan.out
  exit 1
fi
require_grep "不可達" /tmp/kg_docs_lint_orphan.out
require_grep "re-anchor" /tmp/kg_docs_lint_orphan.out

# 2) 不存在的 sha(object db fetch 不到)→ 同樣紅
write_anchor_fixture "0000000000000000000000000000000000000000"
if ./ops/docs_lint.sh --files "$anchor_fixture" >/tmp/kg_docs_lint_nonexistent.out 2>&1; then
  echo "docs_lint 未攔截不存在的 verified_against sha" >&2
  dump_file /tmp/kg_docs_lint_nonexistent.out
  exit 1
fi
require_grep "不是有效 commit" /tmp/kg_docs_lint_nonexistent.out

# 3) 可達 anchor(HEAD 自身 sha)→ 綠
write_anchor_fixture "$(git rev-parse HEAD)"
run_capture /tmp/kg_docs_lint_reachable.out ./ops/docs_lint.sh --files "$anchor_fixture"
require_grep "ERROR: 0" /tmp/kg_docs_lint_reachable.out

# 4) audit 模式:orphan anchor 降 WARN,不翻紅既有 debt
write_anchor_fixture "$orphan_sha"
run_capture /tmp/kg_docs_lint_audit_orphan.out ./ops/docs_lint.sh --audit
require_grep "mode=audit" /tmp/kg_docs_lint_audit_orphan.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_audit_orphan.out
require_grep "不可達" /tmp/kg_docs_lint_audit_orphan.out

cleanup_anchor
trap - EXIT
