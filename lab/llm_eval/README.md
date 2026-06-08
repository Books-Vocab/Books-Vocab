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

## 評分模型（重要）

`scoring.py` **只做客觀的機械格式檢查**（JSON 合法 / schema keys / 繁簡偵測 OpenCC / POS 後綴 / link kind / confidence 範圍）。
**翻譯與語意品質不在此自動評分** —— 同義詞、語感、nuance 的判斷由 **agent 讀 eval report 人工審核**，不靠脆弱的 gold exact-match。

工作流：
```
# 1. 跑 eval（產生 report JSON，含 raw/parsed 輸出 + 格式分數）
cli.py eval --prompt translate_quick --dataset translate_quick_gold \
    --models deepseek-v4-flash --output-dir results

# 2. 產生 reviewable 格式（模型輸出 vs gold join），交給 agent 審核
cli.py review --prompt translate_quick                # 最新 report
cli.py review --prompt translate_quick --range 0:20   # 分塊給平行 reviewer
cli.py review --prompt translate_quick --json         # 機器交接給 subagent
```

## 如何新增 eval

1. 在 `prompts/` 新增 `.md` + 更新 `manifest.yaml`
2. 在 `datasets/` 新增 `.jsonl`（human gold 樣本帶 `gold_status: human_gold` + `gold_*` 欄位）
3. 若有**客觀格式規則**要驗（非品質判斷），才在 `llm_eval/scoring.py` 加 `_PROMPT_SCORERS` entry
