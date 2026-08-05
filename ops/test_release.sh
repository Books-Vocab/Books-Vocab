#!/usr/bin/env bash
# test_release.sh — release.sh 結構與行為驗證（不打 git 遠端；對齊 test_asc.sh 慣例）
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
REL="$WORKSPACE/ops/release.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

# ── 1. Syntax ───────────────────────────────────────────────────────────────
section "Syntax"
[[ -f "$REL" ]] && ok "release.sh exists" || fail_t "release.sh missing"
bash -n "$REL"   && ok "release.sh syntax" || fail_t "release.sh syntax error"

# ── 2. 子命令 dispatch 齊全 ─────────────────────────────────────────────────
section "Subcommand dispatch"
for sub in status changelog bump bump-build tag publish release shipped resubmit; do
  grep -qE "^[[:space:]]*$sub\)" "$REL" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done

# ── 3. release 家族集中 ops/（primitives 已 git mv 進來，scripts/ 舊路徑消失） ─
section "Primitives consolidated into ops/"
[[ -f "$WORKSPACE/ops/release_bump.sh" ]] \
  && ok "ops/release_bump.sh exists"        || fail_t "ops/release_bump.sh missing"
[[ -f "$WORKSPACE/ops/release_changelog.sh" ]] \
  && ok "ops/release_changelog.sh exists"   || fail_t "ops/release_changelog.sh missing"
[[ ! -e "$WORKSPACE/scripts/bump-version.sh" ]] \
  && ok "old scripts/bump-version.sh gone"  || fail_t "scripts/bump-version.sh still present (move incomplete)"
[[ ! -e "$WORKSPACE/scripts/generate-changelog.sh" ]] \
  && ok "old scripts/generate-changelog.sh gone" || fail_t "scripts/generate-changelog.sh still present"

# ── 3b. non-ASC ops test runner exists and keeps help comment-only ───────────
section "Non-ASC ops test runner"
OPS_TEST="$WORKSPACE/ops/test_ops.sh"
[[ -x "$OPS_TEST" ]] \
  && ok "ops/test_ops.sh executable" || fail_t "ops/test_ops.sh missing or not executable"
ops_help="$(bash "$OPS_TEST" --help 2>&1)"
echo "$ops_help" | grep -qE 'set -euo pipefail|^ROOT=|^UV_BIN=' \
  && fail_t "test_ops help leaks shell code" \
  || ok "test_ops help is comment-only"
ops_list="$(bash "$OPS_TEST" --list 2>&1)"
echo "$ops_list" | grep -q '^release$' \
  && ok "test_ops lists release group" || fail_t "test_ops --list missing release"
echo "$ops_list" | grep -q '^podcast-ops$' \
  && ok "test_ops lists podcast-ops group" || fail_t "test_ops --list missing podcast-ops"

# ── 4. release.sh 僅在非 API transaction 路徑委派 bump primitive ─────────────
section "Primitive boundaries"
grep -q 'release_bump.sh' "$REL" \
  && ok "dry-run/iOS bump paths retain release_bump primitive" \
  || fail_t "release.sh lost release_bump primitive for non-transaction paths"
grep -q 'prepare_api_version_transaction' "$REL" \
  && grep -q 'commit_api_version_transaction' "$REL" \
  && ok "API --yes bump is owned by bounded three-file transaction" \
  || fail_t "release.sh missing API three-file transaction authority"
grep -q 'release_changelog.sh' "$REL" \
  && ok "changelog delegates to release_changelog.sh" || fail_t "release.sh not calling release_changelog.sh"

# ── 5. tag 寫入 gate：dry-run 預設，--yes 才 push（對外副作用明示） ───────────
section "Tag gate (dry-run by default)"
grep -q -- '--yes' "$REL" \
  && ok "has --yes confirm flag"            || fail_t "missing --yes flag"
grep -qE 'YES=(0|"")|YES=$' "$REL" \
  && ok "YES defaults to off (dry-run)"     || fail_t "YES not defaulting to dry-run"
tag_body="$(awk '/^cmd_tag\(\)/,/^}/' "$REL")"
# 真正的 push 標的＝`push origin`（script 用 git -C "$ROOT" push origin，dry-run 用中文「推送 origin」不撞）
echo "$tag_body" | grep -q 'push origin' \
  && ok "tag has real push origin"          || fail_t "tag missing push origin"
# 真正的 push/commit/tag 必須在 YES gate 之內
echo "$tag_body" | grep -qE 'if \[\[ \$YES -eq 1 \]\]|if \[ "\$YES"' \
  && ok "tag guards side-effects behind --yes" || fail_t "tag missing --yes guard"
# 負控（鎖不變量）：push origin 不可洩進 dry-run/else 分支 —— 否則無 --yes 也會推
echo "$tag_body" | awk '/else/,/fi/' | grep -q 'push origin' \
  && fail_t "push origin leaked into dry-run branch (would push without --yes)" \
  || ok "dry-run branch contains no push origin"

# ── 5b. detached HEAD 守衛（避免 push origin HEAD；review footgun 回歸） ──────
echo "$tag_body" | grep -q 'detached HEAD' \
  && ok "tag guards detached HEAD"          || fail_t "tag missing detached-HEAD guard (would push origin HEAD)"
echo "$tag_body" | grep -q 'backend/uv.lock' \
  && ok "api tag includes synchronized uv.lock" || fail_t "api tag would leave synchronized uv.lock uncommitted"

# ── 5c. release 統一入口 gate：dry-run 預設、須在 main、委派 deploy/upload ────
section "Release verb gate (unified backend/ios)"
rel_body="$(awk '/^cmd_release\(\)/,/^}/' "$REL")"
echo "$rel_body" | grep -q 'deploy --commit' \
  && ok "release backend delegates to orchestrate deploy" || fail_t "release missing deploy delegation"
echo "$rel_body" | grep -q 'ios_release.sh' \
  && ok "release ios delegates to ios_release.sh --upload" || fail_t "release missing ios_release delegation"
echo "$rel_body" | grep -qE 'branch.*== main|== main.*branch|"\$branch" == main' \
  && ok "release guards on-main"            || fail_t "release missing on-main guard"
# 負控：生產觸點（deploy/upload）不可洩進 dry-run 分支（--yes 前 return）
echo "$rel_body" | awk '/YES -ne 1/,/return 0/' | grep -qE 'deploy --commit|--upload' \
  && fail_t "production touch leaked into release dry-run branch" \
  || ok "release dry-run branch contains no production touch"

# ── 6. 版號格式守衛（x.y.z） ────────────────────────────────────────────────
section "Version format guard"
grep -qE '\[0-9\]\+\\?\.\[0-9\]|[0-9]+\.[0-9]+\.[0-9]+' "$REL" \
  && ok "validates semver x.y.z"            || fail_t "no semver format guard"

# ── 6b. Bash set -u + non-ASCII boundary regression guard ───────────────────
section "Bash variable braces before non-ASCII"
bad_boundary="$(
  rg -n '\$[A-Za-z_][A-Za-z0-9_]*[^[:ascii:]]' "$WORKSPACE/ops" "$WORKSPACE/devops.sh" \
    -g '*.sh' \
    -g '!asc.sh' \
    -g '!test_asc.sh' \
    -g '!ios_release.sh' \
    -g '!test_ios_release.sh' \
    || true
)"
[[ -z "$bad_boundary" ]] \
  && ok "no unbraced shell vars before non-ASCII in non-ASC ops" \
  || fail_t "unbraced shell vars before non-ASCII:\n$bad_boundary"

# ── 7. status / changelog 唯讀（不得碰遠端 / 不寫檔） ────────────────────────
section "Read-only commands stay read-only"
status_body="$(awk '/^cmd_status\(\)/,/^}/' "$REL")"
# 只看「被執行的」git 寫入，不看被印出來的字串：status 印 remediation 提示（例如
# 誤標 tag 的刪除指令）是它的職責，不是副作用。先剔除 echo/printf 行再掃。
status_exec_body() { echo "$status_body" | grep -vE '^[[:space:]]*(echo|printf)\b'; }
status_exec_body | grep -qE 'git push|git commit|git tag ' \
  && fail_t "status has a write/remote op (must be read-only)" \
  || ok "status is read-only"
# 守衛本身不得被上面的剔除規則掏空：植入一個真正的寫入語句必須仍被抓到。
printf '%s\n' '  git push origin main' \
  | grep -vE '^[[:space:]]*(echo|printf)\b' | grep -qE 'git push|git commit|git tag ' \
  && ok "read-only guard still catches a real write op" \
  || fail_t "read-only guard was defanged — a bare git push now slips through"

# ── 8. 不謊稱 CI 自動發版（無 tag-triggered workflow，驗證先於宣稱） ─────────
section "No false CI claim"
! grep -qE 'GitHub Actions 正在執行|CI 正在發版|自動建立 GitHub Release' "$REL" \
  && ok "no aspirational CI-runs claim"     || fail_t "claims CI auto-releases (no such workflow exists)"

# ── 9. --help 不洩漏 shell 程式碼（dogfood A-F6/C：usage sed 範圍越界回歸） ──
section "Help output stays comment-only"
help_out="$(bash "$REL" --help 2>&1)"
echo "$help_out" | grep -qE 'set -euo pipefail|^ROOT=|^YES=' \
  && fail_t "help leaks shell code (set/ROOT/YES bled into usage)" \
  || ok "help is comment-only (no shell code leak)"

# ── 10. status 漂移警示（dogfood A-F2/C：tag↔檔內版號不一致須警告） ──────────
section "Status drift warning"
echo "$status_body" | grep -q '版號漂移' \
  && ok "status warns on tag↔file version drift" || fail_t "status missing drift warning"

