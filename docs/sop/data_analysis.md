<!-- doc-meta
tier: sop
authority: derived
update_trigger: data-analysis-workflow-changed
scope:
  - backend/ops_analyze.py
  - backend/src/kg/ops_cli_parser.py
  - backend/src/kg/ops_cli_queries.py
  - backend/src/kg/vocab_graph.py
  - .claude/skills/data-analysis/
verified_against: 8ec4780950c73b6006649c5c08e69c05962abfc1
-->
# KG Data Analysis SOP

本文件是用戶資料、額度與 knowledge graph 分析的技術入口。`.claude/skills/data-analysis/SKILL.md` 只負責何時使用、唯讀邊界、分析順序與輸出契約；命令與指標以本文件及目前 code 為準。

## 邊界與資料來源

- 只讀 `KG_DATA_DIR` 下的資料；production 查詢一律經 `ops/devops_kg_safe.sh ops-cli`。
- 不直接修改 `cards.db`、graph、embedding、quota 或 user config；要改資料或參數，回到 Worker／Issue Solver 的 branch + PR。
- 使用者 ID 可由 ops CLI 的 resolver 處理模糊輸入，但報告必須寫出解析後的完整 ID。
- 資料根目錄、notebook 檔名與 schema 以 `backend/src/kg/ops_shared.py`、`settings.py` 及 `notebook_files()` 為準，不在文件複製路徑常數。

主要入口：

```bash
./ops/devops_kg_safe.sh ops-cli user-quota <uid> --json
./ops/devops_kg_safe.sh ops-cli user-stats <uid> --json
./ops/devops_kg_safe.sh ops-cli user-config <uid> --json
./ops/devops_kg_safe.sh ops-cli quota-overview --json
./ops/devops_kg_safe.sh ops-cli analyze <uid> [1|2|3|4|5|6|all]
```

`analyze` 的實作入口是 `backend/ops_analyze.py`；不要把舊的本地一次性分析腳本當成 production truth。

## 六層分析契約

| level | 問題 | 必須觀察 |
|---|---|---|
| 1 | 現在是否異常 | 24h cost／quota、呼叫數、active/deleted cards、active links |
| 2 | 額度為何消耗 | 72h call type／provider、input/output、cost、judge share、粗略 rejection signal |
| 3 | 圖譜是否碎片化 | active nodes、linked／isolated、edges、density、degree、connected components |
| 4 | 連結品質如何 | confidence、kind、hub／degree concentration 與異常 link |
| 5 | embedding／threshold 是否合理 | embedding coverage、相似度分布、threshold sweep、candidate/top-k 壓力 |
| 6 | 是否有資料完整性問題 | dangling link、missing/deleted embedding、duplicate／self link、schema／artifact mismatch |

先跑 level 1；只有 level 1 指向異常，或使用者明確要求，才逐層深入。不要一開始傾倒完整資料庫或把所有指標都列進報告。

## 判讀規則

- quota／pricing：以 `backend/src/kg/quota_service.py`、`llm/providers.py` 的現行 code 為準，不引用過期 skill 內的價格快照。
- graph generation：`SIMILARITY_THRESHOLD`、`CANDIDATE_K`、`MAX_DEGREE` 以 `backend/src/kg/vocab_graph.py` 為準；報告同時記錄讀到的 commit／HEAD。
- judge rejection、孤立率、degree、component 與 confidence 都是診斷訊號，不是未經產品決策的自動修正門檻。
- 缺資料、資料過期、provider 不明或報表期間不一致時輸出 `unknown`／`inconclusive`，不可用估算填成健康。

## 輸出契約

每次報告至少包含：

1. user／notebook、資料根目錄來源與分析時間窗；
2. 實際命令、exit status、code／config HEAD；
3. 觀察值、判讀、反證或資料缺口；
4. 是否需要 `devops` 執行 production 動作，或需要建立 GitHub Issue／PR 的工程變更。

分析結果不是 Issue、Project、PR 或本地 backlog 狀態；它只是一份可追溯的 read-only evidence。
