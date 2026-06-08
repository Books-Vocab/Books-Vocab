---
name: cleanup
description: "最快把 repo 收斂到單一真相：先盤 live state、先保住 dirty work、把非黑名單內容推進 main、再把 surviving PR rebase 到新 main。收斂優先，驗證可後置切換。"
user-invocable: true
version: 3.4.0
---

# Cleanup：把 repo 收斂到單一真相

**唯一目標 = 用最短時間把 repo 收斂到清楚、可交接、可繼續工作的狀態。**

不是追求每一步完美，而是先把真相收斂。  
不是先把所有測試跑滿，而是先保住內容、更新 main、消掉殘影、再決定驗證深度。

更精確地說：**cleanup 的第一責任不是清乾淨，而是保存所有 agent 已經做出的工作。**

> 一句話契約：cleanup = 先盤 live state → 先把所有 dirty work 變 durable 並保住 work identity → 收斂非黑名單內容到 `main` → surviving PR rebase 到新 `main` → 再做驗證 / forward-fix / doc 收尾。

---

## v3.3 與原始 cleanup 的差異

這一版不是舊版 wording refresh，而是**協作模型改寫**。

### 1. `all except ...` 的語義變了

原始 cleanup 的黑名單比較接近「不要碰」。  
v3.3 改成：

- **黑名單 PR 不吸收進 `main`**
- **黑名單 PR 不刪、不 merge**
- **但黑名單 PR 必須在主線收斂後 rebase 到最新 `main`**
- **若有衝突，cleanup 當場解掉並 force-push**

也就是：**排除吸收，不排除同步。**

### 2. dirty work 優先 `commit`，不是優先 patch 化

原始 `all` 更偏向先把未提交改動 artifact 化再搬。

v3.3 改成：

- 只要未提交改動 scope 清楚、可形成單一邏輯單位，**先原地 commit**
- 只有內容碎裂、風險高、或不適合直接留在原 branch 上時，才退回 patch / copy 流程

原則：**先把 work 變 durable，再談 cleanup。**

### 2.5 保存的不只是 commit，還要保存 work identity

v3.4 明確補上：**cleanup 必須保存的不只是內容，還有「這份工作現在歸誰、掛在哪裡」的身份感。**

只把 commit 留在 reflog、或偷偷搬到別的 branch 而不回報 mapping，都不算成功保存。

必須同時做到：

- 內容被保存成 commit
- 工作被放進明確 branch / worktree
- agent 能知道「我的工作現在在哪裡」

若某份工作原本掛在 `main` 上，而 cleanup 需要讓 `main` 回到 `origin/main`，那麼：

1. **先建顯式 branch**
2. **必要時建立對應 worktree**
3. **把工作 identity 映射清楚**
4. **再 reset / rebase `main`**

不允許的做法：

- 先 reset `main`，再事後說「commit 還在 reflog」
- 只保存 hash，不保存 branch/worktree 落點
- 讓原 agent 從自己的工作視角感知成「東西不見了」

### 3. 驗證是策略，不是固定順序

原始 cleanup 雖然已經是先 merge 後驗證，但 `all` 仍偏向在 push `main` 前做完整 gate。

v3.3 明確拆成兩種執行策略：

- **verify-first**：需要高把握度時，先在 `final-cleanup` 跑 gate 再推 `main`
- **execution-first**：需要先把結構收斂時，先完成 `main` 收斂與 surviving PR rebase，再回頭補驗證

預設依使用者意圖切換。  
若使用者說「先全部做完我的要求再說」，就走 **execution-first**。

### 4. `final-cleanup` 是一次性容器，不是長住分支

`final-cleanup` 的職責只有三個：

1. 吸收非黑名單內容
2. 作為一次性驗證或推進 `main` 的容器
3. 推進完成後立刻刪除

**它不是第二真相，不應長期存活。**

### 5. 背景長任務必須可取消

若先前已啟動：

- `./ops/ios_ops.sh build`
- `./ops/ios_test.sh --all-targets`
- 長時 pytest / node / deploy / doc generator

而 cleanup 策略中途切成「先收斂再驗證」，就必須：

1. 辨識舊 session / pid
2. 主動取消長時任務
3. 釋放 worktree / lock
4. 再清除暫存 worktree

**不要讓舊的驗證 session 綁住已完成任務的 worktree。**