# ── 11. status 長清單截斷（dogfood A-F3：234 筆 commit 不該吐成 688 行牆） ────
section "Status truncates long commit list"
echo "$status_body" | grep -q 'head -15' \
  && ok "status caps commit list (head -15)" || fail_t "status dumps full commit wall (no truncation)"

# ── 12. release_bump.sh ios 的 sed 必須錨定，不得全域掃 ────────────────────
# 2026-08 起版號提升到 project-level build settings，六個 target-level 覆寫已刪除，所以
# 真實 pbxproj 裡這兩個 key 各只剩兩行、測試 bundle 靠繼承跟進。這個 fixture 因此**不再
# 是現況的縮影**，而是一個刻意保留的反例：檔內存在「不同值的同名 key」時，錨定的 sed
# 不得掃到它。這條守的是「日後有人把某個 target-level 覆寫加回來」的誤傷面。
# 注意它守不住的形狀：覆寫若加回**相同字面值**，錨定 sed 一樣會命中——那要靠 pbxproj
# 結構 lint（已記 backlog），不是這條。
section "bump ios sed stays anchored (never sweeps the file)"
BUMP="$WORKSPACE/ops/release_bump.sh"
# 結構：不得殘留無錨點的全域 sed（[^;]* 不綁當前值＝會掃中所有 target）
grep -q 'MARKETING_VERSION = \[\^;\]\*/MARKETING_VERSION' "$BUMP" \
  && fail_t "release_bump still has unanchored global MARKETING_VERSION sed" \
  || ok "no unanchored global MARKETING_VERSION sed"
# 行為：fixture pbxproj（app=9.9 在前、測試 bundle=1.2.0 在後），bump 後只有 app 變、測試 bundle 不動
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/ios/BooksAndVocab.xcodeproj"
cat > "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* app Release */  MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* tests Debug */  MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
/* tests Release */MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
PBX
KG_ROOT="$TMP" bash "$BUMP" ios 9.9.1 --yes >/dev/null 2>&1 || fail_t "bump ios fixture run failed"
got_app="$(grep -c 'MARKETING_VERSION = 9.9.1;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
got_test="$(grep -c 'MARKETING_VERSION = 1.2.0;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
got_build="$(grep -c 'CURRENT_PROJECT_VERSION = 8;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
[[ "$got_app" -eq 2 ]]  && ok "anchored MARKETING_VERSION → 9.9.1 (2 處)" || fail_t "app bump wrong count: $got_app"
[[ "$got_test" -eq 2 ]] && ok "differently-valued MARKETING_VERSION untouched (still 1.2.0 ×2)" || fail_t "sed swept a differently-valued line: 1.2.0 count=$got_test"
[[ "$got_build" -eq 2 ]] && ok "anchored CURRENT_PROJECT_VERSION → 8 (2 處)" || fail_t "app build bump wrong count: $got_build"

# ── 13. bump 寫入 gate：dry-run 預設、--yes 才寫（對齊 publish / asc.sh set 慣例） ──
section "Bump gate (dry-run by default)"
TMP2="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2"' EXIT
mkdir -p "$TMP2/ios/BooksAndVocab.xcodeproj" "$TMP2/backend/src/kg"
cat > "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* app Release */  MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
PBX
cat > "$TMP2/backend/pyproject.toml" <<'TOML'
[project]
version = "0.1.0"
TOML
cat > "$TMP2/backend/src/kg/api.py" <<'PY'
app = FastAPI(title="kg", version="0.1.0")
PY
cat > "$TMP2/backend/uv.lock" <<'LOCK'
version = 1

[[package]]
name = "kg"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "kg"
version = "8.8.8"
source = { registry = "https://example.invalid/simple" }

[[package]]
name = "unrelated"
version = "9.9.9"
source = { registry = "https://example.invalid/simple" }
LOCK
cp "$TMP2/backend/uv.lock" "$TMP2/backend/uv.lock.before"
chmod 0644 "$TMP2/backend/uv.lock"
lock_mode_before="$(stat -f '%Lp' "$TMP2/backend/uv.lock" 2>/dev/null || stat -c '%a' "$TMP2/backend/uv.lock")"

# 13a. dry-run（無 --yes）：exit 0、不改任何檔
dry_out="$(KG_ROOT="$TMP2" bash "$BUMP" ios 9.9.1 2>&1)" \
  && ok "bump ios dry-run exits 0" || fail_t "bump ios dry-run exited non-zero"
grep -q 'MARKETING_VERSION = 9.9;' "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ! grep -q '9\.9\.1' "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "dry-run leaves pbxproj untouched" || fail_t "dry-run modified pbxproj (must not write without --yes)"
# 13b. dry-run 輸出：舊→新 + 指引 --yes
echo "$dry_out" | grep -q '9.9 → 9.9.1' \
  && ok "dry-run prints old→new version" || fail_t "dry-run missing old→new preview: $dry_out"
echo "$dry_out" | grep -q -- '--yes' \
  && ok "dry-run points to --yes" || fail_t "dry-run does not mention --yes"
# 13c. api dry-run：兩檔皆不動、輸出含舊→新
api_dry="$(KG_ROOT="$TMP2" bash "$BUMP" api 0.2.0 2>&1)" \
  && ok "bump api dry-run exits 0" || fail_t "bump api dry-run exited non-zero"
grep -q 'version = "0.1.0"' "$TMP2/backend/pyproject.toml" \
  && grep -q 'version="0.1.0"' "$TMP2/backend/src/kg/api.py" \
  && ok "api dry-run leaves pyproject+api.py untouched" || fail_t "api dry-run modified version files"
echo "$api_dry" | grep -q '0.1.0 → 0.2.0' \
  && ok "api dry-run prints old→new" || fail_t "api dry-run missing old→new preview: $api_dry"
# 13d0. wrapper 無 --yes：dry-run 不寫檔（wrapper 路徑，非只測 primitive）
KG_ROOT="$TMP2" bash "$REL" bump api 0.2.0 >/dev/null 2>&1 \
  && ok "release.sh bump（無 --yes）exits 0" || fail_t "release.sh bump dry-run exited non-zero"
grep -q 'version = "0.1.0"' "$TMP2/backend/pyproject.toml" \
  && ok "release.sh bump（無 --yes）不寫檔" || fail_t "release.sh bump without --yes wrote files"
cmp -s "$TMP2/backend/uv.lock.before" "$TMP2/backend/uv.lock" \
  && ok "release.sh bump api dry-run leaves uv.lock untouched" || fail_t "release.sh bump api dry-run modified uv.lock"
# 13d1. 多餘 positional 拒絕（不得靜默忽略）
KG_ROOT="$TMP2" bash "$BUMP" ios 9.9.1 extra >/dev/null 2>&1 \
  && fail_t "extra positional silently accepted" || ok "bump 拒絕多餘 positional"
# 13d. --yes 經 release.sh wrapper 傳遞到 primitive（全域 --yes flag 生效）
KG_ROOT="$TMP2" bash "$REL" bump api 0.2.0 --yes >/dev/null 2>&1 \
  || fail_t "release.sh bump api --yes failed"
grep -q 'version = "0.2.0"' "$TMP2/backend/pyproject.toml" \
  && grep -q 'version="0.2.0"' "$TMP2/backend/src/kg/api.py" \
  && ok "release.sh bump --yes writes both api version files" || fail_t "release.sh bump --yes did not write api files"
editable_kg_version="$(awk 'BEGIN { RS="" } /name = "kg"/ && /source = \{ editable = "\." \}/ { if (match($0, /version = "[^"]+"/)) print substr($0, RSTART + 11, RLENGTH - 12) }' "$TMP2/backend/uv.lock")"
registry_kg_version="$(awk 'BEGIN { RS="" } /name = "kg"/ && /source = \{ registry = / { if (match($0, /version = "[^"]+"/)) print substr($0, RSTART + 11, RLENGTH - 12) }' "$TMP2/backend/uv.lock")"
unrelated_version="$(awk 'BEGIN { RS="" } /name = "unrelated"/ { if (match($0, /version = "[^"]+"/)) print substr($0, RSTART + 11, RLENGTH - 12) }' "$TMP2/backend/uv.lock")"
[[ "$editable_kg_version" == "0.2.0" \
   && "$registry_kg_version" == "8.8.8" \
   && "$unrelated_version" == "9.9.9" ]] \
  && ok "release.sh bump api updates only editable kg entry in uv.lock" \
  || fail_t "uv.lock scope wrong: editable=$editable_kg_version registry=$registry_kg_version unrelated=$unrelated_version"
lock_mode_after="$(stat -f '%Lp' "$TMP2/backend/uv.lock" 2>/dev/null || stat -c '%a' "$TMP2/backend/uv.lock")"
[[ "$lock_mode_after" == "$lock_mode_before" ]] \
  && ok "release.sh bump api preserves uv.lock mode" \
  || fail_t "uv.lock mode changed: before=$lock_mode_before after=$lock_mode_after"

# 13e. malformed lock preflight must be all-or-nothing: neither zero nor
# duplicate editable kg entries may leave pyproject/api.py partially bumped.
for lock_shape in zero duplicate; do
  fx="$TMP2/failure-$lock_shape"
  mkdir -p "$fx/backend/src/kg"
  cat > "$fx/backend/pyproject.toml" <<'TOML'
[project]
version = "0.1.0"
TOML
  cat > "$fx/backend/src/kg/api.py" <<'PY'
app = FastAPI(title="kg", version="0.1.0")
PY
  cat > "$fx/backend/uv.lock" <<'LOCK'
version = 1

[[package]]
name = "unrelated"
version = "9.9.9"
source = { registry = "https://example.invalid/simple" }
LOCK
  if [[ "$lock_shape" == duplicate ]]; then
    cat >> "$fx/backend/uv.lock" <<'LOCK'

