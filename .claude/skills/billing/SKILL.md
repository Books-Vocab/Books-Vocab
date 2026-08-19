---
name: billing
description: "KG 成本與帳單分析：盤點、reconciliation、cost drift 與升降級建議。只做 read-only 分析；實際變更交給 devops。"
allowed-tools: Bash, Read, Grep
---

# Billing analysis workflow

這是成本判斷 skill，不是 AWS／GCP 指令手冊。先完成 onboarding，再按問題載入唯一技術來源：

- 月度盤點、drift、預算閾值：[`docs/sop/cost_review.md`](../../../docs/sop/cost_review.md)。
- 金額、供應商、pricing 與 baseline：[`docs/reference/cost_baseline.md`](../../../docs/reference/cost_baseline.md)。
- 目前 provider pricing 與 service mapping：`backend/src/kg/llm/providers.py`、`backend/src/kg/admin_cost_summary.py`。

## 觸發與邊界

使用者問「花多少、漲了沒、成本 drift、token spend、該升／降 bundle」時使用。

- 本 skill 可以查詢、計算、對照 baseline、輸出建議。
- 本 skill 不修改 production、不刪 bucket、不 rotate key、不設定 billing alarm、不執行 bundle 變更。
- 需要執行變更時交給 `devops`；用戶配額／圖譜／產品閾值分析交給 `data-analysis`。
- 發現 pricing、token usage 或資料缺口時，回報工程變更，不在分析 skill 內補資料。

## 路徑

1. 先判斷是月度盤點、單項 drift、供應商 reconciliation 或容量／bundle 建議。
2. 只讀上列對應 SoT；不要把歷史數字當作目前狀態。
3. 依 SOP 的順序取得內部帳、外部帳與 baseline，保留查詢失敗與資料缺口。
4. 以 `baseline / actual / drift / decision / hand-off` 輸出；若需要生產動作，明確交接到 `devops`。

## Hard stop

遇到刪除、強制、寫入 billing／provider／bucket、production restart 或 secret rotation 指令，停止執行並改報「需要 devops／使用者批准」；不要用 skill route 當作權限。

## 輸出契約

- 盤點：服務、baseline、實際值、drift、資料來源與未完成項。
- 建議：現況、建議、每月成本差、容量／供應商風險、執行交接點。
- 任一外部帳或 API 不可用：保留 `unknown`，不能用估算冒充實際值。