---

## Phase 0 — 解析 mode / scope / 驗證策略

先判三件事：

1. **mode**
2. **scope**
3. **verification strategy**

### Mode

| 輸入 | 模式 | 終態 |
|---|---|---|
| `/cleanup` | PR mode | 把指定 PR 收斂進 `main`；其餘本地工作可保留 |
| `/cleanup except A,B` | PR mode + 黑名單 | 收斂除 A/B 外的 PR；黑名單保留 |
| `/cleanup all` | Full convergence | repo 完全收斂：零本地改動、零殘留 branch/worktree、零 open PR |
| `/cleanup all except A,B` | **Scoped full convergence** | 除 A/B 外全部收斂；允許僅保留 `main + surviving PR branches/worktrees` |

### 黑名單解析

```bash
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
```

把使用者輸入翻成：

- PR# → `headRefName`
- branch name → PR#

輸出要明講：

- 哪些會被吸收進 `main`
- 哪些是黑名單 surviving PR

### 驗證策略

預設先判斷使用者語意：

- 若使用者強調「先收斂」「先全部做完」→ `execution-first`
- 若使用者強調「不要冒險」「先驗過再說」→ `verify-first`

若沒明講，預設：

- `PR mode`：偏 `execution-first`
- `all` / `all except`：偏 `verify-first`

---

## Phase 1 — 四層真相盤點（永遠先做）

```bash
git fetch --all --prune
git status
git stash list
git branch -vv
git worktree list
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
./ops/branch_audit.sh --json
./ops/docs_lint.sh --audit
```

四層真相：

1. `origin/main`
2. local committed
3. local uncommitted
4. docs debt

### 1.1 local committed

對每條 branch / worktree：

```bash
git log --oneline --left-right --cherry-pick origin/main...<branch>
git diff --stat origin/main..<branch>
```

判斷：

- 真正 ahead
- tree 等價但 hash 不同
- 已被 squash 吞掉的歷史殘影

> **不能只看 `git branch --merged main`。**  
> squash merge 會讓已整合分支看起來像未 merged。

### 1.2 local uncommitted

對主 checkout 與各 worktree 檢查：

- staged
- unstaged
- untracked

這一步不是立刻搬，而是先分類：

- 可以直接 commit
- 需要 patch / copy
- 屬於黑名單 surviving branch

### 1.3 docs debt

`all` / `all except` 把 docs debt 視為正式收斂項。

目標：

- `WARN=0`
- `ERROR=0`

除非是明確記錄的合法豁免：

- `archive`
- `legal`
- 明示 dated snapshot 且預期過時

---

## Phase 2 — 先把 dirty work 變 durable

這是 v3.3 的第一優先級。

v3.4 補充：這一步不只是在做版本控制 hygiene，而是在**先替每個 agent 的工作建立可搬運、可 rebase、可交接的身份**。

### 規則

只要未提交內容符合以下條件，就**先 commit**：

- scope 清楚
- 邏輯單一
- 不會把 unrelated work 硬綁一起

範例：

- 同一個 iOS copy extraction
- 同一批 lint 修正
- 同一個 ops guard 調整

### 命令

```bash
git add <files...>
git commit -m "<prefix>: <message>"
```

若 dirty work 目前掛在 `main`，而 `main` 稍後必須同步回 `origin/main`，先做：

```bash
git branch <blacklist-branch> main
git worktree add <path> <blacklist-branch>   # 需要持續工作時
```

然後才允許對主 checkout 的 `main` 做 reset / rebase / cleanup。

### `main`-local dirty work 的強制規則

這是硬規則，不是建議：

- **任何黑名單工作若目前掛在 `main`，必須先抽成顯式 branch**
- **若該工作對應到活 agent，優先補對應 worktree**
- **先回報 mapping，再同步 `main`**

回報格式至少要有：

- 原位置：`main`
- 新 branch：`<name>`
- 新 worktree：`<path>`（若有）
- 保留 commits：`<sha list>`

只有完成這一步，才算真正「保存所有 agent 的工作」。

### 何時不用先 commit

以下情況才退回 patch / copy：

- 改動彼此混雜，拆不出乾淨 commit
- 使用者明示不要提交某批工作
- 內容屬於臨時實驗，不應留在原 branch

可退回：

```bash
git diff --binary > /tmp/<name>.patch
git ls-files --others --exclude-standard
```

