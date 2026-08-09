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
# Negative guards ("this string must NOT appear") over a LIST of files.
#
# `grep -q` returns 2 when any listed file is missing — and measured, it returns 2
# **even when a real match exists in another file, in any order**. So a deleted or
# renamed file does not make these noisy, it makes them STOP DETECTING, while the
# `if` stays false and the test stays green. That is the precise failure this repo
# has already paid for once (a `grep -P` guard that failed on every file and
# reported ✓); the file list here includes `.claude/skills/kg-router/SKILL.md`,
# which is a live deletion candidate.
#
# So: assert the files exist FIRST, loudly, then grep. Positive guards above do not
# need this — under `set -e` their rc=2 already fails the test.
forbid_in() {
  local pattern="$1"; shift
  local message="$1"; shift
  local f
  for f in "$@"; do
    if [[ ! -f "$f" ]]; then
      echo "guard input missing: $f (pattern '$pattern' would silently stop being checked)" >&2
      exit 1
    fi
  done
  if grep -q "$pattern" "$@"; then
    echo "$message" >&2
    exit 1
  fi
}

# Self-check, in a subshell, before the real guards run. `forbid_in` exists to turn
# a silent failure into a loud one, and a guard whose own failure mode is silence
# has to prove it can speak — measured three ways on the code this replaced:
#   real violation, all files present  -> old grep rc 0, caught
#   file missing, no violation         -> old grep rc 2, `if` false, "clean"
#   file missing AND real violation    -> old grep rc 2, `if` false, MISSED ENTIRELY
# The third is the one that matters: the old form passed while a genuine violation
# sat in a file it could read.
(
  probe_dir="$(mktemp -d)"
  trap 'rm -rf "$probe_dir"' EXIT
  printf 'VIOLATION\n' >"$probe_dir/has.txt"
  printf 'clean\n' >"$probe_dir/clean.txt"

  if ( forbid_in "VIOLATION" "probe" "$probe_dir/clean.txt" ) ; then :; else
    echo "forbid_in reported a violation that is not there" >&2; exit 1
  fi
  if ( forbid_in "VIOLATION" "probe" "$probe_dir/clean.txt" "$probe_dir/has.txt" ) 2>/dev/null; then
    echo "forbid_in missed a real violation" >&2; exit 1
  fi
  # the whole point: a missing file must NOT read as clean, even with a real
  # violation sitting in a readable sibling
  if ( forbid_in "VIOLATION" "probe" "$probe_dir/gone.txt" "$probe_dir/has.txt" ) 2>/dev/null; then
    echo "forbid_in treated a missing input as clean — the guard is dead and silent" >&2
    exit 1
  fi
) || exit 1

forbid_in "uv run ops/ops_cli.py" \
  "startup docs still reference missing ops/ops_cli.py" \
  CLAUDE.md AGENTS.md
forbid_in "uv run backend/ops_cli.py" \
  "startup docs still reference root-relative backend/ops_cli.py without backend project context" \
  CLAUDE.md AGENTS.md
forbid_in "uv run lab/llm_eval/cli.py" \
  "startup docs still reference missing lab/llm_eval/cli.py" \
  CLAUDE.md AGENTS.md
forbid_in "uv run llm-eval" \
  "startup docs still reference unavailable llm-eval console script" \
  CLAUDE.md AGENTS.md .claude/skills/kg-router/SKILL.md ops/capability_matrix.py
forbid_in "[^/]main 可達.*code commit" \
  "agent-facing config still states the refuted local-main anchor standard (SoT: docs/sop/doc_sync.md step 4 = origin/main reachable)" \
  CLAUDE.md .claude/agents/docs-steward.md

./ops/docs_lint.sh --help > /tmp/kg_docs_lint_help.out
if grep -q '^!/usr/bin/env bash' /tmp/kg_docs_lint_help.out; then
  echo "docs_lint --help should not expose the shebang line" >&2
  dump_file /tmp/kg_docs_lint_help.out
  exit 1
fi
require_grep "docs_lint.sh — docs gate / audit / registry checks" /tmp/kg_docs_lint_help.out
# --help 必須印**完**整個檔頭,不能只印開頭。前身是寫死的 `sed -n '2,24p'`,而註解區早已
# 長到第 31 行,於是「Exit code」與 STALE_THRESHOLD 被靜靜截掉、沒有任何測試察覺。
# 這兩條斷言同時釘住新舊兩種截斷:寫死行號回流,以及檔頭裡不小心插入真正空行
# (會讓現行 awk 提早 exit)。
require_grep "Exit code" /tmp/kg_docs_lint_help.out
require_grep "相容 bash 3.2" /tmp/kg_docs_lint_help.out

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
# `commit-tree` 需要 committer identity。開發機有 global config 所以看不出來，
# 乾淨的 CI 容器沒有 → `fatal: unable to auto-detect email address`、rc=128，
# 而且錯誤跟本測試要驗的東西毫無關係。用 `-c` 就地供給，不動 repo 的 config
# （這支跑在真 repo 裡，不是 temp clone）。慣例對齊 test_branch_audit /
# test_review_audit / test_gate_can_fail 等既有做法。
orphan_sha="$(git -c user.email=docs-lint@example.test -c user.name="docs-lint fixture" commit-tree "HEAD^{tree}" -m "docs_lint orphan anchor fixture")"
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

