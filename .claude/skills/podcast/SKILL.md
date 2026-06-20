---
name: podcast
description: "Book-to-Podcast Pipeline — EPUB → 深度分析 → 製作規劃 → QA → 多集播客腳本 → TTS 音訊 → 詞級字幕"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Podcast Pipeline Skill

> 工程細節(架構/排障/契約)見 `docs/sop/podcast_pipeline.md`。本檔僅 CLI 速查。

## 觸發條件

使用者提供一本書的路徑（EPUB），要求產生播客。

## 管線總覽（15 階段）

```
EPUB → prep → analyst → architect → plan-review → enricher-gap → enricher
       ┃ .plan_approved ┃ → scriptwrite → series-polish → script-review
       ┃ .script_approved ┃ → tts-prep → synthesize → audio-qa → subtitle → cover → publish
```

**兩道人工核准 gate**(`approval_gate_block`):全新 run **預設**跑到 `enricher` 就停(`AWAITING_PLAN_APPROVAL`),`script-review` 後再停一次(`AWAITING_SCRIPT_APPROVAL`)—— 避免在爛計畫上燒 scriptwrite token、爛腳本上燒 TTS。放行:`touch workspaces/<n>/.plan_approved`(或 `.script_approved`)後再 `uv run pipeline.py workspaces/<n>/`,或 dashboard 按 ▶ APPROVE。`--ignore-gates` 還原舊全自動。gate 暫停 = **exit 0**(非失敗);工作區狀態由 monitor 從磁碟 artifact 推導(`.*_approved` 存在或下一相已有產物 → 視為已過閘)。

| # | 階段 | 工具 | 說明 |
|---|------|------|------|
| 1 | `prep` | Claude agent | raw chapters → clean chapters |
| 2 | `analyst` | Claude agent | 深度分析：結構、論證強度、概念索引、引句 |
| 3 | `architect` | Claude agent | 製作決策：壓縮比、集數、主持人設計（AI 命名）、episode plans |
| 4 | `plan-review` | Claude agent | QA gate：覆蓋率、hook chain、時長、一致性 |
| 5 | `enricher-gap` | Claude agent | 識別研究需求：弱論證、需要類比的概念 |
| 6 | `enricher` | Claude agent + web | 按研究清單搜尋外部佐證 |
| 7 | `scriptwrite` | Claude agents ×N | 平行寫對話腳本（含 TTS 標籤） |
| 8 | `series-polish` | Claude agent（單） | 跨集拋光：callback 強化、running bits、人格一致性、系列弧收束 |
| 9 | `script-review` | Claude agents ×N | QA gate：覆蓋率、反模式掃描、TTS tag 品質 |
| 10 | `tts-prep` | Claude agent | 最終 TTS-readiness 審查：挑聲線配對、修 parse-breaking 錯誤、寫入 Voice Mapping |
| 11 | `synthesize` | Vertex AI Gemini TTS + ffmpeg loudnorm | 腳本 → MP3 音訊（-16 LUFS mastering） |
| 12 | `audio-qa` | pydub | wpm / silence / clipping 檢查 → `audio_qa.json`；FAIL 阻斷 |
| 13 | `subtitle` | Whisper forced alignment | 音訊 + 腳本 → 詞級 SRT 字幕 |
| 14 | `cover` | Claude agent + `cover_tool.py`（Pexels 漏斗） | series 封面：agent 讀主題 → search(文字海選)→ contact(編號拼圖複選)→ render(duo 後製) → `plan/cover.png`。series-wide（`--only-episode` 跳過）、冪等（cover.png 存在即 skip）、無 gate |
| 15 | `publish` | `ops/podcast_upload.sh` + boto3 verify | 上傳 workspace → S3（含 cover.png）+ 確認 series 現身 catalog index（retry/backoff、1800s timeout）。**終端 stage、不設 gate**：合成完成即自動上線。憑證/環境從 `lab/podcast/.env` gap-fill(`AWS_PROFILE=kg-podcast` 寫權限、`PODCAST_BUCKET`;monitor 不 load .env 故腳本自補)— 詳見 `docs/sop/podcast_pipeline.md` §upload.sh 憑證模型。手動補傳：dashboard ▶ upload 或 `ops/podcast_upload.sh <ws>` |

