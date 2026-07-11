#!/usr/bin/env bash
# test_kg_reconcile.sh — offline TDD tests for ops/kg_reconcile.sh
#
# 覆蓋（對齊 ops/tests/ 既有 bash 測試風格）：
#   - paths_need_deploy 觸發正則（backend/src、pyproject、Dockerfile、static、
#     index.html → need；uv.lock、ios、docs、.env、data/ → NOT need）
#   - no-change → noop（git 不 pull、compose 不 build）
#   - non-backend change（docs）→ ff-only（compose 不 build、repo ff 到新 sha）
#   - backend change + smoke 全綠 → deployed（compose up、deploy.log 有新行、VERSION 更新）
#   - backend change + smoke 失敗 → rolled-back（git reset --hard ROLLBACK_SHA、
#     compose 第二次 up、poison 寫入、exit 非 0）
#   - poison 命中同 sha → poisoned-skip（compose 不 build）
#   - --dry-run + backend change → dry-run（compose/pull 完全不呼叫、VERSION/state/log 未變）
#   - lock 已被別人持有 → locked（exit 0、不 build）
#   - --help → exit 0 且含用法
#
# 策略：git 用「記錄呼叫 + 委派真 git」的 wrapper mock（同時拿到呼叫可見性與真實
# 狀態保真度）；compose/curl/infra_health 用 stub。每個 flow 跑在臨時 scratch repo
# （git init + 假 commit + 假 backend/VERSION），測完清乾淨。

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RECON="$ROOT/ops/kg_reconcile.sh"
REALGIT="$(command -v git)"

