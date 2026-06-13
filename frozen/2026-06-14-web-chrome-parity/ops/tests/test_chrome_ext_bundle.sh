#!/usr/bin/env bash
# test_chrome_ext_bundle.sh — chrome_ext_bundle.sh 單元測試
#
# 透過 KG_CHROME_EXT_DIR / KG_DIST_DIR 注入 mock 來源與輸出目錄，覆蓋情境：
#   1. 健康 manifest → exit 0，產出 chrome-ext-vX.Y.Z.zip
#   2. zip 內含 manifest.json + 子資料夾檔案
#   3. zip 排除 .DS_Store / .git / README*.md / tools/
#   4. zip 內路徑前綴為 chrome-extension/
#   5. 重跑 idempotent → 同名 zip 覆蓋成功
#   6. manifest 缺 version → exit 1
#   7. manifest.json 不存在 → exit 1
#   8. version 格式異常（含路徑字元）→ exit 1
#   9. Chrome Web Store 不接受的 version 數值 → exit 1

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$WORKTREE/ops/chrome_ext_bundle.sh"
TMPDIR="$(mktemp -d -t kg_chrext_test_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "✗ test 需要 $1，未安裝" >&2; exit 1; }
}
require_cmd zip
require_cmd unzip

# 建一份 mock chrome-extension 目錄
# 用法：build_ext <out_dir> [version=0.1.0] [opts:no_version|no_manifest|bad_version|with_junk|with_tools]
build_ext() {
  local out_dir="$1"; shift
  local version="${1:-0.1.0}"; shift || true
  local opts=("$@")
  mkdir -p "$out_dir/icons" "$out_dir/sidepanel" "$out_dir/content"

  if printf '%s\n' "${opts[@]}" | grep -qx no_manifest; then
    :  # 不建 manifest
  elif printf '%s\n' "${opts[@]}" | grep -qx no_version; then
    cat > "$out_dir/manifest.json" <<JSON
{ "manifest_version": 3, "name": "mock" }
JSON
  elif printf '%s\n' "${opts[@]}" | grep -qx bad_version; then
    cat > "$out_dir/manifest.json" <<JSON
{ "manifest_version": 3, "name": "mock", "version": "1.0/../evil" }
JSON
  else
    cat > "$out_dir/manifest.json" <<JSON
{ "manifest_version": 3, "name": "mock", "version": "$version" }
JSON
  fi

  echo 'console.log("bg");' > "$out_dir/background.js"
  echo '<html></html>'       > "$out_dir/sidepanel/index.html"
  echo 'content'             > "$out_dir/content/content.js"
  printf 'PNG' > "$out_dir/icons/icon128.png"

  if printf '%s\n' "${opts[@]}" | grep -qx with_junk; then
    printf 'mac junk' > "$out_dir/.DS_Store"
    printf 'mac junk' > "$out_dir/icons/.DS_Store"
    mkdir -p "$out_dir/.git/objects"
    printf 'git data' > "$out_dir/.git/HEAD"
    echo 'dev only' > "$out_dir/README.md"
    echo 'dev only' > "$out_dir/README.dev.md"
  fi

  if printf '%s\n' "${opts[@]}" | grep -qx with_tools; then
    mkdir -p "$out_dir/tools"
    echo 'console.log("dev tool");' > "$out_dir/tools/static.mjs"
    mkdir -p "$out_dir/content/tools"
    echo 'console.log("runtime helper");' > "$out_dir/content/tools/runtime.js"
  fi
}

run_bundle() {
  local ext_dir="$1" dist_dir="$2"
  local logfile="$TMPDIR/log_$RANDOM.txt"
  KG_CHROME_EXT_DIR="$ext_dir" KG_DIST_DIR="$dist_dir" \
    "$SCRIPT" >"$logfile" 2>&1
  local rc=$?
  echo "$rc|$logfile"
}

run_help() {
  local logfile="$TMPDIR/log_$RANDOM.txt"
  "$SCRIPT" --help >"$logfile" 2>&1
  local rc=$?
  echo "$rc|$logfile"
}

run_bundle_without_rsync() {
  local ext_dir="$1" dist_dir="$2"
  local logfile="$TMPDIR/log_$RANDOM.txt"
  local bin_dir="$TMPDIR/no-rsync-bin"
  local cmd cmd_path

  mkdir -p "$bin_dir"
  for cmd in bash dirname pwd grep head sed zip cp find rm stat awk mktemp mkdir; do
    cmd_path="$(command -v "$cmd")" || return 1
    ln -sf "$cmd_path" "$bin_dir/$cmd"
  done

  PATH="$bin_dir" KG_CHROME_EXT_DIR="$ext_dir" KG_DIST_DIR="$dist_dir" \
    "$SCRIPT" >"$logfile" 2>&1
  local rc=$?
  echo "$rc|$logfile"
}

