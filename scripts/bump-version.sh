#!/bin/bash
# bump-version.sh — 更新 backend 或 iOS 版本號
# 用法: scripts/bump-version.sh <api|ios> <new-version>
set -euo pipefail

COMPONENT="${1:?用法: bump-version.sh <api|ios> <version>}"
VERSION="${2:?請提供版本號，例如 1.3.0}"

KG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 驗證版本號格式
if ! echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "✗ 版本號格式錯誤：$VERSION（需要 x.y.z）" >&2
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
  local pbxproj="$KG_ROOT/ios/BooksBrowser.xcodeproj/project.pbxproj"

  # 讀取當前最大 build number 並 +1
  local current_build
  current_build=$(grep -o 'CURRENT_PROJECT_VERSION = [0-9]*' "$pbxproj" | head -1 | grep -o '[0-9]*')
  local new_build=$((current_build + 1))

  # 統一更新 MARKETING_VERSION（不管原本是兩段或三段）
  sed -i '' "s/MARKETING_VERSION = [^;]*/MARKETING_VERSION = $VERSION/" "$pbxproj"
  echo "✓ MARKETING_VERSION → $VERSION"

  # 更新 CURRENT_PROJECT_VERSION
  sed -i '' "s/CURRENT_PROJECT_VERSION = [0-9]*/CURRENT_PROJECT_VERSION = $new_build/" "$pbxproj"
  echo "✓ CURRENT_PROJECT_VERSION → $new_build"

  # 驗證
  local count
  count=$(grep -c "MARKETING_VERSION = $VERSION;" "$pbxproj")
  echo "  （已更新 $count 處 MARKETING_VERSION）"
}

case "$COMPONENT" in
  api)  bump_api ;;
  ios)  bump_ios ;;
  *)    echo "✗ 未知 component: $COMPONENT（需要 api 或 ios）" >&2; exit 1 ;;
esac

echo "✓ 版本更新完成：$COMPONENT $VERSION"
