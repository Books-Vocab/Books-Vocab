#!/bin/bash
# kg_reconcile.sh — release=deploy 自動 reconciler（felix-local，launchd 週期驅動）
# =============================================================================
# 一輪冪等 reconcile tick：讓 felix 生產容器 serving 的版本收斂到 origin/prod。
# 由 ops/launchd/com.kg.reconcile.plist 每 StartInterval 拉起跑一輪即退（非常駐
# while-loop）。它就在 felix 上跑 → git / docker / curl 全走本機，不走 SSH。
#
# 三平面模型：origin/prod = 「期望部署狀態」，只有 release 平面的 deploy 推進它
# （見 worktree_orchestrate.py deploy）；origin/main 已降為 backup 鏡像（sync 推），
# reconciler 不再看 main。故多數 tick 是 no-op（prod 只在刻意 release 時前進）。
# 生產 checkout 走專用 clone ~/kg-prod（launchd 以 KG_RECON_REPO 指定；腳本內預設
# 仍 ~/project/kg 讓人在 dev clone dry-run 最小驚訝）。
#
# 收斂目標 = felix 生產容器 == origin/prod：
#   - 變更含 backend 觸發路徑 → git pull + 寫 VERSION + docker compose up --build
#     --force-recreate（旗標不可省：健康 gate 比對容器自報版本，而容器自報的是 import
#     時快取的 bind-mount VERSION，只隨行程重啟改變；見 deploy 區塊註解與 IMP-0056）+
#     健康 gate（localhost + 外部 smoke + infra_health）；失敗自動 ROLLBACK 到部署前
#     的 sha 並把該 origin sha 標 poison（cooldown 內不重試）。
#   - 變更不含 backend → 只 git pull --ff-only（讓 felix repo HEAD 追上 origin/prod，含
#     自我更新本腳本），不 rebuild（容器仍舊 image，但無 backend 差異，正確）。
#   - 無差異 → no-op。
#
# 為何不 source devops.sh：它有頂層 case dispatch + `LOCAL_DIR=$(cd .../backend)`，
# source 時會執行/炸。故此處自足重實作那 ~15 行 git/compose/curl。
#
# ── 安全不變式（違反即 review 判 block）──────────────────────────────────────
#   * 絕不碰 ~/kg-data（唯一生產資料權威副本）。本腳本任何路徑都不對 ~/kg-data
#     做寫/刪/mv。git reset --hard 只作用 repo working tree；生產 data 已於
#     2026-06-16 搬出 git worktree（~/kg-data volume mount），物理隔離。
#   * 絕不 git clean、絕不 reset --hard 到未知 sha（只回滾到 DEPLOY 前捕捉好的
#     ROLLBACK_SHA）、絕不 docker compose down、絕不 system/volume prune、絕不 rm -rf。
#   * fetch/pull 一律 --ff-only 語意；origin 被 rewind（非 ff）→ 不 force，告警 exit
#     非 0 讓人介入。
#   * dry-run 物理上不呼叫任何會變更狀態的指令（在 mutating 動作前 gate）。
#
# 輸出契約：stdout 只印單行機讀 JSON verdict（schema kg.deploy.reconcile.v1）；
# 人類進度/診斷/告警一律走 stderr（對齊 devops.sh 慣例）。
#
# 可注入 seam（測試用，全部有預設值）：見下方 CONFIG 段。
# 單元測試：ops/tests/test_kg_reconcile.sh。
# =============================================================================
set -euo pipefail

# ── CONFIG / seams ──────────────────────────────────────────────────────────
KG_RECON_REPO="${KG_RECON_REPO:-$HOME/project/kg}"        # felix 上 kg repo 路徑
KG_GIT="${KG_GIT:-git}"                                    # git 執行檔（測試注入 mock）
KG_COMPOSE="${KG_COMPOSE:-docker compose}"                 # 測試注入 mock（可多 token）
CURL_BIN="${CURL_BIN:-curl}"
KG_INFRA_HEALTH="${KG_INFRA_HEALTH:-$KG_RECON_REPO/ops/infra_health.sh}"
KG_STATE_FILE="${KG_STATE_FILE:-$KG_RECON_REPO/backups/reconciler.state}"   # poison/cursor 私有游標
KG_DEPLOY_LOG="${KG_DEPLOY_LOG:-$KG_RECON_REPO/backups/deploy.log}"
KG_PUBLIC_URL="${KG_PUBLIC_URL:-https://wordnexus.lol}"
KG_LOCAL_HEALTH_URL="${KG_LOCAL_HEALTH_URL:-http://localhost:8000/api/system/info}"
KG_LOCK_DIR="${KG_LOCK_DIR:-/tmp/kg-deploy.lock}"          # 與 devops.sh acquire_deploy_lock 同一把鎖
KG_GH_TOKEN_ENV="${KG_GH_TOKEN_ENV:-$HOME/.secrets/gh-token.env}"           # GH_TOKEN（私有 repo fetch）
# 下面兩個 knob **兩個探針共用**（localhost 與 external）。刻意不分成兩組：多一組旋鈕
# 就多一個會漂的地方。但要知道兩者等的不是同一件事——
#   localhost：uvicorn 起來（實測 1.2s，秒級，與網路無關）
#   external ：felix 對外連通性（2026-08-04 事故是主機 DNS 掛掉，中斷長度由日誌
#              定界在 (0, ~90s]——下一個 90s tick 的 git fetch 才成功）
# **預算算法取決於失敗是快還是慢**：`--max-time 10` 只在「連得上但回應慢」時被吃滿；
# DNS `no such host` / connection refused 是**瞬間**返回，所以快失敗的總預算只有
# (attempts-1) × delay。delay 從 3 提到 5 就是為了這個：快失敗預算 12s → 20s。
# 誠實地說：**這仍蓋不住 ~90s 的 DNS 中斷**——但自 IMP-0061 起那不再是風險，只是延遲：
# 預算用盡後的結論從「回滾」改成「落地 + 記 smoke=unverified + 告警」（見 external_smoke_ok
# 的三分類）。所以這兩個 knob 現在買的是「多等一下也許就驗到了」，不是「賭中斷有多長」。
KG_RECON_HEALTH_ATTEMPTS="${KG_RECON_HEALTH_ATTEMPTS:-5}"  # 兩個健康探針的輪詢次數
KG_RECON_HEALTH_DELAY="${KG_RECON_HEALTH_DELAY:-5}"        # 每次間隔秒（見上方預算算法）
KG_RECON_POISON_COOLDOWN="${KG_RECON_POISON_COOLDOWN:-3600}"  # poison 冷卻秒（過後允許重試同 sha）
KG_RECON_DRY_RUN="${KG_RECON_DRY_RUN:-0}"