但這是**例外路徑**，不是預設。

---

## Phase 3 — 建立單一整合 worktree（`all` / `all except`）

```bash
git worktree add -b final-cleanup /Users/chenliangyu/kg-worktrees/final-cleanup-<tag> origin/main
```

規則：

- `final-cleanup` 是唯一整合點
- 主 checkout 盡量不動
- 不要同時開多個 cleanup worktree

它只吸收：

- 非黑名單 local committed work
- 非黑名單 local uncommitted work
- 非黑名單 stray files

它**不吸收**：

- 黑名單 PR 的內容
- 黑名單 PR 的 branch identity

---

## Phase 4 — 把非黑名單內容收斂進 `main`

### 4.1 PR mode

對 scope 內且非黑名單的 open PR：

```bash
gh pr view <N> --json mergeable,mergeStateStatus,headRefName,files
gh pr merge <N> --squash --delete-branch
```

原則：

- 不 pre-review
- 只在 mergeability 或語義衝突上停
- 單檔 bug / 風格 / 邊角測試問題後置到 forward-fix

### 4.2 `all` / `all except`

把非黑名單內容先吞進 `final-cleanup`：

```bash
git cherry-pick <commit...>
# 或
git merge --squash <branch>
# 或
git apply --3way /tmp/<patch>
```

原則：

- 能直接 pick 就直接 pick
- 能 squash branch 就 squash
- patch 只用在必要情況

### 4.3 推進 `main`

依驗證策略決定順序：

#### `verify-first`

先在 `final-cleanup` 驗證，再推：

```bash
git push origin final-cleanup:main
```

#### `execution-first`

先完成吸收與結構收斂，再推：

```bash
git push origin final-cleanup:main
```

之後再補驗證與 forward-fix。

> 這裡的關鍵不是命令不同，而是**接受標準不同**。  
> `execution-first` 允許「先把 main 變單一真相，再追測試」。

---

## Phase 5 — surviving PR 同步到新 `main`

這是 v3.3 新增的正式 phase。

適用於：

- `/cleanup except ...`
- `/cleanup all except ...`

### 契約

黑名單 PR 可以保留，但**不能 stale**。  
主線收斂後，它們必須同步到新 `main`。

### 做法

在各自 worktree：

```bash
git rebase origin/main
```

若有衝突：

1. 當場解
2. 保留兩邊語義，不做粗暴二選一
3. `git add`
4. `git rebase --continue`
5. `git push --force-with-lease`

### 衝突原則

黑名單 PR 雖不被吸收，但仍要維持：

- 可繼續 review
- 可繼續 merge
- 不因 cleanup 導致 PR 基底過舊

這一步的定義是：**surviving PR synchronization**。

補充：若 surviving work 不是 PR，而是從 `main` 抽出的黑名單 branch，也適用同一原則。  
也就是：**黑名單 work 不一定要 merge，但必須能在新 `main` 上繼續工作。**

---

## Phase 6 — 驗證與 forward-fix（可後置）

這一階段是否在推 `main` 前執行，取決於策略。

### 最小優先順序

先驗共享面：

- `./ops/docs_lint.sh --audit`
- `./ops/i18n_lint.sh --baseline-check`
- 受影響的 `uv run pytest`
- 受影響的 `node --test`
- `./ops/ios_build.sh`
- 必要時 `./ops/ios_test.sh` 精準 scope
- cleanup 收尾或測試基礎設施變動時，才跑 `./ops/ios_test.sh --all-targets --timeout 1200`

### forward-fix

若驗證或 review 出現問題：

- 不回退整批 cleanup
- 直接最小修補
- 補 commit / PR / squash merge

原則：**main 保持單一真相，問題用新 commit 補。**

---

## Phase 7 — Doc-sync 與 docs debt

### 7.1 本批 doc-sync

依 `docs/sop/doc_sync.md` 與 `docs/registry.yml` 判斷是否需同步。

常見動作：

- 更新內容
- bump `verified_against`
- 修 registry impact 命中之活文檔

### 7.2 docs debt 全清（`all` / `all except`）

`./ops/docs_lint.sh --audit` 的 STALE / ERROR 要清到 0，除非屬於合法豁免。

重點規則：

- `verified_against` 必須指向 **reachable commit**
- `snapshot` tier 不手 bump，重跑 generator
- generator 壞掉也算 cleanup scope

