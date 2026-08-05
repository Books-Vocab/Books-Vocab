<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - lab/llm_eval/
verified_against: 2c661f326
-->
# LLM Eval Workbench

KG 的 LLM eval / prompt engineering workbench。v1 定位是嚴格實驗室:
歷史資料先進 private candidate corpus,人工標成 `human_gold` 後才計入品質分。
當你需要：
- 比較本地 Ollama 和雲端模型輸出品質
- 測試 prompt 變體效果
- 驗證 prompt 修改是否造成 regression
- 產生可人工審查的 JSON/Markdown eval report

## 位置

`lab/llm_eval/`

## 核心 API

```python
from llm_eval import run_eval, make_render_fn, write_report, compare_to_baseline
from llm_eval.registry import PromptRegistry
from llm_eval.datasets import load_dataset

registry = PromptRegistry()
dataset = load_dataset("translate_quick")
render_fn = make_render_fn(registry, "translate_quick")
results = await run_eval(render_fn(dataset[0]), dataset, models=["deepseek-v4-flash", "gemini-2.5-flash-lite"], render_fn=render_fn)
```

## Prompt Registry

`lab/llm_eval/prompts/manifest.yaml` 為機器可讀 prompt 清單。

可用 prompts：
- `translate_quick` — 單字翻譯（t/p/r JSON）
- `translate_phrase` — 片語翻譯（t JSON）
- `translate_explain` — 詞彙解釋（單字 + 片語通吃，e JSON）
- `judge_batch` — 批次詞彙關係判斷
- `judge_selective` — 選擇性批次判斷（max_links）
- `judge_manual` — 手動連結判斷
- `enrich` — 詞彙豐富化（POS + note + collocations + meaning_fix）

Prompt template 格式：markdown + Jinja2 + YAML frontmatter。
Production prompt（`backend/src/kg/` inline f-string）與 eval registry 為**雙軌制**。
目前沒有自動 sync lint;改 production prompt 時需同 PR 手動同步 registry prompt 與測試。

## Datasets

`lab/llm_eval/datasets/*.jsonl`

每行一個 sample，含 `id` + prompt 所需的變數欄位。

### Private Corpus

`lab/llm_eval/private_corpus/` 為本機私有資料區,由 `.gitignore` 排除。
`llm_eval.corpus.build_private_corpus()` 可從匯出的使用者 dump 建立 candidate JSONL。

每筆 private row 必須帶:
- `source=historical_user_data`
- `gold_status=unverified|human_gold`
- `pii_risk=low|medium|high`
- `gold_queue_eligible`
- `weak_reference`(歷史 meaning/POS/root/note;只作弱參考)

高風險樣本不進 gold review queue。未經人工標註的 `unverified` row 不計入品質分。

## 評分機制

分兩層:
- `format_score_avg`:自動格式分,只聚合 `json_valid` / `schema_conform`
- `quality_score_avg`:只在 `gold_status=human_gold` row 上,依明確 gold reference / rubric 產生

未有人工作為 gold 的 dataset 不得宣稱品質提升;只能比較格式、成本、延遲與差異樣本。

| 檢查項 | 適用 Prompt |
|--------|------------|
| JSON parseable / required keys | all(JSON object;judge/enrich 可為 list) |
| 繁體中文（OpenCC s2t） | translate, judge, enrich |
| POS 後綴（adj.→的, adv.→地） | translate_quick, enrich |
| Lemma 正確性（heuristic） | translate_quick |
| Link enum / confidence range | judge |
| POS enum | enrich |
| gold translation/POS/root exact match | translate_quick human_gold |
| gold keyword coverage | translate_explain human_gold |

Judge/enrich 的 JSON list 會保留為 list;translate 類 prompt 回 list 會被判 schema 失敗。

## Provider

Ollama **不進** `backend/src/kg/llm/providers.py`（production 不能誤路由到 local）。
`lab/llm_eval/llm_eval/providers.py` 統一解析 cloud registry + ollama。

Cloud provider 建 client 前必須有對應 API key env；缺 key 直接拋
`MissingProviderApiKeyError`，不帶假 key 打遠端。Ollama 維持 local dummy
key 行為，不需要 `OLLAMA_DUMMY_KEY`。

## 執行引擎

- Bypass TrackedLLM（不寫 token_usage、不扣額度）
- async parallel + per-provider semaphore（預設 5 concurrent）
- Timeout：cloud 60s, Ollama 300s
- Ollama 未啟動時自動標記 `ollama_unavailable`
- 每筆 `EvalResult` 帶 `scores`
- 每個 `EvalSummary` 帶 `format_score_avg` / `quality_score_avg` / `score_breakdown` / `failure_examples`

## Report / Baseline

`llm_eval.reporting.write_report()` 輸出:
- JSON:`lab/llm_eval/results/<timestamp>_<prompt>_<dataset>.json`
- Markdown summary:同名 `.md`

Report 含 git sha、dataset hash、prompt version、model/provider、latency/token/cost、
per-sample raw/parsed output、scores、錯誤摘要。

`compare_to_baseline()` 分開比較:
- `format_delta` / `format_regression`
- `quality_delta` / `quality_regression`

`lab/llm_eval/private_baselines/` 由 `.gitignore` 排除;baseline 更新必須人工決定。

## 測試

```bash
cd lab/llm_eval
PYTHONPATH=../../backend/src uv run --extra dev pytest -q tests/
```

## CLI

```bash
cd lab/llm_eval
uv run python scripts/cli.py --help
```

## 如何新增 eval

1. 在 `prompts/` 新增 `.md` + 更新 `manifest.yaml`
2. 在 `datasets/` 新增 `.jsonl`
3. 在 `llm_eval/scoring.py` 新增 `_PROMPT_SCORERS` entry
4. 在 `tests/` 新增對應測試