# backend 觸發正則（錨定 backend/）——命中才 rebuild image。
# 刻意排除 backend/uv.lock：Dockerfile 走 `pip install .` 只讀 pyproject.toml、不消費
# uv.lock，故「只改 uv.lock」不改 image；真正 dep 變更一定同時動 pyproject.toml（會觸發）。
# 亦刻意排除（皆不進 image）：backend/.env*、backend/VERSION、backend/data/**、
# backend/certs/**、backend/scripts/**、backend/docs/**、ios/**、lab/**、docs/**、
# ops/**、design-system/**。
BACKEND_TRIGGER_RE='^backend/(src/|tests/|static/|pyproject\.toml|pytest\.ini|Dockerfile|docker-compose\.yml|ops_(cli|analyze|edit)\.py|(index|privacy|support|terms|guide)\.html$)'

# ── 小工具 ──────────────────────────────────────────────────────────────────
log()     { printf '%s\n' "$*" >&2; }                                  # 人讀進度 → stderr
alert()   { printf 'ALERT: %s\n' "$*" >&2; }                           # 告警 → stderr（launchd err log 會收）
iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
extract_version() { printf '%s' "$1" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1; }

usage() {
  cat <<'USAGE'
kg_reconcile.sh — push=deploy 自動 reconciler（一輪冪等 tick）

用法：
  kg_reconcile.sh [--once] [--dry-run] [--help]

  --once      跑一輪就退（預設行為，供 launchd 語意清晰）
  --dry-run   印出「會做什麼」但絕不 pull/build/reset/寫任何檔（env KG_RECON_DRY_RUN=1 亦可）
  --help      本說明

語意：讓 felix 生產容器 serving 的版本收斂到 origin/prod。變更含 backend 觸發路徑才
rebuild（否則只 ff-only 追 repo）。部署失敗自動 rollback 到部署前 sha 並 poison 該 sha。
stdout 印單行 JSON verdict（schema kg.deploy.reconcile.v1）；診斷走 stderr。
USAGE
}

# ── 純可測 decider：paths_need_deploy ───────────────────────────────────────
# stdin = newline-separated changed-path 清單；任一行命中 backend 觸發正則 → exit 0
# （need deploy），否則 exit 1。抽成獨立 function 供單測直接呼叫。
paths_need_deploy() {
  local input
  input="$(cat)"
  grep -Eq "$BACKEND_TRIGGER_RE" <<<"$input"
}

# ── poison 游標（單行 latest poison：`poison <sha> <epoch>`）──────────────────
is_poisoned() {
  local sha="$1"
  [[ -f "$KG_STATE_FILE" ]] || return 1
  local line ts now cooldown
  line="$(grep "^poison $sha " "$KG_STATE_FILE" 2>/dev/null | tail -1 || true)"
  [[ -n "$line" ]] || return 1
  ts="$(printf '%s\n' "$line" | awk '{print $3}')"
  [[ -n "$ts" ]] || return 1
  now="$(date +%s)"
  cooldown="$KG_RECON_POISON_COOLDOWN"
  if (( now - ts < cooldown )); then
    return 0   # 仍在冷卻窗內 → poisoned
  fi
  return 1     # cooldown 過 → 允許重試
}

write_poison() {
  local sha="$1" tmp
  mkdir -p "$(dirname "$KG_STATE_FILE")"
  tmp="$(mktemp)"
  { grep -v "^poison $sha " "$KG_STATE_FILE" 2>/dev/null || true; printf 'poison %s %s\n' "$sha" "$(date +%s)"; } > "$tmp"
  mv "$tmp" "$KG_STATE_FILE"
}

# 心跳游標（單行 `tick <epoch>`）。量的是「reconciler 這一輪真的跑起來了」，與有沒有
# 部署無關，故所有 verdict（noop / ff-only / deployed / poisoned-skip / locked）都寫。
# 與 poison 共用同一個 state 檔但前綴不同：既有讀寫者一律錨 `^poison `，不會誤配。
# **刻意記錄一個已知的不變式破口**：這是本檔唯一不在 /tmp/kg-deploy.lock 之下的
# state 讀-改-寫（write_poison / clear_poison 都只在鎖內跑）。兩個重疊的實例理論上
# 能讓 B 的 tick mv 蓋掉 A 剛寫的 poison。launchd 對同 label 的 job 會序列化、
# devops.sh 也從不碰這個檔，故實務上不可達；寫在這裡是為了讓它是**刻意的**而不是
# 意外的——若哪天心跳改由別的排程器驅動，這條就得移進鎖內。
write_tick() {
  local tmp
  mkdir -p "$(dirname "$KG_STATE_FILE")"
  tmp="$(mktemp)"
  { grep -v "^tick " "$KG_STATE_FILE" 2>/dev/null || true; printf 'tick %s\n' "$(date +%s)"; } > "$tmp"
  mv "$tmp" "$KG_STATE_FILE"
}

clear_poison() {
  local sha="$1" tmp
  [[ -f "$KG_STATE_FILE" ]] || return 0
  tmp="$(mktemp)"
  grep -v "^poison $sha " "$KG_STATE_FILE" 2>/dev/null > "$tmp" || true
  mv "$tmp" "$KG_STATE_FILE"
}

append_deploy_log() {
  mkdir -p "$(dirname "$KG_DEPLOY_LOG")"
  printf '%s %s\n' "$(iso_now)" "$*" >> "$KG_DEPLOY_LOG"
}