# --- anchor origin 可達性(第二層,WARN 不 ERROR;IMP-20260805-9bb2d2)---
# 「HEAD 可達」不等於「origin 可達」:本 repo 拓樸是本地 main 為主幹、刻意超前 origin,
# 所以錨在分支自身 commit 的 doc 對 case 3 是綠的,卻正是 cutover rebase 會 orphan 掉的那種。
# 這條知識原本只活在 backlog.py 的 _doc_anchor() docstring 裡,docs_lint 一個字都不說。

# 5) 正控:ORIGIN_REF 落後 HEAD 一格 → anchor(=HEAD)origin 不可達 → WARN + 可照抄的建議 sha,
#    且 exit 0(rc 由 run_capture 把關)。
origin_behind="$(git rev-parse HEAD~1)"
write_anchor_fixture "$(git rev-parse HEAD)"
export KG_DOCS_LINT_ORIGIN_REF="$origin_behind"
run_capture /tmp/kg_docs_lint_origin_warn.out ./ops/docs_lint.sh --files "$anchor_fixture"
unset KG_DOCS_LINT_ORIGIN_REF
require_grep "origin-unreachable" /tmp/kg_docs_lint_origin_warn.out
require_grep "建議改錨" /tmp/kg_docs_lint_origin_warn.out
# 建議的 sha 要是 9 碼短式(全 repo 的 anchor 慣例),不是 40 碼——訊息自稱可照抄。
require_grep "$(git rev-parse --short=9 "$origin_behind")" /tmp/kg_docs_lint_origin_warn.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_origin_warn.out
# summary 也要真的計進去。少了這行,把 `warnings=$((warnings+1))` 整行刪掉四個案子照樣綠:
# 訊息照印、ERROR: 0 照過,只有 --strict 從此抓不到這條。(OK: 1 是 registry 檢查貢獻的,
# 不是同一份 doc 被雙記。)
require_grep "WARN:  1" /tmp/kg_docs_lint_origin_warn.out

# 6) 正控(acceptance 形狀):ORIGIN_REF 是與 HEAD 無血緣的 root commit → 任何 anchor 都必然
#    origin 不可達;此時沒有 merge-base 可建議,第二行必須具名說出「沒有」而不是憑空生一顆 sha。
unrelated_origin="$(git -c user.email=docs-lint@example.test -c user.name="docs-lint fixture" commit-tree "HEAD^{tree}" -m "docs_lint unrelated origin fixture")"
if git merge-base --is-ancestor "$(git rev-parse HEAD)" "$unrelated_origin" 2>/dev/null; then
  echo "fixture bug: HEAD 竟然是無血緣 root commit 的祖先: $unrelated_origin" >&2
  exit 1
fi
export KG_DOCS_LINT_ORIGIN_REF="$unrelated_origin"
run_capture /tmp/kg_docs_lint_origin_norelation.out ./ops/docs_lint.sh --files "$anchor_fixture"
unset KG_DOCS_LINT_ORIGIN_REF
require_grep "origin-unreachable" /tmp/kg_docs_lint_origin_norelation.out
require_grep "無共同祖先" /tmp/kg_docs_lint_origin_norelation.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_origin_norelation.out

# 7) 負控:origin 可達的 anchor 不得冒這條 WARN,否則它退化成無差別警告。
#    錨取 merge-base(origin/main, HEAD) —— 依定義 origin 可達;沒有 origin/main 的 clone
#    (fresh / shallow CI)則落回 HEAD,此時第 8 案的 skip 語意接手,斷言仍成立。
if origin_base=$(git merge-base origin/main HEAD 2>/dev/null) && [ -n "$origin_base" ]; then
  write_anchor_fixture "$origin_base"
else
  write_anchor_fixture "$(git rev-parse HEAD)"
fi
run_capture /tmp/kg_docs_lint_origin_clean.out ./ops/docs_lint.sh --files "$anchor_fixture"
if grep -q "origin-unreachable" /tmp/kg_docs_lint_origin_clean.out; then
  echo "origin 可達的 anchor 不該冒 origin-unreachable(無差別警告)" >&2
  dump_file /tmp/kg_docs_lint_origin_clean.out
  exit 1
fi

# 8) 負控:ORIGIN_REF 根本不存在(未 fetch 的 clone)→ 整段跳過,不得因此變吵或變紅。
write_anchor_fixture "$(git rev-parse HEAD)"
export KG_DOCS_LINT_ORIGIN_REF="refs/remotes/origin/kg-docs-lint-no-such-ref-$$"
run_capture /tmp/kg_docs_lint_origin_missing.out ./ops/docs_lint.sh --files "$anchor_fixture"
unset KG_DOCS_LINT_ORIGIN_REF
if grep -q "origin-unreachable" /tmp/kg_docs_lint_origin_missing.out; then
  echo "ORIGIN_REF 不存在時應整段跳過,不該警告" >&2
  dump_file /tmp/kg_docs_lint_origin_missing.out
  exit 1