> **只換/補既有 published series 的封面**(不重跑 pipeline、不動 audio):用 `ops/podcast_cover_publish.py`(audio-decoupled 原子重發:`--all --workspaces-dir` / `--check`,dry-run 預設)。**`upload.sh` 不可用於只換封面** —— 它重組 audio + reconcile,對 local↔S3 不同步的 series 會誤動資料。見 `docs/sop/podcast_pipeline.md` §封面重發布。

## 完整 CLI 參考

### 基本用法

```bash
cd /Users/chenliangyu/kg/lab/podcast

# 全流程（一個命令跑到底）
uv run pipeline.py /path/to/book.epub

# 自動續跑（偵測已完成階段，從斷點開始）
uv run pipeline.py workspaces/<name>/

# 查看進度 + 可用指令
uv run pipeline.py workspaces/<name>/ --status

# Dry run（只建 workspace，不跑 agent）
uv run pipeline.py /path/to/book.epub --dry-run

# 指定版本化 workflow（新 workspace 預設 v1；resume 讀 workflow_manifest.json）
uv run pipeline.py /path/to/book.epub --workflow-version v1
uv run pipeline.py /path/to/book.epub --workflow-version v2
```

### 階段控制

```bash
# 從指定階段開始（會驗證前置 stage marker 都存在,否則拒跑並提示）
uv run pipeline.py workspaces/<name>/ --skip-to enricher

# 跑到指定階段就停
uv run pipeline.py workspaces/<name>/ --stop-after architect

# 只跑一個階段（同樣驗證前置 marker）
uv run pipeline.py workspaces/<name>/ --only-stage scriptwrite

# 組合：只跑某階段的某一集
uv run pipeline.py workspaces/<name>/ --only-stage scriptwrite --only-episode 4

# 跳過前置 marker 檢查（手動驗證 artifacts 完整時用）
uv run pipeline.py workspaces/<name>/ --skip-to scriptwrite --force

# 核准 gate 後續跑（touch marker 等價 dashboard ▶ APPROVE）
touch workspaces/<name>/.plan_approved   && uv run pipeline.py workspaces/<name>/
touch workspaces/<name>/.script_approved && uv run pipeline.py workspaces/<name>/

# 無視兩道 gate，一路跑到底（還原舊全自動行為）
uv run pipeline.py workspaces/<name>/ --ignore-gates

# 調整平行度（scriptwrite 和 script-review 適用）
uv run pipeline.py workspaces/<name>/ --parallel 5
```

### 個別工具

```bash
# TTS 合成（單檔或整個目錄）
uv run synthesize.py workspaces/<name>/scripts/ep_1_script.md
uv run synthesize.py workspaces/<name>/scripts/
uv run synthesize.py workspaces/<name>/scripts/ --dry-run

# 音訊品質 QA（synthesize 後自動跑；也可獨立）
uv run audio_qa.py workspaces/<name>/scripts/
uv run audio_qa.py workspaces/<name>/scripts/ep_1_pro.mp3 --report qa.json --strict

# 字幕對齊（不可平行，Whisper 吃記憶體）
uv run subtitle.py workspaces/<name>/scripts/ep_1_script.md
uv run subtitle.py workspaces/<name>/scripts/

# 預覽播放
uv run preview.py workspaces/<name>/scripts/ep_1_pro.mp3

# 聲線預覽（TTS 前試聽 15s 前段，確認 voice pair）
uv run voice_preview.py workspaces/<name>
```

### 除錯

```bash
# 結構化日誌（每行一筆 JSON）
cat workspaces/<name>/pipeline_log.jsonl | python -m json.tool

# 只看某階段
grep '"stage":"architect"' workspaces/<name>/pipeline_log.jsonl | python -m json.tool

# 只看錯誤
grep '"error"' workspaces/<name>/pipeline_log.jsonl

# Plan QA 結果
cat workspaces/<name>/plan/review.md

# Script QA 結果
cat workspaces/<name>/scripts/ep_1_review.md
```

