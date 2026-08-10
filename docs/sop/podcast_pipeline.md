<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/podcast/
  - ops/podcast_upload.sh
verified_against: 5c814f970
-->
<!--
  tier 慣例:tier=sop 用 update_trigger=sop-change(對齊其他 sop)。
  本檔雖也是 lab/podcast 程式碼變動的契約,但 lab/podcast 屬實驗 / 工具
  程式碼非 user-facing surface,維持 sop tier、靠 review agent 主動同步,
  不走 reference tier 的硬性 doc-as-code 要求。
-->
# KG Podcast Pipeline SOP

書 → podcast 全流程的工程文檔。`.claude/skills/podcast/SKILL.md` 是 agent 操作手冊（CLI 速查）；這份是**為什麼這樣做、壞了怎麼救**。

關聯文檔:
- `docs/reference/feature_boundary/podcast.md` — iOS player 邊界
- `docs/sop/backend.md` §podcast — `/api/podcasts*` serving
- `docs/reference/tech_index.md` — `podcast.py` router + `podcast_progress.py` SoT

---

## 1. 15 階段架構

主控 `lab/podcast/pipeline.py`，順序執行：

```
EPUB
 ├ 1. prep            raw chapters → clean chapters
 ├ 2. analyst         深度分析(結構/論證/概念/引句)
 ├ 3. architect       製作決策 + Voice Mapping(host TBD)
 ├ 4. plan-review     QA gate(REWRITE_NEEDED / FAIL>2 → 失敗)
 ├ 5. enricher-gap    識別研究需求
 ├ 6. enricher        web 搜尋外部佐證(+WebSearch/WebFetch)
 ╎ ┃ .plan_approved   ── 人工核准 gate 1:放行才寫腳本 ──
 ├ 7. scriptwrite     ×N 平行寫稿(ProcessPoolExecutor)
 ├ 8. series-polish   跨集拋光(callback/running bits/弧收束)
 ├ 9. script-review   ×N 平行 QA(REWRITE_NEEDED → 失敗)
 ╎ ┃ .script_approved ── 人工核准 gate 2:放行才合成音頻(TTS $$)──
 ├10. tts-prep        最終 TTS 審查 + Voice Mapping TBD→實際 voice
 ├11. synthesize      Vertex Gemini TTS + ffmpeg loudnorm
 ├12. audio-qa        pydub wpm/silence/clipping(FAIL 阻斷)
 ├13. subtitle        Whisper forced alignment → 詞級 SRT
 ├14. cover           agent 用 cover_tool 漏斗挑主題相關 Pexels 圖 → duo 後製 → plan/cover.png(series-wide)
 └15. publish         ops/podcast_upload.sh → S3(含 cover.png) + verify 現身 catalog index
```

> `STAGES` list 為 15 個(`pipeline.py` 內,搜 `STAGES = [`)。`cover` 在 `subtitle` 後、`publish` 前(series-wide:一 series 一張封面,`--only-episode` 跳過;冪等:`plan/cover.png` 存在即 skip;無 approval gate)。`publish` 為終端 stage,合成完成即自動上傳 S3(關閉「合成了但沒上傳」的 drift 缺口)——**不設 approval gate**(全自動),失敗 loud-fail（PODCAST_BUCKET/creds 未設或 verify 耗盡即回 False,寫 error log,非 silent）。monitor dashboard `POST /api/workspace/{ws}/upload` 手動上傳保留為冪等修復路徑。若見 `pipeline.py` 頂部 docstring 仍寫舊階數即為殘留,以 `STAGES` 為準。

### 兩道人工核准 gate(`approval_gate_block`)

QA gate(下節)是**機器**判 pass/fail;這兩道是**人工**審查攔截 —— 在燒錢的兩相前停下等製作人放行:

```
PLAN(prep→enricher) ┃.plan_approved┃ SCRIPT(scriptwrite→script-review) ┃.script_approved┃ AUDIO(tts-prep→subtitle)
```

- 全新 run **預設**跑到 `enricher` 就停(exit 0,非失敗),`script-review` 後再停一次。
- 放行:`touch <ws>/.plan_approved`(或 `.script_approved`)後再 `uv run pipeline.py <ws>`(auto-resume 到下一道 gate 或完成),或 dashboard `POST /approve`。
- **bypass 認顯式 `--skip-to`/`--only-stage`(製作人主動驅動=核准),不認 auto-resume** —— 否則未核准就再跑 `pipeline.py <ws>`,auto-resume 把 start_idx 推到 scriptwrite 會靜默跳閘。`--ignore-gates` 一路跑到底(還原舊全自動)。
- monitor 工作區狀態 `awaiting` 從磁碟推導:`.*_approved` 存在 **或** 下一相已有產物(legacy 無標記但有腳本/音頻)→ 視為已過閘,不誤判 awaiting。

### Stage marker / resume

每 stage 成功 `stage_end()` 寫 `.stage_<name>_done`（內容 ISO timestamp）。`detect_resume_point()` 找第一個沒 marker 的 stage。傳 workspace 目錄無 `--skip-to` 時自動 resume。

**脆弱點**:marker 僅代表「stage 函式回傳 True」，不會自動讓下游 marker 因 prompt/input 改動而失效。`stage_provenance/<stage>.json` 會記 input/output artifact hash 與 prompt hash，能事後追溯 drift；但 resume 判斷仍看 marker。手動刪中間檔但留 marker → resume 會跳過。大改 prompt 後請手動 `rm -f .stage_*_done` 從適當階段重跑。

### Workflow versioning / provenance

`lab/podcast/workflow_versions/<version>/` 固化每版 workflow contract。`v1` 是現況 baseline snapshot；`v2` 先作為可分叉實驗副本，後續 producer-cut / script-validate / package-review 等創作改造在此版本上分歧。

每個 workspace 會寫:
- `workflow_manifest.json`: `workflow_version`、`pipeline_commit`、`prompt_fingerprints`、`agent_profile`、`agent_model`、`tts_model`、`validator_versions`、`stage_contracts`、`created_at/updated_at`。
- `stage_provenance/<stage>.json`: stage input/output artifact hashes、prompt version/hash、agent/TTS model、command、validator result、manual approval marker。
- `scripts/ep_N_lineage.json`: scriptwrite / series-polish / script-review / producer-cut / tts-prep 的 before/after hash、edit event、human approval marker。

Fresh workspace 預設 `v1`。`--workflow-version v1|v2` 只在建立或 legacy workspace 補 manifest 時生效；已有 manifest 的 workspace resume 以 `workflow_manifest.json.workflow_version` 為準，CLI 傳入不同版本會 fail-fast，避免同一 workspace 混用 prompt/stage contract。

### Range 控制

| flag | 行為 |
|---|---|
| `--skip-to S` | 從 stage S 起跑;前置 stage marker 缺失會 abort 並列出缺項 |
| `--stop-after S` | 跑到 S 為止 |
| `--only-stage S` | 只跑 S(等價 skip-to=stop-after,同樣驗證前置 marker) |
| `--only-episode N` | 過濾單集(影響 scriptwrite / script-review / synthesize / audio-qa / subtitle) |
| `--parallel N` | scriptwrite + script-review 並發度(預設 3) |
| `--workflow-version V` | 指定版本化 workflow contract(`v1`/`v2`)。新 workspace 預設 `v1`;resume 讀 `workflow_manifest.json`,衝突版本報錯 |
| `--tts-model M` | 凍結該 workspace 的 TTS model(`gemini-3.1-flash-tts-preview` / `gemini-2.5-pro-tts` / `gemini-2.5-flash-tts`),寫入 `.tts_model` sidecar,synthesize stage 讀回。resume 以 sidecar 為準;衝突的 `--tts-model` 報錯。省略 = 用 `synthesize.py` 的 env 預設。詳見 §3 |
| `--force` | 繞過前置 marker 檢查(僅在手動驗證 artifacts 完整時使用) |
| `--ignore-gates` | 無視兩道人工核准 gate,一路跑到底(還原舊全自動) |

