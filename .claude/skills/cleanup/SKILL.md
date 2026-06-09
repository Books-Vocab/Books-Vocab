---
name: cleanup
description: "Converge skill 的 cleanup mode alias：黑名單驅動收斂，核心方法論見 ../converge/。"
user-invocable: true
version: 6.0.0
---

# Cleanup

`cleanup` 不再維護自己的獨立 playbook。  
它是 [`../converge/`](../converge/SKILL.md) 的 **`mode=cleanup` alias**。

## 這個 alias 代表什麼

- 使用者先定黑名單
- 非黑名單工作應收進 `main`
- surviving 黑名單應 rebase 到新 `main`
- 白名單殘影應清掉

## 真正的方法論

請直接讀：

1. [../converge/SKILL.md](../converge/SKILL.md)
2. [../converge/methodology.md](../converge/methodology.md)
3. [../converge/checklists.md](../converge/checklists.md)
4. [../converge/casebook.md](../converge/casebook.md)

## Cleanup Mode 契約

- 先立 `T0 snapshot barrier`
- 本輪只處理 `T0` 以前的白名單/黑名單快照
- 驗證與整合在離線 integration/final worktree 做
- cutover 只做序列化發布，不回頭追逐 hot branch
- `T0` 之後的新 dirty / new commits 自動進下一輪

## 最小輸出

- 黑名單清單
- 每條活分支的 snapshot commit
- 收進 `main` 的白名單內容
- 黑名單的新 base
- preserved work mapping
- remote 同步狀態
- 最終 `git status` / `worktree list` / `branch_audit`
