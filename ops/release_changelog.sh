#!/bin/bash
# release_changelog.sh — 從 git 歷史生成 changelog 草稿（release.sh changelog 的 primitive，唯讀）
# 用法: ops/release_changelog.sh <api|ios> [--draft [<since-ref>]]
#   預設     印自上個 released tag 以來的分類預覽
#   --draft  印 docs/reference/changelog/<ios|api>.md 格式的 "Unreleased" 區段，供發版 agent 策展後貼入
#            <since-ref> 覆寫起點（例 ios/2.0.1+12；build tag 不算 released，預設起點是最近 released tag）
# 來源: first-parent 的 PR 標題（merge body 首行）+ conventional prefix + 路徑（ios/BooksAndVocab/、backend/src/）。
# test/fixture/chore/ci/build/style/refactor/docs/ops 一律是 internal，只計數，永遠不算功能。
set -euo pipefail

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

COMPONENT="${1:?用法: ops/release_changelog.sh <api|ios> [--draft [<since-ref>]]}"
DRAFT=0; [ "${2:-}" = "--draft" ] && DRAFT=1

KG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KG_ROOT"

case "$COMPONENT" in
  api)  SCOPE='api|backend'; PATHRE='^backend/src/' ;;
  ios)  SCOPE='ios';         PATHRE='^ios/BooksAndVocab/' ;;
  *)    echo "✗ 未知 component: $COMPONENT" >&2; exit 1 ;;
esac

# 找最近的 released tag。規則的 owner 是 ops/lib/release_tags.sh，不在這裡再抄一份：
# 曾有逐字副本，release.sh 收緊成「只認 <prefix>x.y.z」時漏了它，於是 changelog 靜默錨在 build tag 上印「無變更」。
# shellcheck source=lib/release_tags.sh
. "$KG_ROOT/ops/lib/release_tags.sh"
LAST_TAG="$(release_last_tag "$COMPONENT" "$KG_ROOT")" \
  || { echo "✗ 無法列出 ${COMPONENT} 的 tag（git 失敗）" >&2; exit 1; }
[ -z "${3:-}" ] || LAST_TAG="$3"
SINCE="${LAST_TAG:-initial}"

# 每筆 first-parent commit → "class<TAB>title"；class ∈ feat|fix|imp|int，只留與本 component 相關者。
ROWS=$(git log --first-parent -m --name-only ${LAST_TAG:+"${LAST_TAG}..HEAD"} \
  --format='%x02%h%x01%s%x01%b%x03' 2>/dev/null | awk -v scope="$SCOPE" -v pathre="$PATHRE" '
BEGIN { RS = "\002"; FS = "\n" }
NR > 1 {
  i = index($0, "\003"); split(substr($0, 1, i - 1), p, "\001"); n = split(substr($0, i + 1), f, "\n")
  title = p[2]
  if (title ~ /^Merge pull request/) {
    m = split(p[3], b, "\n"); title = ""
    for (j = 1; j <= m && title == ""; j++) if (b[j] ~ /[^ ]/) title = b[j]
  } else if (title ~ /^Merge (branch|commit)/) next
  t = tolower(title); type = ""; sc = ""
  if (match(t, /^[a-z]+(\([^)]*\))?!?:/)) {
    pre = substr(t, 1, RLENGTH - 1); type = pre; sub(/[(!].*/, "", type)
    if (pre ~ /\(/) { sc = pre; sub(/^[^(]*\(/, "", sc); sub(/\).*/, "", sc) }
    if (type ~ "^(" scope ")$") { sc = type; type = "" }
  }
  rel = (sc ~ "^(" scope ")$")
  for (j = 1; j <= n; j++) if (f[j] ~ pathre) rel = 1
  if (!rel) next
  if (type ~ /^(test|fixture|chore|ci|build|style|refactor|docs|ops|revert)$/) c = "int"
  else if (type == "feat") c = "feat"
  else if (type == "fix") c = "fix"
  else if (type == "perf") c = "imp"
  else if (t ~ /refactor|extract|split|lint|fixture|evidence|selector|test|測試/) c = "int"
  else if (t ~ /(^|[^a-z])(fix|bug)|修/) c = "fix"
  else if (t ~ /(^|[^a-z])(add|feat)|新增|加入|支援/) c = "feat"
  else c = "imp"
  if (match(p[2], /#[0-9]+/) && title !~ /#[0-9]+/) title = title " (" substr(p[2], RSTART, RLENGTH) ")"
  if (!(title in seen)) { seen[title] = 1; print c "\t" title }
}')

if [ -z "$ROWS" ]; then
  echo "無變更（自 ${SINCE} 以來）"
  exit 0
fi

# sect <class> <heading>：該類有內容才印
sect() {
  local body; body=$(printf '%s\n' "$ROWS" | awk -F'\t' -v c="$1" '$1 == c { print "- " $2 }')
  [ -z "$body" ] || printf '%s\n%s\n\n' "$2" "$body"
  return 0
}
NINT=$(printf '%s\n' "$ROWS" | awk -F'\t' '$1 == "int"' | wc -l | tr -d ' ')

if [ "$DRAFT" = 1 ]; then
  printf '## Unreleased\n\n### 使用者說明（zh-Hant）\n<待策展：商店在地化文案，≤4000 字元>\n\n### What'"'"'s New (en)\n<curate: short store copy>\n\n### Changes\n\n'
  sect feat '#### New'; sect imp '#### Improved'; sect fix '#### Fixed'
  printf '### Internal\n共 %s 項 tooling／test／refactor 變動（草稿：請改成一行摘要）。\n' "$NINT"
else
  printf '## 變更內容（自 %s）\n\n' "$SINCE"
  sect feat '### 新功能'; sect imp '### 改進'; sect fix '### 修復'
  printf '### 內部\n共 %s 項 test／fixture／chore／ci／refactor／docs／ops（不逐條列出）\n' "$NINT"
fi
