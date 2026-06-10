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

## 溝通協定（Board Protocol）

把每條 branch/worktree 當成看板上的一張**卡（card）**，對每張卡標一個**處置（disposition）**，工具調查、agent 執行、receipt 留痕。這是上面三種模式的統一溝通語彙——「all 白」「B, <branch>」就是在這套協定下標卡。

### 一輪的形狀（固定四步）

1. **調查 board** — `uv run python ops/converge_board.py board`：一鍵分類所有卡，取代每輪手刻 bash 重判 ahead/behind/dirty/patch-是否已在-main/有無 origin/checked-out 在哪/是否 live。工具**唯讀 git、fetch-first**（main 會在你手下被平行推進）。
2. **標記 disposition** — 使用者（或 agent 依工具的建議欄）對每張卡標白/黑/B/凍/存。標完用 `plan --marks "..."` 乾跑預覽每卡會做哪些 git 動作（**不執行**），確認無誤。
3. **執行 assemble → gate → cutover** — 所有要進 main 的工作**組裝成單一 candidate**（白吸收、B 落地已提交子集），末端**一次** build-gate「要推的那個 commit」（在乾淨臨時 worktree 編，非 dirty working tree，見下方「Build gate 編 commit」），綠了再**極短 cutover** 推 main，然後 rebase/sync/刪殘影。
4. **紀錄 receipt** — `receipt --round-at <ts> --before b.json --after a.json ...` 吐固定一輪 markdown（board-before 每卡 state、每卡 disposition、candidate sha、gate verdict、main before→after、pushed/deleted/kept）。**時間從外部傳入，工具不碰 now()**（KG 慣例）。讓下輪與使用者看得見歷史。

### State taxonomy（`converge_board.py` 的 7 個 canonical state）

| state | 意義 | 典型建議 |
|-------|------|----------|
| `CURRENT` | == main（0 unique、clean） | 黑（rebase no-op）/ 留 |
| `MERGED` | patch 已全進 main 但 ref 還停在舊 tip（冗餘） | 白（已在 main，吸收+刪冗餘 ref） |
| `AHEAD` | 乾淨、有 unique 已提交工作、在 main 之上 | B 或 白 |
| `DIRTY` | worktree 有未提交改動（**壓倒性優先**，蓋過所有已提交分桶） | 存（先 snapshot） |
| `DIVERGED` | local 已 rebase 但 origin tracking ref 落後，待 force-push sync | 黑（含 origin sync） |
| `STALE_BASE` | behind main，需先 rebase 才能乾淨落地 | 黑（rebase） |
| `ORPHAN` | detached worktree 無 branch | 清 worktree |

precedence：`ORPHAN`（無 branch 可動）> `DIRTY`（有未提交）> 已提交分桶（`MERGED`/`STALE_BASE`/`DIVERGED`/`AHEAD`）。live-agent 啟發式：worktree 有 unique 已提交且 HEAD 是近期 commit → 仍歸 `AHEAD`，但建議 **凍**（不動 live agent）。

### Disposition 語彙

| mark | 別名 | 語意 | 對 branch | 對 main | 對 worktree |
|------|------|------|-----------|---------|-------------|
| **白** | white / W | 吸收進 main + 刪 branch | **刪**（local+remote） | 前進（組裝進 candidate） | **預設保留**（除非明說刪） |
| **黑** | black / K | rebase 到最新 main + 保留 | 保留、rebase | **不前進** | 不動（有 origin 則 sync） |
| **B** | promote | 已提交工作落地 + 保留 + sync | 保留、rebase | 前進（組裝進 candidate） | 不動 |
| **凍** | freeze / F | 完全不動（live agent / 沒好） | 不動 | 不動 | 不動 |
| **存** | snap / S | **修飾詞**：dirty 先 snapshot commit 再執行底下處置 | — | — | snapshot commit（不 stash） |
| （清） | clean / 清 | 清 orphan worktree | — | — | `git worktree remove` / prune |

語法：批量 `all 白` / `all 黑`；逐卡 `B, <branch>` / `白, <branch>`；鏈式依序執行。`存` 套在任一前面，如 `存白, <branch>` = 先 snapshot 再白。CLI 對應：`plan --marks "all=black"`、`plan --marks "feat-x=B,docs-y=white"`（mark 接受 white/W/白、black/K/黑、B/promote、freeze/F/凍、snap/S/存、clean/清）。

### 執行不變量（鐵律落地，不可繞）

