#!/usr/bin/env bash
# install_hooks.sh — 把本 clone 的 git hooks 指到 repo 內的 `.githooks/`。
#
# core.hooksPath 是 per-clone 的本地設定（寫在 .git/config），commit 帶不過去：
# 每個 clone、每台機器、每次重新 clone 都要各跑一次。裝上之後 .githooks/pre-commit
# 才會在 commit 時執行（design-system 與 UI quality 的本地 best-effort 檢查；
# CI 與 worktree cutover gate 仍是硬 gate，本 hook 不取代它們）。
#
# 用法:
#   ops/install_hooks.sh              # 安裝（等同 --yes）
#   ops/install_hooks.sh --yes        # 安裝
#   ops/install_hooks.sh --check      # 只讀不寫；未安裝則 exit 1
#   ops/install_hooks.sh --uninstall  # 逃生口: git config --unset core.hooksPath
#   ops/install_hooks.sh --help
#
# Exit: 0 = 成功 / 已安裝；1 = --check 判定未安裝；2 = 用法錯誤。
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

HOOKS_DIR=".githooks"

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"; }

current_path() { git config --get core.hooksPath 2>/dev/null || true; }

do_check() {
  local val
  val="$(current_path)"
  if [[ "$val" != "$HOOKS_DIR" ]]; then
    printf '✗ core.hooksPath = %s（期望 %s）\n' "${val:-<未設定>}" "$HOOKS_DIR" >&2
    printf '  修法: ops/install_hooks.sh --yes\n' >&2
    return 1
  fi
  if [[ ! -x "$HOOKS_DIR/pre-commit" ]]; then
    printf '✗ %s/pre-commit 不存在或不可執行\n' "$HOOKS_DIR" >&2
    return 1
  fi
  printf '✓ core.hooksPath = %s，%s/pre-commit 可執行\n' "$HOOKS_DIR" "$HOOKS_DIR"
  return 0
}

do_install() {
  git config core.hooksPath "$HOOKS_DIR"
  do_check
}

do_uninstall() {
  git config --unset core.hooksPath 2>/dev/null || true
  local val
  val="$(current_path)"
  printf '✓ 已移除 core.hooksPath（現值: %s）\n' "${val:-<未設定>}"
}

if [[ $# -gt 1 ]]; then
  printf '✗ 一次只接受一個參數\n' >&2
  usage >&2
  exit 2
fi

case "${1:-}" in
  ""|--yes)    do_install ;;
  --check)     do_check ;;
  --uninstall) do_uninstall ;;
  -h|--help)   usage; exit 0 ;;
  *)
    printf '✗ unknown option: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac
