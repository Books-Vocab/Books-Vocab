#!/bin/bash
# release_bump.sh — 更新 backend 或 iOS 版本號（release.sh bump 的 primitive）
# 用法: ops/release_bump.sh <api|ios> <new-version> [--yes]（一般經 ops/release.sh bump 呼叫）
# 預設 dry-run：只印將改的檔與「舊 → 新」版號，不寫檔；加 --yes 才落地
# （對齊 release.sh publish / asc.sh set 的 --yes 寫入慣例）。
set -euo pipefail

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} {exit}' "$0"
}

YES=0
POS=()
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --yes)     YES=1 ;;
    -*)        echo "✗ unknown option: ${arg}" >&2; exit 1 ;;
    *)         POS+=("$arg") ;;
  esac
done

COMPONENT="${POS[0]:?用法: ops/release_bump.sh <api|ios> <version> [--yes]}"
VERSION="${POS[1]:?請提供版本號，例如 1.3.0}"
[[ ${#POS[@]} -le 2 ]] || { echo "✗ 多餘參數：${POS[*]:2}（用法: ops/release_bump.sh <api|ios> <version> [--yes]）" >&2; exit 1; }

KG_ROOT="${KG_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"   # 可由 env 覆寫（測試指向 fixture）

# 驗證版本號格式
if ! echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "✗ 版本號格式錯誤：${VERSION}（需要 x.y.z）" >&2
  exit 1
fi

bump_api() {
  local pyproject="$KG_ROOT/backend/pyproject.toml"
  local api_py="$KG_ROOT/backend/src/kg/api.py"

  # 先讀當前值：dry-run 與 --yes 都印「舊 → 新」計畫（寫面自解）
  local cur_py cur_api
  cur_py="$(grep -m1 '^version = ' "$pyproject" | sed -E 's/.*"([^"]+)".*/\1/')"
  cur_api="$(grep -m1 -o 'version="[^"]*"' "$api_py" | sed 's/version="//;s/"$//')"
  [[ -n "$cur_py" && -n "$cur_api" ]] || { echo "✗ 讀不到當前版本（pyproject/api.py 結構異常）" >&2; exit 1; }
  echo "將改 backend/pyproject.toml：version ${cur_py} → ${VERSION}"
  echo "將改 backend/src/kg/api.py：version ${cur_api} → ${VERSION}"
  [[ $YES -eq 1 ]] || return 0

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

  echo "將改 ios/BooksAndVocab.xcodeproj/project.pbxproj："
  echo "  MARKETING_VERSION ${cur_mv} → ${VERSION}（僅 app target，測試 bundle 不動）"
  echo "  CURRENT_PROJECT_VERSION ${cur_build} → ${new_build}"
  [[ $YES -eq 1 ]] || return 0

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

if [[ $YES -eq 1 ]]; then
  echo "✓ 版本更新完成：$COMPONENT $VERSION"
else
  echo "[dry-run] 未寫入。確認無誤後加 --yes 才會改檔："
  echo "  ./ops/release.sh bump $COMPONENT $VERSION --yes"
fi
