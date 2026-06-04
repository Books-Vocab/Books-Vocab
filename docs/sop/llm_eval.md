<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/llm_eval/
  - docs/reference/llm_eval.md
verified_against: d1a5a383
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
from llm_eval import run_eval
from llm_eval.registry import PromptRegistry
from llm_eval.datasets import load_dataset

registry = PromptRegistry()
prompt = registry.render("translate_quick", word="evoke", context="...")
dataset = load_dataset("translate_quick")
results = run_eval(prompt, dataset, models=["gemma3:4b", "gemini-2.5-flash-lite"])

# 判讀：overall_score > 0.9 為可接受，< 0.7 需調查
for model, summary in results.items():
    print(f"{model}: score={summary.overall_score:.2f}, errors={summary.error_count}")
```

## Prompt 變更 Workflow

1. **先在 registry 建立變體**：`prompts/translate_quick_v2.md` + 更新 `manifest.yaml`
2. **跑 eval 比較**：同 dataset、同 model、不同 prompt version
3. **判讀結果**：
   - 變體 overall_score ≥ 原版 → 考慮合併到 production
   - 變體 overall_score < 原版 → 放棄或迭代
4. **同步 production**：更新 `backend/src/kg/` 對應 f-string
5. **跑 `ops/prompt_sync_lint.sh`** 確認雙軌一致
6. **跑 `ops/docs_lint.sh`** 確認 doc frontmatter 完整

## 結果保留政策

- `lab/llm_eval/results/` 保留最近 20 次 eval + 手動 tagged release
- 超過則由 agent 或人工清理

## 依賴

```bash
cd lab/llm_eval
uv run --extra dev pytest -q tests/   # 跑測試
```
