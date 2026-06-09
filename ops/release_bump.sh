#!/bin/bash
# release_bump.sh — 更新 backend 或 iOS 版本號（release.sh bump 的 primitive）
# 用法: ops/release_bump.sh <api|ios> <new-version>（一般經 ops/release.sh bump 呼叫）
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

COMPONENT="${1:?用法: ops/release_bump.sh <api|ios> <version>}"
VERSION="${2:?請提供版本號，例如 1.3.0}"

KG_ROOT="${KG_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"   # 可由 env 覆寫（測試指向 fixture）

# 驗證版本號格式
if ! echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "✗ 版本號格式錯誤：${VERSION}（需要 x.y.z）" >&2
  exit 1
fi

bump_api() {
  local pyproject="$KG_ROOT/backend/pyproject.toml"
  local api_py="$KG_ROOT/backend/src/kg/api.py"

  # pyproject.toml
  sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$pyproject"
  echo "✓ pyproject.toml → $VERSION"

  # api.py
  sed -i '' "s/version=\"[^\"]*\"/version=\"$VERSION\"/" "$api_py"
  echo "✓ api.py → $VERSION"

  # 驗證
  grep -q "version = \"$VERSION\"" "$pyproject" || { echo "✗ pyproject.toml 更新失敗" >&2; exit 1; }
  grep -q "version=\"$VERSION\"" "$api_py" || { echo "✗ api.py 更新失敗" >&2; exit 1; }
}

bump_ios() {
  local pbxproj="$KG_ROOT/ios/BooksAndVocab.xcodeproj/project.pbxproj"

  # 只改「主 app target」，以其『當前版號值』為錨：避免全域 sed 波及測試 bundle
  # （BooksAndVocabTests/UITests 各有獨立 MARKETING_VERSION/CURRENT_PROJECT_VERSION，不上架，不該被拖著走）。
  # 主 app 的當前值＝檔內第一個（與 release.sh current_version 的 grep -m1 同口徑）。
  local cur_mv cur_build new_build
  cur_mv=$(grep -o 'MARKETING_VERSION = [^;]*' "$pbxproj" | head -1 | sed 's/MARKETING_VERSION = //')
  cur_build=$(grep -o 'CURRENT_PROJECT_VERSION = [0-9]*' "$pbxproj" | head -1 | grep -o '[0-9]*')
  new_build=$((cur_build + 1))
  [[ -n "$cur_mv" && -n "$cur_build" ]] || { echo "✗ 讀不到 app target 當前版號（pbxproj 結構異常）" >&2; exit 1; }

  # 以「= 當前值;」精準錨定，只命中與主 app 同值的 config（Debug+Release 兩處），不碰異值的測試 bundle。
  sed -i '' "s/MARKETING_VERSION = ${cur_mv};/MARKETING_VERSION = $VERSION;/g" "$pbxproj"
  sed -i '' "s/CURRENT_PROJECT_VERSION = ${cur_build};/CURRENT_PROJECT_VERSION = $new_build;/g" "$pbxproj"

  # 驗證 + 回報實際命中數（不再謊稱「6 處」）
  local count
  count=$(grep -c "MARKETING_VERSION = $VERSION;" "$pbxproj")
  [[ "$count" -ge 1 ]] || { echo "✗ MARKETING_VERSION 更新失敗（錨值 $cur_mv 未命中）" >&2; exit 1; }
  echo "✓ MARKETING_VERSION → ${VERSION}（app target ${count} 處；測試 bundle 不動）"
  echo "✓ CURRENT_PROJECT_VERSION → $new_build"
}

case "$COMPONENT" in
  api)  bump_api ;;
  ios)  bump_ios ;;
  *)    echo "✗ 未知 component: ${COMPONENT}（需要 api 或 ios）" >&2; exit 1 ;;
esac

echo "✓ 版本更新完成：$COMPONENT $VERSION"
