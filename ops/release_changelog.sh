#!/bin/bash
# release_changelog.sh — 從 git log 生成 CHANGELOG（release.sh changelog 的 primitive）
# 用法: ops/release_changelog.sh <api|ios>（一般經 ops/release.sh changelog 呼叫）
# 輸出 markdown 到 stdout
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

COMPONENT="${1:?用法: ops/release_changelog.sh <api|ios>}"

KG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KG_ROOT"

# 決定 tag prefix 和 commit prefix
case "$COMPONENT" in
  api)  TAG_PREFIX="api/"; COMMIT_PREFIX="api:" ;;
  ios)  TAG_PREFIX="ios/"; COMMIT_PREFIX="ios:" ;;
  *)    echo "✗ 未知 component: $COMPONENT" >&2; exit 1 ;;
esac

# 找最近的同類 tag
LAST_TAG=$(git tag -l "${TAG_PREFIX}*" --sort=-v:refname 2>/dev/null | head -1)

if [ -z "${LAST_TAG:-}" ]; then
  RANGE=""
  SINCE="initial"
else
  RANGE="${LAST_TAG}..HEAD"
  SINCE="$LAST_TAG"
fi

# 取得相關 commits
if [ -z "$RANGE" ]; then
  ALL_COMMITS=$(git log --oneline --no-merges 2>/dev/null)
else
  ALL_COMMITS=$(git log "$RANGE" --oneline --no-merges 2>/dev/null)
fi

COMMITS=$(echo "$ALL_COMMITS" | grep -i "^[a-f0-9]* ${COMMIT_PREFIX}" || true)
OPS_COMMITS=$(echo "$ALL_COMMITS" | grep -iE "^[a-f0-9]* (ops|docs):" || true)

if [ -z "$COMMITS" ] && [ -z "$OPS_COMMITS" ]; then
  echo "無變更（自 ${SINCE} 以來）"
  exit 0
fi

# 分類輸出
echo "## 變更內容（自 ${SINCE}）"
echo ""

# Features
FEATURES=$(echo "$COMMITS" | grep -iE "(新增|feat|add|支援)" || true)
if [ -n "$FEATURES" ]; then
  echo "### 新功能"
  echo "$FEATURES" | sed 's/^[a-f0-9]* /- /'
  echo ""
fi

# Fixes
FIXES=$(echo "$COMMITS" | grep -iE "(修復|修正|fix|bugfix|hotfix)" || true)
if [ -n "$FIXES" ]; then
  echo "### 修復"
  echo "$FIXES" | sed 's/^[a-f0-9]* /- /'
  echo ""
fi

# Other changes (not features or fixes)
OTHERS=$(echo "$COMMITS" | grep -viE "(新增|feat|add|支援|修復|修正|fix|bugfix|hotfix)" || true)
if [ -n "$OTHERS" ]; then
  echo "### 其他變更"
  echo "$OTHERS" | sed 's/^[a-f0-9]* /- /'
  echo ""
fi

# Ops/Docs
if [ -n "$OPS_COMMITS" ]; then
  echo "### 維運 / 文件"
  echo "$OPS_COMMITS" | sed 's/^[a-f0-9]* /- /'
  echo ""
fi
