---
name: data-analysis
description: "用戶資料與知識圖譜深度分析 — 圖譜拓撲、連結品質、額度消耗、嵌入健康、閾值調優"
allowed-tools: Bash, Read, Grep, Agent
---

# KG Data Analysis Skill

## 觸發條件

- 分析用戶資料 / 圖譜狀態 / 連結品質
- 調查額度消耗模式
- 評估參數（threshold、candidate_k）調優效果
- 診斷圖譜碎片化、孤立節點、連結異常

## 工具鏈

| 工具 | 用途 | 適用場景 |
|------|------|----------|
| `ops-cli user-quota <uid>` | 24h 額度 + 逐時明細 | 快速查看消耗 |
| `ops-cli user-stats <uid>` | 單字庫基本統計 | 快速查看卡片數 |
| `ops-cli user-config <uid>` | user config（translation/review_*/vocab_ui/auto_link） | 查 active notebook / 複習設定 / 翻譯語言 / 自動連結開關 |
| `ops-cli quota-overview` | 全用戶額度對比 | 跨用戶分析 |
| `container-script` | 自訂分析腳本 | 深度分析（見下方方法論） |
| `graph_analysis.py` | 本地圖譜分析（需本地 data） | 開發時用 |

uid 支援模糊匹配：`00287` 自動 resolve 為完整 ID。

## 資料來源

```
/app/data/
├── token_usage.db                    # 全用戶 token 消耗紀錄
├── users.json                        # 用戶 metadata + per-user config（translation/review_clock/review_mode/vocab_ui active notebook/auto_link）
└── users/<uid>/
    ├── cards.db                      # 單字卡（content, meaning, difficulty, review stats）
    ├── graph_<notebook>.json         # 知識圖譜（links array）
    ├── candidates_<notebook>.json    # 待審候選連結
    ├── blocked_<notebook>.json       # 已封鎖連結對
    ├── embeddings_<notebook>.npy     # 向量嵌入（shape: [N, 3072]）
    ├── card_ids_<notebook>.json      # embedding index → card_id 映射
    ├── daily_review_stats.db         # 每日複習統計
    └── notebooks.db                  # 筆記本 metadata
```

## 分析方法論

### Level 1: 快速健檢（30 秒）

```bash
./ops/devops_kg_safe.sh ops-cli user-quota <uid>
./ops/devops_kg_safe.sh ops-cli user-stats <uid>
```

看什麼：
- 額度消耗是否異常（judge 佔比 > 50% = 警訊）
- 卡片活躍數 vs 刪除數

### Level 2: 額度消耗分析

用 `container-script` 查 `token_usage.db`：

```python
# 核心查詢
SELECT call_type, COUNT(*), SUM(input_tokens), SUM(output_tokens),
       AVG(input_tokens), AVG(output_tokens)
FROM token_usage
WHERE user_id = ? AND created_at >= ?
GROUP BY call_type ORDER BY SUM(input_tokens) DESC
```

分析要點：
- **call_type 佔比**：judge > 50% → 門檻可能太低
- **每次 token 數**：judge avg_input ~255 = 正常，> 500 = prompt 需精簡
- **每次 output 數**：judge avg_output ~70 = 正常
- **拒絕率**：`(judge_calls - new_links) / judge_calls`，> 50% = 門檻太低

### Level 3: 圖譜拓撲分析

需要讀 `graph_<notebook>.json` + `cards.db`。

**核心指標：**

| 指標 | 健康範圍 | 計算方式 |
|------|----------|----------|
| 孤立節點率 | < 40% | 無連結卡片 / 總卡片 |
| 平均度 | 2-4 | 2 × 邊數 / 節點數 |
| 最大連通分量佔比 | > 60% | 最大分量 / 已連結節點 |
| 連通分量數 | 越少越好 | BFS/DFS 計數 |
| 聚類係數 | > 0.10 | 三角閉合比率 |
| 最大度 | < 15 | 防止 hub 過度集中 |

**度數分布**：應呈 power-law 長尾。若全是 degree=1 → 圖太稀疏；若有 degree>15 → hub 過度集中。

**連通分量**：理想是一個大分量 + 少量小島。碎片化（多個 5-10 節點的孤島）說明跨語義群的橋接不足。

### Level 4: 連結品質分析

```python
# Confidence 分布
confs = [l["confidence"] for l in links]
# 健康：mean > 0.80, std < 0.15

# Kind 分布
# contrasts_with vs shares_usage 比例應大致平衡
# 若 shares_usage > 80% → 門檻太低，弱關聯都通過了

# 拒絕率 = (judge_calls - links_created) / judge_calls
# 健康：30-50%。>60% = 門檻太低。<20% = 門檻太高（漏連結）
```

### Level 5: 嵌入品質與閾值調優

需要讀 `embeddings_<notebook>.npy` + `card_ids_<notebook>.json`。

```python
# 全局相似度分布
sim_matrix = normalized_embeddings @ normalized_embeddings.T
upper = sim_matrix[np.triu_indices(n, k=1)]
# 看 percentile: P90, P95, P99 對應的相似度值

# 閾值掃描
for threshold in [0.70, 0.75, 0.78, 0.80, 0.85, 0.90]:
    count = (upper > threshold).sum()
    avg_per_card = 2 * count / n
    # 每卡平均候選數：2-5 = 健康，>10 = 門檻太低
```

**閾值調優原則：**
- 目標：拒絕率 30-50%，每卡平均候選 3-6 個
- shares_usage 連結 confidence 通常較低（~0.79），門檻不宜高於 0.82
- contrasts_with 連結 confidence 較高（~0.86），更耐高門檻
- 碎片化嚴重時降門檻，hub 過度集中時升門檻

### Level 6: 問題偵測

自動掃描的異常：
1. **指向已刪除卡片的連結** — 應清理
2. **缺 embedding 的 active 卡片** — pipeline 可能中斷過
3. **已刪除卡片仍有 embedding** — 浪費空間
4. **重複連結**（A↔B 兩條）— 資料不一致
5. **自連結** — bug
6. **高相似度但無連結** — 可能被 judge 誤判 not_applicable
7. **低相似度但有連結** — 可能是手動連結或早期低門檻殘留

## 現有參數參考

| 參數 | 值 | 檔案 |
|------|-----|------|
| SIMILARITY_THRESHOLD | 0.78 | `backend/src/kg/vocab_graph.py:11` |
| CANDIDATE_K | 12 | `backend/src/kg/vocab_graph.py:12` |
| Judge model | gemini-2.5-flash-lite | `backend/src/kg/judge.py:47` |
| Judge temperature | 0.1 | `backend/src/kg/judge.py:77` |
| Confidence threshold | 0.7 | `backend/src/kg/judge.py:138` |
| Embedding model | gemini-embedding-2-preview | `backend/src/kg/embeddings.py:14` |
| Embedding dim | 3072 | `backend/src/kg/embeddings.py:15` |
| ThreadPool workers | 8 | `backend/src/kg/pipeline_service.py:195` |
| PRO daily limit | $0.30 | `backend/src/kg/settings.py` |
| Pricing: Gemini input | $0.10/1M tokens | `backend/src/kg/quota_service.py` |
| Pricing: Gemini output | $0.40/1M tokens | `backend/src/kg/quota_service.py` |

## 腳本慣例

所有分析腳本寫到 `/tmp/` 後用 `container-script` 執行：

```bash
./ops/devops_kg_safe.sh container-script /tmp/my_analysis.py
```

腳本內 data dir 固定為 `/app/data`。需要 numpy 時直接 import（container 內已安裝）。
