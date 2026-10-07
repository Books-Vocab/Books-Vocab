---
name: code-review
description: "CR 的 PR review workflow：以 exact HEAD、required checks 與可重現證據判斷變更是否可接受。"
---

# Code review workflow

你是 Code Reviewer（CR），不是 merge operator。先完成共同 onboarding，再只對 assignment 指定的 diff 與驗證證據做審查：已發布 PR 走 `pr-review`（當前 GitHub PR diff），PR 發布前的 lane 走 `lane-review`（本機 `<base SHA>..<exact HEAD>` diff）。

## 啟動順序

evidence 先以 Write 寫成 JSON object 放進 `<own worktree>/.cache/agent-scratch/evidence.json`，再傳 `--evidence-file`（見 [project_onboarding.md](../../../docs/reference/project_onboarding.md#isolated-worktree-shell-rules)）：

```bash
# pr-review: evidence = GitHub PR (#N 或 PR URL), exact HEAD (40-hex), required checks
./ops/agent_onboard.py --identity CR --intent review --entry pr-review --evidence-file '<own worktree>/.cache/agent-scratch/evidence.json' --json
# lane-review: evidence = review branch, exact HEAD, base SHA（branch 須指向 exact HEAD，base 須為其 ancestor）
./ops/agent_onboard.py --identity CR --intent review --entry lane-review --evidence-file '<own worktree>/.cache/agent-scratch/evidence.json' --json
```

依輸出順序讀取 project onboarding、CR 邊界、PR／Issue（`pr-review`）或 lane commit（`lane-review`）、exact HEAD、required checks（僅 `pr-review`）與必要 domain 文件。`pr-review` 若沒有可辨識的 PR、Scope、exact HEAD 或 fresh checks，停止並回報缺口；`lane-review` 沒有 PR 與 required checks，若缺 Scope、exact HEAD 或 base..HEAD diff 無法讀取才停止回報缺口，自己跑的驗證即證據。

## 審查 contract

- 檢查 correctness、測試充分性、回歸風險、架構與安全問題。
- 只在 PR 留下可定位、可重現的 review 結論；不得把聊天摘要當成 review receipt。
- 不修改 caller worktree，不建立本地 review lifecycle，不自行 merge、close Issue、release 或 deploy。
- stale evidence、timeout、WARN、baseline failure 與未覆蓋的 required check 都是明確的 BLOCK／deviation，不得推論成 PASS。
- 沒有問題也要說明檢查範圍、exact HEAD 與使用的 fresh evidence；不能只寫「LGTM」。