### 四個 QA gate

| stage | gate 條件 | 判讀檔 |
|---|---|---|
| plan-review | 含 `REWRITE_NEEDED` 或 `FAIL` 計數 >2 → 失敗 | `plan/review.md` |
| script-review | 任一集 `ep_N_review.md` 含 `REWRITE_NEEDED` → 失敗 | `scripts/ep_N_review.md` |
| series-polish | 含 `STRUCTURAL_ISSUES_NEED_RESCRIPT` → 失敗;guard 每個 script 仍以 `END_OF_SCRIPT` 結尾(polish 不可剝 sentinel) | `plan/series_polish.md` |
| tts-prep | `plan/tts_prep.md` 含 `READY_FOR_TTS` 且不含 `BLOCKED` | `plan/tts_prep.md` |

---

## 2. overview.md 格式契約

**Voice Mapping 是 host 名 + voice 配對的唯一 source of truth。** `synthesize.py:101` `_parse_overview_hosts` 與 `ops/podcast_upload.sh:118` 都解析這個區塊;格式不對 = host 解析失敗。

```markdown
### Voice Mapping
- **Marcus (Charon)**: Speaker1
- **Priya (Leda)**: Speaker2
```

Regex: `\*\*([^*()]+?)\s*\(([^)]+)\)\*\*:\s*(Speaker[12])`

### 強制規則(architect.md prompt 已寫入)

1. **必須有兩條** `**Name (Voice)**: SpeakerN` 行，否則 synthesize 在 `_parse_overview_hosts:110-117` hard-fail。
2. **host 名不可含 `:` 或 `*`**——`audio_qa.py:47` / `synthesize.py:177` / `subtitle.py:55` 統一用 `[^:*]+` 解析 speaker tag(commit `aa47c723` 後對齊)。空格、連字號、unicode 字母都可以。單詞名仍較好讀但已非硬性要求。
3. **tts-prep 之前 voice 必須是 `(TBD)`**，tts-prep stage 才替換成實際 Gemini voice 名。

> 歷史 bug:upload.sh 曾用 `### Host A:` regex 抓 host(prompt 從未規範的格式)，5/6 production workspace 全空 → metadata.json `hostNames=[]`。修於 `aa47c723`，改用 Voice Mapping。

---

## 3. 音頻生成（最容易壞的那段）

### Vertex 認證

`synthesize.py:43-51` `load_dotenv(ROOT/.env)` 讀 `lab/podcast/.env`:

```
GCP_PROJECT_ID=gen-lang-client-*****
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=gen-lang-client-*****-*.json
TTS_MODEL=gemini-2.5-flash-tts   # 部署預設(.env,2026-06-02 起);synthesize.py 程式碼預設亦同
```

- 走 **Vertex AI 模式**(`vertexai=True`, `synthesize.py:326`)，非 AI Studio API key。
- `GOOGLE_APPLICATION_CREDENTIALS` 是 service account JSON 路徑(相對路徑會解析成 script-dir 絕對路徑)。
- **金鑰歸屬與輪替**:當前 SA 是 GCE 預設 compute SA(`986467056383-compute@developer.gserviceaccount.com`)，權限過大。中期應換成 minimal-scope SA(僅 `roles/aiplatform.user`) + 定期輪替。換機/換帳號時更新 `.env` 與金鑰 JSON 即可，不需改 code。
- `.env` 與金鑰 JSON 已被 `.gitignore`(`lab/podcast/.env`、`lab/podcast/gen-lang-client-*.json`)。

### 模型選擇

| TTS_MODEL | 用途 |
|---|---|
| `gemini-2.5-flash-tts` | **當前預設**(2026-06-02 起)，速度快、配額寬、最便宜($0.30/$2.50 per 1M);品質實測足夠。腳本依此 family 的 palette 生成(見下 family-parametric) |
| `gemini-3.1-flash-tts-preview` | 可選,3.1 官方 audio-tag 名詞情緒集 + per-host director notes(`### PERFORMANCE`)，表情/節奏最佳但 ~8× 貴 |
| `gemini-2.5-pro-tts` | 可選,自然度高但配額嚴(易 429) |

**TTS 選法（兩種,優先序）**：
- **per-workspace 凍結（建議）**：`--tts-model M`(或 dashboard SETTINGS 面板的 TTS MODEL 下拉)→ 寫 `.tts_model` sidecar → `stage_synthesize` 在 synth 前讀回注入 `TTS_MODEL` env。這是**單一還原點**,`/start`、`/resume`、`/approve`、手動 `--skip-to synthesize` 全部經此,故選定後整個 workspace 一致。resume 時 sidecar 為準,衝突的 `--tts-model` 報錯(同 `--mode` 慣例)。
- **全域預設**：沒給 `--tts-model` / sidecar 不存在 → 落 `synthesize.py` 的 `TTS_MODEL` env 預設(`.env`)。

**Stage 1-10 agent 選法**:
- `--agent-profile claude`(或 env `PODCAST_AGENT_PROFILE`)選 billing/profile。**目前只有 `claude`**(走正常 Claude Code 帳號);kimi profile 已於 2026-08-09 隨 Kimi Code plan 一併移除,傳入 `kimi` 會 fail-fast。單一真相 = `agent_profiles.py:PROFILE_DEFAULT_MODEL`(profile→預設 model),要新增第三方 billing 後端在該 registry 加 key,並同步 `monitor/server.py:ALLOWED_AGENT_PROFILES`、`static/app.js:ALLOWED_AGENT_PROFILES`、`index.html` 下拉；`monitor/test_server.py` 的雙向集合契約會拒絕漏加或殘留。
- `--agent-model M`(或 env `PODCAST_AGENT_MODEL`)覆寫 agent model。預設:`claude=opus[1m]`;legacy `PODCAST_CLAUDE_MODEL` 仍支援但只建議當 Claude profile 的相容入口。
- pipeline 會寫 `.agent_profile` / `.agent_model` sidecar;dashboard `/approve`、`/resume`、`/rerun` 無參數續跑時讀回,避免人工 gate 後掉回預設 Claude。要切回 Claude,下一次 CLI 明確帶 `--agent-profile claude` 或 dashboard SETTINGS 改回 `claude` 再開新 run。

**audio-tag palette 是 family-parametric(重要)**：palette 的**唯一 SoT 是 `tts_tags.py:TAG_CONCEPTS`** —— 每個 delivery concept(excitement / whisper / 停頓…)一列,每個 TTS family("3.1"/"2.5"…)一欄(該 family 的 surface tag,缺欄=該 family 不支援)。`palette(family)` / `sanitize_tags_for_family()` / `render_palette_md(family)` 全衍生自它,加新世代 = 加一欄。關鍵事實:Gemini 對**不支援的 inline `[tag]` 不是靜默丟棄,而是當字面唸出來**(社群實證,Google 無 unsupported-tag 契約)—— 所以 palette 必須跟著合成的 family 走。

