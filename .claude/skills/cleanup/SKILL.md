---
name: cleanup
description: "快速收斂分支狀態：scope 圈定 PR → 火速 merge（衝突當場解）→ 收斂後才平行 review+測試 → 殘留問題 forward-fix 補合。收斂優先於驗證。"
user-invocable: true
version: 3.0.0
---

# Cleanup：最快讓分支狀態收斂

**唯一目標 = 用最短時間把 open PR 收斂進 main。** 不是「全流程完美收尾」，是「收斂」。

> 一句話契約：cleanup = scope 圈定 PR → 火速 merge（衝突當場解）→ 收斂完才平行 review+測試 → 殘留問題 forward-fix 補合。**收斂優先於驗證，驗證優先於完美。**

核心反直覺點（v2 → v3 的關鍵調換）：**先 merge，後驗證**。舊流程「先 review 每個 PR 再 merge」慢且擋路；agent 產出的 PR 多半個別已綠，真正阻擋收斂的只有**衝突**。所以把 review/測試/doc-sync 全部後置、async 化，殘留問題用 follow-up commit 補（不 revert、不卡 merge）。

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

**Full convergence（`all`）= PR mode 全跑完，再追加分支/worktree 收斂（見 Phase 2.5）。** 核心差異：`all` 把「branch/worktree 的存在本身」也當待收斂項，目標終態是 `git branch` 只剩 main、`git worktree list` 只剩主 repo、working tree clean。

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

## Phase 1 — 狀態收集（一個 Bash 抓完）

```bash
git status; git stash list; git branch -vv; git worktree list
git log --oneline origin/main..HEAD   # 主 repo 未 push commit
```

辨識：**主 repo working copy 是否被活 agent 佔用**（detached HEAD、未提交改動、checkout 在某 feature branch）。若是 → 主 repo **完全不碰**，所有後續 git/gh 操作走隔離 worktree（見下）。

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

### 坑（記死）
- **`gh pr merge` 前確保自己不在被合的那條 branch 上**：在 PR 分支上跑會讓 gh 合完跳 checkout `main`，撞使用者並行的 local main + 製造「工作被還原」假警報。在 detached HEAD 或別的 worktree（on `main`）執行最安全。
- **絕不 ff/reset 使用者的 local main**：他常並行在 local main 工作。

---

## Phase 2.5 — 分支/worktree 收斂（**僅 `all` mode**）

PR 全收完後跑。逐一處置**每條 local branch + 每個 worktree**，直到只剩 main + 主 repo。決策樹（走 B：不丟未整合工作）：

| 分支狀態 | 處置 |
|---|---|
| 已整合進 main（`git branch --merged main` 列出，**或** 對應 PR `MERGED` / 分支內容已在 main — 見上方 squash-merge 陷阱） | 直接刪 local（`git branch -D`）+ remote（`git push origin --delete`）+ worktree（`git worktree remove`） |
| unpushed 含工作、**驗證綠** | **本地 squash 進 main**（不開 PR），再刪分支 + 移 worktree |
| unpushed 含工作、**驗證紅/不確定** | **報告並停手，不擅自刪**（B 的底線：不丟未整合工作）。列出要使用者裁決 |
| scope 黑名單 / 活 agent 佔用 | 神聖不碰 |

本地 squash 合分支（驗證綠後，在主 repo on main 或 cleanup worktree 跑）：
```bash
# 先在該分支 worktree 跑專案測試 → 綠才合（鐵律 2，不盲合）
git checkout main && git pull --ff-only        # 對齊 origin/main，絕不 ff/reset 使用者 local main
git merge --squash <branch>
git commit                                       # squash 需手動 commit，prefix 照 Identity 表
git push origin main
git worktree remove <branch 的 worktree>
git branch -D <branch>
```
- **驗證先於合**：unpushed 分支的舊測試結果不算數，HEAD 已前移，當下重跑才作數。
- `git branch --merged main` 安全刪 `-d`；未 merge 的用 `-D` 但**只在已 squash 進 main 或使用者裁決後**。

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

