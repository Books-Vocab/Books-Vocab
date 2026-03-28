---
name: execute
description: "Use when there is a plan to execute — handles worktree setup, parallel opus agent dispatch, dual review, PR creation, build verification, and cleanup in one flow."
allowed-tools: Agent, Bash, Read, Edit, Write, Glob, Grep
user-invocable: true
---

# Execute: Plan → PR

拿到 plan 就跑到底。一個 skill 涵蓋從 worktree 到 merge 的全閉環。

**所有 agent 一律 opus。無例外。**

## 流程

### Phase 1: Setup

```bash
# 自動建 worktree
git worktree add .claude/worktrees/exec-<feature> -b worktree-<feature>
```

讀 plan，提取所有 task 的完整文字與上下文。

### Phase 2: Execute（自動）

對每個 task 依序：

1. **Dispatch opus implementer agent**（見 `implementer-prompt.md`）
   - `isolation: "worktree"`（若 plan 中 task 可平行則平行 dispatch，否則依序）
   - 所有 agent 用 `model: "opus"`

2. **處理 implementer 回報**
   - DONE → 進 review
   - DONE_WITH_CONCERNS → 評估後進 review
   - NEEDS_CONTEXT → 補充上下文，重 dispatch
   - BLOCKED → 升級處理（拆小、補 context、escalate 使用者）

3. **Dispatch opus spec reviewer**（見 `spec-reviewer-prompt.md`）
   - ❌ → implementer 修 → 重 review
   - ✅ → 進 code quality review

4. **Dispatch opus code quality reviewer**（見 `code-quality-reviewer-prompt.md`）
   - ❌ → implementer 修 → 重 review
   - ✅ → mark task complete

### Phase 3: Final Review

所有 task 完成後，dispatch opus code-reviewer（見 `code-reviewer.md`）做全量 review。

### Phase 4: PR + Build

```bash
# Push
git push -u origin <branch>

# Create PR
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<bullets>

## Test plan
<checklist>
EOF
)"
```

iOS 專案必須跑：
```bash
./ops/ios_build.sh
```

Build 失敗 → 讀錯誤 ±20 行，修復，重新 commit + push，再 build。

### Phase 5: Cleanup

```bash
git worktree remove <path>
git worktree prune
```

向使用者報告：PR URL、檔案數、行數。

## 平行策略

- Plan 中標記為獨立的 task：**同時 dispatch 多個 opus agent**（各自 worktree isolation）
- 有依賴的 task：依序執行
- 單批不超過 7 個 agent
- 超過 7 個則分批

## 關鍵原則

- **所有 agent 一律 opus** — 不降級，不省 token
- **先寫 failing test** — agent 遵循 TDD
- **完工前必驗證** — 不接受「should work」，要看實際輸出
- **衝突解決**：兩邊都保留，不丟改動
- **GitHub API 延遲**：force-push 後等 5 秒再 merge

## 禁止

- 直接在 main 上改（除非使用者明確指示）
- 跳過任何 review 階段
- 帶著未修的 issue 進下一個 task
- 信任 agent 的 success report 而不驗證
- 用非 opus model
