---
name: cleanup
description: "快速收斂分支狀態：scope 圈定 PR → 火速 merge（衝突當場解）→ 收斂後才平行 review+測試 → 殘留問題 forward-fix 補合。收斂優先於驗證。`all` mode 採四層真相盤點 + 單一 final worktree 一次吞完 + docs_lint 0 STALE/0 ERROR。"
user-invocable: true
version: 3.2.0
---

# Cleanup：最快讓分支狀態收斂

**唯一目標 = 用最短時間把 open PR 收斂進 main。** 不是「全流程完美收尾」，是「收斂」。

> 一句話契約：cleanup = scope 圈定 PR → 火速 merge（衝突當場解）→ 收斂完才平行 review+測試 → 殘留問題 forward-fix 補合。**收斂優先於驗證，驗證優先於完美。**

核心反直覺點（v2 → v3 的關鍵調換）：**先 merge，後驗證**。舊流程「先 review 每個 PR 再 merge」慢且擋路；agent 產出的 PR 多半個別已綠，真正阻擋收斂的只有**衝突**。所以把 review/測試/doc-sync 全部後置、async 化，殘留問題用 follow-up commit 補（不 revert、不卡 merge）。

v3.2 補強：**`all` mode 不再逐條邊清邊猜，而是先建真相、再一次到位。**  
也就是先拆出 4 個 truth surfaces：`origin/main`、local committed、local uncommitted、docs debt；接著在**單一 final-cleanup worktree** 吞掉所有要保留內容，**只跑一次完整驗證**，最後才更新 `main` 與清空 local/worktree/stash。`all` 的目標不是「盡量接近收斂」，而是**repo 單一真相化**。

---

## Phase 0 — Mode + Scope 解析（永遠先做）

先判 **mode**（決定收斂的範圍是「只 PR」還是「整個 repo」），再解析 scope。

| 輸入 | Mode | 收斂目標 |
|---|---|---|
| `/cleanup` | **PR mode**（預設） | 只把 open PR 收進 main；殘留 branch/worktree 留活路 |
| `/cleanup A,B` / `/cleanup except C,D` | **PR mode** + 白/黑名單 | 同上，限縮 PR 範圍 |
| `/cleanup all` | **Full convergence** | repo 完全收斂：零 outstanding PR **+ branch + worktree + local change** |

**`all` 的權威定義（使用者原話，一字不漏）：**

> make sure that the repository is fully converged and synchronized. There are no outstanding branches, worktrees, pull requests, or local changes.

**Full convergence（`all`）= PR mode 全跑完，再追加分支/worktree 收斂（見 Phase 2.5）+ doc-debt 全清（見 Phase 4b）。** 核心差異：`all` 把「branch/worktree 的存在本身」**與「累積的文檔 debt」**也當待收斂項，目標終態是 `git branch` 只剩 main、`git worktree list` 只剩主 repo、working tree clean、**`ops/docs_lint.sh` 0 STALE / 0 ERROR（僅剩有記錄的 legitimate 豁免）**。doc-debt **不論是否本批造成一律清**（使用者指令，2026-06-06）。

> ⚠️ **squash-merge 陷阱（記死）**：判斷分支是否已整合**不能只信 `git branch --merged main`** —— squash-merge 後 commit hash 變了，已整合的分支會被它列為「未 merged」，誤判成活工作而放生。每條未刪分支必須交叉驗證：對應 PR 是否 `MERGED`（`gh pr view <branch> --json state,mergedAt`）／分支內容是否已在 main（`git cat-file -e HEAD:<分支新增的代表檔>`）。任一為真 = 已整合，直接刪 local + remote。

> 效率原則：**能 squash 就不開 PR**。`all` 模式對 unpushed 含工作的分支走**本地 squash 進 main**（`git merge --squash` → commit → push），不繞 GitHub PR round-trip。PR 流程只在「已有 open PR」或「要 review 痕跡/CI gate」時用。

scope 翻成 PR 白/黑名單（使用者常**並行派多個 agent，回來時部分還在做**），列表確認再動手：

