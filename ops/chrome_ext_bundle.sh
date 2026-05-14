#!/usr/bin/env bash
# chrome_ext_bundle.sh — 打包 chrome-extension/ 為發行用 zip
#
# 用法：
#   ./ops/chrome_ext_bundle.sh
#
# 行為：
#   1. 從 chrome-extension/manifest.json 讀 version（regex 抽取，不引入 jq）
#   2. zip 整個 chrome-extension/ 到 dist/chrome-ext-vX.Y.Z.zip
#   3. 排除 .DS_Store / .git / README*.md
#   4. 印 zip 路徑與 size
#
# 環境變數（測試注入）：
#   KG_CHROME_EXT_DIR — 來源目錄，預設 <repo>/chrome-extension
#   KG_DIST_DIR       — 輸出目錄，預設 <repo>/dist

set -o pipefail

# ── Helpers ────────────────────────────────────────────────────────────────
info() { echo "▶ $*"; }
ok()   { echo "✓ $*"; }
err()  { echo "✗ $*" >&2; exit 1; }

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT_DIR="${KG_CHROME_EXT_DIR:-$REPO_ROOT/chrome-extension}"
DIST_DIR="${KG_DIST_DIR:-$REPO_ROOT/dist}"

[[ -d "$EXT_DIR" ]] || err "來源目錄不存在: $EXT_DIR"

MANIFEST="$EXT_DIR/manifest.json"
[[ -f "$MANIFEST" ]] || err "找不到 manifest.json: $MANIFEST"

# ── Tools ──────────────────────────────────────────────────────────────────
command -v zip >/dev/null 2>&1 || err "需要 zip 指令，未安裝"

# ── Extract version ────────────────────────────────────────────────────────
# manifest.json 採鬆綁解析（不依賴 jq）。"version": "X.Y.Z"
VERSION="$(grep -E '"version"[[:space:]]*:' "$MANIFEST" \
  | head -n1 \
  | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"

[[ -n "$VERSION" ]] || err "manifest.json 缺 version 欄位"

# 防止 path traversal / 怪字元 — semver 寬鬆形（含 pre-release）
if ! [[ "$VERSION" =~ ^[0-9]+(\.[0-9]+){0,3}([.-][A-Za-z0-9]+)*$ ]]; then
  err "manifest.json version 字串異常: $VERSION"
fi

# ── Stage & Zip ────────────────────────────────────────────────────────────
mkdir -p "$DIST_DIR"
ZIP_NAME="chrome-ext-v${VERSION}.zip"
ZIP_PATH="$DIST_DIR/$ZIP_NAME"

# 移除舊 zip 確保 idempotent（避免 zip 把新檔追加進舊 archive）
rm -f "$ZIP_PATH"

# Stage：複製 EXT_DIR 內容到 staging/chrome-extension，過程剝掉開發垃圾
STAGE="$(mktemp -d -t kg_chrext_stage_XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT

STAGE_EXT="$STAGE/chrome-extension"
mkdir -p "$STAGE_EXT"

# rsync 才能精確排除；fallback 用 find+cp
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude='.DS_Store' \
    --exclude='.git' \
    --exclude='.git/**' \
    --exclude='README*.md' \
    "$EXT_DIR/" "$STAGE_EXT/" \
    || err "stage 複製失敗"
else
  # fallback：先全複製再刪
  cp -R "$EXT_DIR/." "$STAGE_EXT/" || err "stage 複製失敗"
  find "$STAGE_EXT" -name '.DS_Store' -delete 2>/dev/null
  find "$STAGE_EXT" -type d -name '.git' -prune -exec rm -rf {} + 2>/dev/null
  find "$STAGE_EXT" -maxdepth 2 -type f -name 'README*.md' -delete 2>/dev/null
fi

info "打包 chrome-extension v${VERSION}"
# 在 STAGE 內執行 zip，相對路徑保留 chrome-extension/ 前綴
( cd "$STAGE" && zip -rq "$ZIP_PATH" "chrome-extension" ) \
  || err "zip 失敗"

[[ -f "$ZIP_PATH" ]] || err "zip 未產出: $ZIP_PATH"

# ── Size 報告 ──────────────────────────────────────────────────────────────
if SIZE_BYTES=$(stat -f%z "$ZIP_PATH" 2>/dev/null); then
  : # macOS
elif SIZE_BYTES=$(stat -c%s "$ZIP_PATH" 2>/dev/null); then
  : # Linux
else
  SIZE_BYTES="?"
fi

if [[ "$SIZE_BYTES" != "?" ]]; then
  # human readable (KB)
  SIZE_KB=$(awk -v b="$SIZE_BYTES" 'BEGIN{printf "%.1f", b/1024}')
  SIZE_HUMAN="${SIZE_KB} KB (${SIZE_BYTES} bytes)"
else
  SIZE_HUMAN="unknown"
fi

ok "bundle: $ZIP_PATH"
ok "size:   $SIZE_HUMAN"