- **源頭相容(scriptwrite 注入)**:腳本由 stage agent(`PODCAST_AGENT_PROFILE`/`PODCAST_AGENT_MODEL`,預設 `claude` + `opus[1m]`)生成**一次**。`pipeline.py:inject_tts_palette` 在組 scriptwriter / script_review / tts_prep prompt 時,依該 workspace 實際合成的 family(`resolve_tts_family` = `.tts_model` sidecar → `DEFAULT_TTS_MODEL`)注入 `{tts_engine}`/`{tts_family}`/`{tts_palette}`(= `render_palette_md(family)`)。**腳本天生只用目標 family 的 tag**,reviewer 也按同一 palette 驗。未知 family → loud-fail(要求先在 `TAG_CONCEPTS` 註冊,不靜默猜)。`prompts/*.md` 不再手抄 palette(`test_palette_consistency` 從「3 處一致」改為「placeholder + render round-trip」,drift 結構上不可能)。
- **記錄真實 family**:scriptwrite 成功寫 `.script_tts_family = resolve_tts_family(workspace)`(**非寫死 3.1**)。
- **合成端 backstop(defense-in-depth)**:`synthesize.py:_sanitize_dialogue` 仍對每句套 `sanitize_tags_for_family(text, TTS_FAMILY)` —— 把任何非目標 family 形的 tag 改寫成該 family 形 / 無對應則 strip,**非 palette 括號(如 `[NEW HABIT]`)原樣保留**。這在「腳本 family ≠ 合成 family」(跨 family 混用、或 registry 之前寫的 legacy 腳本)時兜底,正常流程下因源頭已相容多為 no-op。每集 parse 後印 `tag-sanitize (family X): N cross-family tag(s) made safe`。`stage_synthesize` 另比對 `.script_tts_family` 與 `.tts_model`(缺 sidecar 視為 `3.1`),不一致記一筆 informational(非硬 block —— sanitize 已保安全)。
- 不同 model 在單一 workspace 混用仍可(每集分別 synth)但**不該作為錯誤恢復策略**:`the_let_them_theory` workspace 就出現 ep1-2=pro、ep3-5=flash、ep6-8 缺席的混亂混用,難 debug —— per-workspace 凍結正是為了根治此問題。

### 655s padding bug 防線(必讀)