[[package]]
name = "kg"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "kg"
version = "0.1.0"
source = { editable = "." }
LOCK
  fi
  cp "$fx/backend/pyproject.toml" "$fx/backend/pyproject.toml.before"
  cp "$fx/backend/src/kg/api.py" "$fx/backend/src/kg/api.py.before"
  cp "$fx/backend/uv.lock" "$fx/backend/uv.lock.before"
  malformed_rc=0
  KG_ROOT="$fx" bash "$REL" bump api 0.2.0 --yes >/dev/null 2>&1 || malformed_rc=$?
  [[ "$malformed_rc" -ne 0 \
     && "$(cmp -s "$fx/backend/pyproject.toml.before" "$fx/backend/pyproject.toml"; echo $?)" -eq 0 \
     && "$(cmp -s "$fx/backend/src/kg/api.py.before" "$fx/backend/src/kg/api.py"; echo $?)" -eq 0 \
     && "$(cmp -s "$fx/backend/uv.lock.before" "$fx/backend/uv.lock"; echo $?)" -eq 0 \
     && -z "$(find "$fx/backend" -name 'uv.lock.tmp.*' -print -quit)" ]] \
    && ok "malformed uv.lock ($lock_shape editable entries) rejects before any version mutation" \
    || fail_t "malformed uv.lock ($lock_shape) left a partial bump or temp file"
done

# 13f. A readonly destination must fail before any of the three version files
# changes. The old order mutated pyproject/api.py first, then failed while
# copying uv.lock, leaving a partial release bump behind.
readonly_fx="$TMP2/failure-readonly"
mkdir -p "$readonly_fx/backend/src/kg"
cat > "$readonly_fx/backend/pyproject.toml" <<'TOML'
[project]
version = "0.1.0"
TOML
cat > "$readonly_fx/backend/src/kg/api.py" <<'PY'
app = FastAPI(title="kg", version="0.1.0")
PY
cat > "$readonly_fx/backend/uv.lock" <<'LOCK'
version = 1

[[package]]
name = "kg"
version = "0.1.0"
source = { editable = "." }
LOCK
for version_file in \
  "$readonly_fx/backend/pyproject.toml" \
  "$readonly_fx/backend/src/kg/api.py" \
  "$readonly_fx/backend/uv.lock"; do
  cp "$version_file" "$version_file.before"
done
chmod 0444 "$readonly_fx/backend/uv.lock"
readonly_rc=0
KG_ROOT="$readonly_fx" bash "$REL" bump api 0.2.0 --yes >/dev/null 2>&1 || readonly_rc=$?
[[ "$readonly_rc" -ne 0 \
   && "$(cmp -s "$readonly_fx/backend/pyproject.toml.before" "$readonly_fx/backend/pyproject.toml"; echo $?)" -eq 0 \
   && "$(cmp -s "$readonly_fx/backend/src/kg/api.py.before" "$readonly_fx/backend/src/kg/api.py"; echo $?)" -eq 0 \
   && "$(cmp -s "$readonly_fx/backend/uv.lock.before" "$readonly_fx/backend/uv.lock"; echo $?)" -eq 0 \
   && -z "$(find "$readonly_fx/backend" -name '*.tmp.*' -print -quit)" ]] \
  && ok "readonly API version destination rejects without a partial bump" \
  || fail_t "readonly API version destination left a partial bump or temp file"
chmod 0644 "$readonly_fx/backend/uv.lock"

# 13g. Exercise the rollback path itself: fail the second candidate install
# once through PATH, after slot 1 has already been atomically replaced.
rollback_fx="$TMP2/failure-second-rename"
mkdir -p "$rollback_fx/backend/src/kg" "$rollback_fx/fakebin"
cat > "$rollback_fx/backend/pyproject.toml" <<'TOML'
[project]
version = "0.1.0"
TOML
cat > "$rollback_fx/backend/src/kg/api.py" <<'PY'
app = FastAPI(title="kg", version="0.1.0")
PY
cat > "$rollback_fx/backend/uv.lock" <<'LOCK'
version = 1

[[package]]
name = "kg"
version = "0.1.0"
source = { editable = "." }
LOCK
for version_file in \
  "$rollback_fx/backend/pyproject.toml" \
  "$rollback_fx/backend/src/kg/api.py" \
  "$rollback_fx/backend/uv.lock"; do
  cp "$version_file" "$version_file.before"
done
cat > "$rollback_fx/fakebin/mv" <<'SH'
#!/bin/bash
set -euo pipefail
if [[ "${2:-}" == *.tmp.* ]]; then
  count=0
  [[ ! -f "$KG_FAKE_MV_STATE" ]] || count="$(<"$KG_FAKE_MV_STATE")"
  count=$((count + 1))
  printf '%s\n' "$count" > "$KG_FAKE_MV_STATE"
  [[ "$count" -ne 2 ]] || exit 73
fi
exec /bin/mv "$@"
SH
chmod +x "$rollback_fx/fakebin/mv"
rollback_rc=0
rollback_out="$(PATH="$rollback_fx/fakebin:$PATH" \
  KG_FAKE_MV_STATE="$rollback_fx/mv-count" \
  KG_ROOT="$rollback_fx" \
  bash "$REL" bump api 0.2.0 --yes 2>&1)" || rollback_rc=$?
rollback_residue="$(find "$rollback_fx/backend" \( -name '*.tmp.*' -o -name '*.bak.*' \) -print -quit)"
rollback_count="missing"
[[ ! -f "$rollback_fx/mv-count" ]] || rollback_count="$(<"$rollback_fx/mv-count")"
rollback_py_cmp="$(cmp -s "$rollback_fx/backend/pyproject.toml.before" "$rollback_fx/backend/pyproject.toml"; echo $?)"
rollback_api_cmp="$(cmp -s "$rollback_fx/backend/src/kg/api.py.before" "$rollback_fx/backend/src/kg/api.py"; echo $?)"
rollback_lock_cmp="$(cmp -s "$rollback_fx/backend/uv.lock.before" "$rollback_fx/backend/uv.lock"; echo $?)"
[[ "$rollback_rc" -ne 0 \
   && "$rollback_count" -eq 2 \
   && "$rollback_py_cmp" -eq 0 \
   && "$rollback_api_cmp" -eq 0 \
   && "$rollback_lock_cmp" -eq 0 \
   && -z "$rollback_residue" ]] \
  && ok "second rename failure rolls back all three API version files" \
  || fail_t "second rename rollback failed: rc=$rollback_rc mv_count=$rollback_count cmp=$rollback_py_cmp/$rollback_api_cmp/$rollback_lock_cmp residue=${rollback_residue:-none} out=$rollback_out"

# 13h. A backup copy failure happens after mktemp has created the .bak path.
# The failed slot must already belong to transaction cleanup.
backup_fx="$TMP2/failure-backup-copy"
mkdir -p "$backup_fx/backend/src/kg" "$backup_fx/fakebin"
cp "$rollback_fx/backend/pyproject.toml.before" "$backup_fx/backend/pyproject.toml"
cp "$rollback_fx/backend/src/kg/api.py.before" "$backup_fx/backend/src/kg/api.py"
cp "$rollback_fx/backend/uv.lock.before" "$backup_fx/backend/uv.lock"
for version_file in \
  "$backup_fx/backend/pyproject.toml" \
  "$backup_fx/backend/src/kg/api.py" \
  "$backup_fx/backend/uv.lock"; do
  cp "$version_file" "$version_file.before"
done
cat > "$backup_fx/fakebin/cp" <<'SH'
#!/bin/bash
set -euo pipefail
[[ "${3:-}" != *.bak.* ]] || exit 74
exec /bin/cp "$@"
SH
chmod +x "$backup_fx/fakebin/cp"
backup_rc=0
backup_out="$(PATH="$backup_fx/fakebin:$PATH" \
  KG_ROOT="$backup_fx" \
  bash "$REL" bump api 0.2.0 --yes 2>&1)" || backup_rc=$?
backup_residue="$(find "$backup_fx/backend" \( -name '*.tmp.*' -o -name '*.bak.*' \) -print -quit)"
[[ "$backup_rc" -ne 0 \
   && "$(cmp -s "$backup_fx/backend/pyproject.toml.before" "$backup_fx/backend/pyproject.toml"; echo $?)" -eq 0 \
   && "$(cmp -s "$backup_fx/backend/src/kg/api.py.before" "$backup_fx/backend/src/kg/api.py"; echo $?)" -eq 0 \
   && "$(cmp -s "$backup_fx/backend/uv.lock.before" "$backup_fx/backend/uv.lock"; echo $?)" -eq 0 \
   && -z "$backup_residue" ]] \
  && ok "backup copy failure leaves no API mutation or transaction residue" \
  || fail_t "backup copy failure cleanup failed: rc=$backup_rc residue=${backup_residue:-none} out=$backup_out"

KG_ROOT="$TMP2" bash "$REL" bump ios 9.9.1 --yes >/dev/null 2>&1 \
  || fail_t "release.sh bump ios --yes failed"
grep -q 'MARKETING_VERSION = 9.9.1;' "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "release.sh bump --yes writes pbxproj" || fail_t "release.sh bump ios --yes did not write pbxproj"

# ── 14. bump-build：同 MARKETING_VERSION 重送、只 bump CURRENT_PROJECT_VERSION ──
section "Bump-build gate (build number only; App Review resubmit)"
TMP3="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2" "$TMP3"' EXIT
mkdir -p "$TMP3/ios/BooksAndVocab.xcodeproj"
cat > "$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* app Release */  MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* tests Debug */  MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
/* tests Release */MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
PBX
# 14a. dry-run（無 --yes）：exit 0、印舊→新 build、不寫檔
bb_dry="$(KG_ROOT="$TMP3" bash "$REL" bump-build ios 2>&1)" \
  && ok "bump-build ios dry-run exits 0" || fail_t "bump-build ios dry-run exited non-zero: $bb_dry"