# ── 健康探針 ────────────────────────────────────────────────────────────────
# localhost：最多 N 次 × delay 秒，等 200 且 body version == 期望 sha
localhost_health_ok() {
  local want="$1" attempts="$KG_RECON_HEALTH_ATTEMPTS" delay="$KG_RECON_HEALTH_DELAY"
  local i body code ver
  for (( i=1; i<=attempts; i++ )); do
    body="$("$CURL_BIN" -sS -o - -w $'\n%{http_code}' --max-time 10 "$KG_LOCAL_HEALTH_URL" 2>/dev/null || true)"
    code="$(printf '%s\n' "$body" | tail -n1)"
    body="$(printf '%s\n' "$body" | sed '$d')"
    if [[ "$code" == "200" ]]; then
      ver="$(extract_version "$body")"
      if [[ "$ver" == "$want" ]]; then return 0; fi
    fi
    log "  localhost health attempt $i/$attempts: code=${code:-none} ver=${ver:-} (want $want)"
    if (( i < attempts )); then sleep "$delay"; fi
  done
  return 1
}

# 外部 smoke 快子集（CF→tunnel→felix 全鏈）：
#   /api/system/info 200 且 version==期望 sha；/api/health 401/403/200(存在即可)、
#   404 跳過、000/500/其他判紅。
#
# **重試不是可選的**（IMP-0060，2026-08-04 生產實際事故）：這個探針原本只打一次，
# 而同一個 gate 裡的 localhost 探針重試 5 次。單次那一發失敗 → reason=smoke → 回滾
# 一個其實健康的部署（deploy.log 12:40:53Z）。
#
# **根因是 felix 主機端對外連通性（DNS）掛掉，不是 Cloudflare tunnel 在重連。**
# 第一版註解寫成 tunnel 重連，被 review 用日誌否證，四項證據：
#   ① 同一秒 docker build 也死在 `lookup auth.docker.io: no such host`——一個與
#      tunnel、與本容器都無關的公網主機名。
#   ② 拿到的是 `HTTP=000` 而不是 502/530/1033：tunnel 斷線時 Cloudflare edge 會回
#      **帶 HTTP status 的**錯誤頁；000 表示 curl 根本沒拿到 HTTP 回應。
#   ③ 容器 started_at=12:40:36、rollback compose 時間戳 12:40:39，中間還塞了一次
#      localhost sleep——external 那一發只能是**瞬間**返回，不可能吃滿 --max-time 10。
#   ④ 容器自始至終沒重啟過（uptime 連續），所以 tunnel 從來不需要「接回新 origin」。
# 這個差別會改變修法尺寸，所以值得寫清楚：見上方 knob 段的快/慢失敗預算算法。
#
# **重試緩解但蓋不住該事故**：日誌把中斷長度定界在 (0, ~90s]（下一個 90s tick 的 git
# fetch 才成功），而快失敗的預算只有 (attempts-1)×delay = 20s。所以 IMP-0061 的解不是
# 把預算加大（那是拿參數賭中斷長度），而是**把兩個問題分開判**：
#
#   「我這台量不到」 ≠ 「這次部署壞了」
#
# 判準寫成不依賴故障種類的形式：**回滾只有在證據指控被部署的那份 code 時才正當**。
# 走到這個函式時 localhost_health_ok 已經證明新 sha 確實起來了、正在 serving，所以
#   - 拿到 HTTP 回應（200/500/502/530/1033，CF 錯誤頁也算）→ 是關於服務鏈的證據 → `bad`
#   - **一個 HTTP 回應都沒拿到** → 什麼都沒證明，只證明這台機器連不出去 → `unreachable`
# 刻意只問「到底有沒有拿到回應」，不問是幾號——所以不需要那份「CF tunnel 各種故障回
# 什麼 code」的對照表（那份表現在沒人有，而這個設計繞開了對它的依賴）。
#
# 分類結果放 EXTERNAL_SMOKE_CLASS 給 run_health_gate 用；unreachable 不回滾，理由見那裡。
external_smoke_ok() {
  local want="$1" base="$KG_PUBLIC_URL"
  local attempts="$KG_RECON_HEALTH_ATTEMPTS" delay="$KG_RECON_HEALTH_DELAY"
  local i body code ver hcode
  # 「這一輪到底有沒有拿到過任何 HTTP 回應」的見證，是上述三分類的整個支點。
  local saw_response=0
  EXTERNAL_SMOKE_CLASS="unreachable"
  for (( i=1; i<=attempts; i++ )); do
    body="$("$CURL_BIN" -sS -o - -w $'\n%{http_code}' --max-time 10 "$base/api/system/info" 2>/dev/null || true)"
    code="$(printf '%s\n' "$body" | tail -n1)"
    body="$(printf '%s\n' "$body" | sed '$d')"
    # 空字串與 "000" **都**算「沒拿到回應」，兩個都要認：
    #   真 curl 連不出去時會**把 000 印在 stdout** 再 exit 6（2026-08-06 對無法解析的
    #   主機名實測：stdout=[\n000]、rc=6），所以這裡拿到的是字串 "000"；
    #   而 `|| true` 吞掉失敗、或替身靜默退出時，拿到的是空字串。
    # 只認其中一種的實作會在測試裡全綠、在生產照樣誤判——這是這條修法最容易被做假的
    # 地方，故測試對兩種 shape 各跑一次（見 test_kg_reconcile.sh 的 host-outage 段）。
    if [[ -n "$code" && "$code" != "000" ]]; then saw_response=1; fi
    if [[ "$code" != "200" ]]; then
      log "  external attempt $i/$attempts: /api/system/info HTTP=${code:-none} (expect 200)"
    else
      ver="$(extract_version "$body")"
      if [[ "$ver" != "$want" ]]; then
        log "  external attempt $i/$attempts: version=${ver:-} != $want"
      else
        # `|| true` + 補預設，不用 `|| echo 000`：後者在真 curl 失敗時會把 curl 自己印的
        # "000" 與 echo 的 "000" **接起來**變成 "000000"（實測），讓日誌印出無意義的
        # HTTP=000000。同款 bug 亦存在於 ops/infra_health.sh:120，那支還會把 "000000"
        # 寫進 --json 的機讀 value（IMP-0061 review D4；不在本檔 scope，已另記）。
        hcode="$("$CURL_BIN" -sS -o /dev/null -w '%{http_code}' --max-time 10 "$base/api/health" 2>/dev/null || true)"
        [[ -n "$hcode" ]] || hcode="000"
        # 這裡刻意**沒有**「hcode != 000 → saw_response=1」：能走到這支探針的唯一條件是
        # 上面 code=="200"，而迴圈開頭那行早已因此把 saw_response 設為 1。那個守衛點不燃，
        # 留著只會讓人誤以為 /api/health 也是見證來源之一（IMP-0061 review D3）。
        case "$hcode" in
          200|401|403) EXTERNAL_SMOKE_CLASS="ok"; return 0 ;;                          # 存在 → ok
          404) log "  external /api/health 404 → 跳過（非失敗）"; EXTERNAL_SMOKE_CLASS="ok"; return 0 ;;
          *)   log "  external attempt $i/$attempts: /api/health HTTP=$hcode" ;;   # 000/500/其他 → 再試
        esac
      fi
    fi
    if (( i < attempts )); then sleep "$delay"; fi
  done
  # 刻意保留的後果：system/info 拿到 200、但每次 /api/health 都是 000 → saw_response=1
  # → `bad` → 照樣回滾。正確：這台機器**demonstrably 有對外連通性**（200 就是證據），
  # 所以打不通的 /api/health 是真證據。別為了對稱把這裡「簡化」掉。
  if (( saw_response == 1 )); then EXTERNAL_SMOKE_CLASS="bad"; fi
  return 1
}