Vertex `gemini-2.5-pro-tts` 已知 bug(finishReason=OTHER，Google WONTFIX #922):batch 結尾若是很短的 turn，音檔會被 silence 強制 pad 到 ~655s。**`synthesize.py` 有三層防線**:

1. **`MIN_BATCH_END_WORDS=5`(`:256`)** + **`MAX_WORDS_PER_BATCH=800`(`:67`)**:`chunk_turns()` 確保 batch 不結束於 <5 字 turn(`:289`/`:303`)。
2. **system prompt 刻意不用 `Speaker1:` 行格式**(`:128-139`):那行被 TTS 當對白唸出 persona 描述，會撐到 655s。
3. **`_trim_trailing_silence()`(`:374`)**:reverse + `detect_leading_silence` 切 <-45dBFS 尾巴，保留 400ms 自然呼吸。

> 改 `chunk_turns` 或 system prompt 前先讀完上述三段。動掉任何一層都會復發 655s bug。

### 並發 / 重試 / timeout

| env | default | 說明 |
|---|---|---|
| `TTS_MAX_CONCURRENT` | 10 | ThreadPoolExecutor batch 並發上限 |
| `TTS_RETRY_ATTEMPTS` | 4 | 429/503 outer-level 重試 |
| `TTS_BATCH_TIMEOUT` | 600 | 單 batch 的 future wall-clock timeout(秒) |
| `TTS_MASTER_LUFS` | -16 | Apple Podcasts 標準整合響度 |
| `TTS_MASTER` | 1 | 設 0 跳過 loudnorm(無 ffmpeg 自動降級) |

**429 特殊退避**(`synthesize.py:419-422`):per-minute quota 必須等 ≥60s，所以 backoff = `60 + 15*attempt + random*5`，其他 transient 用 `2^attempt`。**這條不能改成統一指數退避**——429 用指數退避會 thrash。

#### Agent-stage 重試(stage 1-10 的 `claude -p`)

| env | default | 說明 |
|---|---|---|
| `PODCAST_STAGE_RETRIES` | 3 | 單一 agent stage 的總嘗試次數(含首次) |
| `PODCAST_STAGE_RETRY_BASE` | 5 | 退避基數(秒);backoff = `min(90, base*2^(n-1)) + jitter`,429 強制 ≥60s |

`pipeline.py:_run_claude_with_retry`(`:549`)包住所有 agent stage(prep/analyst/architect/plan-review/enricher*/scriptwriter/script-review/tts-prep)。**每次重試都是全新 `claude -p`(不 --resume)** —— transient 失敗最常見的是 `400 ... thinking/redacted_thinking blocks ... cannot be modified`(CLI agent loop 在 extended thinking + tool use 下汙染了對話歷史的 thinking 區塊簽章;壞區塊存在 transcript 裡,`--resume`/`--continue`/`--fork-session` 都會重送 → 重現同一個 400,**只有全新對話能繞過**)。

成敗判定看 stream-json **terminal `result` event 的 `is_error`**,不是 exit code(CLI 可能 `subtype:"success"` 但 `is_error:true` 且 exit 1)。retryable 分類(`_is_retryable_claude_failure` `:455`):thinking-block 400 / 429 / 5xx / overload / connection → 重試;auth / 一般 400 / **subprocess timeout** → fatal 不重試(逾時重試 3× 純燒錢,要調 stage timeout 而非靠重試)。

重試要便宜的前提是 **prompt resume-aware**:`architect.md` Step 0 會先列既有 `overview.md` + `ep_*.md`、跳過已完成集數,只補缺的。新增 agent stage 或讓既有 stage 可重試時,prompt 必須遵守同一條 idempotency 契約(讀既有產物 → 只補缺口),否則重試會整批重做。

### ffmpeg loudnorm mastering

兩遍 EBU R128(`_master_with_loudnorm` `:550`)。Pass1 跑 `loudnorm=...:print_format=json`，從 **stderr** 用 `re.search(r"\{[\s\S]*?\}")` 撈 measured params;Pass2 套 `linear=true` + 48kHz MP3 192k 輸出。Target `-16 LUFS / TP=-1.5 / LRA=11`。失敗 fallback 純 export(`:628`)，音量不會正規化但不阻斷。

**ffmpeg 必裝**:`brew install ffmpeg`。

### Batch 快取

`<cache>/batch_NN.wav` 存單 batch 中間結果。Phase 1 載入既有 wav(跳過 API)，Phase 2 只跑缺的。synthesize **中斷續跑** = 直接重跑同指令，已成功的 batch 自動 skip。

---

## 4. 字幕(Whisper forced alignment)

`subtitle.py` 用 **`stable-whisper`**(stable-ts 套件)`model.align(audio, plain_text, language="en")`——**forced alignment 而非轉錄**，餵 script 文字當 ground truth。

| 設定 | 值 | 備註 |
|---|---|---|
| 預設模型 | `medium`(`:238`) | docstring `:22` 寫 `base` 是過時 |
| 語言 | 寫死 `"en"`(`:219`) | **非英文 podcast 無法正確對齊**——未支援中文 |
| 平行度 | 不可平行 | 每集 `load_model` 重載(`:212`)，RAM 大；序列 for-loop 處理多集 |

### speaker 對齊的隱形假設

`build_word_speaker_map`(`:116`)按 **word index** 對應 speaker:假設 Whisper 對齊出的字數 **完全等於 script 字數**。若 alignment 漏字/多字 → speaker tag 整段位移，且**無 assertion、無 warning**(silent corruption)。

**判讀**:聽 SRT 開頭幾秒，若 speaker tag 與真實對話對不上 → alignment 出問題。當前無自動偵測。

---

## 5. 從生成到上線(銜接資料流)

```
lab/podcast/workspaces/<slug>_<hash>/
  workflow_manifest.json                ← workflow 版本 / prompt fingerprints / model / validators / stage contracts
  stage_provenance/<stage>.json         ← 每階段 input/output artifact hash + prompt/model/validator provenance
  plan/overview.md                  ← Voice Mapping(host SoT)
  scripts/ep_N_{pro,flash}.mp3      ← TTS 產出
  scripts/ep_N_{pro,flash}.srt      ← Whisper 對齊
  scripts/ep_N_{pro,flash}.meta.json ← {"tts_model": "<full TTS model id>"} sidecar(monitor 顯示用;檔名仍維持 pro/flash 短 tag 以維持下游 podcast_upload.sh / regex 相容)
  scripts/ep_N_script.md            ← 原稿
  scripts/ep_N_lineage.json         ← 腳本 before/after hash 與 stage edit lineage
       │
       │  ./ops/podcast_upload.sh <workspace>   (config gap-filled from lab/podcast/.env)
       ▼
staging /tmp/podcast_upload_<sid>/   ← 重組成 ep_NN/ 結構
       │  aws s3 sync --delete  (Lightsail Object Storage, AWS_PROFILE=kg-podcast)
       ▼
s3://kg-podcasts-prod/<sid>/
  metadata.json                     ← upload.sh 從 overview.md 解析生成(內嵌逐集字幕 + coverImageURL)
  cover.png                         ← cover stage 產 plan/cover.png,upload.sh 搬上 series 層(無則略)
  ep_NN/{audio.m4a, subtitle.srt, script.md}
  ep_01/preview.m4a                  ← upload.sh 對 ep_01 stream-copy(ffmpeg -t 180 -c copy)出 free-tier 試聽;既有 series 由 ops/podcast_preview_backfill.py 回填
       │
       │  uv run --with boto3 python → 重建 s3://kg-podcasts-prod/index.json(put_object)
       ▼
backend /api/podcasts*               ← podcast.py router(分層授權 guest/free/pro;free 的 audio 端點服務 ep_01/preview.*,proxy 走 boto3 GetObject)
                                       封面:GET /api/podcasts/{sid}/cover(image/png,缺則 404)
       │
       ▼
iOS PodcastSyncService               ← Bearer JWT 拉 series/episode/progress(無 iOS 改動)
```

### upload.sh 憑證 / 環境模型(踩雷史,必讀)

bucket `kg-podcasts-prod` 是 **Lightsail Object Storage,獨立 AWS 帳號 `579635680285`**。寫入只認該 bucket 自身的 access key = 本機 `~/.aws` 的 **`kg-podcast` profile**(`obj-mgmt` user)。default profile(`MaxChen228` @ `967512079054`)對它**只有跨帳號讀**,寫 `PutObject` 一律 `AccessDenied`。

`podcast_upload.sh` 開頭 **gap-fill** 從 `lab/podcast/.env`(gitignored)讀 `AWS_*` / `PODCAST_*`(僅補 caller 未 export 的 key,caller 優先)。故 dashboard ▶ upload / publish stage / 裸 CLI **三條路**都自動拿到 `AWS_PROFILE=kg-podcast` + `PODCAST_BUCKET`(monitor **不** load .env,過去就是這個缺口導致 publish 全 AccessDenied)。`aws` 與 boto3 都自動讀環境的 `AWS_PROFILE`。`.env` 必含:`PODCAST_BUCKET=kg-podcasts-prod` / `PODCAST_BUCKET_REGION=ap-northeast-1` / `AWS_PROFILE=kg-podcast`(profile 名非密鑰)。**值需 bare 不加引號**(gap-fill 用 `read`,不做去引號;`AWS_PROFILE="kg-podcast"` 會連引號一起 export)。

兩段內嵌 Python **一律走 `uv run`**(禁裸 `python3`):metadata 段 `uv run python`、index 段 `uv run --with boto3 python`(host python3 無 boto3,過去靜默留下 stale index)。metadata 段把既有 remote metadata 經 **temp file** 傳入(內嵌逐集字幕 ~1MB,當 argv 會 `Argument list too long`)。

### upload.sh idempotent 保證

- `_SERIES_ID_RE = ^[a-z0-9_]+$` 預先驗證 series_id(對齊 backend `_SERIES_ID_RE`)
- 抓 S3 上既有 `metadata.json` 保留 `createdAt`(避免 re-upload 重設創建時間)
- pro/flash 同集去重(pro 優先)
- m4a 與 mp3 同檔名時 m4a 優先(post-Track-B 預設)
- `aws s3 sync --delete` = 原子換檔(S3 GetObject 永遠對 object 整版,無「半傳輸」概念)
- index 重建本機跑 boto3 → `put_object`,**不需 flock**(S3 last-writer-wins;比舊 SSH+flock 弱,但 race window 只有秒級,影響限於 dashboard 暫時看到舊 index)
- Content-Type 逐檔覆寫(`.m4a`→`audio/mp4`, `.srt`→`text/plain`, `.json`→`application/json`),預防 AVPlayer 拒收 `binary/octet-stream`

### metadata.json schema

由 `ops/podcast_upload.sh:185-196` 產生，`PodcastSeriesDetail`(`SyncService.swift:17`)消費:

| 欄位 | 來源 | 備註 |
|---|---|---|
| `id` | basename(workspace) | = series_id |
| `title` | overview.md H1 | |
| `author` | overview.md `**Type**:` | **語意錯置**——實際是書籍類型而非作者(未修;影響低) |
| `hostNames` | Voice Mapping `**Name (...)**: SpeakerN` | 已修於 aa47c723 |
| `color` / `coverPattern` | 硬編碼 `#5B8C5A` / `waves` | 程序化封面退路;`coverImageURL` 缺(legacy/pre-cover)時 iOS 用這兩個畫 |
| `coverImageURL` | `cover` stage 有產 `cover.png` → `/api/podcasts/<sid>/cover?v=<sha16>`,否則 `null` | backend proxy 路徑(query 僅 cache-bust;iOS 有值才拉遠端封面圖,否則退程序化) |
| `episodes[].durationSec` | ffprobe(缺則 0) | |
| `episodes[].subtitleContent` | inline SRT 全文 | iOS 端直接消費，省一次認證 RTT |

`index.json` = `metadata.json` 去掉 `episodes` + 加 `episodeCount`(故 `coverImageURL` 也在 index entry,series list 即可顯示封面)。

`localAudioPath` **不在後端 JSON**，是 iOS SwiftData 欄位，由 `PodcastDownloadManager` 寫入 `Documents/podcast-downloads/<sid>/<remoteId>.mp3`(離線下載)。

### legacy mount 已下線

`/api/podcast-media/` StaticFiles mount 已於 **2026-05** 移除(commit `7353d31a`)。
- 移除依據:生產 deprecation log 12 天零 hit + 認證端點 734 hit → 全 client 已遷移。
- 唯一 audio 路徑:`GET /api/podcasts/{sid}/{ep_num}/audio`(Bearer JWT，支援 Range/206)。
- 防回歸測試:`test_legacy_podcast_media_mount_removed`(test_podcast_api.py)。

### 自動上傳閉環(pipeline `publish` stage)

`pipeline.py` 跑完 `subtitle` 後自動執行 `publish` stage → `ops/podcast_upload.sh <workspace>` → verify series 現身 `index.json`(retry+backoff,1800s timeout)。**合成完成即上線,無手動步驟**。憑證/bucket 由 `ops/podcast_upload.sh` 從 `lab/podcast/.env` gap-fill(`AWS_PROFILE=kg-podcast` 寫權限 + `PODCAST_BUCKET`,見 §upload.sh 憑證/環境模型);caller 已 export 則優先。未設且 .env 缺則 publish loud-fail（回 False,寫 error log,不 crash、不靜默)。dashboard `POST /api/workspace/{ws}/upload` 手動上傳保留為冪等修復路徑。

