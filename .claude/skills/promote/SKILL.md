---
name: promote
description: "Converge skill 的 promote mode alias：活 branch 已提交子集升格，核心方法論見 ../converge/。"
user-invocable: true
version: 2.0.0
---

# Promote

`promote` 不再維護自己的獨立方法論。  
它是 [`../converge/`](../converge/SKILL.md) 的 **`mode=promote` alias**。

## 這個 alias 代表什麼

- 某條 branch 還在持續修改
- 但其中一部分**已提交內容**要先成為 shared baseline
- 原 branch / worktree 預設仍保留

## 真正的方法論

請直接讀：

1. [../converge/SKILL.md](../converge/SKILL.md)
2. [../converge/methodology.md](../converge/methodology.md)
3. [../converge/checklists.md](../converge/checklists.md)
4. [../converge/casebook.md](../converge/casebook.md)

## Promote Mode 契約

- 只升格本輪 snapshot 以內的**已提交 commits**
- dirty work 若要納入，先落成 snapshot，再切 promote 邊界
- 驗證與整合在離線 integration worktree 做
- cutover 只發布已準備好的 final state
- 除非使用者明確要求，不自動清原 branch / worktree

## 最小輸出

- 本輪 snapshot commit
- 進 `main` 的 commits
- 原 branch 是否已 rebase 到新 `main`
- 原 branch / worktree 是否保留