# 三段健康 gate；失敗設 HEALTH_FAIL_REASON=<health|smoke|infra> 並 return 1
#
# ⚠ 這三個都**必須宣告在頂層**（不是塞進 function 裡）：`set -u` 開著，而 emit_verdict
# 會從 noop / ff-only / locked / dry-run 這些**根本沒進過 gate** 的路徑被呼叫；未宣告的
# 變數在那裡會 unbound → 腳本當場死掉、連 JSON verdict 都來不及印，違反輸出契約。
# 這個失效模式已經咬過本檔一次，見下方回滾告警處 `${VAR}` 大括號那段註解。
HEALTH_FAIL_REASON=""
EXTERNAL_SMOKE_CLASS=""      # ok | unreachable | bad（由 external_smoke_ok 設）
SMOKE_STATE="n/a"            # 進 verdict 與 deploy.log：n/a | ok | unverified | bad

# 從 infra_health --json 抽出 status=="crit" 的 metric key（每行一個）。
# 只用 tr/sed：本腳本的 zero-dependency 契約是 bash/git/curl，不得為了解析 JSON 引入
# jq/python。infra_health 的一筆 metric = 一個 {...}，且 key 恆在 status 之前
# （ops/infra_health.sh:219 的 printf 順序），故先按 '{' 切行再逐行抽。
infra_crit_keys() {
  printf '%s' "$1" | tr '{' '\n' \
    | sed -n 's/.*"key":"\([^"]*\)".*"status":"crit".*/\1/p'
}

# infra_health 的 CRIT 是否**完全可歸因於同一場斷網**——即它只是「這台機器連不出去」
# 的第二個症狀，而不是關於這次部署或這台機器的新證據。
#
# 為什麼需要這個判斷：external_smoke_ok 放行 unreachable 之後，infra_health 會用**同一個
# 外部 URL** 再問一次同一個問題（ops/infra_health.sh:40 PROBE_URL、:197 非 200 一律 crit、
# :238 crit→exit 2）。只看它的 exit code，主機端斷網就會原封不動地變成 reason=infra +
# 回滾 + poison——理由換了個字，行為與修法前一模一樣，而且同一輪 tick 會先發「故不回滾」
# 再發「回滾」兩則互相矛盾的 ALERT（IMP-0061 review D1 實測）。
#
# 兩個條件都成立才算同一場斷網：
#   ① 本輪外部 smoke 已**獨立且重試到預算用盡**地證明拿不到任何 HTTP 回應（unreachable）；
#   ② infra_health 唯一越線的指標就是它自己那支對外 HTTPS 探針（key=http_probe），
#      而呼叫端把 KG_HEALTH_PROBE_URL 釘成 smoke 剛探過的同一個 URL，所以「同一個問題被
#      問了兩次」是結構上為真，不是靠兩邊預設值碰巧相同。
# 其餘任何 crit（容器不見了/磁碟爆了/記憶體/tunnel 掛了/憑證過期/host 指標收不到…）都是
# 關於這台機器或這個服務的真證據 → 照舊擋下並回滾。**斷網不是 infra 這一關的免死金牌**，
# 否則就是用一個更大的洞蓋掉小洞。
# 抽不出任何 crit key（JSON 壞掉/版本不合/被替換）→ 無法歸因就不放行（fail-closed）：
# 「看不懂」絕不等於「沒問題」。
infra_crit_is_same_outage() {
  local crit_keys
  [[ "$EXTERNAL_SMOKE_CLASS" == "unreachable" ]] || return 1
  crit_keys="$(infra_crit_keys "$1")"
  # 恰好一個且就是它：多筆會帶換行，字串比對自然不等；空字串（讀不懂）也不等。
  [[ "$crit_keys" == "http_probe" ]] || return 1
  return 0
}

