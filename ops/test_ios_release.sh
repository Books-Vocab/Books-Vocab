#!/usr/bin/env bash
# test_ios_release.sh — ios_release.sh 結構/行為驗證（不啟 xcodebuild；對齊 test_asc.sh 慣例）
# dogfood C：補 -h/--help guard + --key/--timeout 取值守衛的回歸鎖。
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
IR="$WORKSPACE/ops/ios_release.sh"
PROGRESS_LIB="$WORKSPACE/ops/lib/ios_build_progress.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

# ── 1. Syntax ───────────────────────────────────────────────────────────────
section "Syntax"
[[ -f "$IR" ]] && ok "ios_release.sh exists" || fail_t "ios_release.sh missing"
bash -n "$IR"  && ok "ios_release.sh syntax" || fail_t "ios_release.sh syntax error"

# ── 2. -h/--help 存在且不啟 archive（dogfood C：裸跑直接 xcodebuild archive 的 footgun） ──
section "Help guard (no accidental archive)"
grep -qE '\-h\|--help\)' "$IR" \
  && ok "has -h/--help case"               || fail_t "no -h/--help guard"
# 在 set -e 下，substitution 失敗會中止腳本，故 rc 另用 if 捕捉（避免 help_rc=$? 成死碼）
if help_out="$(bash "$IR" --help 2>&1)"; then ok "--help exits 0 (no xcodebuild)"; else fail_t "--help non-zero exit"; fi
echo "$help_out" | grep -q 'Usage' \
  && ok "--help prints Usage"              || fail_t "--help missing Usage text"
echo "$help_out" | grep -qE 'set -euo pipefail|^SCHEME=|^TEAM_ID=' \
  && fail_t "help leaks shell code"        || ok "help is comment-only (no shell code leak)"

# ── 3. 取值型選項守衛（dogfood C：--key/--timeout 後無值不該 set -u unbound） ──
section "Value-taking options guarded"
grep -q 'need_val' "$IR" \
  && ok "has need_val guard"               || fail_t "missing need_val guard"
kv_out="$(bash "$IR" --key 2>&1 || true)"
echo "$kv_out" | grep -q '需要一個值' \
  && ok "--key with no value → friendly error" || fail_t "--key no-value not friendly (got: $kv_out)"
echo "$kv_out" | grep -qi 'unbound variable' \
  && fail_t "--key no-value still hits set -u unbound" \
  || ok "no set -u unbound crash on missing value"

# ── 4. 對外副作用仍 gated（--upload 才上傳；archive 本身無對外副作用） ────────
section "Upload stays opt-in"
grep -q -- '--upload' "$IR" \
  && ok "upload is an explicit opt-in flag" || fail_t "missing --upload flag"
grep -qE 'DO_UPLOAD=0' "$IR" \
  && ok "DO_UPLOAD defaults off"            || fail_t "DO_UPLOAD not defaulting off"

# ── 5. archive diagnostics：保留 log + .xcresult，第一屏列 warning/error ──────
section "Archive diagnostics"
grep -q -- '-resultBundlePath' "$IR" \
  && ok "archive emits xcresult bundle"       || fail_t "archive missing -resultBundlePath"
grep -q 'kg_ios_release_archive.*log' "$IR" \
  && ok "archive preserves raw log path"      || fail_t "archive missing raw log path"
grep -q 'ios_diagnostics.py' "$IR" \
  && ok "archive calls diagnostics parser"    || fail_t "archive missing diagnostics parser"
grep -q -- '--xcresult' "$IR" && grep -q -- '--log' "$IR" \
  && ok "archive feeds xcresult + log to diagnostics" || fail_t "archive diagnostics missing xcresult/log"

# ── 6. upload diagnostics：altool 長時間無輸出時仍有 keep-alive tick ───────
section "Upload diagnostics"
grep -q 'kg_ios_release_upload.*log' "$IR" \
  && ok "upload preserves raw log path"      || fail_t "upload missing raw log path"
grep -q 'start_tick_monitor "$UPLOAD_LOG" "\[release\]\[upload\]"' "$IR" \
  && ok "upload starts keep-alive monitor"   || fail_t "upload missing keep-alive monitor"
grep -q 'UPLOAD_EXIT=\$?' "$IR" && grep -q 'upload failed (exit \$UPLOAD_EXIT)' "$IR" \
  && ok "upload captures and reports altool exit code" || fail_t "upload exit handling missing"
grep -q 'write_json_verdict "ok" "0" "ok" "ok" "fail"' "$IR" \
  && ok "upload failure writes machine-readable verdict" || fail_t "upload failure verdict missing"
tick_probe="$(
  perl -e 'alarm 5; exec @ARGV' bash -lc '
    source "'"$PROGRESS_LIB"'"
    log="$(mktemp "${TMPDIR:-/tmp}/kg_ios_tick_probe.XXXXXX.log")"
    pid="$(start_tick_monitor "$log" "[probe]" "$(date +%s)")"
    printf "pid=%s\n" "$pid"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  ' 2>/dev/null
)"
echo "$tick_probe" | grep -qE '^pid=[0-9]+$' \
  && ok "upload tick monitor returns PID from command substitution" || fail_t "upload tick monitor command substitution hung/failed: $tick_probe"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