| 輸入 | 語意 |
|---|---|
| `/cleanup A,B`（branch name 或 PR#） | **白名單**：只收這些 |
| `/cleanup except C,D` | **黑名單**：全部扣掉 C,D（給還在做的 agent 留活路） |

```bash
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
```

解析後輸出對應表（branch name → PR#），標明哪些**納入**、哪些**排除（活 agent）**。排除的分支 = 神聖不可侵犯（見 Phase 並發安全）。

---

## Phase 1 — 四層真相盤點（`all` 必做；先盤完再動）

```bash
git fetch --all --prune
git status; git stash list; git branch -vv; git worktree list
gh pr list --state open --json number,title,headRefName,mergeable,mergeStateStatus
./ops/branch_audit.sh --json
./ops/docs_lint.sh --audit
```

對 `all`，一開始就把 repo 拆成 4 個 truth surfaces：

1. `origin/main`：遠端權威真相。
2. local committed：每條 local branch / worktree 到 `origin/main` 的可達差異。
3. local uncommitted：主 checkout 與各 worktree 的 staged / unstaged / untracked。
4. docs debt：`docs_lint --audit` 的 STALE / ERROR 真相。

辨識：**主 repo working copy 是否被活 agent 佔用**（detached HEAD、未提交改動、checkout 在某 feature branch）。若是 → 主 repo **完全不碰**，所有後續 git/gh 操作走隔離 worktree。

> `all` mode 的禁忌：**不要一邊看到 branch 就一邊刪。** 先盤完四層真相，再決定哪些內容要被 final branch 吞掉、哪些只是歷史殘影。

### 1.1 local committed 真相
對每條 local branch / worktree 都跑：

```bash
git log --oneline --left-right --cherry-pick origin/main...<branch>
git diff --stat origin/main..<branch>
```

- `log` 看 commit reachability。
- `diff` 看 tree 是否其實已等價。
- **hash ahead ≠ 內容 ahead**；squash 後常見「commit 不同、tree 相同」。

### 1.2 local uncommitted 真相
主 checkout 與各 worktree 的未提交工作要**先封裝再搬運**，不要直接在原地修：

```bash
git diff --binary > /tmp/kg-main-working.patch
git ls-files --others --exclude-standard
```

- tracked 改動存成 patch。
- untracked 新檔另外列出，必要時直接 copy 進 final worktree。
- 這一步的目的，是把「主 checkout 正在發生的工作」轉成**可重播 artifact**。

### 1.3 docs debt 真相
`all` mode 把 docs debt 視為正式收斂項，不是最後才想到的 housekeeping：

- `./ops/docs_lint.sh --audit` 先跑，先知道總量。
- `snapshot` tier 要靠 generator 重生，不可手 bump。
- `verified_against` 失效要 re-point 到 reachable commit。

## Phase 1.5 — 建唯一整合 worktree（`all` 的主戰場）

`all` mode 不在主 checkout 邊收邊改，而是建立**唯一** final worktree：

```bash
git worktree add -b final-cleanup /Users/chenliangyu/kg-worktrees/final-cleanup-<tag> origin/main
```

- 所有 local committed / uncommitted / stray untracked 都往這裡吞。
- 主 checkout 保持只讀，直到 final branch 全綠。
- 若要多次整合，**重用同一個 final worktree**，不要每合一批就換地方。

---

## Phase 2 — 火速 Merge（收斂的本體，唯一不能延後的階段）

**不 pre-review。直接合。** 但門檻不是零：

### 2a. 並行抓 mergeability + 檔案重疊
```bash
gh pr view <N> --json mergeable,mergeStateStatus,headRefName,files
```
- 用 `files` 預判**同檔衝突**排序：無重疊的先合、共享檔的後合。
- ⚠️ **路徑不相交 ≠ 無衝突**：可能有語義衝突（A 改 source、B 測該 source 的舊行為）。git 層不衝突但組合態測試會紅。這類**不在 merge 時擋**，留給 Phase 3 的組合態測試抓 + forward-fix（範例：#825×#826 → #827）。