echo "$bb_dry" | grep -q '7 → 8' \
  && ok "dry-run prints old→new build" || fail_t "dry-run missing old→new build preview: $bb_dry"
echo "$bb_dry" | grep -q -- '--yes' \
  && ok "dry-run points to --yes" || fail_t "dry-run does not mention --yes"
grep -q 'CURRENT_PROJECT_VERSION = 7;' "$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ! grep -q 'CURRENT_PROJECT_VERSION = 8;' "$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "dry-run leaves pbxproj untouched" || fail_t "bump-build dry-run modified pbxproj"
# 14b. --yes 經 wrapper：只動 app CURRENT_PROJECT_VERSION，MARKETING_VERSION 與測試 bundle 不動
KG_ROOT="$TMP3" bash "$REL" bump-build ios --yes >/dev/null 2>&1 \
  || fail_t "release.sh bump-build ios --yes failed"
bb_pbx="$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj"
[[ "$(grep -c 'CURRENT_PROJECT_VERSION = 8;' "$bb_pbx" || true)" -eq 2 ]] \
  && ok "anchored CURRENT_PROJECT_VERSION → 8 (2 處)" || fail_t "app build bump wrong count"
[[ "$(grep -c 'MARKETING_VERSION = 9.9;' "$bb_pbx" || true)" -eq 2 ]] \
  && ok "MARKETING_VERSION 不動 (still 9.9 ×2)" || fail_t "MARKETING_VERSION was touched by bump-build"
[[ "$(grep -c 'CURRENT_PROJECT_VERSION = 1;' "$bb_pbx" || true)" -eq 2 ]] \
  && ok "differently-valued CURRENT_PROJECT_VERSION untouched (still 1 ×2)" || fail_t "sed swept a differently-valued line"
# 14c. api 拒絕（api 無 build number 概念），錯誤訊息給可行動指引
bb_api="$(KG_ROOT="$TMP3" bash "$REL" bump-build api 2>&1)" \
  && fail_t "bump-build api should be rejected" \
  || { echo "$bb_api" | grep -q 'bump api' \
         && ok "bump-build api 拒絕且指向 bump api" || fail_t "bump-build api error not actionable: $bb_api"; }
# 14d. 多餘 positional 拒絕（不得靜默忽略）
KG_ROOT="$TMP3" bash "$REL" bump-build ios 9.9.1 >/dev/null 2>&1 \
  && fail_t "bump-build extra positional silently accepted" || ok "bump-build 拒絕多餘 positional"
# 14e. primitive 直呼也拒絕 api build-only
KG_ROOT="$TMP3" bash "$BUMP" api --build-only >/dev/null 2>&1 \
  && fail_t "release_bump --build-only api should be rejected" || ok "primitive 拒絕 api --build-only"

# ── 15. iOS 新 marketing version guard + false-tag transaction guard ────────
# `--new-version-after-ready` 存在的唯一理由，是舊 ios/<x.y.z> tag 不代表「上架」，
# 所以只能請 operator 用 typed attestation 背書。新語意下該 tag 由 `shipped ios` 依 ASC
# 驗證後才物化，**它存在本身就是上架證據**，guard 因此可以變成真檢查。
section "iOS new-version guard (verified, not attested) and false-tag guard"
TMP4="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2" "$TMP3" "$TMP4"' EXIT

make_ios_release_fixture() {
  local fixture="$1" remote="$2"
  mkdir -p "$fixture/ops/lib" "$fixture/ios/BooksAndVocab.xcodeproj"
  cp "$REL" "$BUMP" "$fixture/ops/"
  # release.sh source 它；漏了會在 fixture 裡變成「找不到 release_last_tag」而非測到行為。
  cp "$WORKSPACE/ops/lib/release_tags.sh" "$fixture/ops/lib/"
  cat > "$fixture/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 5;
/* app Release */  MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 5;
PBX
  cat > "$fixture/ops/ios_release.sh" <<'STUB'
#!/usr/bin/env bash
root="$(cd "$(dirname "$0")/.." && pwd)"
touch "$root/upload.called"
echo "stub upload invoked" >&2
exit "${STUB_UPLOAD_EXIT:-0}"
STUB
  chmod +x "$fixture/ops/ios_release.sh" "$fixture/ops/release_bump.sh"
  git init -q -b main "$fixture"
  git -C "$fixture" config user.name "Release Test"
  git -C "$fixture" config user.email "release-test@example.invalid"
  git -C "$fixture" add .
  git -C "$fixture" commit -qm "fixture: ios 2.0.0"
  git -C "$fixture" tag ios/2.0.0
  git init -q --bare "$remote"
  git -C "$fixture" remote add origin "$remote"
  git -C "$fixture" push -q origin main ios/2.0.0
}

# 15a. 被移除的 flag 必須硬報錯並指路。靜默忽略最糟：operator 以為自己仍在背書，
#      實際上那個字串不再影響任何判斷。
fx_a="$TMP4/removed-flag"; remote_a="$TMP4/removed-flag.git"
make_ios_release_fixture "$fx_a" "$remote_a"
head_a="$(git -C "$fx_a" rev-parse HEAD)"
noatt_rc=0
noatt_out="$(bash "$fx_a/ops/release.sh" release ios 2.0.1 --new-version-after-ready 2.0.0 --yes 2>&1)" || noatt_rc=$?
[[ "$noatt_rc" -ne 0 ]] \
  && ok "removed --new-version-after-ready hard-errors instead of being ignored" \
  || fail_t "removed --new-version-after-ready was silently accepted"
echo "$noatt_out" | grep -q 'shipped ios' \
  && ok "removed-flag error points at the verb that replaced it" \
  || fail_t "removed-flag error does not name the shipped verb: $noatt_out"
[[ "$(git -C "$fx_a" rev-parse HEAD)" == "$head_a" ]] \
  && grep -q 'MARKETING_VERSION = 2.0.0;' "$fx_a/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && [[ -z "$(git -C "$fx_a" tag -l 'ios/2.0.1*')" ]] \
  && [[ -z "$(git --git-dir="$remote_a" tag -l 'ios/2.0.1*')" ]] \
  && [[ ! -e "$fx_a/upload.called" ]] \
  && ok "removed-flag rejection is pre-mutation (pbx/commit/tag/upload untouched)" \
  || fail_t "removed-flag rejection happened after a mutation"

# 15b. 完全沒有上架 tag 時不得猜。有 build tag 也不算數——那只代表出過 archive。
fx_b="$TMP4/no-shipped-tag"; remote_b="$TMP4/no-shipped-tag.git"
make_ios_release_fixture "$fx_b" "$remote_b"
git -C "$fx_b" tag -d ios/2.0.0 >/dev/null
git -C "$fx_b" tag "ios/2.0.0+5"
mismatch_rc=0
mismatch_out="$(bash "$fx_b/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || mismatch_rc=$?
[[ "$mismatch_rc" -ne 0 ]] \
  && echo "$mismatch_out" | grep -q 'shipped ios' \
  && ok "no shipped tag: refuses and points at the shipped verb instead of guessing" \
  || fail_t "missing shipped tag was not actionably rejected: $mismatch_out"
[[ ! -e "$fx_b/upload.called" ]] \
  && ok "no-shipped-tag refusal is pre-upload" || fail_t "uploaded before the shipped-tag check"

# 15c. 正確 attestation 後 upload 若失敗，不得留下 false release commit/tag/push。
fx_c="$TMP4/upload-failure"; remote_c="$TMP4/upload-failure.git"
make_ios_release_fixture "$fx_c" "$remote_c"
head_c="$(git -C "$fx_c" rev-parse HEAD)"
upload_rc=0
upload_out="$(STUB_UPLOAD_EXIT=23 bash "$fx_c/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || upload_rc=$?
[[ "$upload_rc" -ne 0 && -e "$fx_c/upload.called" ]] \
  && ok "attested release reaches upload and propagates upload failure" \
  || fail_t "attested release did not exercise failing upload: $upload_out"
[[ "$(git -C "$fx_c" rev-parse HEAD)" == "$head_c" ]] \
  && [[ -z "$(git -C "$fx_c" tag -l 'ios/2.0.1*')" ]] \
  && [[ -z "$(git --git-dir="$remote_c" tag -l 'ios/2.0.1*')" ]] \
  && [[ "$(git --git-dir="$remote_c" rev-parse refs/heads/main)" == "$head_c" ]] \
  && ok "upload failure leaves no false release commit/tag/push" \
  || fail_t "upload failure left a false release commit/tag/push"

# 15d. direct tag 也是外部 release marker，必須吃同一個 guard——否則 bump→tag 兩步
#      就是一條繞過 release 的旁路。這裡用倒退版號當探針。
fx_d="$TMP4/direct-tag"; remote_d="$TMP4/direct-tag.git"
make_ios_release_fixture "$fx_d" "$remote_d"
head_d="$(git -C "$fx_d" rev-parse HEAD)"
direct_rc=0
direct_out="$(bash "$fx_d/ops/release.sh" bump ios 1.9.9 --yes 2>&1 && bash "$fx_d/ops/release.sh" tag ios 1.9.9 --yes 2>&1)" || direct_rc=$?
[[ "$direct_rc" -ne 0 \
   && "$(git -C "$fx_d" rev-parse HEAD)" == "$head_d" \
   && ! -e "$fx_d/upload.called" ]] \
  && [[ -z "$(git -C "$fx_d" tag -l 'ios/1.9.9*')" ]] \
  && [[ -z "$(git --git-dir="$remote_d" tag -l 'ios/1.9.9*')" ]] \
  && ok "direct iOS tag enforces the same new-version guard as release" \
  || fail_t "direct iOS tag bypassed the guard: $direct_out"