pass=0; fail=0
ok()      { echo "  ✓ $*"; pass=$((pass+1)); }
bad()     { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

SCRATCHES=()
cleanup() { [[ ${#SCRATCHES[@]} -gt 0 ]] && rm -rf "${SCRATCHES[@]}"; }
trap cleanup EXIT

get_verdict() { printf '%s' "$1" | sed -n 's/.*"verdict":"\([^"]*\)".*/\1/p' | head -1; }

# ── mock curl（fixture 驅動；沿用 test_deploy_smoke.sh 的解析法）─────────────
# fixture 每行：URL_SUBSTRING|HTTP_CODE|BODY_LITERAL
make_mock_curl() {
  local fixture_content="$1"
  local dir="$2"
  local served="${3:-}"          # 選填：容器「實際 serving」版本檔；localhost 動態回此值
  local fixture="$dir/curl_fixture_$RANDOM.txt"
  local script="$dir/mock_curl_$RANDOM.sh"
  printf '%s\n' "$fixture_content" > "$fixture"
  cat >"$script" <<MOCK
#!/usr/bin/env bash
SERVED="$served"
url=""
want_body_plus_http=0
want_http_only=0
next=""
for a in "\$@"; do
  if [[ "\$next" == "w" ]]; then
    if [[ "\$a" == *"%{http_code}" && "\$a" == *\$'\n'* ]]; then
      want_body_plus_http=1
    elif [[ "\$a" == "%{http_code}" ]]; then
      want_http_only=1
    fi
    next=""
  elif [[ "\$a" == "-w" ]]; then
    next="w"
  elif [[ "\$a" == http*://* ]]; then
    url="\$a"
  fi
done
# 動態 localhost：容器 serving 版本 = SERVED 檔內容（模擬 rebuild 後版本改變）。
# SERVED 空 → 該檔缺 → 容器視為 down（000/exit 6）。僅套用於 localhost；外部 URL 走 fixture。
if [[ -n "\$SERVED" && "\$url" == *localhost* ]]; then
  if [[ -s "\$SERVED" ]]; then
    sv="\$(head -1 "\$SERVED" | tr -d '[:space:]')"
    code=200; body="{\"version\":\"\$sv\"}"
    if [[ "\$want_body_plus_http" == "1" ]]; then printf '%s\n%s' "\$body" "\$code";
    elif [[ "\$want_http_only" == "1" ]]; then printf '%s' "\$code";
    else printf '%s' "\$body"; fi
    exit 0
  else
    exit 6
  fi
fi
match_line=""
while IFS= read -r line; do
  [[ -z "\$line" || "\$line" == \#* ]] && continue
  sub="\${line%%|*}"
  if [[ "\$url" == *"\$sub"* ]]; then match_line="\$line"; break; fi
done < "$fixture"
if [[ -z "\$match_line" ]]; then
  echo "mock_curl: no fixture match for url=\$url" >&2
  exit 7
fi
rest="\${match_line#*|}"
code="\${rest%%|*}"
body="\${rest#*|}"
if [[ "\$code" == "000" ]]; then exit 6; fi
if [[ "\$want_body_plus_http" == "1" ]]; then
  printf '%s\n%s' "\$body" "\$code"
elif [[ "\$want_http_only" == "1" ]]; then
  printf '%s' "\$code"
else
  printf '%s' "\$body"
fi
exit 0
MOCK
  chmod +x "$script"
  echo "$script"
}

# ── scratch repo + mocks ────────────────────────────────────────────────────
# kind ∈ backend | docs | none
new_scratch() {
  local kind="$1"
  SC="$(mktemp -d)"; SCRATCHES+=("$SC")
  ORIGIN="$SC/origin.git"; REPO="$SC/repo"; BIN="$SC/bin"
  GITLOG="$SC/git.log"; COMPOSELOG="$SC/compose.log"
  STATE="$SC/backups/reconciler.state"; DEPLOYLOG="$SC/backups/deploy.log"
  VERSIONFILE="$REPO/backend/VERSION"
  SERVEDFILE="$SC/served.txt"     # 容器「實際 serving」版本（compose rebuild 時更新為 VERSION 內容）
  LOCK="$SC/deploy.lock"
  mkdir -p "$BIN" "$SC/backups"

  "$REALGIT" init -q --bare "$ORIGIN"
  "$REALGIT" init -q "$REPO"
  "$REALGIT" -C "$REPO" config user.email t@t.test
  "$REALGIT" -C "$REPO" config user.name t
  mkdir -p "$REPO/backend/src" "$REPO/docs" "$REPO/ios"
  printf 'backend/VERSION\nbackups/\n' > "$REPO/.gitignore"
  echo "print(1)" > "$REPO/backend/src/app.py"
  echo "root" > "$REPO/README.md"
  "$REALGIT" -C "$REPO" add -A
  "$REALGIT" -C "$REPO" commit -qm base
  "$REALGIT" -C "$REPO" branch -M main
  "$REALGIT" -C "$REPO" remote add origin "$ORIGIN"
  "$REALGIT" -C "$REPO" push -qu origin main 2>/dev/null
  SHA_OLD="$("$REALGIT" -C "$REPO" rev-parse --short HEAD)"
  # seed origin/prod = origin/main and check out prod — REPO mimics ~/kg-prod, the
  # dedicated production clone the reconciler tracks (origin/prod, NOT origin/main).
  "$REALGIT" -C "$REPO" branch prod
  "$REALGIT" -C "$REPO" push -qu origin prod 2>/dev/null
  "$REALGIT" -C "$REPO" checkout -q prod

  if [[ "$kind" != "none" ]]; then
    case "$kind" in
      backend) echo "print(2)" >> "$REPO/backend/src/app.py" ;;
      docs)    echo "doc" >> "$REPO/docs/x.md" ;;
    esac
    "$REALGIT" -C "$REPO" add -A
    "$REALGIT" -C "$REPO" commit -qm change
    # the change lands on origin/prod (the release-plane ref); reconciler converges to it
    "$REALGIT" -C "$REPO" push -q origin prod 2>/dev/null
    SHA_NEW="$("$REALGIT" -C "$REPO" rev-parse --short HEAD)"
    "$REALGIT" -C "$REPO" reset --hard -q "$SHA_OLD"
  else
    SHA_NEW="$SHA_OLD"
  fi
  echo "$SHA_OLD" > "$VERSIONFILE"
  echo "$SHA_OLD" > "$SERVEDFILE"   # 容器起始 serving 舊版（與 VERSION 一致）

  # git wrapper mock: 記錄呼叫 + 委派真 git
  cat >"$BIN/git_mock.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GITLOG"
exec "$REALGIT" "\$@"
EOF
  # compose stub: 記錄呼叫 + 模擬 rebuild（容器改 serving 當前 VERSION 內容）+ 成功
  cat >"$BIN/compose_mock.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$COMPOSELOG"
cp "$VERSIONFILE" "$SERVEDFILE" 2>/dev/null || true
exit 0
EOF
  # infra_health stub: exit code 由 env 控制
  cat >"$BIN/infra_mock.sh" <<'EOF'
#!/usr/bin/env bash
exit "${MOCK_INFRA_EXIT:-0}"
EOF
  chmod +x "$BIN/git_mock.sh" "$BIN/compose_mock.sh" "$BIN/infra_mock.sh"
}

run_recon() {
  (
    export KG_RECON_REPO="$REPO"
    export KG_GIT="$BIN/git_mock.sh"
    export KG_COMPOSE="$BIN/compose_mock.sh"
    export CURL_BIN="$MOCK_CURL"
    export KG_INFRA_HEALTH="$BIN/infra_mock.sh"
    export KG_STATE_FILE="$STATE"
    export KG_DEPLOY_LOG="$DEPLOYLOG"
    export KG_PUBLIC_URL="https://wordnexus.lol"
    export KG_LOCAL_HEALTH_URL="http://localhost:8000/api/system/info"
    export KG_LOCK_DIR="$LOCK"
    export KG_GH_TOKEN_ENV="$SC/no-such-token.env"
    export KG_RECON_HEALTH_DELAY=0
    export KG_RECON_HEALTH_ATTEMPTS=2
    "$RECON" "$@"
  )
}

# ── paths_need_deploy 純函式 ────────────────────────────────────────────────
pnd_rc() { ( source "$RECON" >/dev/null 2>&1; set +e; printf '%s\n' "$1" | paths_need_deploy; echo "$?" ); }
need()   { local rc; rc="$(pnd_rc "$1")"; [[ "$rc" == "0" ]] && ok "need: $1" || bad "expected need(0) for $1, got '$rc'"; }
noneed() { local rc; rc="$(pnd_rc "$1")"; [[ "$rc" == "1" ]] && ok "no-need: $1" || bad "expected no-need(1) for $1, got '$rc'"; }

section "Syntax + executable + help"
bash -n "$RECON" && ok "kg_reconcile syntax" || bad "kg_reconcile syntax"
[[ -x "$RECON" ]] && ok "kg_reconcile executable" || bad "kg_reconcile not executable"
help_out="$("$RECON" --help 2>&1)"; help_rc=$?
[[ "$help_rc" -eq 0 ]] && ok "--help exit 0" || bad "--help exit $help_rc"
printf '%s' "$help_out" | grep -qi "reconcile" && ok "--help mentions reconcile" || bad "--help missing usage"

section "paths_need_deploy 觸發正則"
need   "backend/src/x.py"
need   "backend/pyproject.toml"
need   "backend/Dockerfile"
need   "backend/static/a.css"
need   "backend/index.html"
noneed "backend/uv.lock"
noneed "ios/x.swift"
noneed "docs/x.md"
noneed "backend/.env"
noneed "backend/data/x.db"

section "no-change → noop"
new_scratch none
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "noop" ]] && ok "verdict noop" || bad "expected noop, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "noop exit 0" || bad "noop exit $rc"
[[ ! -s "$COMPOSELOG" ]] && ok "noop: compose not called" || bad "noop: compose called ($(cat "$COMPOSELOG"))"
grep -q "pull" "$GITLOG" && bad "noop: git pull called" || ok "noop: git pull not called"

section "non-backend change (docs) → ff-only"
new_scratch docs
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "ff-only" ]] && ok "verdict ff-only" || bad "expected ff-only, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "ff-only exit 0" || bad "ff-only exit $rc"
[[ ! -s "$COMPOSELOG" ]] && ok "ff-only: compose not called" || bad "ff-only: compose called"
grep -q "pull --ff-only" "$GITLOG" && ok "ff-only: git pull --ff-only called" || bad "ff-only: pull not called"
head_now="$("$REALGIT" -C "$REPO" rev-parse --short HEAD)"
[[ "$head_now" == "$SHA_NEW" ]] && ok "ff-only: repo ff'd to origin sha" || bad "ff-only: HEAD=$head_now != $SHA_NEW"

section "backend change + smoke 全綠 → deployed"
new_scratch backend
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|200|{"version":"$SHA_NEW"}
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "deployed" ]] && ok "verdict deployed" || bad "expected deployed, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "deployed exit 0" || bad "deployed exit $rc"
compose_ups="$(grep -c 'up -d --build' "$COMPOSELOG" 2>/dev/null || echo 0)"
[[ "$compose_ups" -eq 1 ]] && ok "deployed: compose up --build once" || bad "deployed: compose up x$compose_ups"
grep -q "sha=$SHA_NEW user=reconciler" "$DEPLOYLOG" && ok "deployed: deploy.log line" || bad "deployed: deploy.log missing"
ver_now="$(cat "$VERSIONFILE")"
[[ "$ver_now" == "$SHA_NEW" ]] && ok "deployed: VERSION == new sha" || bad "deployed: VERSION=$ver_now != $SHA_NEW"

section "backend change + smoke 失敗 → rolled-back"
new_scratch backend
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|500|internal error
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "rolled-back" ]] && ok "verdict rolled-back" || bad "expected rolled-back, got '$v' (out=$out)"
[[ "$rc" -ne 0 ]] && ok "rolled-back exit non-zero ($rc)" || bad "rolled-back expected non-zero exit"
grep -q "reset --hard $SHA_OLD" "$GITLOG" && ok "rolled-back: git reset --hard ROLLBACK_SHA" || bad "rolled-back: reset missing"
compose_ups="$(grep -c 'up -d --build' "$COMPOSELOG" 2>/dev/null || echo 0)"
[[ "$compose_ups" -eq 2 ]] && ok "rolled-back: compose up twice (deploy+rollback)" || bad "rolled-back: compose up x$compose_ups"
grep -q "^poison $SHA_NEW " "$STATE" && ok "rolled-back: poison written for new sha" || bad "rolled-back: poison missing"
grep -q "ROLLED_BACK from=$SHA_NEW to=$SHA_OLD reason=smoke" "$DEPLOYLOG" && ok "rolled-back: deploy.log ROLLED_BACK" || bad "rolled-back: deploy.log ROLLED_BACK missing"
ver_now="$(cat "$VERSIONFILE")"
[[ "$ver_now" == "$SHA_OLD" ]] && ok "rolled-back: VERSION back to old sha" || bad "rolled-back: VERSION=$ver_now != $SHA_OLD"