### 2b. 逐一合
```bash
gh pr merge <N> --squash --delete-branch
```
- 門檻：只合 `MERGEABLE`，或衝突可機械/語義解的。**跳過的是 pre-merge review，不是 mergeability 檢查**——盲合壞 PR 會污染 main，但那風險由 Phase 3 後置測試 + forward-fix 接住。
- 下一個轉 `CONFLICTING` → **一次 `git merge origin/main` 解衝突**（別 10-commit `git rebase`；最終 squash 不需保留分支歷史，merge 通常只剩 1-2 個真衝突）：
  ```bash
  git checkout <branch>; git merge origin/main
  # 解衝突 → git add → git commit
  git push --force-with-lease origin <branch>
  gh pr merge <N> --squash --delete-branch
  ```
- **語義衝突解析是唯一不能延後的正確性工作**：兩 PR 改同塊邏輯時，當場合併兩特性（非二選一），讀 conflict 區塊 + 查欄位語義 + 確認既有慣例 round-trip。其餘（單檔 bug、風格）才後置。

### `all` mode 加嚴：不要在 Phase 2 就把本機活工作一條條直接推 main

`all` mode 對 open PR 仍可先合，但 **local committed / local uncommitted / stray worktree work 一律先吞到 `final-cleanup`，不要逐條直接推 `main`**。原因：

- 逐條清 branch 容易被 worktree bookkeeping / stale refs 反咬。
- 主 checkout 未提交工作若沒先 artifact 化，之後很難證明「哪些真的保留了」。
- 把所有殘留工作先壓成**單一 final branch**，才能只做一次完整驗證。

### 坑（記死）
- **`gh pr merge` 前確保自己不在被合的那條 branch 上**：在 PR 分支上跑會讓 gh 合完跳 checkout `main`，撞使用者並行的 local main + 製造「工作被還原」假警報。在 detached HEAD 或別的 worktree（on `main`）執行最安全。
- **絕不 ff/reset 使用者的 local main**：他常並行在 local main 工作。

---

## Phase 2.5 — 分支/worktree 收斂（**僅 `all` mode**）

PR 全收完後跑。v3.2 的 `all` mode 改成：**先把每條 local branch / worktree 的要保留內容吸進 `final-cleanup`，再一次性清空殘影。** 不是「看到一條刪一條」，而是「先單一真相化，再刪乾淨」。

決策樹（走 B：不丟未整合工作）：

| 分支狀態 | 處置 |
|---|---|
| 已整合進 main（`git branch --merged main` 列出，**或** 對應 PR `MERGED` / 分支內容已在 main — 見上方 squash-merge 陷阱） | 直接刪 local（`git branch -D`）+ remote（`git push origin --delete`）+ worktree（`git worktree remove`） |
| unpushed / local-only 含工作、**驗證綠** | **先 squash / cherry-pick / patch-apply 進 `final-cleanup`**，最後由 `final-cleanup` 一次推進 `main`，再刪分支 + 移 worktree |
| unpushed 含工作、**驗證紅/不確定** | **報告並停手，不擅自刪**（B 的底線：不丟未整合工作）。列出要使用者裁決 |
| scope 黑名單 / 活 agent 佔用 | 神聖不碰 |

本地工作吸進 final branch 的優先順序：

1. 已提交 branch：`git merge --squash --no-commit <branch>` 或 `cherry-pick` 到 `final-cleanup`
2. 主 checkout / 其他 worktree 的 tracked 未提交改動：`git apply --3way /tmp/...patch`
3. untracked 新檔：直接 copy 進 `final-cleanup`，再納入驗證
4. 內容等價的歷史殘影：**不吸，直接列為可刪**

本地 squash 合分支（驗證綠後，在 `final-cleanup` 跑）：
```bash
# 先在該分支 / final worktree 跑專案測試 → 綠才合（鐵律 2，不盲合）
git switch final-cleanup
git merge --squash <branch>
git commit                                       # squash 需手動 commit，prefix 照 Identity 表
```
- **驗證先於吞**：branch 舊測試結果不算數，final branch 形成後要以 final branch 當下輸出為準。
- 直到 `final-cleanup` 全綠前，不更新主 checkout `main`。