assert_rc() {
  local name="$1" expected="$2" got="$3" logfile="$4"
  if [[ "$got" == "$expected" ]]; then
    ok "$name (rc=$got)"
  else
    fail_t "$name expect rc=$expected got rc=$got"
    sed 's/^/      /' "$logfile" >&2
  fi
}

assert_log_contains() {
  local name="$1" needle="$2" logfile="$3"
  if grep -q -- "$needle" "$logfile"; then
    ok "$name contains \"$needle\""
  else
    fail_t "$name missing \"$needle\""
    sed 's/^/      /' "$logfile" >&2
  fi
}

# ── Syntax 先過 ────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$SCRIPT" && ok "chrome_ext_bundle.sh syntax" || fail_t "chrome_ext_bundle.sh syntax"

section "help surface"
out=$(run_help); rc="${out%%|*}"; log="${out##*|}"
assert_rc "help exits 0" 0 "$rc" "$log"
assert_log_contains "help has 用法" "用法：" "$log"

# ── 1. 健康 manifest → 產出 zip ─────────────────────────────────────────────
section "case 1: healthy manifest → produces zip"
EXT1="$TMPDIR/ext1"; DIST1="$TMPDIR/dist1"
build_ext "$EXT1" 0.2.3
out=$(run_bundle "$EXT1" "$DIST1"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "bundle ok" 0 "$rc" "$log"
ZIP1="$DIST1/chrome-ext-v0.2.3.zip"
[[ -f "$ZIP1" ]] && ok "zip produced at $ZIP1" || fail_t "zip not produced at $ZIP1"
assert_log_contains "log shows path" "chrome-ext-v0.2.3.zip" "$log"
assert_log_contains "log shows size" "size" "$log"

# ── 2. zip 內容完整 ──────────────────────────────────────────────────────────
section "case 2: zip contents include manifest + nested files"
if [[ -f "$ZIP1" ]]; then
  LIST="$TMPDIR/list1.txt"
  unzip -Z1 "$ZIP1" > "$LIST"
  grep -qx "chrome-extension/manifest.json"       "$LIST" && ok "contains manifest.json"       || fail_t "missing manifest.json"
  grep -qx "chrome-extension/background.js"       "$LIST" && ok "contains background.js"       || fail_t "missing background.js"
  grep -qx "chrome-extension/sidepanel/index.html" "$LIST" && ok "contains sidepanel/index.html" || fail_t "missing sidepanel/index.html"
  grep -qx "chrome-extension/icons/icon128.png"   "$LIST" && ok "contains icons/icon128.png"   || fail_t "missing icons/icon128.png"
fi

# ── 3. junk 排除 ────────────────────────────────────────────────────────────
section "case 3: zip excludes .DS_Store / .git / README*.md / tools"
EXT3="$TMPDIR/ext3"; DIST3="$TMPDIR/dist3"
build_ext "$EXT3" 1.0.0 with_junk with_tools
out=$(run_bundle "$EXT3" "$DIST3"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "bundle with junk" 0 "$rc" "$log"
ZIP3="$DIST3/chrome-ext-v1.0.0.zip"
if [[ -f "$ZIP3" ]]; then
  LIST3="$TMPDIR/list3.txt"
  unzip -Z1 "$ZIP3" > "$LIST3"
  grep -q "\.DS_Store" "$LIST3" && fail_t "junk: .DS_Store leaked" || ok "junk: no .DS_Store"
  grep -q "^chrome-extension/\.git/" "$LIST3" && fail_t "junk: .git leaked" || ok "junk: no .git"
  grep -q "README.*\.md$" "$LIST3" && fail_t "junk: README*.md leaked" || ok "junk: no README*.md"
  grep -q "^chrome-extension/tools/" "$LIST3" && fail_t "junk: tools/ leaked" || ok "junk: no tools/"
  grep -qx "chrome-extension/content/tools/runtime.js" "$LIST3" && ok "nested runtime tools/ kept" || fail_t "nested runtime tools/ missing"
  # 但仍要包含 manifest
  grep -qx "chrome-extension/manifest.json" "$LIST3" && ok "junk case still has manifest" || fail_t "junk case missing manifest"
fi

# ── 3b. fallback 無 rsync 行為一致 ────────────────────────────────────────
section "case 3b: fallback without rsync excludes only top-level tools"
EXT3B="$TMPDIR/ext3b"; DIST3B="$TMPDIR/dist3b"
build_ext "$EXT3B" 1.0.1 with_junk with_tools
out=$(run_bundle_without_rsync "$EXT3B" "$DIST3B"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "fallback bundle with junk" 0 "$rc" "$log"
ZIP3B="$DIST3B/chrome-ext-v1.0.1.zip"
if [[ -f "$ZIP3B" ]]; then
  LIST3B="$TMPDIR/list3b.txt"
  unzip -Z1 "$ZIP3B" > "$LIST3B"
  grep -q "^chrome-extension/tools/" "$LIST3B" && fail_t "fallback: tools/ leaked" || ok "fallback: no tools/"
  grep -qx "chrome-extension/content/tools/runtime.js" "$LIST3B" && ok "fallback: nested runtime tools/ kept" || fail_t "fallback: nested runtime tools/ missing"
fi

# ── 4. 路徑前綴 ─────────────────────────────────────────────────────────────
section "case 4: zip uses chrome-extension/ prefix"
if [[ -f "$ZIP1" ]]; then
  if unzip -Z1 "$ZIP1" | grep -qv '^chrome-extension/'; then
    fail_t "found entries outside chrome-extension/ prefix"
    unzip -Z1 "$ZIP1" | grep -v '^chrome-extension/' | sed 's/^/      /' >&2
  else
    ok "all entries under chrome-extension/ prefix"
  fi
fi

# ── 5. idempotent 重跑 ─────────────────────────────────────────────────────
section "case 5: idempotent rerun overwrites"
out=$(run_bundle "$EXT1" "$DIST1"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "rerun bundle" 0 "$rc" "$log"
[[ -f "$ZIP1" ]] && ok "zip still present after rerun" || fail_t "zip missing after rerun"

# ── 6. 缺 version → fatal ──────────────────────────────────────────────────
section "case 6: manifest missing version → fatal"
EXT6="$TMPDIR/ext6"; DIST6="$TMPDIR/dist6"
build_ext "$EXT6" 0.0.0 no_version
out=$(run_bundle "$EXT6" "$DIST6"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "missing version" 1 "$rc" "$log"
assert_log_contains "missing version msg" "version" "$log"

# ── 7. manifest.json 不存在 → fatal ───────────────────────────────────────
section "case 7: manifest.json missing → fatal"
EXT7="$TMPDIR/ext7"; DIST7="$TMPDIR/dist7"
build_ext "$EXT7" 0.0.0 no_manifest
out=$(run_bundle "$EXT7" "$DIST7"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "missing manifest" 1 "$rc" "$log"
assert_log_contains "missing manifest msg" "manifest.json" "$log"

# ── 8. version 含非法字元 → fatal ─────────────────────────────────────────
section "case 8: bad version string → fatal"
EXT8="$TMPDIR/ext8"; DIST8="$TMPDIR/dist8"
build_ext "$EXT8" 0.0.0 bad_version
out=$(run_bundle "$EXT8" "$DIST8"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "bad version" 1 "$rc" "$log"

# ── 9. Chrome version 數值規格 → fatal ────────────────────────────────────
section "case 9: Chrome version numeric constraints → fatal"
EXT9A="$TMPDIR/ext9a"; DIST9A="$TMPDIR/dist9a"
build_ext "$EXT9A" 65536.0.0
out=$(run_bundle "$EXT9A" "$DIST9A"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "version segment > 65535" 1 "$rc" "$log"

EXT9B="$TMPDIR/ext9b"; DIST9B="$TMPDIR/dist9b"
build_ext "$EXT9B" 01.2.3
out=$(run_bundle "$EXT9B" "$DIST9B"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "version segment leading zero" 1 "$rc" "$log"

EXT9C="$TMPDIR/ext9c"; DIST9C="$TMPDIR/dist9c"
build_ext "$EXT9C" 0.0.0
out=$(run_bundle "$EXT9C" "$DIST9C"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "version all zero" 1 "$rc" "$log"

EXT9D="$TMPDIR/ext9d"; DIST9D="$TMPDIR/dist9d"
build_ext "$EXT9D" 1.0.0-beta
out=$(run_bundle "$EXT9D" "$DIST9D"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "version prerelease suffix" 1 "$rc" "$log"

EXT9E="$TMPDIR/ext9e"; DIST9E="$TMPDIR/dist9e"
build_ext "$EXT9E" 18446744073709551616.0
out=$(run_bundle "$EXT9E" "$DIST9E"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "version segment overflow guard" 1 "$rc" "$log"

# ── 結果 ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