section "poison 命中同 sha → poisoned-skip"
new_scratch backend
printf 'poison %s %s\n' "$SHA_NEW" "$(date +%s)" > "$STATE"
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "poisoned-skip" ]] && ok "verdict poisoned-skip" || bad "expected poisoned-skip, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "poisoned-skip exit 0" || bad "poisoned-skip exit $rc"
[[ ! -s "$COMPOSELOG" ]] && ok "poisoned-skip: compose not called" || bad "poisoned-skip: compose called"

section "--dry-run + backend change → dry-run（無 mutation）"
new_scratch backend
pre_ver="$(cat "$VERSIONFILE")"
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once --dry-run 2>"$SC/dryerr.txt")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "dry-run" ]] && ok "verdict dry-run" || bad "expected dry-run, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "dry-run exit 0" || bad "dry-run exit $rc"
[[ ! -s "$COMPOSELOG" ]] && ok "dry-run: compose not called" || bad "dry-run: compose called"
grep -q "pull" "$GITLOG" && bad "dry-run: git pull called" || ok "dry-run: git pull not called"
[[ "$(cat "$VERSIONFILE")" == "$pre_ver" ]] && ok "dry-run: VERSION unchanged" || bad "dry-run: VERSION mutated"
[[ ! -f "$STATE" ]] && ok "dry-run: state not written" || bad "dry-run: state written"
[[ ! -f "$DEPLOYLOG" ]] && ok "dry-run: deploy.log not written" || bad "dry-run: deploy.log written"
grep -qi "would" "$SC/dryerr.txt" && ok "dry-run: prints would-actions to stderr" || bad "dry-run: no would-actions"