### 可用 stage 名稱

`prep` · `analyst` · `architect` · `plan-review` · `enricher-gap` · `enricher` · `scriptwrite` · `series-polish` · `script-review` · `tts-prep` · `synthesize` · `audio-qa` · `subtitle` · `cover` · `publish`

## 透明化機制

1. **Stage markers**: 每個階段完成後寫入 `.stage_<name>_done`，用於自動 resume
2. **Workflow manifest**: `workflow_manifest.json` — `workflow_version`、pipeline commit、prompt fingerprints、agent/TTS model、validator versions、stage contracts
3. **Stage provenance**: `stage_provenance/<stage>.json` — stage input/output artifact hash、prompt hash、model/profile、validator result、approval marker
4. **Episode lineage**: `scripts/ep_N_lineage.json` — scriptwrite / series-polish / script-review / producer-cut / tts-prep 的 before/after hash 與 edit event
5. **JSONL log**: `pipeline_log.jsonl` — 每個事件一行 JSON，含時間戳、階段、詳情
6. **Stream events**: `events.jsonl` — **預設開啟**(設 `PODCAST_VERBOSE=0` 關)。內含每個 stage-agent turn 的 tool-use + token usage(含 claude CLI stream-json 的 `result.modelUsage[*].costUSD`,若 provider 有回),以及 synthesize 階段每個 batch 的 `tts_usage` event(input tokens、output audio seconds、model)
7. **Review artifacts**: `plan/review.md`（plan QA）+ `scripts/ep_N_review.md`（script QA）
8. **Agent log**: `log.md` — 每個 Claude agent 自行附加的自然語言日誌
9. **--status**: 一鍵顯示進度 + 所有可用指令

## Dashboard 監控(單命令,零設定)

```bash
cd /Users/chenliangyu/kg/lab/podcast
uv run pipeline.py /path/to/book.epub
```

跑這一行就好。`pipeline.py` 啟動時會:
1. **自動 idempotent 起 dashboard**(`monitor/server.py`,127.0.0.1:8765)— 已開就跳過
2. **自動開瀏覽器**到 `http://127.0.0.1:8765/?ws=<workspace>` 對應這次的書
3. **PODCAST_VERBOSE 預設 ON** — events.jsonl 一定有,cost 一定算

opt-out env:
- `PODCAST_NO_DASHBOARD=1` — 不起 dashboard、不開瀏覽器
- `PODCAST_DASHBOARD_PORT=9000` — 換 port
- `PODCAST_VERBOSE=0` — 關 stream-json(會失去 cost 追蹤)

純 dashboard 手動操作(沒在跑 pipeline 時看舊 workspace):
```bash
./start.sh                 # 啟動 / 重啟
./start.sh 9000            # 自訂 port
./start.sh --stop          # 停掉
```

後端 FastAPI(`monitor/server.py` + `monitor/cost.py` + `monitor/jobs.py` + `monitor/remote.py`)+ 前端 vanilla JS + `static/player.js`。

**Read API**(觀測):
- `GET /api/workspaces` — 名稱列表(`[name,...]`);`?full=1` 回 sidebar summary array(`name/status/milestones/progress/n_stages_done/n_stages_total/episode_count/created/last_updated/total_usd/claude_usd/tts_usd/has_cost_data/active_job`)。`milestones[]` = 四關卡 `{key,label,done,total,ratio}`(plan→script→audio→subtitle,**產物推導非 marker**);`progress` = 四 ratio 均值(整體進度標量;前端改以四條 per-gate ratio 各自渲染,不直接用此值);`created` = workspace 加入時間 epoch(`.created` sidecar,無則灌 birthtime)。`n_stages_*` 為 legacy marker 欄位,**已不用於進度條**(marker 會與產物脫鉤,見 sop)。status cascade `running>done>failed>idle>fresh`;pipeline kind 經 `<ws>/.pipeline_job_id` sidecar 反查 workspace
- `GET /api/workspace/<n>/snapshot` — 歷史事件 + 已完成 stage marker
- `GET /api/workspace/<n>/stream` — SSE,tail `pipeline_log.jsonl` + `events.jsonl`
- `GET /api/workspace/<n>/cost` — 成本聚合(前端每 4 秒 poll)
- `GET /api/workspace/<n>/episodes` — list ep + variant(pro/flash)+ `model`(full TTS id from sidecar，舊集數無 sidecar 時為 `null`)+ size + has_subtitle
- `GET /api/workspace/<n>/episodes/status` — 每集四關卡 `{ep,plan,script,audio,subtitle,variant,audio_bytes}`,artifact-derived(plan ∪ scripts,idle workspace 亦回傳);前端 episode matrix 資料源
- `GET /api/workspace/<n>/episode/<ep>/audio` — MP3 stream(Range / 206 OK)
- `GET /api/workspace/<n>/episode/<ep>/subtitle` — SRT plain text

