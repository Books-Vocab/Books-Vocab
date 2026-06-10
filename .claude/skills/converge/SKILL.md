---
name: converge
description: "Branch/worktree convergence：A=cleanup 全收斂（all black 保留 / all white 刪光），B=promote 單分支升格，組合式全量收斂一次 merge 多個。核心=白名單進 main → 黑名單 rebase → sync remote → 清殘影。"
user-invocable: true
version: 2.0.0
---

# Converge

讓 main 成為最新 shared baseline，所有活分支都基於它。

---

## 三種模式

| 模式 | 白名單 | 黑名單 | 結束後 |
|------|--------|--------|--------|
| **A all black** | 無（全部保留） | 全部 | 全部 rebase 到 main，全部保留 |
| **A all white** | 全部（全部進 main） | 無 | 全部 merge 進 main，全部刪除 |
| **B promote** | 指定的 branch | 其餘 | 白名單 merge 進 main，黑名單 rebase 保留 |
| **組合式全量** | 全部一次性 merge | 無 | 一次 push + 最少 rebase |

---

## 高效配方（先認形狀，再動手）

別逐步探索 —— `branch -vv` 的 ahead/behind + commit subject 通常一眼就定形狀。對症下藥：

**形狀 A：一個 integration superset + N 個 raw 子集**（常見於多 agent 平行做 flow，其中一條是整合 branch）
1. `fetch && branch -vv && worktree list && git status --porcelain`（**一次拿全**；dirty 同呼叫掃各 worktree）。**信 porcelain 當下真相，不信注入的舊 status snapshot。**
2. 看 ahead/behind + subject 認形狀：superset ahead 最多、raw 子集 ahead 少且 subject 同主題 → superset 假設成形。
3. merge superset → main（已 union 過的整合 branch 通常零衝突）。
4. 每個 raw 子集：`git diff main..<branch> -- <該 branch 唯一檔>` **空 = 冗餘 → 刪**（merge 它反而把舊 baseline 共用檔 regress 回 main）。
5. build gate → push（head commit 進 base 會讓對應 PR **自動翻 MERGED**）→ 清殘影 → 問測試。

**判 containment 一律走 tree-diff，禁用 `git cherry`/patch-id**（rebase 過必失準，全噴 `+` 是噪音）。取證取「決定性的那一個」（唯一檔 diff 是否空），不要倒整份 `diff --stat` / `grep '^+'` —— diffstat 的刪除總量已說完故事。

**衝突自動化已落地**：`UITestFixtureSeed.swift` / `PerfLog.swift` / `UITestAppLaunch.swift` 在 `.gitattributes` 設 `merge=union`（append-only case registry，自動聯集兩側新增行，build gate 當 backstop）。本地另開 `git config rerere.enabled true` 重播解法。沒有 integrator 整合的多條 raw branch 仍可能衝突，但這三檔已自動化。

---

## 通用前置步驟

每次 converge 前必做：

```bash
git fetch --all --prune
git branch -vv
git worktree list
git status --short
```

檢查每個 worktree 的 dirty work：

```bash
for wt in $(git worktree list --porcelain | grep '^worktree ' | cut -d' ' -f2-); do
  echo "=== $(basename $wt) ==="
  git -C "$wt" status --short
done
```

---

## Mode A — all black（全部保留，不 merge）

目標：所有分支基於最新 main，內容不進 main。

```bash
# 1. main 有 ahead commits 先 push
git push origin main

# 2. 並行 snapshot（如果有 dirty work）
for wt in <worktree-paths>; do
  git -C "$wt" add -A
  git -C "$wt" commit -m "<prefix>: snapshot — <desc> (converge pre-rebase)"
done

# 3. 並行 rebase 全部 branches → main
for wt in <worktree-paths>; do
  git -C "$wt" fetch origin main
  git -C "$wt" rebase origin/main
  git -C "$wt" push origin HEAD --force-with-lease
done

# 4. 驗收
git branch -vv
git worktree list
git status --short
```

---

## Mode A — all white（全部進 main，全部刪除）

目標：所有分支內容進 main，remote + local + worktree 全清。

```bash
# 1. main push
git push origin main

# 2. 並行 snapshot 所有 worktree（**必做**，否則 dirty work 會丟失）
for wt in <worktree-paths>; do
  git -C "$wt" add -A
  git -C "$wt" commit -m "<prefix>: snapshot — <desc> (converge pre-cleanup)"
done

# 3. main 上一次過 merge 全部 branches
git checkout main
for branch in <all-branches>; do
  git merge "$branch" --no-edit
done
git push origin main

# 4. 清殘影（順序：remote → worktree → local）
# 4a. remote
git push origin --delete <branch1> <branch2> <branch3>

# 4b. worktree
git worktree remove <path1>
git worktree remove <path2>
git worktree remove <path3>
# 若有孤兒（.git 連結壞掉）：git worktree prune --verbose

# 4c. local
git branch -D <branch1> <branch2> <branch3>

# 5. 驗收
git branch -vv          # 只剩 main
git worktree list       # 只剩 main + deploy
git status --short      # 乾淨
```

---

## Mode B — promote（單分支升格，其餘保留）

目標：指定 branch merge 進 main，其餘 rebase 到新 main。