section "lock 已被別人持有 → locked"
new_scratch backend
mkdir -p "$LOCK"
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "locked" ]] && ok "verdict locked" || bad "expected locked, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "locked exit 0" || bad "locked exit $rc"
[[ ! -s "$COMPOSELOG" ]] && ok "locked: compose not called" || bad "locked: compose called"
[[ -d "$LOCK" ]] && ok "locked: 未刪別人的鎖" || bad "locked: 誤刪他人鎖"

section "VERSION 缺失 + 容器 down → graceful noop（block 修復，不崩）"
new_scratch none
rm -f "$VERSIONFILE"
MOCK_CURL="$(make_mock_curl "" "$SC")"           # 無 served、無 fixture → localhost 視為 down
out="$(run_recon --once 2>"$SC/seed.err")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "noop" ]] && ok "missing-VERSION: verdict noop（非崩潰）" || bad "missing-VERSION: expected noop, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "missing-VERSION: exit 0" || bad "missing-VERSION: exit $rc"
[[ -n "$out" ]] && ok "missing-VERSION: stdout 有 verdict（輸出契約守住）" || bad "missing-VERSION: stdout 空（block 未修）"
grep -qi "seed VERSION" "$SC/seed.err" && ok "missing-VERSION: alert 指引 seed VERSION" || bad "missing-VERSION: 無 seed 指引"
[[ ! -s "$COMPOSELOG" ]] && ok "missing-VERSION: compose not called" || bad "missing-VERSION: compose called"

