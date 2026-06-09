---
name: promote
description: "Workflow 2. 活 branch 已提交子集升格：把指定已提交 commits 先拉進 main，再讓原 branch 繼續活著並 rebase 到新 main。"
user-invocable: true
version: 1.0.0
---

# Promote

`promote` = `Promote Active Branch`

這不是 `cleanup` 的別名輸出，而是獨立的命名入口。

## 什麼時候用

- 某條 branch 還在持續修改
- 但其中一部分**已提交內容**已經值得成為 shared baseline
- 你不想打斷 branch 本體，也不想把它整條吸收進 `main`

## 核心契約

- 只 promote **已提交 commits**
- dirty work 若也想納入本輪，先在原 branch commit 成 snapshot
- promote 解決的是內容升格，不自動代表 branch / worktree 生命周期結束
- 除非使用者明確要求，promote 完**不自動清 branch / worktree**

## 執行順序

1. 先讀 [../cleanup/SKILL.md](../cleanup/SKILL.md)：共用哲學與 snapshot 規則
2. 再讀 [../cleanup/playbook.md](../cleanup/playbook.md) 的 `promote` 區段
3. 動手前跑 [../cleanup/checklists.md](../cleanup/checklists.md)
4. 遇到相似情境時讀 [../cleanup/casebook.md](../cleanup/casebook.md)

## 最小輸出契約

- 這輪 promote 的 snapshot commit
- 進 `main` 的 commits
- 原 branch 是否已 rebase 到新 `main`
- branch / worktree 是否保留