**Action API**(製作 — 都會 spawn subprocess,回傳 job_id):
- `POST /api/workspace/<n>/upload` — 跑 `ops/podcast_upload.sh`,422 if 無 ep_*.mp3
- `DELETE /api/workspace/<n>?confirm=<n>` — 本地砍 workspace(confirm 必須等於名字)
- `POST /api/workspace/<n>/rerun?stage=<S>&episode=<N>&drop_marker=true` — `uv run pipeline.py --only-stage`
- `POST /api/workspace/<n>/approve?gate=plan|script` — 寫 `.plan_approved`/`.script_approved` + spawn `pipeline.py <ws>` 續跑下一相;`pending`(前一相未完成)回 409
- `POST /api/workspace/<n>/resume` — spawn `pipeline.py <ws>`(flagless auto-resume,從第一個沒 marker 的階段往後跑到下一道 gate / 完成);與 rerun(單階)、approve(寫標記再續)區隔
- **per-workspace 併發守衛**:`approve` / `resume` / `upload` / `rerun` 四個 spawn endpoint 在任何 state mutation(包含 rerun 砍 stage marker、approve 寫 gate marker)**之前**檢查 `_active_job_for_ws(ws)`,同 workspace 已有 running job → 409,不 spawn、不改 marker。global `MAX_ACTIVE_JOBS` 守 fleet 上限,per-ws 守同一書併寫競爭
- `POST /api/pipeline/start` (multipart `epub` + `parallel` 1-10) — 上傳 EPUB + 跑全流程(預設停在計畫 gate)

**Jobs API**:
- `GET /api/jobs?limit=N`、`GET /api/jobs/<id>?log_bytes=N`、`POST /api/jobs/<id>/kill`

**Remote API**(SSH 到 Lightsail):
- `GET /api/remote/series` — index.json + 每 series du size
- `GET /api/remote/disk` — df + du for the data volume
- `GET /api/remote/reconcile` — workspace↔S3 drift：列「合成了 audio 但 series 不在 S3 catalog」的 workspace，回 `{drifted:[{workspace, reason:"synthesized_not_published"}], publishedCount}`（唯讀）
- `DELETE /api/remote/series/<id>?confirm=<id>` — flock 序列化 rm + index 重建 + 回 `fully_deleted` flag

**回填 / drift CLI**（served-disk↔S3，覆蓋 legacy 實例磁碟 series；新世界 series 直接 pipeline→S3 不落磁碟）：
`ops/devops_kg_safe.sh container-script ops/podcast_backfill_disk.py [--execute|--check|--series <id>]`（預設 dry-run、純新增不刪、`--check` 報 disk 有/S3 缺）。

429 表示同時 job 太多(預設 cap 4 個 running),412 → 422 → 413(epub >200MB)→ 500 各有意義。

**Agent 走 HTTP API 後 GUI 可見性**：

