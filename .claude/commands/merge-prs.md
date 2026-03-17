---
description: 批量審查、合併 PR，同步本地，跑測試驗證
---

# PR 批量 Merge 流程

你是 KG 專案的 PR merger。按以下步驟執行：

## 1. 列出所有 open PR

```bash
gh pr list
```

## 2. 平行取得每個 PR 的 metadata + diff

對每個 PR **同時**執行：
- `gh pr view <N> --json title,body,additions,deletions,files,mergeable,mergeStateStatus`
- `gh pr diff <N>`

## 3. 審查並報告

對每個 PR 報告：

```
### PR #N — 標題 (+A/-D, F files) [MERGEABLE|CONFLICTING]
- 邏輯/設計是否正確
- 是否遵循 design token 規範（raw color/font/spacing/animation 違規）
- L10n 雙語是否完整
- 問題或風險標註
```

**審查重點**：
- 不只看 summary，要讀 diff 找隱藏 bug（如 HTTP/2 case-sensitive header）
- 確認 Localizable.strings 的 en + zh-Hant 都有新增
- 確認 @Observable / @Environment / @Bindable 用法正確

## 4. 排序 merge 順序

- **CLEAN 先 merge，CONFLICTING 後處理**
- 如果兩個 PR 改同一個檔案（尤其 Localizable.strings），預期第二個會衝突
- backend-only PR 優先（不影響 iOS 編譯）

## 5. 逐一 merge

```bash
gh pr merge <N> --squash --delete-branch
```

每 merge 一個後：
1. 如果下一個 PR 原本是 CLEAN，它可能已變 CONFLICTING（因為 main 前進了）
2. 需要 rebase：
   ```bash
   git stash  # 如有本地未提交改動
   git fetch origin
   git checkout <branch>
   git rebase origin/main
   # 解衝突（Localizable.strings 最常見：保留雙方新增的 key）
   git add <files> && git rebase --continue
   git push --force-with-lease origin <branch>
   gh pr merge <N> --squash --delete-branch
   ```

## 6. 同步本地 main

```bash
git stash  # 如有未提交改動
git fetch origin
git rebase origin/main
git stash pop
```

注意：squash merge 後本地 main 的原始 commit 會 diverge，`git pull` 會失敗，**必須用 rebase**。

## 7. 測試驗證（平行執行）

```bash
# iOS 編譯（自動排隊鎖）
./ops/ios_build.sh

# Backend 測試
python -m pytest backend/tests/ -x -q
```

兩者獨立，用背景任務平行跑。

## 8. 部署（如果有 backend 變更）

```bash
./ops/devops_kg_safe.sh backup
./ops/devops_kg_safe.sh deploy
```

## 9. 報告結果

```
- PR #N ✅ merged — 標題
- PR #M ✅ merged — 標題
- iOS 編譯 ✅ / ❌
- 後端測試 ✅ N passed / ❌
- 部署 ✅ HTTP 200 / （無 backend 變更，跳過）
```

## 踩坑備忘

1. **Localizable.strings 永遠會衝突**：每個 PR 都在末尾加 key，解法是保留雙方所有新增行
2. **切 branch 前一定 stash**：忘了 stash 會被 git 擋住
3. **`--force-with-lease` 不是 `--force`**：rebase 後推 branch 用前者，能防覆蓋
4. **`gh pr merge` 可能靜默成功但本地不知道**：merge 後一定 `fetch` 確認
5. **HTTP header 之類的隱性 bug**：review 時要讀 code 不是只看 PR body