---

## Phase 並發安全（正交但永遠生效）

與「快」不衝突，是前提：

1. **Scope 黑名單分支 + 其 working copy/worktree 完全不碰**。
2. **主 repo 被活 agent 佔用時，所有 git/gh 操作走隔離 worktree**：
   ```bash
   git worktree add /Users/chenliangyu/kg-worktrees/cleanup-<tag> main   # on main 分支，便於 gh
   # 所有 merge / 解衝突 / 測試 / doc-sync 都在這跑，做完 git worktree remove
   ```
   （`main` 通常沒被任何 worktree 佔用，可在 cleanup worktree 認領。）
3. **不派非隔離的 doc-sync agent**——它動主 checkout 的 HEAD/index 會跟 cleanup 撞。doc-sync 一律在 worktree 自己做，或派 **`isolation: worktree`** 的單一 agent。

---

## Phase 3 — 收斂後驗證（後置、平行、async）

合完才跑。問題用 forward-fix，不回退。

### 3a. 組合態測試（在 `final-cleanup`，一次驗整體）
專案命令（cwd 不靠持久，一律 subshell 或絕對路徑）：
- backend：`(cd backend && uv run pytest -q <被動到的 test 檔...>)`（**必用 `uv run`**，裸 python3 會用錯版本致假失敗）
- chrome：`(cd chrome-extension && node --test shared/*.test.js)`
- ops shell：`(cd <wt> && ./ops/tests/test_<x>.sh)`
- iOS：先跑 `./ops/ios_build.sh`;若合併內容動 iOS 行為 / UI / test infra,依 `docs/sop/ios.md §iOS 開發驗證梯度` 跑最小足夠 `./ops/ios_test.sh` scope。cleanup all / release / scheme/test runner 變更收尾跑 `./ops/ios_test.sh --all-targets --timeout 1200`。若當前環境 simulator 不可用,明確記錄阻塞證據,不可用 build 假裝 test 綠。
- **優先跑「跨 PR 共享面」的測試**（web_auth / api 契約 / sync_lifecycle / i18n lint），這是語義衝突最會炸的地方。

`all` mode 的重點是：**不要每吸一批就重跑整套。** 先把所有要保留的內容都吸進 `final-cleanup`，最後跑一次完整 gate：

- targeted pytest / node tests
- `./ops/test_ios_ops.sh`（若動到 ios ops surface）
- `./ops/ios_build.sh`
- 必要時 `./ops/ios_test.sh --all-targets --timeout 1200`
- `./ops/docs_lint.sh --audit`

### 3b. 平行 review（逐項，鐵律 4）
合進的每個 PR 派 1 個 background opus agent（`model: opus`, `run_in_background: true`, `general-purpose`）審 diff：隱藏 bug、生產熱路徑（tracked_llm/api/deps/vocab_crud/web_auth）契約相容、i18n 對齊（鐵律 8）、Pydantic v2/@Observable 慣例。**只分析不改**。

### 3c. Forward-fix（殘留問題的標準解）
測試紅 / review BLOCK → 在 cleanup worktree 開 fix branch → 最小修正 → 驗證綠 → 開 PR → squash-merge。**不 revert 已合的 PR、不卡整批收斂**。commit prefix 照 Identity 表（`api:`/`ios:`/`ops:`/`docs:`）。

---

## Phase 4 — Doc-sync + Doc-debt 全清（後置，可派隔離 agent）

兩件事：**4a** 同步本批 code 變更的 doc（一向如此）；**4b** 清掉 repo **累積的全部 doc-debt**——`all` mode 必跑、不論是否本批造成（使用者指令，2026-06-06）。