run_health_gate() {
  local new="$1"
  if ! localhost_health_ok "$new"; then HEALTH_FAIL_REASON="health"; return 1; fi
  # 外部 smoke 三分類。注意這裡**只有 `bad` 會擋**——
  # `unreachable` 不回滾的理由不是「寬容」，是「回滾在此刻既無正當性也不可靠」：
  #   ① 無正當性：localhost 剛剛才證明 ${new} healthy 在跑，沒有任何證據指控這份 code；
  #   ② 不可靠：回滾要跑 `--build`，而 2026-08-04 事故裡它正是被同一個 DNS 故障弄死的
  #      （IMP-0060 C2）。兩個失效是**相關的**——gate 最容易假失敗的時候，正是回滾最
  #      不可能成功的時候。對相關失效做自動補償，只會把一個問題變成兩個。
  # 放行後 gate 退化成 localhost + infra_health。**注意 infra_health 並不純本機**：它自己
  # 也會從這台機器打同一個外部 URL，非 200 一律 crit（見下方 infra 段與 infra_crit_is_same_outage）。
  # 第一版註解寫成「兩者純本機、免疫於同一場斷網」是錯的，而且錯得剛好讓 D1 看不見。
  if external_smoke_ok "$new"; then
    SMOKE_STATE="ok"
  elif [[ "$EXTERNAL_SMOKE_CLASS" == "unreachable" ]]; then
    SMOKE_STATE="unverified"
    alert "外部 smoke 全程拿不到任何 HTTP 回應（是 felix 對外連通性中斷，不是服務回 5xx）。localhost 已證明 ${new} 健康在跑，故**不回滾**；請從第二個地點確認 ${KG_PUBLIC_URL} 是否可達。本次已記 smoke=unverified。"
  else
    SMOKE_STATE="bad"; HEALTH_FAIL_REASON="smoke"; return 1
  fi
  # infra_health：改吃 --json 並**看它為什麼 crit**，不是只看 exit code。理由與判準寫在
  # infra_crit_is_same_outage 上方。KG_HEALTH_PROBE_URL 在這裡釘死，讓「它探的就是 smoke
  # 剛探過的那個 URL」成為結構事實而非對預設值的假設（ops/infra_health.sh:40 讀這個 env）。
  local ih ih_json
  set +e
  # KG_HEALTH_DEPLOY_DRIFT=0：部署收斂是本腳本自己的職責，把自己的收斂狀態當成自己的
  # 健康條件會構成迴圈——release 推進 origin/prod 後、下一輪收斂完成前必然 drift，於是
  # 這一關會回滾一次本來健康的部署。故對自我 gate 關掉那組 metric（IMP-0022）。
  ih_json="$(KG_HEALTH_PROBE_URL="${KG_PUBLIC_URL}/api/system/info" KG_HEALTH_DEPLOY_DRIFT=0 "$KG_INFRA_HEALTH" --json 2>/dev/null)"
  ih=$?
  set -e
  case "$ih" in
    0) : ;;                                             # ok
    1) log "  infra_health WARN (exit 1) — 記警告仍 pass" ;;
    *)                                                  # 2=crit
      if infra_crit_is_same_outage "$ih_json"; then
        log "  infra_health CRIT (exit ${ih})，唯一越線的是它自己那支對外探針 http_probe"
        alert "infra_health 同樣 CRIT，但唯一越線的指標是它自己那支對外 HTTPS 探針（${KG_PUBLIC_URL}/api/system/info，與剛才的外部 smoke 同一個 URL、同一場斷網）；host 其餘指標正常，localhost 已證明 ${new} 健康在跑。故**同樣不回滾**，本次仍記 smoke=unverified。"
      else
        HEALTH_FAIL_REASON="infra"
        log "  infra_health CRIT (exit ${ih}) crit keys: $(infra_crit_keys "$ih_json" | tr '\n' ' ')"
        return 1
      fi
      ;;
  esac
  return 0
}

# live 容器自報版本（crash-consistency 交叉驗證用）：GET localhost /api/system/info 抽
# version；非 200 或抽不到 → 回空字串（呼叫端據此不覆蓋 VERSION 游標）。純 read-only。
reconcile_live_version() {
  local body code
  body="$("$CURL_BIN" -sS -o - -w $'\n%{http_code}' --max-time 5 "$KG_LOCAL_HEALTH_URL" 2>/dev/null || true)"
  code="$(printf '%s\n' "$body" | tail -n1)"
  body="$(printf '%s\n' "$body" | sed '$d')"
  [[ "$code" == "200" ]] || return 0
  extract_version "$body"
}

# ── verdict 輸出（stdout 唯一機讀 payload）───────────────────────────────────
DEPLOYED_SHA="unknown"
ORIGIN_SHA="unknown"
BACKEND_CHANGED="false"
emit_verdict() {
  printf '{"schema":"kg.deploy.reconcile.v1","verdict":"%s","deployed_sha":"%s","origin_sha":"%s","backend_changed":%s,"smoke":"%s","ts":"%s"}\n' \
    "$1" "$DEPLOYED_SHA" "$ORIGIN_SHA" "$BACKEND_CHANGED" "$SMOKE_STATE" "$(iso_now)"
}

# ── git 封裝（一律 -C repo；fetch 可注入 GH_TOKEN credential helper，不改 remote URL）
git_fetch() {
  if [[ -n "${GH_TOKEN:-}" ]]; then
    "$KG_GIT" -C "$KG_RECON_REPO" \
      -c "credential.https://github.com.username=x-access-token" \
      -c "credential.helper=!f() { echo \"password=${GH_TOKEN}\"; }; f" \
      fetch origin prod >&2
  else
    "$KG_GIT" -C "$KG_RECON_REPO" fetch origin prod >&2
  fi
}