| GUI 面板 | 可見？ | 說明 |
|----------|--------|------|
| Jobs 面板（running/done/failed） | ✅ | job 進 registry，即時狀態 |
| Job log tail | ✅ | `GET /api/jobs/{id}?log_bytes=N` |
| Kill 按鈕 | ✅ | `POST /api/jobs/{id}/kill`（SIGTERM process group） |
| Stage 進度條 | ✅ | SSE tail `pipeline_log.jsonl`，0.5s 延遲 |
| Live Activity feed | ✅ | SSE tail `events.jsonl`，0.5s 延遲 |
| Cost breakdown | ✅ | 每 4s poll `events.jsonl` |
| Episode matrix | ✅ | 每 5s poll artifact 目錄 |
| APPROVE 按鈕（409 守衛） | ✅ | per-workspace 守衛正確感知此 job |
| RESUME 按鈕（409 守衛） | ✅ | 同上，不重複 spawn |

直接 CLI（不走 API）：Jobs 面板、Kill、APPROVE/RESUME 守衛全部 ❌；SSE + stage 進度仍 ✅（dashboard 讀的是磁碟檔案）。

UI:KPI strip(TOTAL COST / ELAPSED / CONTEXT NOW / TOKENS OUT) + 13 stage 進度條(scriptwrite / script-review / synthesize 三段平行階段展開顯示每集 EP tile) + COST BREAKDOWN 表(逐 stage:model、calls、input/output tokens、cache R/W、audio、$) + LIVE ACTIVITY feed。

**成本計算來源**(`monitor/cost.py`):
- Stage 1-10(agent):直接讀 claude CLI stream-json 的 `result.modelUsage[model].costUSD`。Claude profile 通常有完整 USD;Kimi profile 若 endpoint 不回 `costUSD`,以 Kimi Code 帳單為準
- Stage 11(Vertex TTS):從 `tts_usage` event 取 `input_tokens` × `output_tokens`,套 `VERTEX_PRICING` dict。當前 default `gemini-2.5-flash-tts` $0.30/$2.50 per 1M(audio = 25 tok/sec,無 long tier);`gemini-3.1-flash-tts-preview` $1.00/$20、舊 `gemini-2.5-pro-tts` $1.25/$10 也保留。`response.usage_metadata` 缺失時 fallback 估算(`input ≈ chars/4`、`output ≈ audio_sec × 25`),event 標 `usage_source: "estimated"`
- Stage 12-13(audio_qa / Whisper):本地跑,$0
- Pricing 來源:Vertex Gemini 3.1 Flash TTS 用 AI Studio TTS-specific row($1/$20);2.5-pro-tts 用 Vertex 公告 base Gemini 2.5 Pro rate。`verified_against: "2026-05-30"`。改單價編輯 `VERTEX_PRICING` 或 env `PODCAST_TTS_PRICING='{"model":{...}}'` 覆寫。

## Dashboard HTTP API 完整速查

`BASE=http://127.0.0.1:8765`（本機，無 auth）

### 觀測（Read-only）

```bash
# Workspace 列表（附完整 sidebar 資料）
curl -sf "$BASE/api/workspaces?full=1" | python3 -m json.tool

# 單 workspace 概況（stage markers + 歷史 events）
curl -sf "$BASE/api/workspace/$WS/snapshot" | python3 -m json.tool

# 每集四關卡（plan/script/audio/subtitle artifact 推導）
curl -sf "$BASE/api/workspace/$WS/episodes/status" | python3 -m json.tool

# 成本明細（逐 stage USD）
curl -sf "$BASE/api/workspace/$WS/cost" | python3 -m json.tool

# Jobs 列表（最新 8 筆）
curl -sf "$BASE/api/jobs?limit=8" | python3 -m json.tool

# 單 job 狀態 + log tail
curl -sf "$BASE/api/jobs/$JOB?log_bytes=8192" | python3 -m json.tool
```

### Action（spawn subprocess，回傳 `{job_id}`）

