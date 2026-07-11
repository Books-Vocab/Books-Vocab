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
#   - 變更含 backend 觸發路徑 → git pull + 寫 VERSION + docker compose up --build +
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
KG_RECON_HEALTH_ATTEMPTS="${KG_RECON_HEALTH_ATTEMPTS:-5}"  # localhost 健康輪詢次數
KG_RECON_HEALTH_DELAY="${KG_RECON_HEALTH_DELAY:-3}"        # 每次間隔秒
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
external_smoke_ok() {
  local want="$1" base="$KG_PUBLIC_URL"
  local body code ver hcode
  body="$("$CURL_BIN" -sS -o - -w $'\n%{http_code}' --max-time 10 "$base/api/system/info" 2>/dev/null || true)"
  code="$(printf '%s\n' "$body" | tail -n1)"
  body="$(printf '%s\n' "$body" | sed '$d')"
  if [[ "$code" != "200" ]]; then log "  external /api/system/info HTTP=${code:-none} (expect 200)"; return 1; fi
  ver="$(extract_version "$body")"
  if [[ "$ver" != "$want" ]]; then log "  external version=${ver:-} != $want"; return 1; fi
  hcode="$("$CURL_BIN" -sS -o /dev/null -w '%{http_code}' --max-time 10 "$base/api/health" 2>/dev/null || echo 000)"
  case "$hcode" in
    200|401|403) : ;;                                   # 存在 → ok
    404) log "  external /api/health 404 → 跳過（非失敗）" ;;
    *)   log "  external /api/health HTTP=$hcode → 判紅"; return 1 ;;   # 000/500/其他
  esac
  return 0
}

# 三段健康 gate；失敗設 HEALTH_FAIL_REASON=<health|smoke|infra> 並 return 1
HEALTH_FAIL_REASON=""
run_health_gate() {
  local new="$1"
  if ! localhost_health_ok "$new"; then HEALTH_FAIL_REASON="health"; return 1; fi
  if ! external_smoke_ok "$new";  then HEALTH_FAIL_REASON="smoke";  return 1; fi
  local ih
  set +e; "$KG_INFRA_HEALTH" >/dev/null 2>&1; ih=$?; set -e
  case "$ih" in
    0) : ;;                                             # ok
    1) log "  infra_health WARN (exit 1) — 記警告仍 pass" ;;
    *) HEALTH_FAIL_REASON="infra"; log "  infra_health CRIT (exit $ih)"; return 1 ;;   # 2=crit
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
  printf '{"schema":"kg.deploy.reconcile.v1","verdict":"%s","deployed_sha":"%s","origin_sha":"%s","backend_changed":%s,"ts":"%s"}\n' \
    "$1" "$DEPLOYED_SHA" "$ORIGIN_SHA" "$BACKEND_CHANGED" "$(iso_now)"
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
  local crc
  set +e; ( cd "$KG_RECON_REPO/backend" && $KG_COMPOSE up -d --build ) >&2; crc=$?; set -e

  local ok=1
  if (( crc != 0 )); then
    HEALTH_FAIL_REASON="build"; ok=0
    log "  compose up --build 失敗 (exit $crc)"
  elif ! run_health_gate "$new_sha"; then
    ok=0
  fi

  if (( ok == 1 )); then
    append_deploy_log "sha=$new_sha user=reconciler"
    clear_poison "$ORIGIN_SHA"
    log "✓ DEPLOY 成功：version=$new_sha"
    emit_verdict "deployed"
    exit 0
  fi

  # 3) ROLLBACK：只回滾到捕捉好的 ROLLBACK_SHA（絕不 clean、絕不到未知 sha）
  local reason="$HEALTH_FAIL_REASON"
  alert "部署健康 gate 失敗 (reason=$reason)，回滾 $new_sha → $rollback_sha"
  "$KG_GIT" -C "$KG_RECON_REPO" reset --hard "$rollback_sha" >&2
  printf '%s\n' "$rollback_sha" > "$KG_RECON_REPO/backend/VERSION"
  set +e; ( cd "$KG_RECON_REPO/backend" && $KG_COMPOSE up -d --build ) >&2; set -e
  # 回滾後確認舊版健康（best-effort，不 gate verdict；連舊版都不健康則更大聲告警）
  if localhost_health_ok "$rollback_sha"; then
    log "  回滾後 localhost 健康確認：$rollback_sha OK"
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
    log "[dry-run] would: (cd backend && $KG_COMPOSE up -d --build)"
    log "[dry-run] would: 健康 gate（localhost + 外部 smoke + infra_health）"
    log "[dry-run] would: 失敗則 rollback 到 $DEPLOYED_SHA + poison $ORIGIN_SHA"
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