# 15e. 已上架 tag 存在也不授權 semver 倒退。
fx_e="$TMP4/downgrade"; remote_e="$TMP4/downgrade.git"
make_ios_release_fixture "$fx_e" "$remote_e"
head_e="$(git -C "$fx_e" rev-parse HEAD)"
downgrade_rc=0
downgrade_out="$(bash "$fx_e/ops/release.sh" release ios 1.9.9 --yes 2>&1)" || downgrade_rc=$?
[[ "$downgrade_rc" -ne 0 \
   && "$(git -C "$fx_e" rev-parse HEAD)" == "$head_e" \
   && ! -e "$fx_e/upload.called" ]] \
  && echo "$downgrade_out" | grep -q '高於.*2.0.0' \
  && ok "iOS new marketing version must increase monotonically" \
  || fail_t "iOS downgrade was not safely rejected: $downgrade_out"

# 15f. 合法恢復：版號已在 HEAD、upload 成功時，跳過空 commit 並 tag/push current HEAD。
fx_f="$TMP4/already-committed"; remote_f="$TMP4/already-committed.git"
make_ios_release_fixture "$fx_f" "$remote_f"
sed -i '' 's/MARKETING_VERSION = 2.0.0;/MARKETING_VERSION = 2.0.1;/g; s/CURRENT_PROJECT_VERSION = 5;/CURRENT_PROJECT_VERSION = 6;/g' \
  "$fx_f/ios/BooksAndVocab.xcodeproj/project.pbxproj"
git -C "$fx_f" add ios/BooksAndVocab.xcodeproj/project.pbxproj
git -C "$fx_f" commit -qm "fixture: version already committed"
committed_head="$(git -C "$fx_f" rev-parse HEAD)"
committed_rc=0
committed_out="$(bash "$fx_f/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || committed_rc=$?
[[ "$committed_rc" -eq 0 && -e "$fx_f/upload.called" \
   && "$(git -C "$fx_f" rev-parse HEAD)" == "$committed_head" \
   && "$(git -C "$fx_f" rev-parse 'refs/tags/ios/2.0.1+6^{commit}')" == "$committed_head" \
   && "$(git --git-dir="$remote_f" rev-parse 'refs/tags/ios/2.0.1+6^{commit}')" == "$committed_head" \
   && "$(git --git-dir="$remote_f" rev-parse refs/heads/main)" == "$committed_head" ]] \
  && ok "already-committed version uploads then tags/pushes current HEAD" \
  || fail_t "already-committed version left a partial release: $committed_out"

# 15g. 事故本體：有一個版本出過 build、卻還沒有上架 tag，就直接發下一版。
#      2.0.1 事故就是這個形狀——2.0.0 還在審（build 5 已上傳），卻已 bump 成 2.0.1。
#      build tag 讓這件事**第一次變成可檢查的**：介於已上架版本與本次版本之間、
#      有 build tag 卻沒有上架 tag 的版本 = 尚未確認上架，不得跳過。
fx_g="$TMP4/pending-version"; remote_g="$TMP4/pending-version.git"
make_ios_release_fixture "$fx_g" "$remote_g"
git -C "$fx_g" tag -d ios/2.0.0 >/dev/null
git -C "$fx_g" tag "ios/1.6.0"            # 真正上架的是 1.6.0
git -C "$fx_g" tag "ios/2.0.0+5"          # 2.0.0 出過 build，但沒人確認它上架了
git -C "$fx_g" tag "ios/2.0.0+6"
head_g="$(git -C "$fx_g" rev-parse HEAD)"
pending_rc=0
pending_out="$(bash "$fx_g/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || pending_rc=$?
[[ "$pending_rc" -ne 0 && ! -e "$fx_g/upload.called" \
   && "$(git -C "$fx_g" rev-parse HEAD)" == "$head_g" ]] \
  && ok "skipping a version that has builds but no shipped tag is refused pre-upload" \
  || fail_t "released past an unconfirmed version (the 2.0.1 incident shape): $pending_out"
echo "$pending_out" | grep -q '2\.0\.0' \
  && ok "pending-version error names the version that was about to be skipped" \
  || fail_t "pending-version error does not name 2.0.0: $pending_out"
# 正控：補上 2.0.0 的上架 tag 後，同一條命令必須放行——否則上面那條可能是任何原因擋的。
git -C "$fx_g" tag "ios/2.0.0"
allow_rc=0
allow_out="$(bash "$fx_g/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || allow_rc=$?
[[ "$allow_rc" -eq 0 && -e "$fx_g/upload.called" \
   && -n "$(git -C "$fx_g" tag -l 'ios/2.0.1+6')" ]] \
  && ok "same command proceeds once the intermediate version is confirmed shipped" \
  || fail_t "guard blocks even after the pending version is resolved: $allow_out"

# ── 版號漂移分類（ios/2.0.1 誤標事故：tag 高於檔內 = 版號被撤回，不是待對齊）──
# 事故形狀：`ops: release ios 2.0.1` 打了 tag，其後 `ios: correct 2.0.0 build 6
# resubmission` 把 MARKETING_VERSION 還原成 2.0.0，2.0.1 從未上架。留著的 tag 讓
# last_tag 回 ios/2.0.1，於是 --new-version-after-ready 逼 operator attest 一個
# 不存在的版本、且新版號被強制 > 2.0.1（2.0.1 永久燒掉）。舊的單一漂移警示只會
# 說「發版前先 bump 對齊」——照做會復活被撤回的版號，方向剛好相反。
drift_fn="$(sed -n '/^classify_version_drift()/,/^}/p' "$REL")"
if [[ -n "$drift_fn" ]]; then
  drift_probe() {
    bash -lc "$(sed -n '/^valid_semver()/,/^}/p' "$REL")
$(sed -n '/^semver_gt()/,/^}/p' "$REL")
$drift_fn
classify_version_drift '$1' '$2'"
  }
  [[ "$(drift_probe 2.0.0 2.0.0)" == none ]] \
    && ok "drift: equal versions report none" || fail_t "drift equal invalid: $(drift_probe 2.0.0 2.0.0)"
  [[ "$(drift_probe 2.0.0 2.0.1)" == ahead ]] \
    && ok "drift: file ahead of tag is a pending bump" || fail_t "drift ahead invalid: $(drift_probe 2.0.0 2.0.1)"
  [[ "$(drift_probe 2.0.1 2.0.0)" == mistagged ]] \
    && ok "drift: tag ahead of file is a withdrawn version (mistagged)" \
    || fail_t "drift mistagged invalid: $(drift_probe 2.0.1 2.0.0)"
  [[ "$(drift_probe 2.0 2.0.0)" == none ]] \
    && ok "drift: two-segment ios version normalizes before comparison" \
    || fail_t "drift 2-seg normalization invalid: $(drift_probe 2.0 2.0.0)"
  [[ "$(drift_probe '' 2.0.0)" == none ]] \
    && ok "drift: unknown tag version stays quiet" || fail_t "drift empty-tag invalid: $(drift_probe '' 2.0.0)"
else
  fail_t "release.sh has no classify_version_drift seam (ios/2.0.1 mistag stays undiagnosed)"
fi
echo "$status_body" | grep -q 'classify_version_drift' \
  && ok "status classifies drift instead of always advising a bump" \
  || fail_t "status still emits a single undirected drift warning"
echo "$status_body" | grep -q '誤標' \
  && ok "status names the mistagged case" || fail_t "status has no mistagged branch"

# ── 16. last_tag 只認 released 形狀（build tag 不得污染） ────────────────────
# `git tag -l "ios/*"` 的 `*` 會跨 `/` 比對，而 `--sort=-v:refname` 把 ios/2.0.0+6
# 排在 ios/2.0.0 之上。所以一旦開始記 build tag，未收緊的 last_tag 會回 build tag，
# 讓 guard / status / changelog range 全部改讀一個不是「已上架版本」的東西。
section "last_tag recognizes only the released x.y.z shape"

# 直接對規則的 owner 取證，不再從 release.sh 抽函式體：抽取式 probe 只證明「那段程式碼
# 這樣寫」，證不到任何呼叫端——所以它可以在 release_changelog.sh 靜默壞掉時全綠。
# 呼叫端由下面的 status 斷言與 §18 的 changelog 斷言各自覆蓋。
last_tag_probe() {  # $1=fixture root  $2=component
  bash -c "set -euo pipefail
. '$WORKSPACE/ops/lib/release_tags.sh'
release_last_tag '$2' '$1'"
}

TMP5="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2" "$TMP3" "$TMP4" "$TMP5"' EXIT
fx_lt="$TMP5/last-tag"
mkdir -p "$fx_lt"
git init -q -b main "$fx_lt"
git -C "$fx_lt" config user.name "Release Test"
git -C "$fx_lt" config user.email "release-test@example.invalid"
git -C "$fx_lt" commit -q --allow-empty -m "fixture"
for t in ios/1.6.0 ios/2.0.0 ios/2.0.0+5 ios/2.0.0+6 api/2.0.1; do
  git -C "$fx_lt" tag "$t"
done

# 負控先行：確認未收緊的 glob 真的會撈到 build tag，否則下面那條測試沒在測東西。
[[ "$(git -C "$fx_lt" tag -l 'ios/*' --sort=-v:refname | head -1)" == "ios/2.0.0+6" ]] \
  && ok "raw ios/* glob does rank the build tag first (guard is load-bearing)" \
  || fail_t "fixture does not reproduce build-tag pollution — the last_tag test proves nothing"

lt_ios="$(last_tag_probe "$fx_lt" ios)"
[[ "$lt_ios" == "ios/2.0.0" ]] \
  && ok "last_tag ios skips build tags and returns ios/2.0.0" \
  || fail_t "last_tag ios returned '${lt_ios}' (build tag leaked into released-version lookup)"
lt_api="$(last_tag_probe "$fx_lt" api)"
[[ "$lt_api" == "api/2.0.1" ]] \
  && ok "last_tag api unaffected" || fail_t "last_tag api returned '${lt_api}'"