### 4a. 本批 doc-sync
跳過條件：純樣板 / doc-only。否則合進的 code 變更照 `docs/sop/doc_sync.md` 路由同步。
- 多數 PR 應已 doc-as-code 自帶 doc 改動。剩餘走 `(cd <wt> && ./ops/docs_lint.sh)` 日常 gate：
  - 檢視 registry impact hints,再依 `docs/registry.yml` trigger 判斷本批 code 是否真的影響活文檔 → 改內容 + bump `verified_against` 到 main 可達 code commit。
  - 重點審：`sync_lifecycle.md`(SoT)、`backend.md`、`product_surface.md`/`tech_index.md`(SoT)、`cost_baseline.md`（費率變動時）。
  - 全 repo debt 盤點才跑 `./ops/docs_lint.sh --audit`;既有 invalid anchor / stale WARN 不阻塞本批 cleanup,除非是本批引入或本批觸發的文檔。
- 派 doc-auditor 時用 `doc-auditor-prompt.md`；**agent 只分析、主 agent 統一 Edit**；要派會 commit 的就 `isolation: worktree`。
- 完成 `docs:` commit（commit 無妨；push 見下）。

### 4b. Doc-debt 全清（`all` mode 必跑；其它 mode 至少跑並把無法當場清的列入報告）
跑 `(cd <wt> && ./ops/docs_lint.sh --audit)`，把**每一條** STALE / ERROR 清到 0（或縮到有記錄的 legitimate 豁免）。**這是 `all` 收斂終態的一部分，不是 best-effort。** 量大時派多個 doc-auditor agent（`model: opus`, `run_in_background: true`）平行審，但 **agent 只分析、主 agent 統一 Edit + 單一 `docs:` commit**（要派會自行 commit 的就 `isolation: worktree`）。逐條按 lint 訊號處置：

| docs_lint 訊號 | 根因 | 處置 |
|---|---|---|
| **STALE**（`verified_against..HEAD` 動到 scope 超閾值） | 內容可能落後 | 派 doc-auditor 比對 doc vs 自 `verified_against` 以來動到其 scope 的 commit：**內容仍對** → 只 bump `verified_against` 到 HEAD；**內容過時** → 套 agent 回報的精確 Edit + bump |
| **ERROR — `verified_against` 不是有效 commit** | 該 hash 被 squash 掉了（歷史重寫） | 確認內容仍對後，re-point `verified_against` 到**當前有效 commit**（HEAD，或最近動到該 scope 的 commit）；內容已過時則先修內容再 re-point |
| **ERROR — frontmatter 缺漏/格式壞** | `<!-- doc-meta -->` 不完整 | 補齊/修正 frontmatter 欄位 |
| **snapshot tier（機器生成）STALE** | 該檔由腳本產出，**不可手 bump** | 重跑生成腳本再生：`ios_baseline.md` → `ops/gen_ios_baseline.sh`；web token → `gen_web_tokens.py`。腳本產物不手改 |

**legitimate 豁免**（保留並在報告列出，不強清）：tier=`archive`（凍結歷史，不更新不引用）、tier=`legal`（不在 lint 掃描範圍）、明示 dated snapshot 且 `verified_against` 標註過時為預期者。

- 派 doc-auditor 時用 `doc-auditor-prompt.md`（把該 doc 的 `verified_against..HEAD` scope diff 餵進「變更清單」欄）。
- bump `verified_against` 前**務必確認 hash 是當前 reachable commit**（squash 後舊 hash 會失效，這正是 ERROR 的來源）。
- 完成 `docs:` commit（commit 無妨；push 見下）。doc-debt 清除可與本批 doc-sync 合進同一個 `docs:` commit，或分開——邏輯獨立就分。

> v3.2 補充：若 generator 本身在清 debt 過程爆掉（例如 `pipefail` + `head` 導致的 `141/SIGPIPE`），**修 generator 本身就是 cleanup scope**。不能繞過 generator 假裝 debt 已清。

---

## Phase 5 — 部署（預設跳過，需明確指示）

**部署生產一律須使用者明確指示**，不自動跑。  
**push 遠端分兩類看**：

- PR mode / 一般 cleanup：push 遠端須使用者明確指示。
- `all` mode：若 final branch 已吸收所有要保留內容、驗證全綠，**可直接 push `main`** 作為 repo 收斂終態的一部分。