```bash
# 全流程啟動（停在 plan gate）
curl -sf -X POST "$BASE/api/pipeline/start" \
  -F "epub=@/path/to/book.epub" -F "parallel=3"

# Gate 核准 + 自動 resume（寫 marker + spawn）
curl -sf -X POST "$BASE/api/workspace/$WS/approve?gate=plan"
curl -sf -X POST "$BASE/api/workspace/$WS/approve?gate=script"

# 從斷點自動續跑（不寫 marker，只 spawn）
curl -sf -X POST "$BASE/api/workspace/$WS/resume"

# 重跑單 stage（砍 marker + spawn）
curl -sf -X POST "$BASE/api/workspace/$WS/rerun?stage=scriptwrite&drop_marker=true"
# 單集
curl -sf -X POST "$BASE/api/workspace/$WS/rerun?stage=scriptwrite&episode=2&drop_marker=true"

# 上傳到 S3（跑 ops/podcast_upload.sh）
curl -sf -X POST "$BASE/api/workspace/$WS/upload"

# Kill running job（SIGTERM process group）
curl -sf -X POST "$BASE/api/jobs/$JOB/kill"

# 刪除 workspace（不可逆，confirm 必須等於 ws 名）
curl -sf -X DELETE "$BASE/api/workspace/$WS?confirm=$WS"
```

### 錯誤碼速查

| 碼 | 意義 |
|----|------|
| 409 | ① per-workspace 已有 running job（守衛擋）② approve 時前一相未完成（pending gate） |
| 422 | 無可上傳的音訊（upload 拒）|
| 413 | EPUB 超過 `PODCAST_MAX_EPUB_BYTES`（預設 200MB，可 env 覆寫）|
| 429 | 超過 global `MAX_ACTIVE_JOBS`（預設 4）|

## 主持人動態命名

- Architect 根據書的語言/風格自動設計主持人名字（不再硬編碼）
- `overview.md` 的 Voice Mapping section 定義 name → Speaker1/Speaker2 映射
- `synthesize.py` 和 `subtitle.py` 從 `overview.md` 動態讀取

## Workspace 命名規則（series_id 約束）

- Workspace 目錄名格式：`<slug>_<hash>`，其中 `slug` 由 `pipeline.py:_sanitize_slug()`（SoT，`max_len=30`）從書名產生
- **必須符合 `^[a-z0-9_]+$`**（backend `_SERIES_ID_RE` 與 `ops/podcast_upload.sh` 強制）
- Sanitize 演算法：lowercase → 非字母數字 → `_` → strip 首尾 `_` → 截斷 30 chars → re-rstrip
- `ops/podcast_upload.sh` 直接用 `basename(workspace)` 當 `series_id`；不合法時上傳成功但 API 全 404

## 限制 / 依賴

- `subtitle.py` 不可平行（Whisper 每集 load_model 重載，記憶體大）；預設 `--model medium`，非英文無法正確對齊
- `synthesize.py` 內部已平行，`TTS_MAX_CONCURRENT=10`（撞 Vertex 429 時降到 3-5）
- `scriptwrite` / `script-review` 平行度預設 3，用 `--parallel N` 調整
- **`ffmpeg` 需安裝**（mastering loudnorm 用）；無 ffmpeg 時自動降級為純 export，音量不會正規化
- Claude agent 每 stage 有 timeout（Enricher 2700s / Scriptwriter 1800s / Reviewer 1200s / 其他 1500s）