### audioFormat 解析(S3 模式 mp3/m4a)

backend `_audio_filename`(podcast.py)S3 模式**讀 series `metadata.json` 的 `audioFormat`** 決定 `audio.{m4a,mp3}` key;欄位缺失則 probe bucket(head_object m4a→mp3),per-(bucket,series) 快取。upload.sh 與 backfill 都會寫 `audioFormat`。**歷史 bug**:舊碼 S3 模式硬回 `audio.m4a`,legacy mp3 series 的 audio 端點 404(bucket 一直空才沒爆),修於 `f4f6b013`/`beaa33c4`。

### served-disk → S3 回填 + drift reconcile(`ops/podcast_backfill_disk.py`)

Track-B 切 S3-only 時,既有在 backend 實例磁碟 `/app/data/podcasts/`(served 佈局)的 series 未遷移 → bucket 空 → `/api/podcasts` 回 `[]`(2026-06 incident)。回填工具消費 served-disk 佈局(非 workspace),容器內 boto3 執行:

```bash
# 1. dry-run 看計畫(預設;不寫)
./ops/devops_kg_safe.sh container-script ops/podcast_backfill_disk.py
# 2. 實際上傳(純新增、不刪、head_object 冪等 skip-existing)
./ops/devops_kg_safe.sh container-script ops/podcast_backfill_disk.py --execute
# 3. drift 檢查(唯讀;disk 有/S3 缺 → 報 missing_in_s3 + exit≠0)
./ops/devops_kg_safe.sh container-script ops/podcast_backfill_disk.py --check
```

注入 `audioFormat`(探 ep_01 副檔名)、content-type 對齊 upload.sh、`index.json` 永遠重傳(防殘留空 index)、`_key_exists` 對非-404 故障 loud-fail(不誤報 drift)。`--series <id>` 限定範圍。

**drift 安全網兩面**(來源不同,勿混):
- **served-disk↔S3**(上述 `--check`):覆蓋 legacy 實例磁碟 series。回填後恆 in-sync,ad-hoc 驗證用。
- **workspace↔S3**(monitor `GET /api/remote/reconcile`):覆蓋「pipeline 合成 audio 但 publish 上傳靜默失敗」。新世界 series 直接 pipeline→S3、不落實例磁碟,故 drift 來源是 lab workspaces。回 `{drifted:[{workspace, reason:"synthesized_not_published"}], publishedCount}`。

### 封面重發布(`ops/podcast_cover_publish.py` — audio-decoupled)

**只換/補既有 series 封面時用這個,不要用 `upload.sh`。** `upload.sh` 從 local workspace 重組 audio 並 reconcile(prune S3 orphans);若 local 與 S3 不同步(e.g. workspace audio 後來被清、或 metadata 有 `audioAvailable:false` 佔位 episode),它會重生 metadata、可能丟佔位 episode、重置 `createdAt`、甚至誤刪 audio。封面變更必須與 audio 解耦。

```bash
set -a; source lab/podcast/.env; set +a   # PODCAST_BUCKET + AWS_PROFILE 寫權限
# 生成層(若還沒 cover.png):跑 pipeline cover stage 或派 agent 照 prompts/cover.md 漏斗,產出 <ws>/plan/cover.png
# 發布層(原子上線):
uv run --no-project --with boto3 python ops/podcast_cover_publish.py --all --workspaces-dir lab/podcast/workspaces            # dry-run 預覽
uv run --no-project --with boto3 python ops/podcast_cover_publish.py --all --workspaces-dir lab/podcast/workspaces --execute  # 實際寫
uv run --no-project --with boto3 python ops/podcast_cover_publish.py --all --workspaces-dir lab/podcast/workspaces --check    # cover⟷metadata drift
```

**原子靠排序**(S3 無跨-object 事務):① PUT `<sid>/cover.png`(新 key,metadata 未指 → client 看舊狀態) → ② RMW `<sid>/metadata.json` set `coverImageURL=/api/podcasts/<sid>/cover?v=<sha16>`(單-object 原子替換,可見性翻轉,先①後②保證 metadata 指向時 cover 必已在;`v` 為 cover bytes SHA-256 前 16 碼,backend 忽略 query,iOS 用它做本地 cache-bust) → ③ 從 bucket 全量重建 `index.json`(不丟其他 series)。任何中斷點皆安全 → **可重入 + 冪等**(同圖同 URL;不 bump `updatedAt`,body byte-stable;重跑收斂)。`--check` 分類 `in_sync` / `url_without_cover_png`(metadata 指但圖缺 → 404) / `cover_png_without_url`(圖在但 metadata 沒指,②沒跑完) / `unpublished` / `pending_publish`(local 有圖待發,或 local cover bytes 的 sha16 與 metadata `v` 不符)。dry-run 預設、PNG magic + series_id `\A[a-z0-9_]+\Z`(對齊 backend) + published gate(拒對無 metadata.json 的 series 發封面)、404 vs 真實 fault 區分(鐵律 1)。legacy 無 `?v=` 的 cover URL 在無 local bytes 比對時仍視為指向 cover,`--check` 不會誤報；一旦提供 local cover,legacy URL 會被標為待發布以補上 version token。

### Headless 觀測 CLI(`ops/podcast_ops.py` — 不必起 dashboard)

過去要看 pipeline 狀態/花費/drift 都得 `./start.sh` 起 uvicorn + 開瀏覽器。這支 CLI 把同一套 disk-derived 邏輯(`monitor/workspace_status.py`、`monitor/cost.py`,**同一份實作,不漂移**)搬上終端,可 SSH / cron / `| jq`:

```bash
# 純磁碟(免 boto3):
uv run --no-project python ops/podcast_ops.py status   --workspaces-dir lab/podcast/workspaces           # 狀態瀑布 + 集數 + 進度 + 花費
uv run --no-project python ops/podcast_ops.py episodes  <ws> --workspaces-dir lab/podcast/workspaces      # 逐集 plan/script/audio/subtitle 矩陣
uv run --no-project python ops/podcast_ops.py cost      --workspaces-dir lab/podcast/workspaces           # 聚合花費 + by-model(--workspace <ws> 看單一明細)
uv run --no-project python ops/podcast_ops.py covers    --workspaces-dir lab/podcast/workspaces           # 有音頻卻缺 plan/cover.png
uv run --no-project python ops/podcast_ops.py logs      <ws> --last 10 --workspaces-dir lab/podcast/workspaces  # 尾段 pipeline_log 事件(--errors-only 只看 error；失敗的 WHY)
# 需 S3(boto3 + PODCAST_BUCKET,缺則 clean exit 3):
set -a; source lab/podcast/.env; set +a
uv run --no-project --with boto3 python ops/podcast_ops.py reconcile --workspaces-dir lab/podcast/workspaces  # workspace↔S3「合成了但沒上 S3」drift
uv run --no-project --with boto3 python ops/podcast_ops.py series                                            # S3 catalog + 容量
```

- **`status` exit code 給 cron 訊號**:`2`=有 workspace 卡 failed(pipeline_log 有未解決 stage 失敗且無 done marker)、`1`=有 awaiting 人工核准、`0`=全 ok;**不存在的 `--workspaces-dir` 一律 exit 3 硬失敗**(不再靜默 `0 total` 假裝健康)。狀態瀑布與 dashboard sidebar 完全一致(running 僅 dashboard 有 live job tracker 時報,headless 永不臆測)。
- **`--json` 契約**:stdout 只有 JSON(零前綴,`| jq` 可直接吃),所有 banner/cost warning 走 stderr;失敗也走 `{"ok":false,"error":...}` 結構化吐 stdout。
- **每個非終態都「知道為何 + 知道下一步」**:`status` 在表格(`AUD` 音檔集數 / `AGE` 距上次 pipeline_log 活動 / `GATES`)下,為每個 failed/awaiting/idle 印 reason + **可複製的 next_step 指令**:
  - `failed` → 帶 `error`(尾段最近一筆 error event 的 msg)+ `failed_at`(ts)+ `--skip-to <stage>` resume 指令;細節用 `logs <ws>` 看完整 retry 敘事,不必手挖 `pipeline_log.jsonl`。
  - `awaiting` → `awaiting_gate`(plan/script)+ `touch .../.{gate}_approved` 核准指令。
  - `idle` → **裸 auto-resume 指令**(不焊 `--skip-to`:marker drift 會讓 81%-done ws 誤報 `prep`;裸跑由 pipeline 自身 `detect_resume_point` 定點)。`resume_stage` 欄保留 marker 原始真相供參。
- **failed ≠ 集數不全**:一個 workspace 可能七集全綠卻 `failed`——多半是 `publish` stage 上傳失敗(synthesized-not-published),此時 `reconcile` 會同時抓到。

---

## 6. 排障 runbook

### Synthesize 中途中斷(let_them 案例)

症狀:某些 ep 有 pro.mp3、某些只有 flash.mp3、某些缺;`pipeline_log.jsonl` 顯示 synthesize 後沒有 `.stage_synthesize_done`。

排查:
1. `rm .stage_synthesize_done`(若存在)。
2. `uv run synthesize.py workspaces/<name>/scripts/` 直接重跑——已成功的 batch 走 cache，缺的補。
3. 若混用 pro/flash 想統一回 pro:`rm scripts/ep_N_flash.{mp3,srt}` + `rm -rf scripts/.cache/*` 後重跑。
4. 若連續 429:檢查 `TTS_MAX_CONCURRENT`(降到 3-5)、確認金鑰專案配額(`gcloud --project <pid> ai-platform quotas list`)。

### scriptwrite/script-review 失敗看不到 log

根因:`pipeline.py:401,418` 平行子行程傳 `log=None`，agent stderr 不進 `pipeline_log.jsonl`，只到 stdout。

繞道:
1. `--parallel 1` 改序列跑，stderr 進 `pipeline_log.jsonl`。
2. 或 `--only-stage scriptwrite --only-episode N` 跑單集直接看 stdout。
3. 各 worker 失敗仍會寫 `claude_<label>.stderr.log`(workspace 根目錄)。

### audio-qa FAIL 判讀

`audio_qa.json` 內每集會有 `wpm`、`max_silence_ms`、`peak_dbfs`、`avg_dbfs`。
- `wpm < 110 or > 200` = TTS 撐長或念太快;通常是 chunk 問題或 655s padding 沒清乾淨。
- `max_silence_ms > 4000` = 中間有可疑長靜音;聽 audio 確認。
- `peak_dbfs >= -0.5` = clipping;loudnorm 失敗或 fallback 純 export。
- `avg_dbfs < -30` = 整體幾乎靜音;TTS 失敗或檔損。

### 字幕 speaker tag 整段錯位

根因:Whisper 對齊字數 ≠ script 字數(見 §4)。當前無自動修復。
- 短期:用文字編輯器手動切 SRT 修正開頭 speaker tag。
- 長期:`build_word_speaker_map` 應改成 token-overlap 對齊而非 index 對齊。

### plan-review / script-review REWRITE_NEEDED

不是錯誤，是 QA gate。讀對應 review.md 看 reviewer 指出的問題:
- plan-review:`plan/review.md`
- script-review:`scripts/ep_N_review.md`

調整 prompt / source 後 `rm .stage_<stage>_done` + 重跑該 stage。連續 REWRITE 3 次以上要懷疑是 reviewer prompt 過嚴而非 plan 真的壞。

### Voice Mapping 解析失敗

症狀:synthesize `_parse_overview_hosts` 報 `Expected 2 hosts in Voice Mapping`，或 upload.sh 印 `⚠ no Voice Mapping section found`。

修法:
1. 確認 `plan/overview.md` 內有 `### Voice Mapping` 區塊且兩行 host 都是 `**Name (Voice)**: SpeakerN` 格式(見 §2)。
2. 確認 voice 不再是 `(TBD)`——tts-prep stage 應已替換。若沒，`rm .stage_tts-prep_done` 重跑 tts-prep。

---

## 7. 已知技術債(優先級排序)

| 優先 | 項目 |
|---|---|
| 高 | compute 預設 SA 金鑰權限過大，應換 minimal-scope SA 並輪替 |
| 中 | `subtitle.py:22` 寫 base 實 medium;`tts_prep.md:24` 寫 Flash 實 pro |
| 中 | scriptwrite/script-review 平行 stage 吞 agent 錯誤(`log=None`) |
| 中 | Whisper speaker tag word-index 對齊脆弱、無 assertion |
| 中 | 缺 unit test:`chunk_turns` / `_parse_overview_hosts` / `parse_script` / `script_word_count` |
| 低 | `chunk_turns` 邊界 turn 可超出 800 word soft budget(無硬上限) |
| 低 | `author` 欄位塞書籍類型而非作者 |
| 低 | `color`/`coverPattern` 全 series 硬編碼 |
| 低 | metadata.json `subtitleContent` 缺與否未做 schema validation(`subtitle_content=null` iOS 會 fetch fallback，但無 warning) |

---

## 8. 監控(`monitor/server.py` + `monitor/cost.py`)

本機 FastAPI + uvicorn dashboard，預設 `127.0.0.1:8765`。