section "VERSION 缺失但容器健在 → 以 live 版重建游標（crash-consistency）"
new_scratch none
rm -f "$VERSIONFILE"
MOCK_CURL="$(make_mock_curl "" "$SC" "$SERVEDFILE")"   # served=SHA_OLD（容器健在自報舊版）
out="$(run_recon --once 2>"$SC/live.err")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "noop" ]] && ok "live-recover: verdict noop（recovered==origin）" || bad "live-recover: expected noop, got '$v' (out=$out)"
[[ "$rc" -eq 0 ]] && ok "live-recover: exit 0" || bad "live-recover: exit $rc"
[[ -f "$VERSIONFILE" && "$(cat "$VERSIONFILE")" == "$SHA_OLD" ]] && ok "live-recover: VERSION 游標由 live 重建==$SHA_OLD" || bad "live-recover: VERSION 未重建（=$(cat "$VERSIONFILE" 2>/dev/null))"
grep -qi "serving" "$SC/live.err" && ok "live-recover: alert 標明以實際版為準" || bad "live-recover: 無 live-mismatch alert"
[[ ! -s "$COMPOSELOG" ]] && ok "live-recover: compose not called（已同版）" || bad "live-recover: compose called"

section "crash-window：VERSION 宣稱 new 但容器 serving old → 自癒重部署"
new_scratch backend
echo "$SHA_NEW" > "$VERSIONFILE"       # 謊稱已部署 new（VERSION 於 health 確認前寫入後斷電）
# SERVED 仍 = SHA_OLD（容器實際 serving 舊，compose 未成功跑完）
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|200|{"version":"$SHA_NEW"}
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
out="$(run_recon --once 2>"$SC/crash.err")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "deployed" ]] && ok "crash-window: 自癒→verdict deployed" || bad "crash-window: expected deployed, got '$v' (out=$out)"
grep -qi "serving" "$SC/crash.err" && ok "crash-window: 偵測 VERSION 與 live 不一致" || bad "crash-window: 未偵測不一致"
[[ "$(cat "$VERSIONFILE")" == "$SHA_NEW" ]] && ok "crash-window: 重部署後 VERSION==$SHA_NEW" || bad "crash-window: VERSION=$(cat "$VERSIONFILE") != $SHA_NEW"
grep -q 'up -d --build' "$COMPOSELOG" && ok "crash-window: compose up 重建" || bad "crash-window: compose 未跑"

