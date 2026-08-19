---
name: data-analysis
description: "KG 用戶資料、quota 與 knowledge graph 的唯讀分析：先健檢，再按證據深入到額度、拓撲、連結品質、embedding 與異常。"
allowed-tools: Bash, Read, Grep
---

# Data analysis workflow

這個 skill 是分析路由與判讀邊界，不是 SQL／graph 演算法手冊。完整技術契約在 [`docs/sop/data_analysis.md`](../../../docs/sop/data_analysis.md)，目前實作以 `backend/ops_analyze.py` 與 `backend/src/kg/` 為準。

## 觸發與邊界

使用者要求查用戶 quota／cards／graph、分析連結品質、追查 embedding／pipeline 異常或調查參數影響時使用。

- 只讀 production data；查詢走 `./ops/devops_kg_safe.sh ops-cli`。
- 不直接寫 DB、改 user config、刪 link、調 threshold 或改 quota；工程修復走 Worker／Issue Solver 的 branch + PR。
- 成本與 provider 帳務走 `billing`；production restart／資料操作走 `devops`。

## 標準路徑

1. 先跑 `user-quota`、`user-stats` 或 `quota-overview`，確認 user、時間窗與資料 freshness。
2. 只有初篩指向異常才跑 `ops-cli analyze <uid> 1|2|3|4|5|6|all`；按 level 逐層深入，不一次載入所有資料。
3. 對照 `docs/sop/data_analysis.md` 的判讀規則與目前 code 常數；任何 mismatch、缺檔或 stale source 都保留為 deviation。
4. 把 read-only 結果收斂成 evidence；需要修復時建立 GitHub Issue／PR，不在本 skill 內偷偷變更 production。

## 輸出契約

回報 user／notebook、時間窗、實際命令與 exit status、觀察值、判讀、反證／缺口、code HEAD，以及是否需要 devops 或工程 hand-off。沒有足夠資料時回報 `inconclusive`，不能把猜測報成健康。