**單命令流程**(預設):跑 `uv run pipeline.py <epub>` 時,`pipeline.py:_ensure_dashboard_running()` 會自動 idempotent 起 dashboard + open 瀏覽器到 `?ws=<workspace>`。`PODCAST_VERBOSE` 預設 `"1"`(設 `"0"` 才關),events.jsonl 一定產生。

Env opt-out:
- `PODCAST_NO_DASHBOARD=1` — 不起 dashboard、不開瀏覽器
- `PODCAST_DASHBOARD_PORT=N` — 換 port
- `PODCAST_VERBOSE=0` — 關 stream-json(events.jsonl 不寫,cost 不算)

純手動操作 dashboard(不跑 pipeline,單看舊 workspace):`./start.sh [port] | --stop`。idempotent 啟停 wrapper(PID file、`lsof` 清 port、`nohup uv run`、curl 健康檢查)。

Endpoints:

**Read**(觀測):
- `GET /api/workspaces` — workspace 名稱列表(`[name, ...]`,back-compat 形狀)
- `GET /api/workspaces?full=1` — sidebar 用,每個 workspace 回 `{name, status, milestones, gates, progress, n_stages_done, n_stages_total, episode_count, created, last_updated, total_usd, claude_usd, tts_usd, has_cost_data, active_job}`。
  - **`milestones[]`(進度真相層)** — 四個產物關卡 `{key,label,done,total,ratio}`,順序 `plan→script→audio→subtitle`。`target` 集數 = `max(plan/episodes/ep_*.md, scripts/ep_*_script.md, ep_*_{pro,flash}.mp3, ep_*_{pro,flash}.srt)`;plan 關卡 binary(`plan/overview.md` 存在 → ratio 1.0),其餘三關 `ratio = min(1, done/target)`。`progress` = 四 ratio 均值(整體進度標量;前端 sidebar 改以四條 per-gate ratio bar 各自渲染,此值目前不直接渲染,保留供排序/未來用)。**刻意不用 stage marker**:marker 是 pipeline 自我記帳,rerun 砍 marker / 部分還原 / 手動清都會與實際產物脫鉤,實測 marker 數與「離成品多遠」近乎反相關(`flow` 0 markers 卻有 8 集音訊 vs 他者 9/13 markers 零音訊)。`n_stages_*` 保留僅供 status cascade + 向後相容。
  - **`created`** — workspace 加入時間 epoch。SoT 為 `<ws>/.created` sidecar(epoch float);不存在時灌目錄 birthtime(macOS `st_birthtime`,Linux 退 `st_mtime`)並寫回 `.created`,防後續 rsync/還原重設 inode birth time。sidebar 按此分組。
  - **`gates[]`(兩道核准 gate 三態)** — `[{key:"plan",state},{key:"script",state}]`,`state ∈ passed|awaiting|pending`。`passed` ⇔ 下一相已有產物(`n_script>0` / `n_audio>0`)或 `.*_approved` 標記存在;`awaiting` ⇔ 本相完成、下一相空、未核准;`pending` ⇔ 本相未完成。前端側欄三相雙閘軌 + `awaiting` 狀態由此渲染。
  - status ∈ `running|done|failed|awaiting|idle|fresh`,cascade 優先序如左所列(`awaiting` 介於 failed 與 idle:任一 gate `awaiting` → 工作區 `awaiting`);cost 按 model family 切(`tts` substring → tts_usd,其餘 → claude_usd);`active_job` 為 `{job_id,label,kind}` 或 null。pipeline kind 的 job 透過 `<ws>/.pipeline_job_id` sidecar(由 pipeline.py 在 PODCAST_JOB_ID env 存在時寫入)反查 workspace
- `GET /api/workspace/{ws}/snapshot` — `pipeline_log.jsonl` + `events.jsonl` + stage marker 摘要
- `GET /api/workspace/{ws}/stream` — SSE,每 0.5s tail jsonl,15s heartbeat
- `GET /api/workspace/{ws}/cost` — 成本聚合(前端每 4 秒 poll;見 §8.1)
- `GET /api/workspace/{ws}/episodes` — list 已生成的 episode + variant(pro/flash)+ `model`(完整 TTS id,從 sidecar `.meta.json` 讀;舊集數無 sidecar 時為 `null`,UI 顯示「pro (?)」/「flash (?)」表示世代未知)+ size + has_subtitle
- `GET /api/workspace/{ws}/episodes/status` — 每集四關卡布林 `{ep,plan,script,audio,subtitle,variant,audio_bytes}`,artifact-derived(集合 = plan ∪ scripts,idle workspace 亦回傳);前端 episode matrix 資料源,排除 `ep_N_review.md`/`ep_N_voice_preview.mp3` 干擾項
- `GET /api/workspace/{ws}/episode/{ep}/audio` — MP3 stream(`FileResponse` 處理 Range / 206)
- `GET /api/workspace/{ws}/episode/{ep}/subtitle` — SRT 純文字

**Action**(製作:spawn 子程序回 job_id):
- `POST /api/workspace/{ws}/upload` — `bash ops/podcast_upload.sh <ws>`;422 if 無 ep_*.mp3
- `DELETE /api/workspace/{ws}?confirm=<ws>` — 本地砍 workspace,confirm 字串必須等於 ws_name
- `POST /api/workspace/{ws}/rerun?stage=<S>&episode=<N>&drop_marker=true` — `uv run pipeline.py --only-stage`,預設先砍 `.stage_<S>_done`
- `POST /api/workspace/{ws}/approve?gate=plan|script` — 寫 `.plan_approved`/`.script_approved` + spawn `pipeline.py <ws>` 續跑下一相;gate `pending`(前一相未完成)回 409,`bogus` 回 400
- `POST /api/workspace/{ws}/resume` — spawn `pipeline.py <ws>`(flagless auto-resume,從第一個沒 marker 的階段往後跑到下一道 gate / 完成);前端情境式推進鈕在「非 gate、有未完工」時呼叫(rerun=單階、approve=寫標記再續、resume=純續跑)
- **per-workspace 併發守衛**:`approve` / `resume` / `upload` / `rerun` 四個 spawn endpoint 在開子行程前皆檢查 `_active_job_for_ws(ws_name)`(配對 route 同 sidebar:`metadata.workspace` 或 `<ws>/.pipeline_job_id` sidecar)。同一 workspace 已有 running job → 一律回 **409**,不 spawn、不寫 gate marker、不砍 stage marker。global 上限 `MAX_ACTIVE_JOBS`(預設 4)獨立守不同 workspace 的合計上限
- `POST /api/pipeline/start` (multipart `epub` + `parallel` 1-10 + 選填 `tts_model`) — 存到 `monitor/.uploads/`(預設 cap 200MB)+ spawn 全流程(預設停在計畫 gate 等核准)。`tts_model` 經 server 端 `ALLOWED_TTS_MODELS`(`tts_config.py`)白名單驗證,非法值回 **422**;合法值 append `--tts-model`(寫 `.tts_model` sidecar)
- `POST /api/pipeline/start-saga` (multipart `epubs[]` ≥2 + `title` + `spoiler_mode` + `parallel` + 選填 `tts_model`) — saga(多書連續 feed);`tts_model` 同上驗證/凍結。注意 `approve`/`resume` 續跑無需再帶 `tts_model`——synth 階段一律從 `.tts_model` sidecar 還原