# ── 三平面解耦迴歸鎖：main 前進不觸發部署，reconciler 只看 origin/prod ──────────
section "prod 落後 main（main 有 backend 前進）→ noop 且從不看 main（解耦迴歸鎖）"
new_scratch none
# 讓 origin/main 超前 origin/prod 一個 backend commit；origin/prod 仍 == deployed。
# 舊模型（追 main）會在此部署；新模型（追 prod）必須 noop。
"$REALGIT" -C "$REPO" checkout -q main
echo "print(9)" >> "$REPO/backend/src/app.py"
"$REALGIT" -C "$REPO" add -A
"$REALGIT" -C "$REPO" commit -qm "main-only backend（不進 prod）"
"$REALGIT" -C "$REPO" push -q origin main 2>/dev/null
"$REALGIT" -C "$REPO" checkout -q prod
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "noop" ]] && ok "prod-behind-main: verdict noop（main 的 backend 不觸發部署）" || bad "prod-behind-main: expected noop, got '$v' (out=$out)"
[[ ! -s "$COMPOSELOG" ]] && ok "prod-behind-main: compose 未跑" || bad "prod-behind-main: compose 被觸發（$(cat "$COMPOSELOG")）"
if grep -qE "origin/main|origin main" "$GITLOG"; then
  bad "prod-behind-main: reconciler 竟碰 main（$(grep -E 'origin/main|origin main' "$GITLOG" | head -1)）"
else
  ok "prod-behind-main: git.log 從不出現 main（reconciler 只 fetch/diff prod）"
fi

section "prod 前進純非 backend → ff-only 但 VERSION 游標未變（釘不寫游標決策）"
new_scratch docs
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "ff-only" ]] && ok "ff-only-no-write: verdict ff-only" || bad "ff-only-no-write: expected ff-only, got '$v' (out=$out)"
[[ "$(cat "$VERSIONFILE")" == "$SHA_OLD" ]] && ok "ff-only-no-write: VERSION 游標未變（仍 ${SHA_OLD}）" || bad "ff-only-no-write: VERSION=$(cat "$VERSIONFILE") 被寫（§2.4 要求非 backend ff-only 不動游標）"

section "origin/prod 未 seed（首次啟用前）→ 非 dry-run 優雅 noop 不崩（守輸出契約）"
new_scratch none
# 模擬 origin/prod 尚未 seed：刪 origin 的 prod + 本地 tracking ref。fetch origin prod 會 fatal，
# 但容錯後應落到 rev-parse origin/prod→unknown→noop，而非 set -e 中止（回歸 IMPORTANT #1）。
"$REALGIT" -C "$ORIGIN" update-ref -d refs/heads/prod 2>/dev/null || true
"$REALGIT" -C "$REPO" update-ref -d refs/remotes/origin/prod 2>/dev/null || true
MOCK_CURL="$(make_mock_curl "" "$SC")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$rc" -eq 0 ]] && ok "unseeded-prod: exit 0（fetch fatal 已容錯，不崩）" || bad "unseeded-prod: exit ${rc}（fetch 未容錯 → set -e 中止）"
[[ "$v" == "noop" ]] && ok "unseeded-prod: verdict noop（優雅落 unknown handler）" || bad "unseeded-prod: expected noop, got '$v' (out=$out)"
[[ -n "$out" ]] && ok "unseeded-prod: 有 JSON verdict（輸出契約守住）" || bad "unseeded-prod: stdout 空（契約破）"
[[ ! -s "$COMPOSELOG" ]] && ok "unseeded-prod: compose 未跑" || bad "unseeded-prod: compose 被觸發"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