## 常用環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `PODCAST_AGENT_PROFILE` | `claude` | Stage 1-10 agent billing/profile:`claude` 走正常 Claude Code;`kimi` 仍呼叫 `claude -p`,但注入 Kimi Code endpoint/token env。CLI 也可用 `--agent-profile claude|kimi`;workspace 會寫 `.agent_profile` 供 approve/resume 讀回 |
| `PODCAST_AGENT_MODEL` | `opus[1m]`(claude) / `kimi-for-coding`(kimi) | Stage 1-10 agent model;CLI 也可用 `--agent-model M`。legacy `PODCAST_CLAUDE_MODEL` 仍支援但只建議當 Claude profile 相容入口 |
| `PODCAST_KIMI_API_KEY` / `PODCAST_KIMI_KEY_FILE` | `~/.secrets/kimi.env` | Kimi profile token 來源。優先序:`PODCAST_KIMI_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → key file;缺 key 時 fail-fast |
| `PODCAST_STAGE_RETRIES` | `3` | 每個 agent stage 的總嘗試次數。transient 失敗(thinking-block 400 / 429 / 5xx)以**全新** `claude -p` 重試(繞過被汙染的 thinking 對話歷史);auth / 一般 400 / timeout 不重試。詳見 `docs/sop/podcast_pipeline.md` §Agent-stage 重試 |
| `TTS_MODEL` | `gemini-2.5-flash-tts`(code 預設與 `.env` 一致,2026-06-02 起) | Vertex TTS 模型;3.1-flash-preview / 2.5-pro 可選。audio-tag palette 為 family-parametric(SoT `tts_tags.py:TAG_CONCEPTS`):scriptwrite 依目標 family 注入對應 palette,synthesize 端 `sanitize_tags_for_family` 兜底跨 family tag |
| `TTS_MAX_CONCURRENT` | `10` | TTS batch 並發上限 |
| `TTS_RETRY_ATTEMPTS` | `4` | 429/503 指數退避重試次數 |
| `TTS_MASTER` | `1` | 設 `0` 關閉 loudnorm mastering |
| `TTS_MASTER_LUFS` | `-16` | 目標整合響度（Apple Podcasts 標準） |
| ~~`PODCAST_SSH_KEY`~~ | — | **已廢棄**：上傳全走 S3，無 SSH。見 `lab/podcast/monitor/remote.py:20` |
| ~~`PODCAST_REMOTE_SERVER`~~ | — | **已廢棄**：S3 取代遠端 SSH 端點（Lightsail 已 terminate）。設了也無效 |
| ~~`PODCAST_REMOTE_DIR`~~ | — | **已廢棄**：資產根目錄改 S3 catalog。設了也無效 |
| `PODCAST_SSH_TIMEOUT` | `20` | SSH 連線 timeout 秒數 |
| `PODCAST_MAX_ACTIVE_JOBS` | `4` | Monitor 同時 running 的 subprocess job 上限,超過回 429 |
| `PODCAST_JOB_HISTORY` | `100` | Monitor 留多少筆已完成 job log(超過 LRU 砍最舊) |
| `PODCAST_MAX_EPUB_BYTES` | `200 * 1024 * 1024` | `/api/pipeline/start` 接受的 EPUB 上限 |

## Workspace 結構

```
workspaces/<slug>_<hash>/
  .stage_prep_done               ← 階段完成標記
  .stage_analyst_done
  ...
  pipeline_log.jsonl             ← 結構化日誌
  workflow_manifest.json          ← workflow 版本 / prompt fingerprints / model / validators / stage contracts
  stage_provenance/<stage>.json   ← 每階段 input/output artifact hash + validator result
  log.md                         ← agent 自然語言日誌
  raw_chapters/raw_ch_*.md
  source/metadata.md
  source/chapters/ch_*.md
  plan/analysis.md               ← analyst 深度分析
  plan/overview.md               ← architect 製作規劃
  plan/episodes/ep_*.md          ← episode plans + enrichments
  plan/review.md                 ← plan QA 結果
  plan/research_brief.md         ← enricher gap 研究清單
  scripts/
    ep_N_script.md               ← 對話腳本
    ep_N_lineage.json             ← 腳本 before/after hash 與 stage edit lineage
    ep_N_review.md               ← script QA 結果
    ep_N_pro.mp3                 ← TTS 音訊（loudnorm 過）
    ep_N_pro.srt                 ← 詞級字幕
    ep_N_pro.meta.json           ← {"tts_model": "gemini-2.5-pro-tts"} sidecar（含完整模型 id，monitor UI 顯示用；舊集數可能沒有）
  audio_qa.json                  ← 音訊 QA 報告
  claude_*.stderr.log            ← agent 失敗時的 stderr tail
```

## Agent 行為指引

### 偵測 dashboard

```bash
curl -sf --max-time 2 http://127.0.0.1:8765/api/workspaces > /dev/null \
  && echo API || echo CLI
