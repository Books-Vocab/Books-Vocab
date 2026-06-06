#!/usr/bin/env bash
# docs_lint.sh — 掃描 docs/ frontmatter 並回報 staleness
#
# 邏輯:
#   1. 對每份 docs/**/*.md(除了 assets/),解析 doc-meta frontmatter
#   2. 確認 5 個必填欄位齊全:tier / authority / update_trigger / scope / verified_against
#   3. 對非 archive doc,計算 verified_against..HEAD 期間有多少 commit 動過 scope 路徑
#      - 超過 STALE_THRESHOLD(預設 30)→ WARN
#      - verified_against 不是有效 sha(且不是 frozen)→ ERROR
#
# 用法:
#   ops/docs_lint.sh                 # 全掃描
#   ops/docs_lint.sh --changed       # 只掃本分支/工作樹變更的 docs
#   ops/docs_lint.sh --since <rev>   # 只掃 <rev>..HEAD + 工作樹變更的 docs
#   ops/docs_lint.sh --files <docs...>
#   ops/docs_lint.sh --strict        # 任何 WARN 都 exit 1
#   STALE_THRESHOLD=10 ops/docs_lint.sh
#
# Exit code:
#   0 — 全部 OK 或僅 WARN
#   1 — 有 ERROR(欄位缺失 / verified_against 無效)或 --strict 模式下有 WARN
#
# 相容 bash 3.2(macOS 預設),不使用 mapfile / readarray。

set -euo pipefail

# 切到 main checkout（cwd 無關）。--show-toplevel 從 linked worktree 內會回傳【該 worktree】路徑，
# 致 staleness 用 worktree 不完整歷史計算（verified_against commit 可能不可達 → 誤判 / ERROR）。
# 改用 --git-common-dir 派生 main checkout：從 main / 任意 worktree / 子目錄皆正確。
if _gcd="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" && [ -n "$_gcd" ]; then
  cd "$(dirname "$_gcd")"                 # git >= 2.31
else
  cd "$(git rev-parse --git-common-dir)/.."   # 古董 git fallback（git-common-dir 從 worktree 回絕對；從 main 回相對亦正確）
fi

STALE_THRESHOLD="${STALE_THRESHOLD:-30}"
STRICT=0
MODE="all"
SINCE_REV=""
FILE_ARGS=()

usage() {
  sed -n '1,22p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --strict)
      STRICT=1
      shift
      ;;
    --changed)
      MODE="changed"
      shift
      ;;
    --since)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --since" >&2
        exit 2
      fi
      MODE="changed"
      SINCE_REV="$2"
      shift 2
      ;;
    --files)
      MODE="files"
      shift
      while [ "$#" -gt 0 ]; do
        case "$1" in
          --*) break ;;
          *) FILE_ARGS+=("$1"); shift ;;
        esac
      done
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

REQUIRED_FIELDS="tier authority update_trigger scope verified_against"
VALID_TIERS="policy sop reference snapshot runbook archive assets"

errors=0
warnings=0
ok=0

filter_docs() {
  awk '
    /\.md$/ &&
    $0 !~ /^docs\/assets\// &&
    $0 !~ /^docs\/legal\// &&
    $0 ~ /^docs\// { print }
  ' | sort -u
}

all_docs() {
  find docs -type f -name "*.md" \
    ! -path "docs/assets/*" \
    ! -path "docs/legal/*" | sort
}

default_changed_base() {
  if [ -n "${DOCS_LINT_BASE:-}" ]; then
    printf '%s\n' "$DOCS_LINT_BASE"
    return
  fi
  if git rev-parse --verify origin/HEAD >/dev/null 2>&1; then
    git merge-base origin/HEAD HEAD
    return
  fi
  git rev-parse HEAD
}

changed_docs() {
  base="${SINCE_REV:-$(default_changed_base)}"
  if ! git rev-parse --verify "$base^{commit}" >/dev/null 2>&1; then
    echo "ERROR --since/changed base 不是有效 commit: $base" >&2
    exit 2
  fi
  {
    git diff --name-only --diff-filter=ACMR "$base..HEAD" -- docs
    git diff --name-only --diff-filter=ACMR --cached -- docs
    git diff --name-only --diff-filter=ACMR -- docs
    git ls-files --others --exclude-standard docs
  } | filter_docs
}