```bash
# 1. main push
git push origin main

# 2. snapshot 目標 branch（如果 dirty）
git -C <target-worktree> add -A
git -C <target-worktree> commit -m "<prefix>: snapshot — <desc> (converge pre-promote)"

# 3. merge 目標 branch
git checkout main
git merge <target-branch> --no-edit
git push origin main

# 4. 所有其他 branch rebase → 新 main
for wt in <other-worktrees>; do
  git -C "$wt" fetch origin main
  git -C "$wt" rebase origin/main
  git -C "$wt" push origin HEAD --force-with-lease
done

# 5. 目標 branch 也 rebase（保留不刪）
git -C <target-worktree> fetch origin main
git -C <target-worktree> rebase origin/main
git -C <target-worktree> push origin HEAD --force-with-lease

# 6. 驗收
git branch -vv
git worktree list
git status --short
```

---

## 組合式全量收斂（最高效）

**適用：**所有 branches 都要進 main，不刪除。

**核心：**一次 merge 全部 + 一次 push + 最少 rebase。

```bash
# Phase 0: 盤現況
git fetch --all --prune
git branch -vv
git worktree list

# Phase 1: 並行 snapshot
git -C <wt1> add -A && git -C <wt1> commit -m "..."
git -C <wt2> add -A && git -C <wt2> commit -m "..."

# Phase 2: 並行 rebase 全部 → current main（減少 merge conflict）
git -C <wt1> fetch origin main && git -C <wt1> rebase origin/main && git -C <wt1> push origin HEAD --force-with-lease
git -C <wt2> fetch origin main && git -C <wt2> rebase origin/main && git -C <wt2> push origin HEAD --force-with-lease

# Phase 3: main 上一次過 merge 全部
git checkout main
git merge <branch1> <branch2> <branch3> --no-edit   # octopus merge
git push origin main

# Phase 4: 並行 rebase 全部 → 最終 main（fast-forward）
git -C <wt1> fetch origin main && git -C <wt1> rebase origin/main && git -C <wt1> push origin HEAD --force-with-lease
git -C <wt2> fetch origin main && git -C <wt2> rebase origin/main && git -C <wt2> push origin HEAD --force-with-lease

# Phase 5: 驗收
git branch -vv
git worktree list
```

**成本對比：**

| 方式 | push main | rebase 輪次 |
|------|-----------|-------------|
| 逐個 B（Round 3+4） | N 次 | 2N 次 |
| **組合式** | **1 次** | **2 次** |

---

## 輸出報告模板

每次 converge 結束必報告：

```
## Converge — <Mode>

**main:** `<hash>`

**進了 main 的內容：**
- branch / commits / PR #

**Snapshot 已提交：**
- <worktree>: <hash> — <desc>

**已 rebase + remote sync：**
| Branch | HEAD | 狀態 |
|--------|------|------|
| ... | ... | ahead N / = main |

**已刪除：**
- remote: ...
- local: ...
- worktree: ...

**還活著的 branch:** ...
**git status:** 乾淨 / 有 untracked ...
```

---

## 實戰踩坑（11 條）

### 1. 清殘影順序

**all white 正確順序：**remote → worktree → local branch

錯誤：先 `git branch -D` → branch 刪不掉（還綁著 worktree）

### 2. 沒有 upstream 的 branch

`git push` 會噴 fatal。**預設命令：**`git push origin HEAD --force-with-lease`

### 3. 孤兒 worktree

`.git` 連結壞掉時 `git worktree remove` 報 fatal。**修復：**`git worktree prune --verbose`

### 4. 不能跨 worktree checkout

在 worktree A 裡不能 `git checkout main`。**修復：**`cd <target-worktree>` 或 `git -C <path>`

### 5. remote branch 不存在

`git push origin --delete` 報 `remote ref does not exist`。**修復：**跳過繼續清 local + worktree

### 6. 熱檔案多 worktree 漂移

`ICloudDownloadManager.swift`、`UITestFixtureSeed.swift` 會在多個 worktree 同時被改。**修復：**改完就 commit，不留 dirty work 過夜

### 7. main 上有 dirty work 會擋 merge

merge 前必須 `git status` 確認乾淨，否則 `error: Your local changes would be overwritten`

### 8. `git rebase origin/main` 顯示 up to date 但有 commits

branch 的 commits 內容已經在 main 中（不同 hash），rebase 會 drop。**無害，直接 merge 即可。**

### 9. all white 時 worktree 有 dirty work 不處理就刪 = 丟失

必須先 snapshot + merge 進 main，再清殘影。不要用 `git worktree remove --force` 硬幹。

### 10. octopus merge 遇 conflict 會直接失敗

`git merge A B C` 若有任何兩個 branch 衝突，git 不支援 octopus conflict 解決。**修復：**fallback 到逐個 merge

### 11. converge 後 branch 又長 dirty work = 循環

如果有人在 worktree 持續工作，每次 converge 都會發現新 dirty。**修復：**
- 紀律：converge 前停手
- 或接受「不完美收斂」，最後一次 snapshot 留在 branch 上

---

## 鐵律

- **先 fetch**，永遠先看 origin/main 的真實狀態
- **merge / rebase 前確認 working tree 乾淨**（`git status`）— rebase 不允許 dirty tree
- dirty 時：**立即 commit snapshot**，不 stash（stash 會丟身份資訊）
- **force-push 只用 `--force-with-lease`**，不用 `-f`
- **刪 remote branch 前先確認它存在**，不存在就跳過
- **all white 清 worktree 前先 snapshot**，否則 dirty work 會丟失
- **驗證以 build gate 為準，耗時測試問過再跑**：merge 完成後跑 `ios_ops.sh build` 當 gate（編譯綠即可推進），**不自主跑耗時測試**（UI/all-targets）。流程順序固定：先 push + 清乾淨殘影，**再問使用者要不要跑測試**。若使用者要跑且測試失敗 → revert 或 hotfix，不讓 main 壞著。