# ── DEPLOY 路徑（已持鎖；含失敗自動 ROLLBACK）────────────────────────────────
deploy_and_gate() {
  local rollback_sha="$1"    # DEPLOY 前捕捉的回滾錨點（= deployed_sha，已驗可解析）

  # 1) ff-only pull（origin/prod rewind 則不 force，告警 exit）
  if ! "$KG_GIT" -C "$KG_RECON_REPO" pull --ff-only origin prod >&2; then
    alert "git pull --ff-only origin prod 失敗（origin/prod 被 rewind 或非 ff）。不 force，需人工介入。"
    exit 3
  fi
  local new_sha
  new_sha="$("$KG_GIT" -C "$KG_RECON_REPO" rev-parse --short HEAD)"
  printf '%s\n' "$new_sha" > "$KG_RECON_REPO/backend/VERSION"
  log "→ DEPLOY: $rollback_sha → ${new_sha}，重建容器…"

  # 2) 重建並啟動（compose 失敗視為部署失敗 → rollback，不讓 set -e 直接中斷）
  #
  # `--force-recreate` 讓下面健康 gate 的**前提為真**，而不是碰運氣。gate 比對容器自報
  # 版本與 ${new_sha}，但容器自報的是 bind-mount 進去的 backend/VERSION、且在 import 時
  # 就快取——所以那個值只隨**行程重啟**改變。而 `up -d --build` 只在 image digest 或
  # 解析後的 compose config hash 變了才 recreate：命中 BACKEND_TRIGGER_RE 卻不進 image
  # 的改動（compose.yml 的註解、Dockerfile 的註解、pyproject 的 [tool.*]）兩者皆不變，
  # 容器不重啟 → 自報舊版 → gate 判失敗 → 回滾 + poison + 告警。而 poison 只冷卻
  # 3600 秒，冷卻完下一 tick 又看到 origin/prod 領先，於是**每小時重演一次**（IMP-0056）。
  #
  # 代價很小且只落在原本會炸的那條路上：image 真的變了時 compose 本來就會 recreate，
  # 這個旗標是 no-op；只有「其實什麼都沒變」時才多付一次數秒重啟。手動 break-glass 路徑
  # `devops.sh cmd_deploy` 早已這樣做（IMP-0052），兩條部署路徑本來就該同語意。
  local crc
  set +e; ( cd "$KG_RECON_REPO/backend" && $KG_COMPOSE up -d --build --force-recreate ) >&2; crc=$?; set -e

  local ok=1
  if (( crc != 0 )); then
    HEALTH_FAIL_REASON="build"; ok=0
    log "  compose up --build 失敗 (exit $crc)"
  elif ! run_health_gate "$new_sha"; then
    ok=0
  fi

  if (( ok == 1 )); then
    # smoke=unverified 要留在**持久且可 grep 的**地方。stderr 的 ALERT 只是次要通知——
    # 沒有人保證有人在讀 launchd 的 err log，而這條落地是「已部署但外部沒驗過」，
    # 事後一定要查得到是哪一次。後綴形式，既有的 `sha=<x> user=reconciler` grep 不受影響。
    if [[ "$SMOKE_STATE" == "unverified" ]]; then
      append_deploy_log "sha=$new_sha user=reconciler smoke=unverified"
    else
      append_deploy_log "sha=$new_sha user=reconciler"
    fi
    clear_poison "$ORIGIN_SHA"   # 部署確實落地了，解除 poison
    log "✓ DEPLOY 成功：version=$new_sha"
    emit_verdict "deployed"
    exit 0
  fi

  # 3) ROLLBACK：只回滾到捕捉好的 ROLLBACK_SHA（絕不 clean、絕不到未知 sha）
  local reason="$HEALTH_FAIL_REASON"
  alert "部署健康 gate 失敗 (reason=$reason)，回滾 $new_sha → $rollback_sha"
  "$KG_GIT" -C "$KG_RECON_REPO" reset --hard "$rollback_sha" >&2
  printf '%s\n' "$rollback_sha" > "$KG_RECON_REPO/backend/VERSION"
  # 這裡也必須 force。理由要寫成**不依賴進入路徑**的形式：回滾的職責是讓 git tree、
  # VERSION 游標與跑著的容器三者一致，而唯一能無條件保證第三項的手段就是重建。
  #
  # （別把理由寫成「部署路徑剛剛 recreate 過所以容器已被動過」——進到這個區塊有兩條路，
  #  `crc != 0`（build 就失敗）那條**根本沒 recreate 過**，前提在該入口為假。代價是那條
  #  路現在會多付一次數秒重啟去重建一顆本來好好的容器；接受，因為改成有條件就等於重新
  #  引入「我能預測 compose 會不會 recreate」這個假設，而 IMP-0056 整件事就是它被證偽。）
  #
  # 不 force 的後果實測有兩個，第二個比第一個嚴重：
  #   ① 不進 image 的改動回滾時 image 一樣沒變 → 不 recreate → 容器仍自報 new_sha →
  #      下面的 localhost_health_ok "$rollback_sha" 失敗 → 誤發「生產可能雙壞」最高級告警。
  #   ② 下一 tick 的 crash-consistency 交叉驗證（見下方 live_ver 段）看到 live(new)
  #      != VERSION(old) 且 new 仍可解析 → **把游標寫回剛被回滾且被 poison 的那個 sha**，
  #      changed 變空 → noop 早退、poison 檢查走不到。deploy.log 記著 ROLLED_BACK、
  #      state 有 poison，游標卻宣告已收斂在該 sha 上——回滾在游標層被靜默撤銷。
  # 回滾這一次 compose 的退出碼**必須看**（IMP-0060 的 C2）。原本整個丟棄，而
  # 2026-08-04 事故當下它真的失敗了：`--build` 要向 registry 取 python:3.13-slim 的
  # metadata，而主機 DNS 正掛著（`lookup auth.docker.io: no such host`）。後果是
  # git tree 退回舊 sha、VERSION 寫成舊 sha、**容器仍跑著新版**——回滾根本沒發生。
  #
  # 兩個失效模式是**相關的不是獨立的**：健康 gate 最容易假失敗的時候（對外連通性壞），
  # 正是回滾的 `--build` 最不可能成功的時候。所以這裡不能假設回滾一定會成功。
  local rrc=0
  set +e; ( cd "$KG_RECON_REPO/backend" && $KG_COMPOSE up -d --build --force-recreate ) >&2; rrc=$?; set -e
  if (( rrc != 0 )); then
    # 講清楚操作者該做什麼：不是「兩版都壞」，是「git 退了但容器沒退」。
    # `${VAR}` 的大括號不是風格，是必要：`$rollback_sha，` 這種「變數緊接全形標點」
    # 會讓 bash 把標點的首個 byte 吃進變數名 → `unbound variable` → set -u 當場殺掉
    # 腳本，連 verdict 都來不及印。**發作條件是有 UTF-8 locale，不是沒有 LANG**——
    # 2026-08-08 實測同形 fixture：無 LANG/LC_ALL/LC_CTYPE → rc=0、LC_ALL=C → rc=0、
    # LC_ALL=C.UTF-8 / en_US.UTF-8 / LANG=en_US.UTF-8 → rc=1 unbound variable。
    # gate 的 subprocess runner 釘 LC_CTYPE=C.UTF-8（`ops/lib/streaming_command.py`），
    # 所以它死。**綠的條件是 LANG / LC_ALL / LC_CTYPE 三個都沒設**（agent 的 Bash tool
    # 就是這種）——只說「LC_CTYPE 未設」不夠：`LANG=en_US.UTF-8` 而 LC_CTYPE 未設
    # （macOS Terminal.app 預設）實測 rc=1，照樣死。本段先前寫反了，照舊敘述跑
    # `env -u LANG` 驗證會看到綠並誤判這行安全。
    alert "回滾的 compose 失敗 (exit ${rrc})：git tree 與 VERSION 已回到 ${rollback_sha}，但**容器很可能仍跑著 ${new_sha}**。回滾未生效，需人工確認容器實跑版本再決定前進或後退。"
  fi
  # 回滾後確認舊版健康（best-effort，不 gate verdict；連舊版都不健康則更大聲告警）
  if localhost_health_ok "$rollback_sha"; then
    log "  回滾後 localhost 健康確認：$rollback_sha OK"
  elif (( rrc != 0 )); then
    # 上面那條已經說明了原因，這裡不要再發一次語意相反的「雙壞」誤導告警。
    log "  回滾後 localhost 仍非 $rollback_sha —— 與上方 compose 失敗一致，不重複告警。"
  else
    alert "回滾後舊版 $rollback_sha localhost 健康未確認 — 生產可能雙壞，需立即人工檢查。"
  fi
  write_poison "$ORIGIN_SHA"
  append_deploy_log "ROLLED_BACK from=$new_sha to=$rollback_sha reason=$reason"
  emit_verdict "rolled-back"
  exit 1
}

