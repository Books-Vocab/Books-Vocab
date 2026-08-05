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
# 外部：MOCK_EXTERNAL_FAIL_FIRST=<n> 讓前 n 次外部 /api/system/info 直接失敗。
# 模擬的是**主機端對外連通性中斷**（2026-08-04 事故是 felix DNS 掛掉，同一秒 docker
# build 也在 auth.docker.io 上吐 no-such-host），不是 tunnel 重連——後者會回帶
# HTTP status 的 CF 錯誤頁，而事故拿到的是 exit 6 / HTTP=000（連回應都沒有）。
# 注意：本段在 **unquoted heredoc** 內，反引號會在寫檔當下被當成命令替換執行。
# 引用含反引號的日誌時一律改寫成純文字——這個坑今天已經咬過兩次（EXCLUDED_GROUPS
# 那次直接讓整支腳本 rc=141 一個字都沒印）。
# 已知**未**建模：時間。這裡計次不計時，且 harness 把 DELAY 釘成 0，所以綠燈只證明
# 「重試了 N 次」，不證明「等得夠久」——而後者才是這條修法真正想買的東西。
# 只挑外部主機名。用 *system/info* 比對的話 localhost 探針（KG_LOCAL_HEALTH_URL 也是
# .../api/system/info）會一起被擋掉並混進計數；現在沒炸只是因為上面 SERVED 分支先 exit。
if [[ -n "\${MOCK_EXTERNAL_FAIL_FIRST:-}" && "\$url" == *wordnexus.lol* && "\$url" == *system/info* ]]; then
  n=\$(cat "$dir/external_calls" 2>/dev/null || echo 0)
  n=\$((n+1)); echo "\$n" > "$dir/external_calls"
  if (( n <= MOCK_EXTERNAL_FAIL_FIRST )); then exit 6; fi
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
  SERVEDFILE="$SC/served.txt"     # 容器「實際 serving」版本（compose recreate 時更新為 VERSION 內容）
  IMAGECHANGED="$SC/image_changed"  # 存在 = 這次改動真的動到 image / 解析後 compose config
  RECREATELOG="$SC/recreate.log"    # 每次真的 recreate 記一行（與「版本變了」分開觀測）
  CONTAINER_DEAD="$SC/container_dead"  # 存在 = recreate 後容器起不來（用來測雙壞告警）
  LOCK="$SC/deploy.lock"
  mkdir -p "$BIN" "$SC/backups"

  "$REALGIT" init -q --bare "$ORIGIN"
  "$REALGIT" init -q "$REPO"
  "$REALGIT" -C "$REPO" config user.email t@t.test
  "$REALGIT" -C "$REPO" config user.name t
  mkdir -p "$REPO/backend/src" "$REPO/docs" "$REPO/ios"
  printf 'backend/VERSION\nbackups/\n' > "$REPO/.gitignore"
  echo "print(1)" > "$REPO/backend/src/app.py"
  # 命中 BACKEND_TRIGGER_RE 但**不進 image** 的檔案，用來造出 backend-noimage 情境
  printf 'services:\n  api:\n    build: .\n' > "$REPO/backend/docker-compose.yml"
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
      backend) echo "print(2)" >> "$REPO/backend/src/app.py"; : > "$IMAGECHANGED" ;;
      # 命中 trigger、但改的是不進 image 的檔案的註解：`docker compose config --hash`
      # 不變、Dockerfile 沒有 COPY 到它 → image digest 不變 → compose 不 recreate。
      # 這是 IMP-0056 實際踩到的形狀，**刻意不設 IMAGECHANGED**。
      backend-noimage) printf '# a comment; nothing here enters the image\n' >> "$REPO/backend/docker-compose.yml" ;;
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
  # compose stub: 記錄呼叫 + 依 **docker 真正的 recreate 語意** 決定容器要不要換版。
  #
  # 舊版無條件 `cp VERSION served`，也就是模型裡的 compose **永遠**會 recreate。那比
  # docker 聽話：`up -d --build` 只在 image digest 或**解析後**的 compose config hash
  # 變了才 recreate，`--force-recreate` 才是無條件。於是「compose 沒 recreate」這條
  # 路徑在測試裡根本不存在，而它正是 IMP-0056 的整個故事：健康 gate 比對容器自報版本
  # 與新 sha，沒 recreate 就永遠不相等 → 假失敗 → 回滾 + poison + 每小時重來。
  # 測試替身比真實依賴聽話，等於把待測的失效模式從世界上刪掉。
  #
  # recreate 另外記一個計數檔，不要只靠「served 版本變了」推斷：**一次不改變版本的
  # recreate 在後者眼裡完全隱形**，而停機成本正好落在那種 recreate 上（build 失敗後的
  # 回滾就是）。把「該不該重啟」與「重啟後是哪一版」拆成兩個可分別斷言的事實。
  # MOCK_COMPOSE_FAIL_NTH=<n> 讓第 n 次呼叫回非零，用來覆蓋 build 失敗分支。
  cat >"$BIN/compose_mock.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$COMPOSELOG"