files_docs() {
  if [ "${#FILE_ARGS[@]}" -eq 0 ]; then
    echo "ERROR --files 需要至少一個 docs/*.md 路徑" >&2
    exit 2
  fi
  printf '%s\n' "${FILE_ARGS[@]}" | filter_docs
}

case "$MODE" in
  all) DOCS=$(all_docs) ;;
  changed) DOCS=$(changed_docs) ;;
  files) DOCS=$(files_docs) ;;
  *) echo "internal error: unknown MODE=$MODE" >&2; exit 2 ;;
esac

if [ -z "$DOCS" ]; then
  echo "docs_lint: no docs selected (mode=$MODE)"
  exit 0
fi

while IFS= read -r f; do
  [ -z "$f" ] && continue

  # Extract frontmatter block(只抓第一個 <!-- doc-meta ... -->,避免被 doc 內其他 HTML 註解誤抓)
  meta=$(awk '/<!-- doc-meta/{flag=1} flag{print} /-->/{if(flag){exit}}' "$f")
  if [ -z "$meta" ]; then
    echo "ERROR $f — 沒有 <!-- doc-meta --> frontmatter"
    errors=$((errors+1))
    continue
  fi

  # Validate required fields
  missing=""
  for field in $REQUIRED_FIELDS; do
    if ! echo "$meta" | grep -qE "^${field}:"; then
      missing="$missing $field"
    fi
  done
  if [ -n "$missing" ]; then
    echo "ERROR $f — 缺欄位:$missing"
    errors=$((errors+1))
    continue
  fi

  # value 解析:抓 ": " 後面的內容,strip 前後空白與引號(YAML scalar 容錯)
  tier=$(echo "$meta" | grep -E "^tier:" | head -1 | sed -E 's/^tier:[[:space:]]*//; s/^"//; s/"$//')
  verified=$(echo "$meta" | grep -E "^verified_against:" | head -1 | sed -E 's/^verified_against:[[:space:]]*//; s/^"//; s/"$//')

  # Validate tier
  if ! echo " $VALID_TIERS " | grep -q " $tier "; then
    echo "ERROR $f — 非法 tier: $tier(允許: $VALID_TIERS)"
    errors=$((errors+1))
    continue
  fi

  # Archive: skip staleness
  if [ "$tier" = "archive" ]; then
    if [ "$verified" != "frozen" ]; then
      echo "WARN  $f — archive doc verified_against 應為 'frozen',實際: $verified"
      warnings=$((warnings+1))
    else
      ok=$((ok+1))
    fi
    continue
  fi

  # Validate verified_against is real commit
  if ! git rev-parse --verify "$verified^{commit}" >/dev/null 2>&1; then
    echo "ERROR $f — verified_against 不是有效 commit: $verified"
    errors=$((errors+1))
    continue
  fi

  # Extract scope paths
  scope_paths=$(echo "$meta" | awk '
    /^scope:/ { in_scope=1; next }
    in_scope && /^  - / { sub(/^  - /,""); print; next }
    in_scope && !/^  / { in_scope=0 }
  ')

  if [ -z "$scope_paths" ]; then
    echo "WARN  $f — scope 為空,無法計算 staleness"
    warnings=$((warnings+1))
    continue
  fi

  # Count commits in scope between verified..HEAD
  # NUL-delimit so scope paths containing whitespace survive as single args
  # (plain `xargs` word-splits on spaces → undercounts staleness). -0 is BSD-safe.
  commits_in_scope=$(printf '%s\n' "$scope_paths" | tr '\n' '\0' | xargs -0 git log --oneline "$verified..HEAD" -- 2>/dev/null | wc -l | tr -d ' ')

  if [ "$commits_in_scope" -gt "$STALE_THRESHOLD" ]; then
    echo "STALE $f — $verified..HEAD 期間 $commits_in_scope 個 commit 動到 scope(閾值 $STALE_THRESHOLD)"
    warnings=$((warnings+1))
  else
    ok=$((ok+1))
  fi
done <<EOF
$DOCS
EOF

echo ""
echo "─────────────────────────────────────"
echo "OK:    $ok"
echo "WARN:  $warnings"
echo "ERROR: $errors"
echo "─────────────────────────────────────"

[ "$errors" -gt 0 ] && exit 1
[ "$STRICT" -eq 1 ] && [ "$warnings" -gt 0 ] && exit 1
exit 0
