<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - lab/llm_eval/
verified_against: 74bf32da
-->
# LLM Eval Workbench

KG 的 LLM eval / prompt engineering workbench。
當你需要：
- 比較本地 Ollama 和雲端模型輸出品質
- 測試 prompt 變體效果
- 驗證 prompt 修改是否造成 regression

## 位置

`lab/llm_eval/`

## 核心 API

```python
from llm_eval import run_eval, compare_prompts
from llm_eval.registry import PromptRegistry
from llm_eval.datasets import load_dataset

registry = PromptRegistry()
prompt = registry.render("translate_quick", word="evoke", context="...")
dataset = load_dataset("translate_quick")
results = run_eval(prompt, dataset, models=["gemma3:4b", "gemini-2.5-flash-lite"])
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
Production prompt（`backend/src/kg/` inline f-string）與 eval registry 為**雙軌制**，
由 `ops/prompt_sync_lint.sh` 檢查一致性。

## Datasets

`lab/llm_eval/datasets/*.jsonl`

每行一個 sample，含 `id` + prompt 所需的變數欄位。

## 評分機制

純 rule-based，零額外 API 成本。

| 檢查項 | 適用 Prompt |
|--------|------------|
| JSON parseable / required keys | all |
| 繁體中文（OpenCC s2t） | translate, judge, enrich |
| POS 後綴（adj.→的, adv.→地） | translate_quick, enrich |
| Lemma 正確性（heuristic） | translate_quick |
| Link enum / confidence range | judge |
| POS enum | enrich |

評分邏輯重用 production parsing：`kg.translate_service._parse_json_payload`、
`kg.judge.parsing._parse_batch_response`、
`kg.enrich._parse_enrich_response` 中的驗證邏輯。

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

## 測試

```bash
cd lab/llm_eval
PYTHONPATH=../../backend/src uv run --extra dev pytest -q tests/
```

## 如何新增 eval

1. 在 `prompts/` 新增 `.md` + 更新 `manifest.yaml`
2. 在 `datasets/` 新增 `.jsonl`
3. 在 `llm_eval/scoring.py` 新增 `_PROMPT_SCORERS` entry
4. 在 `tests/` 新增對應測試
