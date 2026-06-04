# KG LLM Eval / Prompt Engineering Workbench

## 這是什麼

KG 的 LLM eval / prompt engineering workbench。
當你需要：
- 比較本地 Ollama 和雲端模型輸出品質
- 測試 prompt 變體效果
- 驗證 prompt 修改是否造成 regression

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

## 可用 Prompts

見 `prompts/manifest.yaml`

## 可用 Datasets

見 `datasets/`（JSONL 格式）

## 如何新增 eval

1. 在 `prompts/` 新增 `.md` + 更新 `manifest.yaml`
2. 在 `datasets/` 新增 `.jsonl`
3. 在 `llm_eval/scoring.py` 新增對應的 `_PROMPT_SCORERS` entry