fi
require_grep "ERROR: 0" /tmp/kg_docs_lint_origin_missing.out

# --- reanchor orphan verified_against(IMP-20260806-32b6ee) ---
# reanchor 只掃 tracked docs；沿用真實 doc 做 fixture，測完以備份復原，避免
# untracked fixture 被跳過，也避免把測試 anchor 留在工作樹。
reanchor_doc="docs/sop/doc_sync.md"
reanchor_doc_backup="$(mktemp /tmp/kg_docs_lint_reanchor_doc.XXXXXX)"
cp -p "$reanchor_doc" "$reanchor_doc_backup"
cleanup_reanchor() {
  cp -p "$reanchor_doc_backup" "$reanchor_doc"
  rm -f "$reanchor_doc_backup"
  cleanup_anchor
}
trap cleanup_reanchor EXIT

write_reanchor_anchor() {
  new_anchor="$1"
  reanchor_tmp="${reanchor_doc}.reanchor-test.$$"
  awk -v new_anchor="$new_anchor" '
    /^verified_against:/ && !replaced {
      sub(/^verified_against:[[:space:]]*.*/, "verified_against: " new_anchor)
      replaced=1
    }
    { print }
  ' "$reanchor_doc" > "$reanchor_tmp"
  mv "$reanchor_tmp" "$reanchor_doc"
}

# 9) stable patch-id 唯一匹配:orphan commit 與 HEAD 使用相同 parent/tree，
#    因而 diff 等價但 object 不在 HEAD 祖先鏈；dry-run 不應改 doc。
reanchor_candidate="$(git rev-parse HEAD)"
reanchor_parent="$(git rev-parse "${reanchor_candidate}^")"
reanchor_orphan_sha="$(git -c user.email=docs-lint@example.test -c user.name="docs-lint fixture" commit-tree "${reanchor_candidate}^{tree}" -p "$reanchor_parent" -m "docs_lint reanchor orphan fixture")"
if git merge-base --is-ancestor "$reanchor_orphan_sha" HEAD; then
  echo "fixture bug: reanchor orphan commit 竟然可達 HEAD: $reanchor_orphan_sha" >&2
  exit 1
fi
write_reanchor_anchor "$reanchor_orphan_sha"
cp -p "$reanchor_doc" /tmp/kg_docs_lint_reanchor_before_dry_run.out
run_capture /tmp/kg_docs_lint_reanchor_dry_run.out ./ops/docs_lint.sh --reanchor --search-depth 1
require_grep "patch-id match" /tmp/kg_docs_lint_reanchor_dry_run.out
require_grep "mapped=1 unmatched=0" /tmp/kg_docs_lint_reanchor_dry_run.out
if ! cmp -s /tmp/kg_docs_lint_reanchor_before_dry_run.out "$reanchor_doc"; then
  echo "reanchor dry-run 不得改寫 tracked doc" >&2
  exit 1
fi

# 10) --commit 落地唯一映射後，該 doc 應可通過既有 --files gate。
run_capture /tmp/kg_docs_lint_reanchor_commit.out ./ops/docs_lint.sh --reanchor --search-depth 1 --commit
require_grep "landed 1 mapping(s) (--commit)" /tmp/kg_docs_lint_reanchor_commit.out
require_grep "verified_against: $(git rev-parse --short=9 "$reanchor_candidate")" "$reanchor_doc"
run_capture /tmp/kg_docs_lint_reanchor_files.out ./ops/docs_lint.sh --files "$reanchor_doc"
require_grep "ERROR: 0" /tmp/kg_docs_lint_reanchor_files.out

# 11) patch-id 無匹配時具名報錯並非零，絕不猜測鄰近 commit。
reanchor_unmatched_sha="$(git -c user.email=docs-lint@example.test -c user.name="docs-lint fixture" commit-tree "HEAD^{tree}" -p HEAD -m "docs_lint reanchor unmatched fixture")"
write_reanchor_anchor "$reanchor_unmatched_sha"
if ./ops/docs_lint.sh --reanchor --search-depth 1 >/tmp/kg_docs_lint_reanchor_unmatched.out 2>&1; then
  echo "reanchor unmatched fixture 不應被猜測成成功" >&2
  dump_file /tmp/kg_docs_lint_reanchor_unmatched.out
  exit 1
fi
require_grep "$reanchor_doc" /tmp/kg_docs_lint_reanchor_unmatched.out
require_grep "patch-id 無唯一匹配(0 個候選),不猜" /tmp/kg_docs_lint_reanchor_unmatched.out

cleanup_reanchor
trap - EXIT