### 3a. 組合態測試（在 cleanup worktree，已 ff 到 origin/main）
專案命令（cwd 不靠持久，一律 subshell 或絕對路徑）：
- backend：`(cd backend && uv run pytest -q <被動到的 test 檔...>)`（**必用 `uv run`**，裸 python3 會用錯版本致假失敗）
- chrome：`(cd chrome-extension && node --test shared/*.test.js)`
- ops shell：`(cd <wt> && ./ops/tests/test_<x>.sh)`
- iOS：**只 compile**（此沙盒無 PTY 跑不了 sim 測試）`./ops/ios_build.sh`；動 navigation/發版時加 `--catalyst` 雙跑。**不主動跑 `ios_test.sh`**。
- **優先跑「跨 PR 共享面」的測試**（web_auth / api 契約 / sync_lifecycle / i18n lint），這是語義衝突最會炸的地方。

### 3b. 平行 review（逐項，鐵律 4）
合進的每個 PR 派 1 個 background opus agent（`model: opus`, `run_in_background: true`, `general-purpose`）審 diff：隱藏 bug、生產熱路徑（tracked_llm/api/deps/vocab_crud/web_auth）契約相容、i18n 對齊（鐵律 8）、Pydantic v2/@Observable 慣例。**只分析不改**。

### 3c. Forward-fix（殘留問題的標準解）
測試紅 / review BLOCK → 在 cleanup worktree 開 fix branch → 最小修正 → 驗證綠 → 開 PR → squash-merge。**不 revert 已合的 PR、不卡整批收斂**。commit prefix 照 Identity 表（`api:`/`ios:`/`ops:`/`docs:`）。

---

## Phase 4 — Doc-sync（後置，可派隔離 agent）

跳過條件：純樣板 / doc-only。否則合進的 code 變更照 `docs/sop/doc_sync.md` 路由同步。

- 多數 PR 應已 doc-as-code 自帶 doc 改動。剩餘走 `(cd <wt> && ./ops/docs_lint.sh)` 日常 gate：
  - 依 `docs/registry.yml` trigger 判斷本批 code 是否真的影響活文檔 → 改內容 + bump `verified_against` 到 main 可達 code commit。
  - 全 repo debt 盤點才跑 `./ops/docs_lint.sh --audit`;既有 invalid anchor / stale WARN 不阻塞本批 cleanup,除非是本批引入或本批觸發的文檔。
- 重點審：`sync_lifecycle.md`(SoT)、`backend.md`、`product_surface.md`/`tech_index.md`(SoT)、`cost_baseline.md`（費率變動時）。
- 派 doc-auditor 時用 `doc-auditor-prompt.md`；**agent 只分析、主 agent 統一 Edit**；要派會 commit 的就 `isolation: worktree`。
- 完成 `docs:` commit（commit 無妨；push 見下）。

---

## Phase 5 — 部署（預設跳過，需明確指示）

**push 遠端 / 部署生產一律須使用者明確指示**，不自動跑。有 backend 變更且使用者授權才：
```bash
./ops/devops_kg_safe.sh backup && ./ops/devops_kg_safe.sh deploy
```
**生產禁令（鐵律 7，永禁）**：`docker compose down -v` / `docker system prune -a` / `rm -rf /home/ubuntu/*`。運維只走 `devops_kg_safe.sh`，不繞 wrapper。

---

## Phase 6 — 收尾 + 報告

收尾固定順序（先移 worktree 才刪得掉 branch）：
```bash
git worktree remove <cleanup-wt>
git worktree remove <殘留>; git branch -D <merged-branch>
git push origin --delete <殘留 remote 分支>   # --delete-branch 常因 worktree 占用失敗，手動補
git fetch --prune
```
- codex 自己的 `~/.codex/worktrees/*` 由 codex session 清，不確定別動。
- 主 repo local main 由使用者/活 agent 自行 rebase 對齊（**不 ff/reset**）。

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
- doc-sync：✅ / 派 isolation agent / 跳過
- worktree/branch 收尾：✅
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
7. **push/deploy 須明確指示**；生產禁令永不繞過。
