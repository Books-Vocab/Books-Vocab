#!/usr/bin/env bash
# verify_design_system.sh — 設計系統跨平台完整性 gate（一支跑齊所有 guard）
#
# 把散落的設計系統 guard 收斂成單一入口，給 pre-commit hook（.githooks/pre-commit）
# 與 CI（.github/workflows/design-system.yml）共用。任一失敗即 exit 1。
#
# 跑：
#   1. token_drift_check.py        — tokens.json 鏡像 iOS Swift literal（值層）
#   2. gen_web_tokens.py --check   — 所有生成 CSS 與 tokens.json 一致（無 stale 副本）
#   2b. gen_figma_sets.py --check  — Tokens Studio sidecar 投影與 tokens.json 一致（無 stale）
#   2c. gen_web_components.py --check — component structures / review-gradient 無 stale
#   3. component_fidelity_check.py — web primitive 組裝對齊 iOS 元件契約（組裝層，若存在）
# 這些 ops 腳本皆 stdlib-only，刻意用 `uv run --no-project` 與 backend 的 68 套件
# venv 解耦 — 設計系統 gate 不該依賴 backend 可安裝。
#
# 用法:  ops/verify_design_system.sh
# Exit:  0 = 全綠；1 = 任一 guard 失敗。
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

PY=(uv run --no-project --python 3.13 python)

fail=0
run() {
  local name="$1"; shift
  printf '\n▶ %s\n' "$name"
  if "$@"; then
    printf '  \033[32m✓ PASS\033[0m — %s\n' "$name"
  else
    printf '  \033[31m✗ FAIL\033[0m — %s\n' "$name"
    fail=1
  fi
}

run "token drift (tokens.json ↔ iOS Swift)" "${PY[@]}" ops/token_drift_check.py
run "web token gen (CSS ↔ tokens.json)"     "${PY[@]}" ops/gen_web_tokens.py --check
run "Figma sidecar (Tokens Studio ↔ tokens.json)" "${PY[@]}" ops/gen_figma_sets.py --check
run "web component gen (structures ↔ components.json)" "${PY[@]}" ops/gen_web_components.py --check
run "Style Dictionary (Swift ↔ tokens.json)" npm run build:check
if [ -f ops/component_fidelity_check.py ]; then
  run "component fidelity (primitive ↔ iOS)" "${PY[@]}" ops/component_fidelity_check.py
fi
echo
if [ "$fail" -ne 0 ]; then
  printf '\033[31m❌ design-system verify FAILED\033[0m\n'
  exit 1
fi
printf '\033[32m✅ design-system verify PASSED\033[0m\n'