有 backend 變更且使用者授權才：
```bash
./ops/devops_kg_safe.sh backup && ./ops/devops_kg_safe.sh deploy
```
**生產禁令（鐵律 7，永禁）**：`docker compose down -v` / `docker system prune -a` / `rm -rf /home/ubuntu/*`。運維只走 `devops_kg_safe.sh`，不繞 wrapper。

---

## Phase 6 — 收尾 + 報告

`all` mode 的收尾固定順序（先更新 `main`，再清本機殘影）：

```bash
git push origin final-cleanup:main
```

確認 remote `main` 已是 final branch 後，再做：

```bash
git reset --hard origin/main
git clean -fd
git stash clear
git worktree remove <殘留 worktree>
git worktree prune
git branch -D <已吸收的本地分支>
git push origin --delete <殘留 remote 分支>   # PR 已關但 remote branch 還在時手動補
git fetch --prune
```

- **僅 `all` mode**：在內容已被 `final-cleanup` 保留且驗證全綠後，允許 agent 直接把主 checkout `reset --hard origin/main` 以達成「零 local changes」終態。
- codex / `.claude` 殘留 worktree 若其內容已被 final branch 吸收或證明為過時 shadow，就直接移除。
- 最終狀態必須實測：
  - `git status --short --branch` 乾淨
  - `git worktree list` 只剩主 repo
  - `gh pr list --state open` 為空
  - `./ops/branch_audit.sh --json` `total=0`
  - `./ops/docs_lint.sh --audit` `WARN=0 ERROR=0`

報告：
```
## Cleanup 完成（scope: <白/黑名單>）
### Merged
- #N ✅ 標題 ｜ #M ✅（衝突已解）｜ #K ✅ forward-fix
### 排除（活 agent，未動）
- <branch> (#J)
### 驗證
- backend ✅ N passed ｜ chrome ✅ ｜ iOS compile ✅/跳過
- forward-fix: #X（修 <跨 PR 組合態問題>）
### Doc / Git
- doc-sync（4a 本批）：✅ / 派 isolation agent / 跳過
- doc-debt 全清（4b，`all` 必含）：✅ docs_lint N STALE+M ERROR → 0（豁免 X 條已列）/ 跳過（非 all）
- worktree/branch/local-change 收尾：✅ `git status clean` / `worktree list=1` / `branch_audit total=0`
- 部署：跳過（待明確指示）
```

---

## 踩坑備忘（KG 實戰固化）

1. **收斂優先**：別在 merge 前卡 review/測試，那是後置工作。
2. **路徑不相交 ≠ 無衝突**：語義衝突（source vs 測該 source 的測試）靠組合態測試 + forward-fix 抓，不靠 merge 時人眼。
3. **主 repo 被活 agent 佔用就走 worktree**，別跟它搶 HEAD（最大時間殺手）。
4. **`gh pr merge` 不要在被合分支上跑**（gh 會跳 checkout main 撞 local main）。
5. **squash 後 local diverge**：worktree `git merge --ff-only origin/main`（或 reset 到 origin/main），**絕不碰使用者 local main**。
6. **backend 測試必 `uv run pytest`**；cwd 不靠持久，一律 subshell。
7. **doc-debt 清除（Phase 4b）兩陷阱**：(a) `ERROR verified_against 不是有效 commit` = 該 hash 被 squash 重寫掉了，re-point 前先確認內容仍對、新 hash 是當前 reachable；(b) `snapshot` tier（`ios_baseline.md` 等）STALE **不可手 bump**，必須重跑生成腳本（`ops/gen_ios_baseline.sh`），手改會與下次再生衝突。`archive`/`legal` tier 不清，列入豁免。
8. **generator 失敗也是 cleanup scope**：像 `pipefail` + `head` 造成的 `141/SIGPIPE`，不修 generator 就不算全收斂。
9. **`all` mode 的正確姿勢是單一 final branch，不是逐條就地清**。先真相盤點、再吞進 final branch、最後一次性 reset/清空本機殘影。
10. **push/deploy 須分開看**：`all` mode 可直接 push `main` 以達成 repo 收斂；**部署**仍須明確指示，生產禁令永不繞過。