**Jobs**:
- `GET /api/jobs?limit=N`、`GET /api/jobs/{id}?log_bytes=N`、`POST /api/jobs/{id}/kill`
- 同時 running cap = `PODCAST_MAX_ACTIVE_JOBS`(預設 4);超過 spawn 回 HTTP 429

**Remote**(boto3 → Lightsail Object Storage,2026-06 Track B 後不再走 SSH):
- `GET /api/remote/series` — 抓 S3 `index.json` + 用 `list_objects_v2` 算 per-series size + orphan(沒在 index 但有 prefix)
- `GET /api/remote/disk` — bucket 總用量;total 由 `PODCAST_BUCKET_QUOTA_BYTES` env 配置(預設 5 GiB,對應 Lightsail `small_1_0`)
- `DELETE /api/remote/series/{id}?confirm=<id>` — `delete_objects` 批刪 `{id}/` 下所有 key + 重建 `index.json`(`put_object`);回 `{deleted, fully_deleted, remaining, rm_errors, bad_metadata_files}`;`fully_deleted` 走「再 `list_objects_v2` 確認」(防 eventual consistency)

`events.jsonl` 內容:claude CLI stream-json 的 tool-use + `result.modelUsage[*].costUSD`,以及 `synthesize.py` 寫的 `tts_usage` events。

### Monitor env vars(額外於 .env 的 pipeline 變數)

| 變數 | 預設 | 說明 |
|------|------|------|
| `PODCAST_BUCKET` | *(必填)* | Lightsail Object Storage bucket(e.g. `kg-podcasts-prod`) |
| `PODCAST_BUCKET_REGION` | `ap-northeast-1` | 同 Lightsail instance region(免 egress 費)|
| `PODCAST_BUCKET_ENDPOINT_URL` | *unset* | S3-compatible endpoint URL;Lightsail/AWS 留空,R2/minio 才設 |
| `PODCAST_BUCKET_QUOTA_BYTES` | `5368709120`(5 GiB) | UI 顯示「磁碟」總量基準;升級 bundle 時改這個 |
| `AWS_PROFILE` | `kg-podcast`(從 .env gap-fill) | bucket 寫權限身分(Lightsail Object Storage obj-mgmt key,account 579635680285);default profile 跨帳號只讀。亦可改用 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 直接帶 key |

> 2026-06 Track B 前的 `PODCAST_SSH_KEY` / `PODCAST_REMOTE_SERVER` / `PODCAST_REMOTE_DIR` / `PODCAST_SSH_TIMEOUT` 已**廢棄**,monitor 不再讀。**舊 `.env` 留著無害但無效果**。
| `PODCAST_MAX_ACTIVE_JOBS` | `4` | 同時 running 上限,超過 spawn 回 429 |
| `PODCAST_JOB_HISTORY` | `100` | 完成 job log LRU 保留筆數 |
| `PODCAST_MAX_EPUB_BYTES` | `200*1024*1024` | `/api/pipeline/start` upload cap |
| `PODCAST_TTS_PRICING` | (unset) | 暫時覆寫 `VERTEX_PRICING` dict 的 JSON 字串(見 §8.1) |

### 8.1 成本聚合(`monitor/cost.py`)

逐行掃 `events.jsonl`,輸出 `{total_usd, by_stage, by_model, pricing, warnings}`。

**成本來源**:
- **Stage 1-10(agent)**:直接讀 claude CLI stream-json 的 `result.modelUsage[model].costUSD`。Claude profile 時這是 CLI 套 Anthropic 官方單價(含 cache 折扣、1M context premium)算好的值。不自己重算。(若日後接非官方 endpoint 的 profile:該 endpoint 若不回 `modelUsage.costUSD`,dashboard 會有 token 無 USD,須以該家帳單為準。)
- **Stage 11(Vertex Gemini TTS)**:從每筆 `tts_usage` event 拿 `input_tokens` / `output_tokens`,套 `VERTEX_PRICING` dict 算。當前預設(`.env` TTS_MODEL)`gemini-2.5-flash-tts`,$0.30/$2.50 per 1M(audio = 25 tok/sec,無 long tier)。`gemini-3.1-flash-tts-preview` $1.00/$20、舊 `gemini-2.5-pro-tts` $1.25/$10(≤200K)、$2.50/$15(>200K)。event 缺 `model` 欄時 fallback 取當前預設 `gemini-2.5-flash-tts`(`monitor/cost.py:254`)。`verified_against: 2026-06-02`。
- **Stage 12-13**:本地 pydub / Whisper,$0。

**Token 來源優先序**(`synthesize.py:_synthesize_one`):
1. `response.usage_metadata.prompt_token_count` / `candidates_token_count` — Vertex 回傳真值
2. Fallback 估算:`input ≈ len(prompt)/4`、`output ≈ audio_seconds × 25`(Google 官方 25 tokens/sec)。event 標 `usage_source: "estimated"`,dashboard 顯示 ⚠ warning。

**改 Vertex 單價**:編輯 `VERTEX_PRICING`(SoT 即程式碼),或 env `PODCAST_TTS_PRICING='{"model":{...}}'` 暫覆寫。改完同步本節 `verified_against` 日期。

### 8.2 Dashboard UI

四段:
1. **KPI strip** — TOTAL COST(claude $ / tts $ 拆分) / ELAPSED / CONTEXT NOW(% of 1M + peak) / TOKENS OUT(+ fresh / cache R / cache W)
2. **13-stage 進度條** — pending / running / done / failed 四態;`scriptwrite` / `script-review` / `synthesize` 是平行階段,每集顯示為 EP tile(running 會脈衝)
3. **COST BREAKDOWN 表** — stage × (model, calls, input, output, cache R/W, audio, USD),底列 TOTAL
4. **LIVE ACTIVITY feed** — `tool_use` / `text` / `result` / `tts_usage` / stage 邊界,新事件插頂;**`[...]` 方括號內容(TTS 情緒 tag 如 `[amused]`、集數清單如 `[1, 2, 3]`)行內高亮成 badge**(`highlightTags()`,先 escape 再包 span;`error`/`stage_fail` 行不高亮)

**nav SETTINGS(⚙)面板**(localStorage `podcast-monitor:settings`,套用於下一條 pipeline,非追溯)。**每個旋鈕單一來源**——PARALLEL/TTS model/agent profile 只在此調,不在 nav 或其他 modal 重複:
- **PARALLEL WORKERS**(1-10):scriptwrite/script-review/synthesize 並發度(原 nav 常駐 input 已移除,收斂於此)
- **TTS MODEL**:下拉(空=env 預設 `gemini-2.5-flash-tts` / 三個白名單 model);選定後腳本即依該 family 的 palette 生成(family-parametric,見 §3)。submit 時隨 `tts_model` 送出
- **AGENT PROFILE / AGENT MODEL**:profile 下拉(目前只有 `claude`)+ 可空 model override。submit 時隨 `agent_profile`/`agent_model` 送出;pipeline 寫 `.agent_*` sidecar,後續 approval/resume job 讀回。

(spoiler mode 仍只在 NEW PODCAST modal 設定,不鏡射進此面板——避免同一旋鈕兩處可調。)

KPI 之外的數字會即時更新;cost 表用 polling(events.jsonl tail 完一輪後 server 端重算,前端每 4s fetch)。**pipeline 未開 `PODCAST_VERBOSE=1` 時**,events.jsonl 不存在 → cost 表顯示「No cost data yet」+ warning bar 提示開 flag。