# ── 主流程（一輪 tick）──────────────────────────────────────────────────────
main() {
  local dry_run="$KG_RECON_DRY_RUN"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --once)    shift ;;                 # 預設即一輪；接受以對齊 launchd
      --dry-run) dry_run=1; shift ;;
      --help|-h) usage; exit 0 ;;
      *) log "unknown arg: $1"; usage >&2; exit 2 ;;
    esac
  done
  [[ "$dry_run" == "1" ]] && log "[dry-run] 只預覽，不執行任何 mutation"

  # 心跳：放在 fetch 之前、且對所有 verdict 都寫——它量的是 liveness，不是部署。
  # `|| true` 不可省：檔案系統暫時寫不進去不該讓整輪 reconcile 在 set -e 下中止，
  # 缺一拍遠比停機好。dry-run 短路是護欄（測試斷言 dry-run 不得寫 state）。
  [[ "$dry_run" == "1" ]] || write_tick || true

  # 取 GH_TOKEN（私有 repo fetch）；dry-run 不 source（不寫/不改環境依賴仍讀值無妨，但
  # 保持一致：僅在需要 fetch 時才需要）。source 不算 mutation，安全。
  if [[ -f "$KG_GH_TOKEN_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$KG_GH_TOKEN_ENV" || true
  fi

  # 1) fetch（dry-run 不動 .git，改用現有 refs 預覽）
  #    容錯（不可省，set -e 下）：origin/prod 尚未 seed 時 `fetch origin prod` 會 fatal exit 128，
  #    若直接 git_fetch 會在下方 unknown→noop 優雅處理「之前」就中止 main（無 JSON verdict、
  #    launchd err log 噴、違反輸出契約）。故 fetch 失敗只告警不中止 → 落到 rev-parse origin/prod
  #    →unknown→noop 的既有優雅路徑（首次啟用 seed 前、或網路異常皆適用）。
  if [[ "$dry_run" == "1" ]]; then
    log "[dry-run] would: git fetch origin prod"
  else
    git_fetch || alert "fetch origin/prod 失敗（尚未 seed 或網路異常）——改用現有 tracking ref 判斷，缺則本輪 noop。"
  fi

  # 2) deployed_sha（容器版本真相）= backend/VERSION；origin_sha = origin/prod
  #    註：`|| true` 不可省——set -euo pipefail 下 VERSION 缺檔會令 cat exit 1，經 pipefail
  #    傳播使賦值觸 errexit，下一行 `|| unknown` fallback 反成死碼（首次啟用/VERSION 遺失即崩）。
  DEPLOYED_SHA="$(cat "$KG_RECON_REPO/backend/VERSION" 2>/dev/null | head -1 | tr -d '[:space:]' || true)"
  [[ -n "$DEPLOYED_SHA" ]] || DEPLOYED_SHA="unknown"
  ORIGIN_SHA="$("$KG_GIT" -C "$KG_RECON_REPO" rev-parse --short origin/prod 2>/dev/null || echo unknown)"

  if [[ "$ORIGIN_SHA" == "unknown" ]]; then
    alert "無法解析 origin/prod（fetch 失敗或 ref 缺失；首次啟用需 seed origin/prod），本輪 no-op。"
    emit_verdict "noop"; exit 0
  fi

  # 2b) crash-consistency 交叉驗證（非 dry-run；純觀測 read-only）——reconciler 信「實際狀態」
  #     而非游標：VERSION 是「宣稱」部署版，但 backend/VERSION 於 deploy 時 build/health 確認
  #     「之前」就寫入；felix 無 UPS，若該窗口斷電/被 kill，VERSION 會宣稱 new 但容器實際仍
  #     serving 舊 image。用 live 容器自報 version 為準：不一致（或 VERSION 缺失/不可解析）且
  #     live 版可解析為 commit → 以 live 版覆蓋 DEPLOYED_SHA 並修正 VERSION 游標對齊現實，
  #     從實際狀態重新收斂（自癒 crash-window drift；亦救 VERSION 遺失但容器健在）。
  if [[ "$dry_run" != "1" ]]; then
    local live_ver
    live_ver="$(reconcile_live_version)"
    if [[ -n "$live_ver" && "$live_ver" != "$DEPLOYED_SHA" ]] \
       && "$KG_GIT" -C "$KG_RECON_REPO" rev-parse --verify --quiet "${live_ver}^{commit}" >/dev/null 2>&1; then
      alert "VERSION 宣稱 deployed=$DEPLOYED_SHA 但容器實際 serving=${live_ver}（疑上次部署寫 VERSION 後未完成即中斷）。以實際版為準重新收斂並修正游標。"
      DEPLOYED_SHA="$live_ver"
      printf '%s\n' "$live_ver" > "$KG_RECON_REPO/backend/VERSION"
    fi
  fi

  # baseline 必須可解析才能算 diff；否則不做「驚訝的」rebuild，警告 + no-op，等人 seed VERSION。
  if ! "$KG_GIT" -C "$KG_RECON_REPO" rev-parse --verify --quiet "${DEPLOYED_SHA}^{commit}" >/dev/null 2>&1; then
    alert "backend/VERSION='$DEPLOYED_SHA' 無法解析為 commit（首次啟用需人工 seed VERSION）。本輪 no-op。"
    emit_verdict "noop"; exit 0
  fi

  # 3) 收斂判斷：deployed..origin/prod 的變更檔
  local changed
  changed="$("$KG_GIT" -C "$KG_RECON_REPO" diff --name-only "${DEPLOYED_SHA}..origin/prod" -- . 2>/dev/null || true)"

  if [[ -z "$changed" ]]; then
    log "已同版（deployed=$DEPLOYED_SHA == origin=${ORIGIN_SHA}），no-op。"
    emit_verdict "noop"; exit 0
  fi

  # 4) 是否含 backend 觸發路徑
  if printf '%s\n' "$changed" | paths_need_deploy; then
    BACKEND_CHANGED="true"
  else
    BACKEND_CHANGED="false"
  fi

  # 5) 不含 backend → 只 ff-only pull（追 origin/prod，含自我更新本腳本），不 rebuild
  #    ⚠ 刻意「不寫 VERSION」（勿順手修）：容器 /app/VERSION 是 bind-mount 即時反映 host，
  #    但 system.py 於 import 時已快取 version，非重啟不更新自報值。若此路徑寫 VERSION=new，
  #    下一 tick 的 crash-consistency 交叉驗證會看到 live(old) != VERSION(new) → 誤判 crash-
  #    window 把 VERSION 覆寫回 old → 反覆。故只前進 repo、不動游標。代價：若 origin/prod 最後
  #    一次前進為純非 backend，之後每 tick 重覆 emit ff-only（pull 為 no-op）—— prod 前進本就
  #    罕見且多為 backend，此雜訊可忽略。
  if [[ "$BACKEND_CHANGED" == "false" ]]; then
    if [[ "$dry_run" == "1" ]]; then
      log "[dry-run] would: git pull --ff-only origin prod（追 $DEPLOYED_SHA → ${ORIGIN_SHA}，不 rebuild）"
      emit_verdict "dry-run"; exit 0
    fi
    log "非 backend 變更 → ff-only 追 repo（$DEPLOYED_SHA → ${ORIGIN_SHA}），不 rebuild。"
    # 此路徑不持 deploy 鎖（僅追 repo，不 rebuild）→ 失敗可能是 origin/prod rewind，也可能是與
    # 人工 deploy 併發撞 git index.lock。兩者皆不 force：告警 exit，下一 tick 自然重試。
    if ! "$KG_GIT" -C "$KG_RECON_REPO" pull --ff-only origin prod >&2; then
      alert "ff-only pull 失敗（origin/prod 被 rewind 或 git 併發鎖）。不 force，本輪略過待下一 tick。"
      exit 3
    fi
    emit_verdict "ff-only"; exit 0
  fi

  # 6) 含 backend → DEPLOY 路徑

  # 6b) poison 檢查（read-only；即使 dry-run 也是真實 preview：poison 內真的不會部署）
  if is_poisoned "$ORIGIN_SHA"; then
    log "origin=$ORIGIN_SHA 於 cooldown 內被標 poison（上輪部署失敗回滾過）→ 跳過。"
    emit_verdict "poisoned-skip"; exit 0
  fi

  if [[ "$dry_run" == "1" ]]; then
    log "[dry-run] would: acquire lock $KG_LOCK_DIR"
    log "[dry-run] would: git pull --ff-only origin prod → 寫 backend/VERSION=$ORIGIN_SHA"
    log "[dry-run] would: (cd backend && $KG_COMPOSE up -d --build --force-recreate)"
    # 三分類要在 dry-run 這一面也看得見：操作者在這裡預覽「會發生什麼」，而「量不到會
    # 落地並記 unverified」是本腳本最反直覺的一條行為，藏起來等於沒有（review D5）。
    log "[dry-run] would: 健康 gate（localhost → 外部 smoke 三分類 → infra_health）"
    log "[dry-run] would: 外部 smoke 拿得到 HTTP 回應但不合格（bad），或 infra_health 有 http_probe 以外的 crit → rollback 到 ${DEPLOYED_SHA} + poison ${ORIGIN_SHA}"
    log "[dry-run] would: 外部 smoke 全程拿不到任何回應（unreachable，= 這台機器連不出去）→ 照樣落地，記 smoke=unverified 於 verdict 與 deploy.log 並告警，不 rollback；此時 infra_health 若只有 http_probe crit 也一併視為同一場斷網"
    emit_verdict "dry-run"; exit 0
  fi

  # 6a) 取鎖（與人工 deploy 互斥）。取不到 = 有人在 deploy → 讓下一 tick 再收斂，不報錯。
  if ! mkdir "$KG_LOCK_DIR" 2>/dev/null; then
    log "deploy 鎖 $KG_LOCK_DIR 已被持有（人工 deploy 進行中？）→ 本輪讓路。"
    emit_verdict "locked"; exit 0
  fi
  trap 'rmdir "$KG_LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

  # 6c) 捕捉 ROLLBACK 錨點（DEPLOY 前的 deployed_sha）後進 deploy+gate（含失敗自動回滾）
  deploy_and_gate "$DEPLOYED_SHA"
}

# 只在被「執行」時跑 main；被 source（測試取純函式）時不跑。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
