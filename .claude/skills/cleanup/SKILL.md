---
name: cleanup
description: "全流程收尾：merge open PRs → update docs → git cleanup → test → deploy。一次 /cleanup 搞定所有。"
user-invocable: true
version: 2.0.0
---

# Cleanup: 全流程收尾

合併 merge-prs、update-docs、git-cleanup 三個流程。每個 phase 結束後報告，使用者確認再進下一步。

---

## Phase 1 — 狀態收集（平行執行）

```bash
git status
git stash list
git branch -a
git log --oneline origin/main..HEAD  # 未 push commits
git worktree list
gh pr list --state open
```

報告分類：未提交修改 / 未 push commit / stash / 非 main 分支 / 額外 worktree / open PR。

如果有未提交修改，先 `git stash` 再繼續。

---

## Phase 2 — Merge PRs

跳過條件：無 open PR。

### 2a. 平行取得每個 PR 的 metadata + diff

```bash
gh pr view <N> --json title,body,additions,deletions,files,mergeable,mergeStateStatus
gh pr diff <N>
```

### 2b. 審查並報告

對每個 PR 報告：

```
### PR #N — 標題 (+A/-D, F files) [MERGEABLE|CONFLICTING]
- 邏輯/設計是否正確
- design token 違規（raw color/font/spacing/animation）
- L10n 雙語完整性
- 問題或風險
```

審查重點：
- 讀 diff 找隱藏 bug（如 HTTP/2 case-sensitive header）
- 確認 Localizable.strings 的 en + zh-Hant 都有新增
- 確認 @Observable / @Environment / @Bindable 用法正確

### 2c. 排序 merge 順序

- CLEAN 先，CONFLICTING 後
- 同檔案衝突預判（尤其 Localizable.strings）
- backend-only PR 優先（不影響 iOS 編譯）

### 2d. 逐一 merge（使用者確認後）

```bash
gh pr merge <N> --squash --delete-branch
```

每 merge 一個後，如果下一個 PR 變 CONFLICTING：

```bash
git fetch origin
git checkout <branch>
git rebase origin/main
# 解衝突（Localizable.strings：保留雙方新增 key）
git add <files> && git rebase --continue
git push --force-with-lease origin <branch>
gh pr merge <N> --squash --delete-branch
```

### 2e. 同步本地 main

```bash
git fetch origin
git rebase origin/main
```

注意：squash merge 後本地 commit 會 diverge，**必須用 rebase 不能 pull**。

---

## Phase 3 — Update Docs

跳過條件：Phase 2 無任何 merge 且無 code 變更（`change_list` 為空）。

### 3a. Snapshot

```bash
# 上次文檔更新 commit
git log --oneline --all --grep="docs:" -1

# 從那之後的 non-merge commits
git log --oneline <last_docs_sha>..HEAD --no-merges

# 帶 doc-meta 的文檔及其 verified_against
grep -r "verified_against" docs/

# 當前 HEAD
git rev-parse --short HEAD
```

產出：`change_list`、`stale_map`（verified_against != HEAD 的文檔）、`head_sha`。

同時將 `CLAUDE.md` 的 "Implemented Product Surface" 段落納入審計。

### 3b. Parallel Audit（opus agents，背景執行）

為每份 stale 文檔 dispatch 1 個 agent（`model: "opus"`，`run_in_background: true`）。

每個 agent 收到：文檔完整內容 + `change_list` + doc-auditor-prompt.md 的指令。

### 3c. Execute

收齊 audit 報告後：
1. 列出所有建議的摘要表，供使用者確認
2. 逐一 Edit（精確到 old_string → new_string）
3. 更新修改過文檔的 `verified_against` → `head_sha`

### 3d. Self-check

```bash
grep -r "verified_against" docs/
git diff --stat
```

### 規則
- Phase 3b agent 只分析不 Edit — 所有修改由主 agent 統一執行
- CLAUDE.md Product Surface 必須納入審計
- 不創建新文檔，只更新現有文檔
- verified_against 只在有內容修改時才更新

---

## Phase 4 — Git Cleanup

### 4a. 清理項目（使用者確認後執行）

- 刪殘留分支：`git branch -D <branch>` + `git push origin --delete <branch>`
- 清 stash：`git stash drop` / `git stash clear`
- Prune stale refs：`git remote prune origin`

### 4b. 狀態確認

```bash
git status
git stash list
git branch -a
git worktree list
```

---

## Phase 5 — 測試驗證（平行執行）

跳過條件：Phase 2 無任何 merge。

```bash
# iOS 編譯（自動排隊鎖）
./ops/ios_build.sh

# Backend 測試
python -m pytest backend/tests/ -x -q
```

兩者獨立，用背景任務平行跑。

---

## Phase 6 — 部署（如有 backend 變更）

跳過條件：merge 的 PR 中無 backend 檔案變更。

```bash
./ops/devops_kg_safe.sh backup
./ops/devops_kg_safe.sh deploy
```

---

## Phase 7 — 最終報告

```
## Cleanup 完成

### PRs
- PR #N ✅ merged — 標題
- PR #M ✅ merged — 標題

### Docs
| 文檔 | 變更摘要 | verified_against |
|------|----------|-----------------|
| ... | ... | ✅ <sha> |

### Git
- 分支清理：N 個已刪
- Stash：已清 / 無
- Worktree：已清 / 無

### 驗證
- iOS 編譯 ✅ / ❌
- 後端測試 ✅ N passed / ❌
- 部署 ✅ HTTP 200 / 跳過
```

---

## 踩坑備忘

1. **Localizable.strings 永遠會衝突**：每個 PR 都在末尾加 key，解法是保留雙方所有新增行
2. **切 branch 前一定 stash**：忘了 stash 會被 git 擋住
3. **`--force-with-lease` 不是 `--force`**：rebase 後推 branch 用前者
4. **squash merge 後本地會 diverge**：必須 `git rebase origin/main`，不能 `git pull`
5. **docs 審計只改過時內容**：不做「順便改善」