---

## Phase 8 — 收尾

### `all`

終態：

- `git status` 乾淨
- `git worktree list` 只剩主 repo
- `gh pr list --state open` 為空
- `./ops/branch_audit.sh --json` `total=0`
- `./ops/docs_lint.sh --audit` `WARN=0 ERROR=0`

### `all except A,B`

終態：

- `main` 已是最新單一真相
- 非黑名單 branch/worktree/local change 全清
- 僅保留：
  - 主 repo `main`
  - surviving PR 對應 branch/worktree
- 或從 `main` 抽出的黑名單 branch/worktree
- surviving PR 都已 rebase 到最新 `main`
- `branch_audit` 只剩黑名單 PR

### 清除動作

內容已保留後，依序清：

```bash
git worktree remove <cleanup worktree>
git worktree prune
git branch -D <absorbed branch>
git push origin --delete <obsolete remote branch>
git fetch --prune
```

若主 checkout 本身就是要收斂到乾淨：

```bash
git switch main
git reset --hard origin/main
git clean -fd
git stash clear
```

### `final-cleanup` 收尾規則

推進 `main` 後：

- 立刻刪 worktree
- 立刻刪 `final-cleanup` branch

**不允許讓它留成長住真相。**

---

## 背景任務取消規則

若 cleanup 過程中策略切換，或使用者明示「先不要測全部」：

1. 找出仍綁住 cleanup worktree 的 pid / session
2. 取消：
   - `xcodebuild`
   - `ios_test.sh`
   - `ios_ops.sh build`
   - 其他長時測試 / generator
3. 確認 lock 與 worktree 已釋放
4. 再做 worktree remove

範例：

```bash
ps -Ao pid,ppid,command | rg 'final-cleanup|ios_test.sh|ios_ops.sh build|xcodebuild'
kill <pid...>
kill -9 <pid...>   # 只在正常 kill 無效時
```

---

## 並發安全

永遠生效：

1. 黑名單 surviving PR 不吸收、不刪，但允許 rebase / 解衝突 / force-push
2. 黑名單工作若原本掛在 `main`，先抽 branch/worktree，再同步 `main`
3. 主 checkout 若被活工作佔用，就用隔離 worktree 操作
4. cleanup 不能只保存 commit，還要保存 work identity 的 mapping
5. 不在被 merge 的 PR branch 上執行 `gh pr merge`
6. 不 non-interactive reset 使用者正在工作的 branch
7. doc-sync / review / test agent 若會動 git，必須隔離在 worktree

---

## 報告格式

```text
## Cleanup 完成
scope: <mode + 白/黑名單>

### 收斂到 main
- <branch/commit/PR> → main

### surviving PR
- #885 back：rebase 到 <sha>，已 force-push
- #886 codex/ios-front-techdebt：rebase 到 <sha>，已解衝突並 force-push

### blacklisted work preserved
- 原本掛在 `main` 的工作：已抽到 <branch> / <worktree>
- preserved commits: <sha...>
- agent remap: <old location> → <new location>

### 驗證
- strategy: verify-first / execution-first
- 已跑：<commands>
- 後置：<commands or known failures>

### 最終狀態
- git status: clean / dirty
- worktrees: <count and names>
- branch_audit: <summary>
- docs_lint --audit: <summary>
```

---

## 踩坑備忘

1. `all except` 不是「完全不碰黑名單」，而是「不吸收，但要同步」。
2. dirty work 不先 commit，cleanup 風險會暴增。
3. 只保存 commit、不保存 branch/worktree mapping，agent 仍會感知成「工作被清掉」。
4. 若黑名單工作掛在 `main`，先抽 branch/worktree，再 reset `main`；反過來做會造成工作身份消失。
5. `final-cleanup` 只是容器，不是第二主線。
6. `gh pr merge` 不要在 PR branch 上跑，避免 gh 切回 `main` 撞使用者工作。
7. squash 後 branch 是否已整合，要看 reachability / tree，不看單一 merged flag。
8. 驗證可以後置，但**已知失敗要明講**，不能假裝全綠。
9. 長時背景測試若不再需要，必須主動取消，不要讓它卡住 worktree 清理。
10. docs debt 在 `all` / `all except` 是正式收斂項，不是附帶 housekeeping。
