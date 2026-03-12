#!/bin/bash
# iOS Design System Token Lint
# 掃描 raw color/font/animation/transition 違規
# 用法: bash scripts/ios_token_lint.sh
# Exit 0 = clean, Exit 1 = violations found

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IOS_ROOT="$PROJECT_ROOT/ios/BooksBrowser"

EXCLUDE_FILES="AppColors.swift|AppTheme.swift|VocabSkin.swift|AppMetrics.swift|AppFonts.swift"

VIOLATIONS=0

scan_file() {
  local label="$1"
  local pattern="$2"
  local file="$3"
  local exclude_pattern="${4:-}"
  local lineno=0
  local relpath="${file#$PROJECT_ROOT/}"

  while IFS= read -r line; do
    lineno=$((lineno + 1))
    if echo "$line" | grep -qE "$pattern" 2>/dev/null; then
      if [[ -z "$exclude_pattern" ]] || ! echo "$line" | grep -qE "$exclude_pattern" 2>/dev/null; then
        echo "[VIOLATION] $label: $relpath:$lineno: $(echo "$line" | sed 's/^[[:space:]]*//')"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    fi
  done < "$file"
}

while IFS= read -r -d '' swift_file; do
  basename_file="$(basename "$swift_file")"
  if echo "$basename_file" | grep -qE "^($EXCLUDE_FILES)$"; then
    continue
  fi

  # 1. Raw color
  scan_file "raw-color" \
    'Color\.(red|blue|green|white|black)[^a-zA-Z]|Color\(red:|#colorLiteral' \
    "$swift_file"

  # 2. Raw font
  scan_file "raw-font" \
    '\.font\(\.system\(|Font\.custom\(' \
    "$swift_file"

  # 3. Raw animation (exclude lines containing AppMotion)
  scan_file "raw-animation" \
    '\.animation\(\.default|\.animation\(\.easeIn|\.animation\(\.easeOut|\.animation\(\.easeInOut|\.animation\(\.linear[^(]|withAnimation\(\.spring\(|withAnimation\(\.easeOut|withAnimation\(\.easeIn|withAnimation\(\.linear' \
    "$swift_file" \
    'AppMotion'

  # 4. Raw transition (exclude AppTransition / AnyTransition)
  scan_file "raw-transition" \
    '\.transition\(\.opacity|\.transition\(\.slide|\.transition\(\.scale|\.transition\(\.move' \
    "$swift_file" \
    'AppTransition|AnyTransition'

done < <(find "$IOS_ROOT" -name "*.swift" -print0)

if [[ $VIOLATIONS -eq 0 ]]; then
  echo "[OK] No violations found."
  exit 0
else
  echo ""
  echo "[SUMMARY] $VIOLATIONS violation(s) found."
  exit 1
fi