calls=\$(( \$(wc -l < "$COMPOSELOG") ))
if [[ -n "\${MOCK_COMPOSE_FAIL_NTH:-}" && "\$calls" == "\$MOCK_COMPOSE_FAIL_NTH" ]]; then
  echo "compose: build failed (injected)" >&2
  exit 1
fi
if [[ "\$*" == *--force-recreate* || -f "$IMAGECHANGED" ]]; then
  echo x >> "$RECREATELOG"
  if [[ -f "$CONTAINER_DEAD" ]]; then
    : > "$SERVEDFILE"        # 容器重建後起不來 → 什麼版本都沒 serving
  else
    cp "$VERSIONFILE" "$SERVEDFILE" 2>/dev/null || true
  fi
fi
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

section "外部 smoke 前兩次連不上 → 重試後仍 deployed（不得假回滾）"
# IMP-0060，這是**生產實際發生過的事故**（2026-08-04 12:40Z）：容器 recreate 後
# localhost 探針重試 5 次撐過了啟動，但 external_smoke_ok 只打**一次**，那一次落在
# Cloudflare tunnel 還沒接回新 origin 的窗口內 → HTTP=000 → reason=smoke → 回滾。
# 兩個探針對同一件事（服務剛起來需要幾秒）有不同的耐心，而只有其中一個有重試。
# force-recreate 讓每次部署都會 recreate，於是這個原本偶發的失敗變成每次必中。
new_scratch backend
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|200|{"version":"$SHA_NEW"}
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
# harness 把 KG_RECON_HEALTH_ATTEMPTS 釘在 2（跑得快），所以注入 1 次失敗＝落在預算內。
out="$(MOCK_EXTERNAL_FAIL_FIRST=1 run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "deployed" ]] && ok "external flap: verdict deployed" || bad "external flap: expected deployed, got '$v' — 單次探針把 tunnel 重連當成部署失敗"
[[ "$rc" -eq 0 ]] && ok "external flap: exit 0" || bad "external flap: exit $rc"
grep -q "ROLLED_BACK" "$DEPLOYLOG" 2>/dev/null && bad "external flap: 假回滾了" || ok "external flap: 未回滾"
ext_calls="$(cat "$SC/external_calls" 2>/dev/null || echo 0)"
[[ "$ext_calls" -ge 2 ]] && ok "external flap: 真的重試了（$ext_calls 次）" || bad "external flap: 只打了 $ext_calls 次 — 沒有重試，上面的綠是別的原因"

section "外部 smoke 一直連不上 → 仍必須回滾（重試不得變成無條件放行）"
new_scratch backend
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|200|{"version":"$SHA_NEW"}
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
out="$(MOCK_EXTERNAL_FAIL_FIRST=99 run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "rolled-back" ]] && ok "external down: 仍回滾" || bad "external down: expected rolled-back, got '$v' — 重試把真失敗吃掉了"
grep -q "reason=smoke" "$DEPLOYLOG" && ok "external down: 理由記成 smoke" || bad "external down: deploy.log 沒記 reason=smoke"

section "backend change 但不動 image → 仍 deployed（不得假回滾）"
# IMP-0056：`backend/docker-compose.yml` 的純註解改動命中 BACKEND_TRIGGER_RE，但不進
# image、也不改變解析後的 config hash，所以 compose 不 recreate。健康 gate 比對容器
# 自報版本與新 sha，於是永遠不相等 → 回滾 + poison + 告警；poison 只冷卻 3600 秒，
# 冷卻完下一 tick 又看到 origin/prod 領先 → 再部署再失敗，**每小時自我重複**，
# 直到有人推一個真的會動 image 的 commit 為止。
new_scratch backend-noimage
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|200|{"version":"$SHA_NEW"}
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
out="$(run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "deployed" ]] && ok "no-image change: verdict deployed" || bad "no-image change: expected deployed, got '$v' — 這就是每小時重複的假回滾 (out=$out)"
[[ "$rc" -eq 0 ]] && ok "no-image change: exit 0" || bad "no-image change: exit $rc"
[[ -s "$DEPLOYLOG" ]] && ok "no-image change: 探針讀得到 deploy.log（正控）" || bad "no-image change: deploy.log 是空的 — 反向斷言無從區分「沒回滾」與「路徑打錯」"
grep -q "^poison " "$STATE" 2>/dev/null && bad "no-image change: poison 寫入了 — 冷卻後會再炸一次，這正是迴圈" || ok "no-image change: 未寫 poison"
grep -q "ROLLED_BACK" "$DEPLOYLOG" 2>/dev/null && bad "no-image change: deploy.log 記了 ROLLED_BACK" || ok "no-image change: 未回滾"
ver_now="$(cat "$VERSIONFILE")"
[[ "$ver_now" == "$SHA_NEW" ]] && ok "no-image change: VERSION == new sha" || bad "no-image change: VERSION=$ver_now != $SHA_NEW"
served_now="$(cat "$SERVEDFILE")"
[[ "$served_now" == "$SHA_NEW" ]] && ok "no-image change: 容器實際 serving 新 sha" || bad "no-image change: serving=$served_now != ${SHA_NEW}（容器沒被 recreate）"

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

