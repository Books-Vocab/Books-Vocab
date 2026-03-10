---
description: 分析變更並執行版本發布（backend / iOS / both）
---

# Release 流程

你是 KG 專案的發布管理員。請按以下步驟執行：

## 1. 分析現況

執行以下指令收集資訊：

```bash
# 找最近的 tag
git tag -l "api/*" --sort=-v:refname | head -1
git tag -l "ios/*" --sort=-v:refname | head -1

# 分析 backend 變更
git log $(git tag -l "api/*" --sort=-v:refname | head -1)..HEAD --oneline --no-merges | grep -i "^[a-f0-9]* api:" || echo "（無 backend 變更）"

# 分析 iOS 變更
git log $(git tag -l "ios/*" --sort=-v:refname | head -1)..HEAD --oneline --no-merges | grep -i "^[a-f0-9]* ios:" || echo "（無 iOS 變更）"

# 分析 ops/docs 變更
git log $(git tag -l "api/*" --sort=-v:refname | head -1)..HEAD --oneline --no-merges | grep -iE "^[a-f0-9]* (ops|docs):" || true
```

如果沒有任何 tag 存在，用 `git log --oneline --no-merges` 取所有 commits。

## 2. 向使用者報告

用以下格式報告：

```
上次 Backend 版本：api/x.y.z（或「尚未發版」）
  → 之後有 N 個 commit：[簡要列出]
  → 建議版本：x.y.z（原因）

上次 iOS 版本：ios/x.y.z（或「尚未發版」）
  → 之後有 N 個 commit：[簡要列出]
  → 建議版本：x.y.z（原因）

要發布哪些？
```

版本號建議邏輯：
- 有 breaking change / 大功能 → **minor** bump
- 僅修復、微調 → **patch** bump
- 架構重寫 → **major** bump
- 如果是首次發版，根據現有 pyproject.toml / xcodeproj 版本提議

## 3. 等待使用者確認

**不要自行決定**，等使用者說：
- 「好」→ 按建議執行
- 「只發 backend」→ 只處理 backend
- 「版本改 2.0.0」→ 用使用者指定的版本號
- 其他調整 → 照辦

## 4. 執行發布

確認後依序執行：

### 對每個要發布的 component：

```bash
# 更新版本號
scripts/bump-version.sh <api|ios> <version>

# 生成 changelog 預覽
scripts/generate-changelog.sh <api|ios>
```

展示 changelog 給使用者看，確認無誤後：

```bash
# Commit
git add -A
git commit -m "ops: release <component> <version>"

# Tag
git tag <api|ios>/<version>

# Push（含 tag）
git push origin main --tags
```

如果同時發布 backend 和 iOS：
1. 先 bump 兩邊版本
2. 一次 commit：`ops: release api <ver> + ios <ver>`
3. 打兩個 tag
4. 一次 push

## 5. 報告結果

```
✓ 已推送 tag，GitHub Actions 正在執行：
  - Backend: [連結到 Actions]
  - iOS: [連結到 Actions]

下一步：等 CI 完成，會自動建立 GitHub Release。
```

## 注意事項

- push 前確認 working tree 乾淨
- 如果有未 commit 的變更，先詢問使用者是否要一起包進去
- **絕不跳過使用者確認步驟**
