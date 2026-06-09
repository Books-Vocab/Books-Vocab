#!/bin/bash
# iOS Design System Token Lint
# 用法: bash scripts/ios_token_lint.sh
# Exit 0 = clean, Exit 1 = violations found

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IOS_ROOT="$PROJECT_ROOT/ios/BooksAndVocab"

# 設計系統定義檔（排除）
EXCLUDE="--exclude=AppColors.swift --exclude=AppTheme.swift --exclude=VocabSkin.swift --exclude=AppMetrics.swift --exclude=AppFonts.swift"

VIOLATIONS=0

check() {
  local label="$1"
  local pattern="$2"
  local exclude_pattern="${3:-}"
  local results

  results=$(grep -rnE "$pattern" "$IOS_ROOT" --include="*.swift" $EXCLUDE 2>/dev/null)

  if [[ -n "$exclude_pattern" && -n "$results" ]]; then
    results=$(echo "$results" | grep -vE "$exclude_pattern")
  fi

  if [[ -n "$results" ]]; then
    while IFS= read -r line; do
      local relpath="${line#$PROJECT_ROOT/}"
      echo "[VIOLATION] $label: $relpath"
      VIOLATIONS=$((VIOLATIONS + 1))
    done <<< "$results"
  fi
}

# 1. Raw color
check "raw-color" \
  'Color\.(red|blue|green|white|black)[^a-zA-Z]|Color\(red:|#colorLiteral'

# 2. Raw font
check "raw-font" \
  '\.font\(\.system\(|Font\.custom\('

# 3. Raw animation (排除 AppMotion 用法)
check "raw-animation" \
  '\.animation\(\.(default|easeIn|easeOut|easeInOut)|\.animation\(\.linear[^(]|withAnimation\(\.(spring|easeOut|easeIn|linear)\(' \
  'AppMotion'

# 4. Raw transition (排除 AnyTransition 定義)
check "raw-transition" \
  '\.transition\(\.(opacity|slide|scale|move)\b' \
  'AnyTransition|AppTransition'

# 結果
if [[ $VIOLATIONS -eq 0 ]]; then
  echo "[OK] No violations found."
  exit 0
else
  echo ""
  echo "[SUMMARY] $VIOLATIONS violation(s) found."
  exit 1
fi