# 沒有任何 released tag 時必須「回空且 exit 0」：呼叫端在 set -e 下用 lt="$(last_tag …)"，
# 一個非零 exit 會讓 status 整個中斷，而不是走「（尚未發版）」分支。
fx_lt_empty="$TMP5/last-tag-empty"
mkdir -p "$fx_lt_empty"
git init -q -b main "$fx_lt_empty"
git -C "$fx_lt_empty" config user.name "Release Test"
git -C "$fx_lt_empty" config user.email "release-test@example.invalid"
git -C "$fx_lt_empty" commit -q --allow-empty -m "fixture"
git -C "$fx_lt_empty" tag "ios/2.0.0+6"
empty_rc=0
lt_empty="$(last_tag_probe "$fx_lt_empty" ios)" || empty_rc=$?
[[ "$empty_rc" -eq 0 && -z "$lt_empty" ]] \
  && ok "last_tag with build tags but no released tag returns empty and exits 0" \
  || fail_t "last_tag build-tag-only repo: rc=$empty_rc out='${lt_empty}' (would abort status under set -e)"

# 呼叫端取證：release.sh status 必須報 released tag，而不是排在它前面的 build tag。
mkdir -p "$fx_lt/ops/lib" "$fx_lt/ios/BooksAndVocab.xcodeproj" "$fx_lt/backend/src/kg"
cp "$REL" "$fx_lt/ops/"
cp "$WORKSPACE/ops/lib/release_tags.sh" "$fx_lt/ops/lib/"
cat > "$fx_lt/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 6;
MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 6;
PBX
printf '[project]\nversion = "2.0.1"\n' > "$fx_lt/backend/pyproject.toml"
status_fx="$(bash "$fx_lt/ops/release.sh" status 2>&1)"
echo "$status_fx" | grep -E '^■ ios' | grep -q 'ios/2.0.0+6' \
  && fail_t "status reports the build tag as the last released version: $(echo "$status_fx" | grep -E '^■ ios')" \
  || ok "status caller reports the released tag, not the build tag"

# ── 17. build tag：(version, build) → 封版 commit ───────────────────────────
# Apple 只保留「當前」appStoreVersion，versionString 是可變欄位，build number 每個
# marketing version 重新計數。所以「哪顆 commit 產生了哪顆 build」這個事實只有 repo
# 能保存，而且必須在出 archive 的當下捕捉——事後無從重建（ios/2.0.0 指向 build 5 的
# commit、實際上架 build 6 的事故，就是靠 pbxproj 編輯時戳夾送審時戳硬反推出來的）。
section "iOS build tag records which commit produced (version, build)"

# 17a. release ios 成功後封的是 ios/<ver>+<build>，且**不得**順手打 ios/<ver>：
#      後者是「已上架」的斷言，upload 完成的那一刻沒有任何人知道它會不會過審。
fx_bt="$TMP5/build-tag"; remote_bt="$TMP5/build-tag.git"
make_ios_release_fixture "$fx_bt" "$remote_bt"
bt_rc=0
bt_out="$(bash "$fx_bt/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || bt_rc=$?
bt_head="$(git -C "$fx_bt" rev-parse HEAD)"
[[ "$bt_rc" -eq 0 && -e "$fx_bt/upload.called" ]] \
  && ok "release ios uploads and completes" || fail_t "release ios failed: $bt_out"
[[ "$(git -C "$fx_bt" rev-parse -q --verify 'refs/tags/ios/2.0.1+6^{commit}' 2>/dev/null)" == "$bt_head" ]] \
  && ok "build tag ios/2.0.1+6 seals the commit that produced the archive" \
  || fail_t "no ios/2.0.1+6 build tag at the sealing commit: $bt_out"
git -C "$fx_bt" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && fail_t "release minted ios/2.0.1 — repo claimed a shipped fact it cannot know at upload time" \
  || ok "release does not mint the shipped tag it cannot know yet"
[[ "$(git --git-dir="$remote_bt" rev-parse -q --verify 'refs/tags/ios/2.0.1+6^{commit}' 2>/dev/null)" == "$bt_head" ]] \
  && ok "build tag is pushed to origin (the other clone needs the same record)" \
  || fail_t "build tag stayed local"

# 17b. 同一 (version, build) 從兩顆不同 commit 出 archive = 真歧義，必須 refuse，
#      而且要在 upload 之前——TestFlight upload 不可逆，先確定封得下去再送。
fx_bc="$TMP5/build-tag-conflict"; remote_bc="$TMP5/build-tag-conflict.git"
make_ios_release_fixture "$fx_bc" "$remote_bc"
sealed_bc="$(git -C "$fx_bc" rev-parse HEAD)"
git -C "$fx_bc" tag "ios/2.0.1+6"
conflict_rc=0
conflict_out="$(bash "$fx_bc/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || conflict_rc=$?
[[ "$conflict_rc" -ne 0 ]] \
  && ok "conflicting build tag is refused" || fail_t "conflicting build tag was silently accepted: $conflict_out"
[[ ! -e "$fx_bc/upload.called" ]] \
  && ok "conflict refusal happens before the irreversible upload" \
  || fail_t "uploaded to TestFlight before discovering we could not seal the result"
[[ "$(git -C "$fx_bc" rev-parse 'refs/tags/ios/2.0.1+6^{commit}')" == "$sealed_bc" \
   && "$(git -C "$fx_bc" rev-parse HEAD)" == "$sealed_bc" ]] \
  && ok "conflict leaves the existing build tag and HEAD untouched" \
  || fail_t "conflict moved the existing build tag or HEAD"
# 這條斷言必須綁在**同一行**同時出現 tag 名與既有 commit：只 grep 短 sha 會被 git 的
# push range 行（`84b9bb5..312e381 main -> main`）滿足，於是在完全沒有拒絕訊息時也變綠。
echo "$conflict_out" | grep -q "ios/2.0.1+6.*$(git -C "$fx_bc" rev-parse --short "$sealed_bc")" \
  && ok "conflict error names both the build tag and the commit it already points at" \
  || fail_t "conflict error is not actionable (no single line naming tag + existing commit): $conflict_out"

# 17c. 冪等：同一 (version, build) 已封在這顆 commit → noop，不是錯誤。
#      重跑一次收尾（例如 push 中斷後補跑）不該逼人手動刪 tag。
fx_bi="$TMP5/build-tag-idempotent"; remote_bi="$TMP5/build-tag-idempotent.git"
make_ios_release_fixture "$fx_bi" "$remote_bi"
bash "$fx_bi/ops/release.sh" bump ios 2.0.1 --yes >/dev/null 2>&1 \
  || fail_t "idempotent fixture bump failed"
git -C "$fx_bi" add ios/BooksAndVocab.xcodeproj/project.pbxproj
git -C "$fx_bi" commit -qm "ios: seal 2.0.1 build 6"
sealed_bi="$(git -C "$fx_bi" rev-parse HEAD)"
git -C "$fx_bi" tag "ios/2.0.1+6"
idem_rc=0
idem_out="$(bash "$fx_bi/ops/release.sh" tag ios 2.0.1 --yes 2>&1)" || idem_rc=$?
[[ "$idem_rc" -eq 0 \
   && "$(git -C "$fx_bi" rev-parse HEAD)" == "$sealed_bi" \
   && "$(git -C "$fx_bi" rev-parse 'refs/tags/ios/2.0.1+6^{commit}')" == "$sealed_bi" \
   && "$(git --git-dir="$remote_bi" rev-parse -q --verify 'refs/tags/ios/2.0.1+6^{commit}' 2>/dev/null)" == "$sealed_bi" ]] \
  && ok "re-sealing the same (version, build) at the same commit is a noop that still pushes" \
  || fail_t "idempotent re-tag failed: rc=$idem_rc out=$idem_out"

# ── 18. changelog 也吃同一條「released tag」規則 ────────────────────────────
# §16 只證明了 release.sh 裡的 last_tag 函式，證不到任何呼叫端——而 release_changelog.sh
# 帶著同一段邏輯的第二份逐字副本。build tag 一存在，`changelog ios` 就靜默錨在它上面、
# 把整份 changelog 清空（無錯誤訊息），而 status 的結尾提示正是 bump → changelog → release。
# 兩份實作就是這次事故的根因，所以除了行為，也釘住「不得再有第三份」。
section "changelog shares the released-tag rule (no second implementation)"
CHANGELOG="$WORKSPACE/ops/release_changelog.sh"
TAGLIB="$WORKSPACE/ops/lib/release_tags.sh"

[[ -f "$TAGLIB" ]] \
  && ok "ops/lib/release_tags.sh exists (single owner of the tag rule)" \
  || fail_t "ops/lib/release_tags.sh missing — release.sh and release_changelog.sh still carry two copies"
grep -q 'git tag -l' "$CHANGELOG" \
  && fail_t "release_changelog.sh still enumerates tags itself (second implementation of the released-tag rule)" \
  || ok "release_changelog.sh no longer enumerates tags itself"

fx_cl="$TMP5/changelog"
mkdir -p "$fx_cl/ops/lib"
cp "$CHANGELOG" "$fx_cl/ops/"
[[ ! -f "$TAGLIB" ]] || cp "$TAGLIB" "$fx_cl/ops/lib/"
git init -q -b main "$fx_cl"
git -C "$fx_cl" config user.name "Release Test"
git -C "$fx_cl" config user.email "release-test@example.invalid"
git -C "$fx_cl" commit -q --allow-empty -m "ios: before shipping"
git -C "$fx_cl" tag ios/2.0.0
git -C "$fx_cl" commit -q --allow-empty -m "ios: 新增 after shipping"
git -C "$fx_cl" tag "ios/2.0.0+6"          # build tag 指向較新的 commit
cl_out="$(bash "$fx_cl/ops/release_changelog.sh" ios 2>&1)"
echo "$cl_out" | grep -q '自 ios/2\.0\.0[^+]' && ! echo "$cl_out" | grep -q '2\.0\.0+6' \
  && ok "changelog anchors on the released tag, not the build tag" \
  || fail_t "changelog anchored on a build tag: $cl_out"