```

- **API**（dashboard 在跑）→ 走下方「HTTP API 路徑」
- **CLI**（dashboard 不在）→ 走下方「直接 CLI fallback」

---

### HTTP API 路徑（優先）

GUI 可完整監控：jobs panel、kill、APPROVE 按鈕、SSE 即時 feed 全部有效。

```bash
BASE=http://127.0.0.1:8765
cd /Users/chenliangyu/kg/lab/podcast

# 1. 確保 dashboard 啟動（idempotent）
./start.sh

# 2. 上傳 EPUB 並啟動全流程（停在 plan gate）
JOB=$(curl -sf -X POST "$BASE/api/pipeline/start" \
  -F "epub=@/path/to/book.epub" -F "parallel=3" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 3. 等 workspace 出現
#    pipeline 解析 EPUB→slug 後寫 .pipeline_job_id sidecar，dashboard 才能反查。
#    start_pipeline metadata 不含 workspace，必須從 active_job 比對取得。
WS=""
while [ -z "$WS" ]; do
  sleep 5
  WS=$(curl -sf "$BASE/api/workspaces?full=1" | python3 -c "
import sys, json
for w in json.load(sys.stdin):
  if isinstance(w, dict) and (w.get('active_job') or {}).get('job_id') == '$JOB':
    print(w['name']); break
" 2>/dev/null)
done
echo "workspace: $WS"

# _poll JOB_ID — 等 job 結束；succeeded=gate 或完成；failed/killed=中止
_poll() {
  while true; do
    S=$(curl -sf "$BASE/api/jobs/$1?log_bytes=0" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
    echo "job $1: $S"
    case "$S" in
      pending|running) sleep 15 ;;
      succeeded)       break ;;
      *)               echo "ERROR: job $1 → $S"; exit 1 ;;
    esac
  done
}

# 4. Poll 到 plan gate
_poll "$JOB"

# 5. 審 plan/overview.md + plan/review.md → approve（自動 spawn resume，回傳新 job_id）
JOB=$(curl -sf -X POST "$BASE/api/workspace/$WS/approve?gate=plan" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 6. Poll 到 script gate
_poll "$JOB"

# 7. 審 scripts/ep_*_review.md → approve（自動 spawn resume，回傳新 job_id）
JOB=$(curl -sf -X POST "$BASE/api/workspace/$WS/approve?gate=script" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 8. Poll 到全部完成（subtitle done）
_poll "$JOB"

# 9. 上傳到 S3
curl -sf -X POST "$BASE/api/workspace/$WS/upload"
```

**Resume / 重跑單 stage**（pipeline 中途斷掉）：

```bash
# 從斷點自動續跑
curl -sf -X POST "$BASE/api/workspace/$WS/resume"

# 只重跑某 stage（例如 scriptwrite 第 2 集）
curl -sf -X POST "$BASE/api/workspace/$WS/rerun?stage=scriptwrite&episode=2&drop_marker=true"
```

**失敗診斷**：

```bash
# 看 job log 最後 8KB（key 是 log_tail）
curl -sf "$BASE/api/jobs/$JOB?log_bytes=8192" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['log_tail'])"

# 也可直接讀 jsonl
grep '"error"' workspaces/$WS/pipeline_log.jsonl
```

---

### 直接 CLI fallback

dashboard 未啟動時使用。GUI 的 jobs panel 看不到此 process，但 SSE feed + stage 進度仍會反映（dashboard 若之後再啟動可補看）。

```bash
cd /Users/chenliangyu/kg/lab/podcast

# 全流程
uv run pipeline.py /path/to/book.epub

# 自動續跑
uv run pipeline.py workspaces/<name>/

# 查進度
uv run pipeline.py workspaces/<name>/ --status

# Gate 核准
touch workspaces/<name>/.plan_approved   && uv run pipeline.py workspaces/<name>/
touch workspaces/<name>/.script_approved && uv run pipeline.py workspaces/<name>/
```

若失敗：讀 `pipeline_log.jsonl` 和 review 檔案判斷原因，用 `--skip-to` 從斷點續跑。

---

### 完成後回報

workspace 路徑、各集音訊長度（`ffprobe` 或 `/api/workspace/{ws}/episodes`）、總檔案大小。
