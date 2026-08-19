---
name: app-debug
description: "KG bug、test failure、unexpected behavior 的根因調查與量測路由；不直接授予 production 或 destructive 權限。"
---

# KG debug route

這個 skill 只規範除錯的判斷、證據與交接；穩定技術細節以
[`docs/sop/debug.md`](../../../docs/sop/debug.md) 為唯一 SoT。載入前必須已完成
`project → identity → assignment` onboarding；需要改 code 時必須有 branch／worktree
與 structured Scope。

## 固定流程

1. 保存 exact failure：錯誤、reproducer、environment、current HEAD 與影響面。
2. 先靜態追溯 source／call path、test、fixture、log 或 health；可由現有證據判定時不
   先加猜測性 patch。
3. 若是 behavior／performance／UI／timing，先寫可證偽預測：一個成功簽名、至少兩個
   失敗簽名及其下一步；先 instrument／capture，再改行為。兩次預測未命中即停止推理，
   轉 measurement loop。
4. 需要多個獨立假說時可 fan-out，但每個 agent 必須有不重疊 Scope、獨立 reproducer、
   evidence 與結論；不得把猜測合併成「可能通過」。
5. 實作走 RED → minimal fix → GREEN；檢查 regression、source／test／docs impact，
   再以 `kg-receipt` hand back。

## 邊界

- iOS／Simulator／真機 capture 讀 [`docs/sop/ios.md`](../../../docs/sop/ios.md) 與
  `docs/sop/ui_flow_evidence.md`；PerfLog 的 API、category 與 retention 只看
  `ios/BooksAndVocab/Services/PerfLog.swift` 與 debug SOP。
- backend、infra、deploy、restore 不能由本 skill 自行跨界；分別 route 到 domain
  docs 與 `devops_kg_safe.sh`／release／backup SOP。
- 不直接寫 `main`、不直接改 production、不繞 safe wrapper、不保留 raw UI video，除非
  assignment 明確要求並符合對應批准邊界。

## 交接最小內容

`reproducer`、exact HEAD、commands／exit status、evidence identity、root cause、
changed paths、regression result、docs impact、deviation、未解 blocker 與下一步。
「應該好了」或只有一個綠色測試不能結案。