echo "$cl_out" | grep -q 'after shipping' \
  && ok "changelog still lists commits made after the released tag" \
  || fail_t "changelog silently emptied itself (no error, just no content): $cl_out"

# ── 19. shipped ios：驗證式物化上架 tag（非背書式） ─────────────────────────
# 「哪顆 build 上架了」的 owner 是 ASC，「哪顆 commit 產生它」的 owner 是 repo。
# shipped 做的是這兩者的 join，而且只在確認上架後才物化成 ios/<x.y.z>。
# ASC 查詢走 KG_ASC_SHIPPED_CMD 注入點，所以這一整節離線可跑、不碰網路與憑證。
section "shipped ios materializes the shipped tag from ASC + build tag"

make_shipped_fixture() {  # $1=fixture $2=remote $3=stub 印出的內容 $4=stub exit code
  make_ios_release_fixture "$1" "$2"
  git -C "$1" tag -d ios/2.0.0 >/dev/null      # 上架 tag 由 shipped 產生，不預設存在
  cat > "$1/asc-stub.sh" <<STUB
#!/usr/bin/env bash
printf '%s\n' "$3"
exit ${4:-0}
STUB
  chmod +x "$1/asc-stub.sh"
}

# 19a. dry-run 預設：查得到、也 join 得到，但沒有 --yes 就不得建立 tag。
fx_s="$TMP5/shipped"; remote_s="$TMP5/shipped.git"
make_shipped_fixture "$fx_s" "$remote_s" "2.0.0 6"
sealed_s="$(git -C "$fx_s" rev-parse HEAD)"
git -C "$fx_s" tag "ios/2.0.0+6"
dry_rc=0
dry_s="$(KG_ASC_SHIPPED_CMD="$fx_s/asc-stub.sh" bash "$fx_s/ops/release.sh" shipped ios 2>&1)" || dry_rc=$?
[[ "$dry_rc" -eq 0 ]] && ok "shipped dry-run exits 0" || fail_t "shipped dry-run exited $dry_rc: $dry_s"
[[ -z "$(git -C "$fx_s" tag -l 'ios/2.0.0')" ]] \
  && ok "shipped dry-run creates no tag" || fail_t "shipped dry-run created a tag"
echo "$dry_s" | grep -q -- '--yes' \
  && ok "shipped dry-run points to --yes" || fail_t "shipped dry-run does not mention --yes: $dry_s"

# 19b. --yes：ios/2.0.0 落在 build tag 指的那顆 commit 上，並推 origin。
yes_rc=0
yes_s="$(KG_ASC_SHIPPED_CMD="$fx_s/asc-stub.sh" bash "$fx_s/ops/release.sh" shipped ios --yes 2>&1)" || yes_rc=$?
[[ "$(git -C "$fx_s" rev-parse 'refs/tags/ios/2.0.0^{commit}')" == "$sealed_s" \
   && "$(git --git-dir="$remote_s" rev-parse -q --verify 'refs/tags/ios/2.0.0^{commit}' 2>/dev/null)" == "$sealed_s" ]] \
  && ok "shipped joins (version, build) to the sealing commit and pushes" \
  || fail_t "shipped tag wrong or unpushed: $yes_s"

# 19c. 冪等：再跑一次是 noop，不是錯誤（tag 已與 ASC 一致）。
again_rc=0
again_s="$(KG_ASC_SHIPPED_CMD="$fx_s/asc-stub.sh" bash "$fx_s/ops/release.sh" shipped ios --yes 2>&1)" || again_rc=$?
[[ "$again_rc" -eq 0 && "$(git -C "$fx_s" rev-parse 'refs/tags/ios/2.0.0^{commit}')" == "$sealed_s" ]] \
  && ok "re-running shipped against an already-correct tag is a noop" \
  || fail_t "second shipped run failed or moved the tag: $again_s"

# 19d. 上架 tag 已存在但指向別顆 commit → 不移動。immutable 是這個 tag 的全部價值：
#      一個 released marketing version 只會有一顆上架 build，所以歧義必須人工裁決。
fx_sm="$TMP5/shipped-mismatch"; remote_sm="$TMP5/shipped-mismatch.git"
make_shipped_fixture "$fx_sm" "$remote_sm" "2.0.0 6"
wrong_sm="$(git -C "$fx_sm" rev-parse HEAD)"
git -C "$fx_sm" tag "ios/2.0.0" "$wrong_sm"
git -C "$fx_sm" commit -q --allow-empty -m "ios: the real sealing commit"
right_sm="$(git -C "$fx_sm" rev-parse HEAD)"
git -C "$fx_sm" tag "ios/2.0.0+6" "$right_sm"
mm_rc=0
mm_out="$(KG_ASC_SHIPPED_CMD="$fx_sm/asc-stub.sh" bash "$fx_sm/ops/release.sh" shipped ios --yes 2>&1)" || mm_rc=$?
[[ "$mm_rc" -ne 0 && "$(git -C "$fx_sm" rev-parse 'refs/tags/ios/2.0.0^{commit}')" == "$wrong_sm" ]] \
  && echo "$mm_out" | grep -q 'tag -d ios/2.0.0' \
  && ok "shipped refuses to move an existing shipped tag and prints the manual remediation" \
  || fail_t "shipped moved or silently accepted a conflicting shipped tag: $mm_out"

# 19e. 沒有對應 build tag（發版於本機制上線前）→ 明確說「沒有紀錄」，不猜。
fx_sn="$TMP5/shipped-norecord"; remote_sn="$TMP5/shipped-norecord.git"
make_shipped_fixture "$fx_sn" "$remote_sn" "2.0.0 6"
nr_rc=0
nr_out="$(KG_ASC_SHIPPED_CMD="$fx_sn/asc-stub.sh" bash "$fx_sn/ops/release.sh" shipped ios --yes 2>&1)" || nr_rc=$?
[[ "$nr_rc" -ne 0 && -z "$(git -C "$fx_sn" tag -l 'ios/2.0.0')" ]] \
  && echo "$nr_out" | grep -q -- '--commit' \
  && ok "missing build tag: refuses and offers the manual --commit escape hatch" \
  || fail_t "missing build tag was not actionably refused: $nr_out"

# 19f. --commit 人工覆寫可用，但必須把「這是人工斷言」印出來——它繞過的正是查證。
manual_sn="$(git -C "$fx_sn" rev-parse HEAD)"
man_rc=0
man_out="$(KG_ASC_SHIPPED_CMD="$fx_sn/asc-stub.sh" bash "$fx_sn/ops/release.sh" shipped ios --commit "$manual_sn" --yes 2>&1)" || man_rc=$?
[[ "$(git -C "$fx_sn" rev-parse 'refs/tags/ios/2.0.0^{commit}')" == "$manual_sn" ]] \
  && ok "--commit override lands the shipped tag" || fail_t "--commit override did not tag: $man_out"
echo "$man_out" | grep -q '人工' \
  && ok "--commit override announces it is a human assertion, not a verified join" \
  || fail_t "--commit override does not flag itself as manual: $man_out"

# 19g. ASC 查不到（斷網 / 憑證壞 / 無 READY_FOR_SALE）→ 硬停，不得降級成猜測。
fx_sf="$TMP5/shipped-ascfail"; remote_sf="$TMP5/shipped-ascfail.git"
make_shipped_fixture "$fx_sf" "$remote_sf" "" 1
git -C "$fx_sf" tag "ios/2.0.0+6"
af_rc=0
af_out="$(KG_ASC_SHIPPED_CMD="$fx_sf/asc-stub.sh" bash "$fx_sf/ops/release.sh" shipped ios --yes 2>&1)" || af_rc=$?
[[ "$af_rc" -ne 0 && -z "$(git -C "$fx_sf" tag -l 'ios/2.0.0')" ]] \
  && ok "ASC lookup failure refuses instead of falling back to a guess" \
  || fail_t "ASC failure produced a tag anyway: $af_out"

# 19h. ASC 回傳格式不合 → 同樣硬停（別把垃圾字串寫進 tag 名）。
fx_sg="$TMP5/shipped-garbage"; remote_sg="$TMP5/shipped-garbage.git"
make_shipped_fixture "$fx_sg" "$remote_sg" "not-a-version xyz"
gb_rc=0
gb_out="$(KG_ASC_SHIPPED_CMD="$fx_sg/asc-stub.sh" bash "$fx_sg/ops/release.sh" shipped ios --yes 2>&1)" || gb_rc=$?
[[ "$gb_rc" -ne 0 && -z "$(git -C "$fx_sg" tag -l 'ios/*' | grep -v '+' || true)" ]] \
  && ok "malformed ASC response is rejected before any tag is written" \
  || fail_t "malformed ASC response was accepted: $gb_out"

# ── 20. resubmit ios：同版號、新 build 的重送 ───────────────────────────────
# 這條路徑（bump-build + ios_release.sh --upload）原本**完全不留任何紀錄**——沒有
# commit、沒有 tag，這正是 ios/2.0.0 指向 build 5 而實際上架 build 6 的成因。
# 它現在和 release 對稱：upload 成功才封版，失敗不留 false marker。
section "resubmit ios seals the same-version rebuild"

# 20a. dry-run 預設：不 upload、不改檔，且要印出將產生的 build number。
fx_r="$TMP5/resubmit"; remote_r="$TMP5/resubmit.git"
make_ios_release_fixture "$fx_r" "$remote_r"
head_r="$(git -C "$fx_r" rev-parse HEAD)"
rdry_rc=0
rdry="$(bash "$fx_r/ops/release.sh" resubmit ios 2>&1)" || rdry_rc=$?
[[ "$rdry_rc" -eq 0 && ! -e "$fx_r/upload.called" ]] \
  && ok "resubmit dry-run exits 0 without uploading" || fail_t "resubmit dry-run misbehaved: $rdry"