- **fetch-first** — 每輪第一步 `git fetch` + porcelain；信當下 porcelain，不信注入的舊 status snapshot。main 會在你手下被平行 commit 推進，just-in-time rebase。
- **dirty 先 snapshot，永不 stash** — dirty 卡（含被任何非凍處置選中的 dirty worktree）先 `git add -A && commit` snapshot，**絕不 stash**（會丟使用者身份/未提交 work）。
- **single-candidate-gate** — 所有要進 main 的工作組裝成**單一 candidate**，末端**一次** build-gate（編 commit 非 dirty working tree），不分段 gate。
- **never-clobber-main-dirty** — 不覆寫 main worktree 的 dirty；gate 在臨時乾淨 worktree 編。
- **白刪 branch 留 worktree** — 白 = 刪 branch（local+remote），worktree **預設保留**（除非明說）。
- **B/黑 要 rebase + sync 保留的 branch** — 保留的 branch 落地後 rebase 到新 main，有 origin tracking 則 `--force-with-lease` sync。
- **force-push 只用 `--force-with-lease`**；刪 remote 前先確認存在，不存在跳過。

調查引擎：`ops/converge_board.py`（`board` / `plan` / `receipt`，唯讀 git，schema `kg.converge.board.v1`，pure 層全 7 state 有單元測試 `ops/tests/test_converge_board.py` / `test_ops.sh converge-board`）。執行細節（assemble/gate/cutover/清殘影）見下方各模式 recipe；build-gate 與 `merge=union` 自動化見「高效配方」段，與本協定交叉引用。

---

## 高效配方（先認形狀，再動手）

別逐步探索 —— `branch -vv` 的 ahead/behind + commit subject 通常一眼就定形狀。對症下藥：

**形狀 A：一個 integration superset + N 個 raw 子集**（常見於多 agent 平行做 flow，其中一條是整合 branch）
1. `fetch && branch -vv && worktree list && git status --porcelain`（**一次拿全**；dirty 同呼叫掃各 worktree）。**信 porcelain 當下真相，不信注入的舊 status snapshot。**
2. 看 ahead/behind + subject 認形狀：superset ahead 最多、raw 子集 ahead 少且 subject 同主題 → superset 假設成形。
3. merge superset → main（已 union 過的整合 branch 通常零衝突）。
4. 每個 raw 子集：`git diff main..<branch> -- <該 branch 唯一檔>` **空 = 冗餘 → 刪**（merge 它反而把舊 baseline 共用檔 regress 回 main）。
5. **build gate 編「commit」不編 working tree**（下方）→ push（head commit 進 base 會讓對應 PR **自動翻 MERGED**）→ 清殘影 → 問測試。push/刪必須是「已讀到綠燈 verdict」之後的**獨立 call**，不可與讀 verdict 同一呼叫。

**判 containment 一律走 tree-diff，禁用 `git cherry`/patch-id**（rebase 過必失準，全噴 `+` 是噪音）。取證取「決定性的那一個」（唯一檔 diff 是否空），不要倒整份 `diff --stat` / `grep '^+'` —— diffstat 的刪除總量已說完故事。

### Build gate 編 commit，不編 dirty working tree

main worktree 是使用者的即時工作桌，常帶**未提交的 WIP**。直接 `ios_ops.sh build` 會把使用者的 dirty 一起編 → false-red 算到 converge 頭上，逼你花一輪歸責（實戰踩過：`suppressFoldAnimation` 私有跨檔錯其實是使用者 WIP）。**不能 stash**（會丟使用者身份/work）。正解是在乾淨臨時 worktree 編「要推的那個 commit」：

```bash
gate=$(mktemp -d)/converge-gate
git worktree add --detach "$gate" HEAD        # HEAD = 已 merge 好、要推的 commit
( cd "$gate" && ./ops/ios_ops.sh build )      # shlock + git-common-dir 共享 DerivedData，多 worktree 安全、cache 仍 warm
git worktree remove "$gate"                    # 編完即移
```

綠 = 這次 converge sound（與使用者 WIP 紅不紅無關）；紅 = 真的是被收的 commit 壞了，revert/hotfix。**fetch + porcelain 永遠第一步**（main 會在你手下被平行 commit 推進），且**永不 stash、永不 clobber main 的 dirty**。

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
- **驗證以 build gate 為準，耗時測試問過再跑**：merge 完成後跑 build 當 gate（編譯綠即可推進），**不自主跑耗時測試**（UI/all-targets）。**gate 必須編「要推的 commit」而非 main 的 dirty working tree**——在 `git worktree add --detach` 的乾淨臨時 worktree 編（見「高效配方 › Build gate 編 commit」），否則使用者未提交的 WIP 會造成 false-red。流程順序固定：先 push + 清乾淨殘影，**再問使用者要不要跑測試**；push/刪是讀到綠燈 verdict 後的獨立動作。若使用者要跑且測試失敗 → revert 或 hotfix，不讓 main 壞著。
