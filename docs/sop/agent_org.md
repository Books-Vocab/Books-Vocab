<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - CLAUDE.md
  - .claude/agents/
  - .claude/skills/kg-router/
  - .claude/skills/kg-receipt/
verified_against: a6ad9d5d
-->
# 組織營運手冊（總經理 SOP）

> 本文是 CLAUDE.md「組織模型(營運憲法)」的**可執行版**——憲法定義「節點 / 邊 / 委派契約」,本文定義「總經理拿到任務後怎麼跑」。
> **權威在憲法**;本文只串指標、給可填模板與已驗證實例,**不複述**鐵律與契約定義(SoT 零重複)。

## 何時讀本文

總經理(上一階為執行長的節點)接到**有複雜度**的任務——需拆解 / 跨部門 / 多步驟 / 接手陌生範圍——時讀。純樣板(typo / rename / 單檔已指明範圍)不適用。冷啟動找入口先觸發 `kg-router`。

## 任務生命週期:七拍

逐拍進行,每拍指向既有規則,不重述判準:

1. **Intake 受理** — 意圖澄清。只有「升級觸發」(見 CLAUDE.md 組織模型)才回問執行長,否則自決後告知。
2. **Planning 規劃** — 拆 WBS;選派任形狀(見下);決定派哪些下一階(部門名冊查法見 CLAUDE.md 組織模型「部門名冊」)。
3. **Execution 執行** — 下行 task brief(模板見下);**所有 `Agent()` 背景執行**(鐵律5),主線不阻塞。
4. **Review gate 逐項** — 每個交付立即過 review,PASS 才下一個;禁批次(鐵律4 / `docs/sop/review_discipline.md`)。
5. **Integration & Verify 整合驗證** — 彙整下一階產出;宣稱完成前必有**當下驗證輸出**(鐵律2)。
6. **Report 回報** — 上行 receipt(`kg-receipt`)+ 明確下一步,交回上一階。
7. **Retro 復盤** — 工具摩擦依鐵律9 判定處理。

## 升級觸發補充:human-only blocker 即時升級

> 基準觸發清單在 CLAUDE.md 組織模型「升級給執行長的觸發」,不複述;本節新增一類並定義其**時效**。

- **執行中發現只有使用者本人能做的外部動作**(GUI-only 操作、帳號持有人專屬簽署、外部系統人工步驟)→ **當下立即告知執行長**,不等收尾 receipt;告知後**繼續平行推進其餘可做的工作**,讓人工動作與 agent 工作同時進行。
- 觸發時點 = blocker **定讞**(確認無 agent 可行替代路徑)那一刻。晚報一分鐘就損失一分鐘可平行的人工時間(2026-07-08 實例:ASC API 403 需帳號持有人 GUI 簽協議,開場 10 分鐘定讞卻批到收尾 receipt 才告知,白損 40 分鐘)。

## 委派成本門檻(要不要派,先於怎麼派)

「粗活全下放」不是無下限——委派本身有成本(agent 啟動 + 全套 receipt)。Planning 拍先判:

- **trivial**(同時滿足:單檔、約 ≤10 行、純樣板 / 無語意風險)→ **當前節點直接做**,免下放、免全套 receipt;review 豁免依 `docs/sop/review_discipline.md`「Receipt 契約」的 `Review-Exempt` 白名單。
- **非 trivial** → 照常走委派契約(下行 task brief / 上行 receipt)。

本門檻與鐵律5 **正交**:這裡判的是「要不要派 agent」;一旦決定派,鐵律5(所有 `Agent()` 背景化)照常適用,不因工作小而改同步。

## 派任形狀

- **fan-out(平行 / map-reduce)** — 子任務彼此獨立 → 一次派多個下一階,各自背景跑,總經理彙整。管理幅度:一次直接下一階建議 **≤5**(見 CLAUDE.md「對話啟動流程」的 2–5 建議),並發勿爆。
- **pipeline(接力)** — 前一交付餵後一(例:`podcast` 分析 → 規劃 → 腳本 → TTS → 字幕)。每棒仍是「上一階 → 單一下一階」,**深 pipeline 不是深巢狀**。
- **協作介質** — 下一階之間**不平輩直連**;共享狀態走 SoT docs / git(blackboard),跨節點交集靠檔案而非傳話。

## 下一階的兩種角色

委派前先分清你派的是哪一種:

- **部門(work-doer)** — 擁有 scope、產出改動。由上一階委派「一塊工作」。Line:`ios` / `backend` / `ops-engineer`(做 domain);Staff:`docs-steward`(維 SoT)、`platform-steward`(推 kaizen)。
- **通用審核器(shared reviewer)** — **不**擁有 scope、**不**產出改動,只審「任何節點自己的產出」。`code-reviewer` 即此:**任何節點**(不限總經理)完成一個可交付單位時,自行調用它當鐵律4 的自查 gate,審畢回給調用它的那個節點(上一階)。它是橫切共享服務,不是某人專屬部門。

## 下行 task brief 模板

> 五欄的**定義**見 CLAUDE.md 組織模型「下行 = task brief」;此處只給可填骨架 + 一個已驗證實例。

```
目標:      <一句話要什麼>
DoD:       <怎樣算完成、要附哪個當下驗證輸出>
邊界:      <不准碰什麼 / 越界就回報上一階>
必讀 SoT:  <對應 registry / feature_boundary / 鐵律編號,指過去>
回報格式:  kg-receipt（欄位見 .claude/skills/kg-receipt/SKILL.md）
```

**已驗證實例**(2026-06-13,ops 邊 smoke):目標=驗 ops Line 邊契約;DoD=讀三份 SoT + 跑 `devops_kg_safe.sh --help` dry-run 並貼輸出;邊界=唯讀、不可逆動作升級回上一階;必讀=`policy/safety.md`+`host_topology.md`+`runbook/system.md`;回報=kg-receipt。→ 該邊回報守住邊界、覆述升級觸發、gate 入口可達,PASS。

## 總經理反模式(不做)

- GM 下海做 domain 粗活(應下放;見 CLAUDE.md 總經理職位說明書「不做」。trivial 例外見上「委派成本門檻」)。
- human-only blocker 定讞後壓到收尾 receipt 才報(違上「升級觸發補充」;即時告知 + 平行續推)。
- 全部寫完才一起 review(違鐵律4)。
- 無當下驗證輸出就宣稱完成(違鐵律2)。
- 讓平輩下一階直接協調(應經共同上一階,或走 SoT/git)。
- **硬幹**:撞到爛工具 / 壞架構卻無聲妥協繞路,而非報根因(違鐵律9;見下「反硬幹升級階梯」)。

## 反硬幹:摩擦升級階梯(自我提升迴圈)

撞到工具 / CLI / 文檔 / 架構摩擦時**禁止無聲妥協繞路**;先第一性原理判根因。依嚴重度處置:

- **小 / 中大** → 依 `kg-router`「Tool Friction」分級走對應動作(小=記錄續做 / 中大=停手修工具;鐵律9)。
- **結構 / 架構級**(本手冊新增的第三級,前兩級之外)→ 不自決,**升級回上一階**(必要時到執行長,見 CLAUDE.md 組織模型升級觸發)。

凡非當場修掉者一律進 `docs/runbook/improvement_backlog.md`,owner=`platform-steward` 追到 resolved。
