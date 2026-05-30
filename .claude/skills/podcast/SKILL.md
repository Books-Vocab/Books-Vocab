---
name: podcast
description: "Book-to-Podcast Pipeline — EPUB → 深度分析 → 製作規劃 → QA → 多集播客腳本 → TTS 音訊 → 詞級字幕"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Podcast Pipeline Skill

> 工程細節(架構/排障/契約)見 `docs/sop/podcast_pipeline.md`。本檔僅 CLI 速查。

## 觸發條件

使用者提供一本書的路徑（EPUB），要求產生播客。

## 管線總覽（13 階段）

```
EPUB → prep → analyst → architect → plan-review → enricher-gap → enricher → scriptwrite → series-polish → script-review → tts-prep → synthesize → audio-qa → subtitle
```

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

`prep` · `analyst` · `architect` · `plan-review` · `enricher-gap` · `enricher` · `scriptwrite` · `series-polish` · `script-review` · `tts-prep` · `synthesize` · `audio-qa` · `subtitle`

## 透明化機制

1. **Stage markers**: 每個階段完成後寫入 `.stage_<name>_done`，用於自動 resume
2. **JSONL log**: `pipeline_log.jsonl` — 每個事件一行 JSON，含時間戳、階段、詳情
3. **Stream events**: `events.jsonl` — **預設開啟**(設 `PODCAST_VERBOSE=0` 關)。內含每個 claude turn 的 tool-use + token usage(含 `result.modelUsage[*].costUSD` 官方成本),以及 synthesize 階段每個 batch 的 `tts_usage` event(input tokens、output audio seconds、model)
4. **Review artifacts**: `plan/review.md`（plan QA）+ `scripts/ep_N_review.md`（script QA）
5. **Agent log**: `log.md` — 每個 Claude agent 自行附加的自然語言日誌
6. **--status**: 一鍵顯示進度 + 所有可用指令

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
- `POST /api/pipeline/start` (multipart `epub` + `parallel` 1-10) — 上傳 EPUB + 跑全流程

**Jobs API**:
- `GET /api/jobs?limit=N`、`GET /api/jobs/<id>?log_bytes=N`、`POST /api/jobs/<id>/kill`

**Remote API**(SSH 到 Lightsail):
- `GET /api/remote/series` — index.json + 每 series du size
- `GET /api/remote/disk` — df + du for the data volume
- `DELETE /api/remote/series/<id>?confirm=<id>` — flock 序列化 rm + index 重建 + 回 `fully_deleted` flag

429 表示同時 job 太多(預設 cap 4 個 running),412 → 422 → 413(epub >200MB)→ 500 各有意義。

UI:KPI strip(TOTAL COST / ELAPSED / CONTEXT NOW / TOKENS OUT) + 13 stage 進度條(scriptwrite / script-review / synthesize 三段平行階段展開顯示每集 EP tile) + COST BREAKDOWN 表(逐 stage:model、calls、input/output tokens、cache R/W、audio、$) + LIVE ACTIVITY feed。

**成本計算來源**(`monitor/cost.py`):
- Stage 1-10(Claude):直接讀 `result.modelUsage[model].costUSD` — 這是 claude CLI 官方算的值(含 cache 折扣 + 1M context premium),不自己算
- Stage 11(Vertex TTS):從 `tts_usage` event 取 `input_tokens` × `output_tokens`,套 `VERTEX_PRICING` dict。當前 default `gemini-3.1-flash-tts-preview` $1.00/$20 per 1M(audio = 25 tok/sec,無 long tier);舊 `gemini-2.5-pro-tts` $1.25/$10 也保留。`response.usage_metadata` 缺失時 fallback 估算(`input ≈ chars/4`、`output ≈ audio_sec × 25`),event 標 `usage_source: "estimated"`
- Stage 12-13(audio_qa / Whisper):本地跑,$0
- Pricing 來源:Vertex Gemini 3.1 Flash TTS 用 AI Studio TTS-specific row($1/$20);2.5-pro-tts 用 Vertex 公告 base Gemini 2.5 Pro rate。`verified_against: "2026-05-30"`。改單價編輯 `VERTEX_PRICING` 或 env `PODCAST_TTS_PRICING='{"model":{...}}'` 覆寫。

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
| `PODCAST_CLAUDE_MODEL` | `opus[1m]` | Stage 1-10(Claude agent)的 `claude -p` model;stage 11-13 是 Vertex TTS / pydub / Whisper 不受影響。`[1m]` 是 deliberate default — scriptwriter / enricher / series-polish 跨多章推理需 1M context window,改 `sonnet` 前先確認 |
| `PODCAST_STAGE_RETRIES` | `3` | 每個 agent stage 的總嘗試次數。transient 失敗(thinking-block 400 / 429 / 5xx)以**全新** `claude -p` 重試(繞過被汙染的 thinking 對話歷史);auth / 一般 400 / timeout 不重試。詳見 `docs/sop/podcast_pipeline.md` §Agent-stage 重試 |
| `TTS_MODEL` | `gemini-2.5-flash-tts`(`.env` 覆寫為 `gemini-2.5-pro-tts`) | Vertex TTS 模型;部署實際用 Pro,程式碼預設 Flash |
| `TTS_MAX_CONCURRENT` | `10` | TTS batch 並發上限 |
| `TTS_RETRY_ATTEMPTS` | `4` | 429/503 指數退避重試次數 |
| `TTS_MASTER` | `1` | 設 `0` 關閉 loudnorm mastering |
| `TTS_MASTER_LUFS` | `-16` | 目標整合響度（Apple Podcasts 標準） |
| `PODCAST_SSH_KEY` | `~/.ssh/lightsail_default.pem` | Monitor remote endpoints + `ops/podcast_upload.sh` 用的 SSH key |
| `PODCAST_REMOTE_SERVER` | `ubuntu@13.193.212.134` | Lightsail VPS 連線目標(必要時改 host topology) |
| `PODCAST_REMOTE_DIR` | `~/knowledge_graph_api/data/podcasts` | 遠端 podcast 資產根目錄 |
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
    ep_N_review.md               ← script QA 結果
    ep_N_pro.mp3                 ← TTS 音訊（loudnorm 過）
    ep_N_pro.srt                 ← 詞級字幕
    ep_N_pro.meta.json           ← {"tts_model": "gemini-2.5-pro-tts"} sidecar（含完整模型 id，monitor UI 顯示用；舊集數可能沒有）
  audio_qa.json                  ← 音訊 QA 報告
  claude_*.stderr.log            ← agent 失敗時的 stderr tail
```

## Agent 行為指引

1. 確認 EPUB 路徑存在
2. 執行 `uv run pipeline.py <path>`
3. 若失敗，讀 `pipeline_log.jsonl` 和 review 檔案判斷原因
4. 用 `--skip-to` 從斷點續跑
5. 完成後告知：workspace 路徑、各集音訊長度、檔案大小
