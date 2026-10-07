<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - lab/llm_eval/
verified_against: 51ce9228ce64c1897850b8fcab672364b17f8731
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

`corpus-build` 與 `gold-queue` 寫入前以 `git check-ignore` 檢查每個輸出檔：
落在任一 git work tree 內且未被 ignore（含已 tracked、git 不可用）時以 exit 2
拒寫，除非帶 `--allow-unignored`。只有 git 明確回報 `not a git repository`、
且路徑往上沒有任何 `.git`、未設 `GIT_DIR`／`GIT_WORK_TREE` 時才視為不在 work
tree 而放行；其他 git 失敗（dubious ownership、權限、repo 損毀）一律 fail
closed 當作可 commit。
`corpus-build --output-dir` 預設為 `lab/llm_eval/private_corpus/`（以 package
root 解析，與 cwd 無關）。

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

Cloud provider 建 client 前必須有對應 API key env；缺 key 時 client factory 拋
`MissingProviderApiKeyError`，不帶假 key 打遠端。Ollama 維持 local dummy
key 行為，不需要 `OLLAMA_DUMMY_KEY`。

Retry 由 OpenAI SDK client 負責，次數由 `providers.EVAL_MAX_RETRIES`（2，即最多 3 次請求）
顯式固定：408/409/429/5xx 與連線錯誤以 exponential backoff + jitter 重試，並遵守
`Retry-After`／`retry-after-ms`。runner 不再疊第二層 retry；整個重試鏈仍受單次
call timeout 約束。

## 執行引擎

- Bypass TrackedLLM（不寫 token_usage、不扣額度）
- async parallel + per-provider semaphore（預設 5 concurrent）；`EvalConfig` 對
  `concurrency < 1`（`Semaphore(0)` 會永久等待）與 `limit < 1`（`0` 曾被當成
  「不限」跑完整個 dataset）拋 `ValueError`，CLI 對應參數 exit 2
- `--models` 可給 provider 名（如 `gemini`）：實際請求與計價都用該 provider 的
  registry `chat_model`
- 成本依**實際請求的 model** 計價：provider 的 registry 價格只屬於其
  `chat_model`；其他 cloud model 查 `runner._MODEL_PRICES`（USD／1M tokens，
  附來源），查不到時 `total_cost_usd` 為 `None`（CLI／report 顯示 `n/a`），
  不以 provider 預設價冒充；Ollama 恆為 0
- Timeout：cloud 60s, Ollama 300s（含 SDK retry 的整條呼叫）
- 每筆失敗都記在該 `EvalResult.error`，不中止其他 model：`timeout`、
  `missing_api_key: <ENV>`（不送任何請求）、`ollama_unavailable`、重試耗盡後的
  `<ExceptionType>: <message>`
- Ollama 可達性探測以 `asyncio.to_thread` 執行，不阻塞 event loop
- 每筆 `EvalResult` 帶 `scores`
- 每個 `EvalSummary` 帶 `format_score_avg` / `quality_score_avg` / `score_breakdown` / `failure_examples`

## Report / Baseline

`llm_eval.reporting.write_report()` 輸出:
- JSON:`lab/llm_eval/results/<timestamp>_<prompt>_<dataset>.json`
- Markdown summary:同名 `.md`

Report 含 git sha、dataset hash、prompt version、model/provider、latency/token/cost、
per-sample raw/parsed output、scores、錯誤摘要。git sha 取 workbench 所在 checkout
的 HEAD（`llm_eval.paths.PACKAGE_ROOT`），不取 caller cwd。

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

所有預設路徑以 package root（`lab/llm_eval/`，`llm_eval.paths`）解析，從 repo
root、`lab/llm_eval` 或任何 cwd 執行結果相同；使用者明確給的相對路徑仍相對 cwd。

| 預設 | 路徑 |
|---|---|
| `eval --output-dir`（不帶值） | `lab/llm_eval/results/` |
| `review --results-dir` | `lab/llm_eval/results/` |
| `corpus-build --output-dir` | `lab/llm_eval/private_corpus/` |

`review` 未給 `--results` 時，讀 results dir 內每個 report JSON，以 JSON 內
`prompt.name` == `--prompt`、`dataset_name` == `--dataset` 精確比對，取
`timestamp` 最新者；不解析檔名（`<ts>_<prompt>_<dataset>` 在名稱含底線時有歧義），
非 report 的 JSON 略過。

`eval` 的 exit status 只表示這次 run 是否完成所要求的評估；結果表／JSON／report
一律先輸出，再回傳：

| 情況 | exit | 時機 |
|---|---|---|
| 任一 `--models` 無法解析 provider | 1 | 發出任何請求前 |
| `--baseline` 讀不到、不是 report 形狀（`models` 為 object、各 model 為 object、`*_score_avg` 為數字或 null） | 1 | 發出任何請求前 |
| 任一 model 全部 sample 都 error（例如缺 key、Ollama 不可達） | 1 | run 結束後 |
| 任一 model `format_regression` 或 `quality_regression` | 1 | run 結束後 |
| 其餘（含部分 sample error） | 0 | — |

失敗原因逐條寫到 stderr；`--json` 另帶 `failures` 陣列（成功時為 `[]`）。

## 如何新增 eval

1. 在 `prompts/` 新增 `.md` + 更新 `manifest.yaml`
2. 在 `datasets/` 新增 `.jsonl`
3. 在 `llm_eval/scoring.py` 新增 `_PROMPT_SCORERS` entry
4. 在 `tests/` 新增對應測試
