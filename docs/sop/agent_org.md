<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - CLAUDE.md
  - .claude/agents/
  - .claude/skills/kg-router/
  - .claude/skills/kg-receipt/
verified_against: d5542a1
-->
# 組織營運手冊（總經理 SOP）

> 本文是 CLAUDE.md「組織模型(營運憲法)」的**可執行版**——憲法定義「節點 / 邊 / 委派契約」,本文定義「總經理拿到任務後怎麼跑」。
> **權威在憲法**;本文只串指標、給可填模板與已驗證實例,**不複述**鐵律與契約定義(SoT 零重複)。

## 何時讀本文

總經理(上一階為執行長的節點)接到**有複雜度**的任務——需拆解 / 跨部門 / 多步驟 / 接手陌生範圍——時讀。純樣板(typo / rename / 單檔已指明範圍)不適用。冷啟動找入口先觸發 `kg-router`。

## 任務生命週期:七拍

逐拍進行,每拍指向既有規則,不重述判準:

1. **Intake 受理** — 意圖澄清。只有「升級觸發」(見 CLAUDE.md 組織模型)才回問執行長,否則自決後告知。
2. **Planning 規劃** — 拆 WBS;選派任形狀(見下);決定派哪些下一階(`.claude/agents/` 目錄即名冊,`ls` + frontmatter `description` 查職責)。
3. **Execution 執行** — 下行 task brief(模板見下);**所有 `Agent()` 背景執行**(鐵律5),主線不阻塞。
4. **Review gate 逐項** — 每個交付立即過 review,PASS 才下一個;禁批次(鐵律4 / `docs/sop/review_discipline.md`)。
5. **Integration & Verify 整合驗證** — 彙整下一階產出;宣稱完成前必有**當下驗證輸出**(鐵律2)。
6. **Report 回報** — 上行 receipt(`kg-receipt`)+ 明確下一步,交回上一階。
7. **Retro 復盤** — 工具摩擦:小問題記 tooling debt、中大型立即修工具(鐵律9)。

## 派任形狀

- **fan-out(平行 / map-reduce)** — 子任務彼此獨立 → 一次派多個下一階,各自背景跑,總經理彙整。管理幅度:一次直接下一階建議 **≤5**(見 CLAUDE.md「對話啟動流程」的 2–5 建議),並發勿爆。
- **pipeline(接力)** — 前一交付餵後一(例:`podcast` 分析 → 規劃 → 腳本 → TTS → 字幕)。每棒仍是「上一階 → 單一下一階」,**深 pipeline 不是深巢狀**。
- **協作介質** — 下一階之間**不平輩直連**;共享狀態走 SoT docs / git(blackboard),跨節點交集靠檔案而非傳話。

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

- GM 下海做 domain 粗活(應下放;見 CLAUDE.md 總經理職位說明書「不做」)。
- 全部寫完才一起 review(違鐵律4)。
- 無當下輸出就宣稱「完成 / 應該可以」(違鐵律2)。
- 讓平輩下一階直接協調(應經共同上一階,或走 SoT/git)。