section "不動 image 的改動 + smoke 失敗 → 回滾後容器要真的回到舊版"
# 部署路徑加了 --force-recreate 之後產生的**二階效應**：容器已經被動過，所以回滾若不也
# force，image 沒變 → 不 recreate → 容器仍自報 new_sha → 回滾後健康確認失敗 → 誤發
# 「生產可能雙壞，需立即人工檢查」這種最高級告警。IMP-0056 原本判定回滾路徑不該加旗標，
# 那個判斷在部署路徑加了之後就過期了。
new_scratch backend-noimage
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|500|internal error
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
# 告警走 stderr（kg_reconcile.sh:70），所以要接住 stderr 才看得到——原本這裡寫成
# `grep -q ... "$out"`，把一個**字串**當檔名餵給 grep，於是它永遠找不到檔案、永遠回
# 非零、`||` 那側永遠印 ✓。空斷言，而且就出現在專門在抓空斷言的這一輪裡。
ERRLOG="$SC/recon.err"
out="$(run_recon --once 2>"$ERRLOG")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "rolled-back" ]] && ok "no-image rollback: verdict rolled-back" || bad "no-image rollback: expected rolled-back, got '$v'"
[[ "$rc" -ne 0 ]] && ok "no-image rollback: exit non-zero ($rc)" || bad "no-image rollback: 回滾卻 exit 0"
served_now="$(cat "$SERVEDFILE")"
[[ "$served_now" == "$SHA_OLD" ]] && ok "no-image rollback: 容器實際回到舊版" || bad "no-image rollback: serving=$served_now != ${SHA_OLD}（回滾沒 recreate，會誤發雙壞告警）"
# 正控：先證明這個探針**看得到**告警，否則下面那條「沒有雙壞告警」跟「根本沒接到 stderr」
# 長得一模一樣。
grep -q "ALERT: 部署健康 gate 失敗" "$ERRLOG" && ok "no-image rollback: 探針讀得到告警（正控）" || bad "no-image rollback: 連預期中的 gate 失敗告警都沒讀到 — 探針壞了，不是行為對了"
grep -q "回滾後舊版" "$ERRLOG" && bad "no-image rollback: 誤發雙壞告警" || ok "no-image rollback: 未誤發雙壞告警"

section "每一個 compose 呼叫都必須 force-recreate（字面防護）"
# 行為斷言更強，但 IMP-0052 當年是靠**字面**斷言抓到的：`devops.sh` 掉了同一個旗標，
# 紅了 6.5 週。兩條部署路徑既然同語意，就配同形的防護。
# 用「所有呼叫點」而非「第 N 行」，新增第三個呼叫點會自動被涵蓋；dry-run 的預覽字串
# 也含 ${KG_COMPOSE}，所以這條同時釘住「預覽不得少報那個會造成停機的旗標」。
naked="$(grep -n '\$KG_COMPOSE up -d --build' "$RECON" | grep -vE '^[0-9]+:[[:space:]]*#' | grep -v -- '--force-recreate' || true)"
[[ -z "$naked" ]] && ok "所有 compose 呼叫與 dry-run 預覽都帶 --force-recreate" || bad "有 compose 呼叫沒帶 --force-recreate: $naked"
# 自測：探針要真的找得到呼叫點，否則上面是空迴圈式的全綠。
call_sites="$(grep -c '\$KG_COMPOSE up -d --build' "$RECON" || echo 0)"
[[ "$call_sites" -ge 3 ]] && ok "字面探針找到 $call_sites 處 compose 呼叫（deploy/rollback/dry-run）" || bad "字面探針只找到 $call_sites 處 — 探針壞了，不是程式對了"

