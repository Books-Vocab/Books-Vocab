---
name: kg-receipt
description: "在 commit／PR 或 worktree hand-back 收尾時，輸出可驗證的最小交接摘要。"
---

# Handoff summary

這個 skill 只產生文字摘要，不保存資料、不建立工作項目、不取代 GitHub PR。

## Required fields

- result：做了什麼；
- branch／worktree／exact HEAD；
- Issue／PR external ID（若已有）；
- Scope；
- commands、exit status、log／artifact path；
- deviations、blockers、需要下一位做的安全動作。

## Rules

只報當下有輸出的證據。clean tree、舊 log、未執行的命令與推測都不能寫成 pass。若測試 timeout、權限不足、基線失敗或工作樹被他人占用，原樣報告並停止需要該條件的後續動作。
