---
name: podcast
description: "Book-to-Podcast Pipeline — EPUB → 深度分析 → 製作規劃 → QA → 多集播客腳本 → TTS 音訊 → 詞級字幕"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Podcast Pipeline Skill

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
# 從指定階段開始
uv run pipeline.py workspaces/<name>/ --skip-to enricher

# 跑到指定階段就停
uv run pipeline.py workspaces/<name>/ --stop-after architect

# 只跑一個階段
uv run pipeline.py workspaces/<name>/ --only-stage scriptwrite

# 組合：只跑某階段的某一集
uv run pipeline.py workspaces/<name>/ --only-stage scriptwrite --only-episode 4

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
3. **Review artifacts**: `plan/review.md`（plan QA）+ `scripts/ep_N_review.md`（script QA）
4. **Agent log**: `log.md` — 每個 Claude agent 自行附加的自然語言日誌
5. **--status**: 一鍵顯示進度 + 所有可用指令

## 主持人動態命名

- Architect 根據書的語言/風格自動設計主持人名字（不再硬編碼）
- `overview.md` 的 Voice Mapping section 定義 name → Speaker1/Speaker2 映射
- `synthesize.py` 和 `subtitle.py` 從 `overview.md` 動態讀取

## 限制 / 依賴

- `subtitle.py` 不可平行（Whisper 記憶體大）
- `synthesize.py` 內部已平行，但 `TTS_MAX_CONCURRENT=3`（避免撞 Vertex 429）
- `scriptwrite` / `script-review` 平行度預設 3，用 `--parallel N` 調整
- **`ffmpeg` 需安裝**（mastering loudnorm 用）；無 ffmpeg 時自動降級為純 export，音量不會正規化
- Claude agent 每 stage 有 timeout（Enricher 2700s / Scriptwriter 1800s / Reviewer 1200s / 其他 1500s）

## 常用環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `TTS_MODEL` | `gemini-2.5-flash-tts` | Vertex TTS 模型（Pro 版：`gemini-2.5-pro-tts`） |
| `TTS_MAX_CONCURRENT` | `3` | TTS batch 並發上限 |
| `TTS_RETRY_ATTEMPTS` | `4` | 429/503 指數退避重試次數 |
| `TTS_MASTER` | `1` | 設 `0` 關閉 loudnorm mastering |
| `TTS_MASTER_LUFS` | `-16` | 目標整合響度（Apple Podcasts 標準） |

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
  audio_qa.json                  ← 音訊 QA 報告
  claude_*.stderr.log            ← agent 失敗時的 stderr tail
```

## Agent 行為指引

1. 確認 EPUB 路徑存在
2. 執行 `uv run pipeline.py <path>`
3. 若失敗，讀 `pipeline_log.jsonl` 和 review 檔案判斷原因
4. 用 `--skip-to` 從斷點續跑
5. 完成後告知：workspace 路徑、各集音訊長度、檔案大小