section "build 失敗 → rolled-back，且回滾確實重建容器"
# 這條分支原本零覆蓋（compose stub 恆 exit 0），而它正是 rollback 旗標新成本的落點：
# build 失敗時部署路徑根本沒 recreate 過，回滾仍無條件重建一顆本來好好的容器。
# 這裡把那次重建**斷言出來**，成本就不是隱形的了。
new_scratch backend
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|200|{"version":"$SHA_OLD"}
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
out="$(MOCK_COMPOSE_FAIL_NTH=1 run_recon --once 2>/dev/null)"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "rolled-back" ]] && ok "build-fail: verdict rolled-back" || bad "build-fail: expected rolled-back, got '$v'"
grep -q "reason=build" "$DEPLOYLOG" && ok "build-fail: 理由記成 build" || bad "build-fail: deploy.log 沒記 reason=build"
recreates="$(wc -l < "$RECREATELOG" 2>/dev/null | tr -d ' ' || echo 0)"
[[ "$recreates" == "1" ]] && ok "build-fail: 僅回滾那次 recreate（部署那次 build 就死了）" || bad "build-fail: recreate x${recreates}（預期 1）"
served_now="$(cat "$SERVEDFILE")"
[[ "$served_now" == "$SHA_OLD" ]] && ok "build-fail: 容器停在舊版" || bad "build-fail: serving=$served_now != $SHA_OLD"

section "回滾自己的 compose 失敗 → 必須說「回滾未生效」，不得說「雙壞」"
# IMP-0060 的 C2，**生產實際發生過**：健康 gate 因主機 DNS 掛掉而假失敗 → 進回滾 →
# 回滾的 `--build` 也因為同一個 DNS 取不到 registry metadata 而失敗 → 退出碼被整個丟棄
# → git tree 與 VERSION 退回舊 sha，容器卻仍跑新版。接著舊版健康檢查當然不符，於是發出
# 「生產可能雙壞」——語意相反的誤導告警。真相是回滾根本沒發生。
#
# 兩個失效**相關而非獨立**：gate 最容易假失敗的時候，正是回滾最不可能成功的時候。
# 注意這個 seam（MOCK_COMPOSE_FAIL_NTH）**早就存在**，`=1` 測了部署 build 失敗，
# 只是從來沒有人寫 `=2`。不是替身不夠忠實，是買好的儀器沒去讀。
new_scratch backend
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|500|internal error
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
ERRLOG="$SC/recon.err"
out="$(MOCK_COMPOSE_FAIL_NTH=2 run_recon --once 2>"$ERRLOG")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "rolled-back" ]] && ok "rollback-build-fail: verdict rolled-back" || bad "rollback-build-fail: expected rolled-back, got '$v'"
grep -q "回滾的 compose 失敗" "$ERRLOG" && ok "rollback-build-fail: 明確告知回滾未生效" || bad "rollback-build-fail: 回滾 compose 的退出碼被吞掉了 — 這正是生產當天發生的事"
grep -q "生產可能雙壞" "$ERRLOG" && bad "rollback-build-fail: 仍發語意相反的『雙壞』告警" || ok "rollback-build-fail: 未發誤導的雙壞告警"
served_now="$(cat "$SERVEDFILE")"
[[ "$served_now" == "$SHA_NEW" ]] && ok "rollback-build-fail: 容器確實仍跑新版（與告警一致）" || bad "rollback-build-fail: serving=${served_now}，告警與事實不符"

section "回滾後容器起不來 → 必須發雙壞告警"
# 這是上一條反向斷言的**正控**：先前只斷言「沒有雙壞告警」，把那個告警字串改名一樣全綠
# （reviewer 實測），因為 ✓ 與「這字串根本永遠找不到」長得一樣。這裡讓它真的發生一次。
# 順帶關掉「force-recreate 新引入的風險完全沒測」這個洞。
new_scratch backend
: > "$CONTAINER_DEAD"        # recreate 後容器起不來
MOCK_CURL="$(make_mock_curl "$(cat <<EOF
wordnexus.lol/api/system/info|500|internal error
wordnexus.lol/api/health|401|{"detail":"x"}
EOF
)" "$SC" "$SERVEDFILE")"
ERRLOG="$SC/recon.err"
out="$(run_recon --once 2>"$ERRLOG")"; rc=$?
v="$(get_verdict "$out")"
[[ "$v" == "rolled-back" ]] && ok "double-fail: verdict rolled-back" || bad "double-fail: expected rolled-back, got '$v'"
grep -q "回滾後舊版" "$ERRLOG" && ok "double-fail: 雙壞告警確實發得出來（正控）" || bad "double-fail: 連舊版都不健康卻沒發最高級告警 — 那條反向斷言是空的"

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
