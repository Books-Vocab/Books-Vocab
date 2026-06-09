<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/llm_eval/
  - docs/reference/llm_eval.md
verified_against: df2a59d5
-->
# LLM Eval Runbook

## 何時該跑 eval

| 情境 | 動作 |
|------|------|
| 修改 production prompt（`backend/src/kg/translate_service.py` 等） | 跑 eval 確認無 regression |
| 新增 prompt 變體 | 跑 eval 比較原版 vs 變體 |
| 本地 Ollama 下載新模型 | 跑 eval 快速評估品質 |
| 雲端 provider 換模型（`providers.py:REGISTRY`） | 跑 eval 比較新舊模型 |
| PR 涉及 LLM 輸出格式變更 | 跑 eval 確認 schema conform |

## 執行步驟

```python
import asyncio
from llm_eval import make_render_fn, run_eval, write_report
from llm_eval.registry import PromptRegistry
from llm_eval.datasets import load_dataset

registry = PromptRegistry()
dataset = load_dataset("translate_quick")
render_fn = make_render_fn(registry, "translate_quick")
results = asyncio.run(run_eval(
    render_fn(dataset[0]), dataset,
    models=["deepseek-v4-flash", "gemini-2.5-flash-lite"],
    render_fn=render_fn,
))

for model, summary in results.items():
    print(model, summary.format_score_avg, summary.quality_score_avg, summary.error_count)
```

## Prompt 變更 Workflow

1. **先在 registry 建立變體**：`prompts/translate_quick_v2.md` + 更新 `manifest.yaml`
2. **建立 / 更新 private candidate corpus**：`private_corpus/` 只留本機,不 commit
3. **人工標 gold**：每輪 30-50 筆,標 `gold_status=human_gold` + 明確 reference/rubric
4. **跑 eval 比較**：同 dataset、同 model、不同 prompt version
5. **判讀結果**：
- `format_score_avg` 不得退步
- `quality_score_avg` 只在 human-gold set 上比較
   - 沒有 human-gold 時不得宣稱品質提升
6. **人工讀 failure examples**：確認錯誤型態可接受
7. **同步 production**：更新 `backend/src/kg/` 對應 f-string
8. **跑 `ops/docs_lint.sh`** 確認 doc frontmatter 完整

## Private Corpus / Gold

`llm_eval.corpus.build_private_corpus()` 建立的是 candidate corpus,不是 gold。

必守規則:
- `source=historical_user_data` 的歷史 meaning/note/link 只作 weak reference
- `pii_risk=high` 不進 gold review queue
- `gold_status=unverified` 不計入 `quality_score_avg`
- `translate_quick` gold 用 `gold_translation` / `gold_pos` / `gold_root`
- `translate_explain` gold 用 `gold_keywords`
- private corpus / private baseline / results 預設不 commit

## 結果保留政策

- `lab/llm_eval/results/` 由 `.gitignore` 排除,避免 raw output 洩漏
- `lab/llm_eval/private_baselines/` 由 `.gitignore` 排除
- 手動接受的 baseline 需保留對應 report JSON 與人工審查紀錄

## 依賴

```bash
cd lab/llm_eval
uv run python scripts/cli.py --help      # 查 CLI
PYTHONPATH=../../backend/src uv run --extra dev pytest -q tests/   # 跑測試
```