grep -q 'CURRENT_PROJECT_VERSION = 5;' "$fx_r/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "resubmit dry-run leaves pbxproj untouched" || fail_t "resubmit dry-run wrote pbxproj"
echo "$rdry" | grep -q 'ios/2.0.0+6' \
  && ok "resubmit dry-run names the build tag it will create" \
  || fail_t "resubmit dry-run does not preview the build tag: $rdry"

# 20b. --yes：build +1、marketing 不動、封 ios/2.0.0+6，且不得產生上架 tag。
rres_rc=0
rres="$(bash "$fx_r/ops/release.sh" resubmit ios --yes 2>&1)" || rres_rc=$?
sealed_r="$(git -C "$fx_r" rev-parse HEAD)"
[[ "$rres_rc" -eq 0 && -e "$fx_r/upload.called" ]] \
  && ok "resubmit uploads" || fail_t "resubmit did not upload: $rres"
[[ "$(grep -c 'CURRENT_PROJECT_VERSION = 6;' "$fx_r/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)" -eq 2 \
   && "$(grep -c 'MARKETING_VERSION = 2.0.0;' "$fx_r/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)" -eq 2 ]] \
  && ok "resubmit bumps build only, marketing version untouched" \
  || fail_t "resubmit changed the marketing version"
[[ "$sealed_r" != "$head_r" \
   && "$(git -C "$fx_r" rev-parse 'refs/tags/ios/2.0.0+6^{commit}')" == "$sealed_r" \
   && "$(git --git-dir="$remote_r" rev-parse -q --verify 'refs/tags/ios/2.0.0+6^{commit}' 2>/dev/null)" == "$sealed_r" ]] \
  && ok "resubmit seals ios/2.0.0+6 at the new commit and pushes it" \
  || fail_t "resubmit did not seal the rebuild: $rres"
# 上架 tag 必須還是原本那顆：重送不代表上架。
[[ "$(git -C "$fx_r" rev-parse 'refs/tags/ios/2.0.0^{commit}')" == "$head_r" ]] \
  && ok "resubmit does not touch the shipped tag" || fail_t "resubmit moved ios/2.0.0"

# 20c. upload 失敗 → 不留 commit / tag / push（與 release 同一條不變式）。
fx_rf="$TMP5/resubmit-failure"; remote_rf="$TMP5/resubmit-failure.git"
make_ios_release_fixture "$fx_rf" "$remote_rf"
head_rf="$(git -C "$fx_rf" rev-parse HEAD)"
rf_rc=0
rf_out="$(STUB_UPLOAD_EXIT=23 bash "$fx_rf/ops/release.sh" resubmit ios --yes 2>&1)" || rf_rc=$?
[[ "$rf_rc" -ne 0 && -e "$fx_rf/upload.called" \
   && "$(git -C "$fx_rf" rev-parse HEAD)" == "$head_rf" \
   && -z "$(git -C "$fx_rf" tag -l 'ios/2.0.0+6')" \
   && -z "$(git --git-dir="$remote_rf" tag -l 'ios/2.0.0+6')" ]] \
  && ok "failed resubmit upload leaves no commit/tag/push" \
  || fail_t "failed resubmit left a false marker: $rf_out"

# 20d. api 拒絕，且指路。
ra_rc=0
ra_out="$(bash "$fx_r/ops/release.sh" resubmit api --yes 2>&1)" || ra_rc=$?
[[ "$ra_rc" -ne 0 ]] && echo "$ra_out" | grep -q 'ios' \
  && ok "resubmit api is rejected with guidance" || fail_t "resubmit api not rejected: $ra_out"

# 20e. 須在 main（與 release 同一條前提：發布的是本地主幹）。
git -C "$fx_r" checkout -q -b side
rb_rc=0
rb_out="$(bash "$fx_r/ops/release.sh" resubmit ios --yes 2>&1)" || rb_rc=$?
[[ "$rb_rc" -ne 0 ]] && echo "$rb_out" | grep -q 'main' \
  && ok "resubmit refuses off main" || fail_t "resubmit ran off main: $rb_out"
git -C "$fx_r" checkout -q main

# ── 21. status 說實話：ios 專案版號 / build tag 對照；api 是否真的上生產 ────
# 舊 status 對 ios 只印「上個 tag」與「檔內版本」，兩者都是 2.0.0 → 報「無漂移」，
# 而那顆 tag 其實指著沒上架的 build 5 的 commit。版號字串相等不代表 tag 指對地方。
section "status reports build-level truth, not just version strings"

make_status_fixture() {  # $1=fixture  $2=marketing  $3=build
  mkdir -p "$1/ops/lib" "$1/ios/BooksAndVocab.xcodeproj" "$1/backend/src/kg"
  cp "$REL" "$1/ops/"
  cp "$WORKSPACE/ops/lib/release_tags.sh" "$1/ops/lib/"
  cat > "$1/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<PBX
MARKETING_VERSION = $2; CURRENT_PROJECT_VERSION = $3;
MARKETING_VERSION = $2; CURRENT_PROJECT_VERSION = $3;
PBX
  printf '[project]\nversion = "2.0.1"\n' > "$1/backend/pyproject.toml"
  git init -q -b main "$1"
  git -C "$1" config user.name "Release Test"
  git -C "$1" config user.email "release-test@example.invalid"
  git -C "$1" add .
  git -C "$1" commit -qm "ios: fixture"
}

# 21a. 專案當下的 (version, build) 沒有 build tag → 具名警告。
#      這是「這顆 build 沒被記錄」的唯一徵兆；沉默的話它就會像 2.0.0 那樣事後才被發現。
fx_st="$TMP5/status-nobuildtag"
make_status_fixture "$fx_st" 2.0.0 6
git -C "$fx_st" tag ios/2.0.0
st_out="$(bash "$fx_st/ops/release.sh" status 2>&1)"
echo "$st_out" | grep -q 'MARKETING_VERSION=2.0.0' && echo "$st_out" | grep -q 'CURRENT_PROJECT_VERSION=6' \
  && ok "status prints the project's marketing version and build number" \
  || fail_t "status does not print (version, build): $st_out"
echo "$st_out" | grep -q 'ios/2.0.0+6' \
  && ok "status names the missing build tag for the current (version, build)" \
  || fail_t "status is silent about the unrecorded build: $st_out"

# 21b. build tag 存在 → 列出對照，且不再警告「沒有紀錄」。
fx_st2="$TMP5/status-buildtags"
make_status_fixture "$fx_st2" 2.0.0 6
sealed_st="$(git -C "$fx_st2" rev-parse HEAD)"
git -C "$fx_st2" tag ios/2.0.0
git -C "$fx_st2" tag "ios/2.0.0+5"
git -C "$fx_st2" tag "ios/2.0.0+6"
st2_out="$(bash "$fx_st2/ops/release.sh" status 2>&1)"
echo "$st2_out" | grep -q 'ios/2.0.0+5' && echo "$st2_out" | grep -q 'ios/2.0.0+6' \
  && ok "status lists the known build tags" || fail_t "status does not list build tags: $st2_out"
echo "$st2_out" | grep -q '沒有 build tag' \
  && fail_t "status warns about a missing build tag that actually exists: $st2_out" \
  || ok "status does not warn when the current build is recorded"

# 21c. api：latest api/<ver> tag 是否已是 origin/prod 的祖先（= 該版號是否真的上生產）。
fx_sp="$TMP5/status-prod"
make_status_fixture "$fx_sp" 2.0.0 6
git -C "$fx_sp" tag api/2.0.1
prod_base="$(git -C "$fx_sp" rev-parse HEAD)"
git -C "$fx_sp" update-ref refs/remotes/origin/prod "$prod_base"
sp_out="$(bash "$fx_sp/ops/release.sh" status 2>&1)"
echo "$sp_out" | grep -q 'api/2.0.1 已在 origin/prod' \
  && ok "status says the api tag is already on origin/prod" \
  || fail_t "status does not report api tag→prod ancestry: $sp_out"
# 反向：prod 落後於 tag 時必須改口，否則上面那條可能是恆真字串。
git -C "$fx_sp" commit -q --allow-empty -m "api: after prod"
git -C "$fx_sp" tag -d api/2.0.1 >/dev/null
git -C "$fx_sp" tag api/2.0.1
sp2_out="$(bash "$fx_sp/ops/release.sh" status 2>&1)"
echo "$sp2_out" | grep -q 'api/2.0.1 尚未進 origin/prod' \
  && ok "status flips to 尚未進 origin/prod when the tag is not deployed" \
  || fail_t "status reports prod ancestry as a constant: $sp2_out"

# ── 22. pending 版本的上界（review 找到） ───────────────────────────────────
section "pending-version bounds"

# 22b. 高於本次版本的 build tag 不是「被跳過的版本」。把它算進 pending，會用 2.0.1
#      事故的說詞去擋一件根本沒發生的事。
fx_ub="$TMP5/pending-upper"; remote_ub="$TMP5/pending-upper.git"
make_ios_release_fixture "$fx_ub" "$remote_ub"
git -C "$fx_ub" tag "ios/3.0.0+1"          # 另一條線的實驗性 build，與本次無關
ub_rc=0
ub_out="$(bash "$fx_ub/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || ub_rc=$?
[[ "$ub_rc" -eq 0 && -n "$(git -C "$fx_ub" tag -l 'ios/2.0.1+6')" ]] \
  && ok "a build tag above the requested version does not block the release" \
  || fail_t "3.0.0 build tag blocked an unrelated 2.0.1 release: $ub_out"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
