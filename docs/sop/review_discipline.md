<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - .claude/skills/
  - .claude/agents/
  - docs/sop/
verified_against: 7b4dee42
-->
# 逐項 Review 落地手冊（鐵律 4）

> KG 鐵律 4：每完成一個 fix/feature 立即 dispatch review agent，PASS 才下一個。禁「全部寫完再一起 review」。
> 本文是這條鐵律的可執行版 — 何時派、prompt 模板、PASS 判準、blocker 處理路徑。

## 何時派 review

派：
- 任一獨立可 commit 的 code change（feature / bugfix / refactor / migration）
- doc 系統批次修改 ≥3 個檔
- ops 腳本 / CI / hook 變動
- 鐵律相關文件（CLAUDE.md / policy/safety.md / runbook/system.md）改動

不派（避免 review 通膨）：
- 純 typo / 重命名 / 自動格式化
- 機器產出 snapshot（對應下方 `Review-Exempt: generated-snapshot`）
- 單行 fix 且該檔 ≤30 行

`phased` skill 已在第 N phase（N≥2）強制背景派 review 審 N-1 phase；本 SOP 把同樣模式擴到 phased 以外的場景。

## 怎麼派

> 派 `code-reviewer` agent 時,下方「Prompt 必含元素」§3–§6 已內建於 `.claude/agents/code-reviewer.md`(指回本 SOP,零重複),prompt 只需給 **commit hash + scope + 本次特別關注點**;用 general-purpose 當 reviewer 才需完整帶齊六項。

## Receipt 契約（機械可驗）

每個要被本 SOP 管的 commit message 必須二選一：

- `Reviewed-by: <reviewer>`
- `Review-Exempt: <reason>`

允許的 `Review-Exempt` 僅限：

- `trivial-typo`
- `rename-only`
- `format-only`
- `generated-snapshot`
- `single-line-small-file`

用 [`ops/review_audit.sh`](../../ops/review_audit.sh) 審 `origin/main..HEAD`（或 `--base` / `--rev-range` 指定範圍）。它不判斷 review 品質，只判斷 receipt 是否存在且合法；任一 commit 缺 receipt 或 exemption reason 不在白名單，exit `2`它稽核的 repo 是**呼叫端所在的** git toplevel（可用 `$KG_REVIEW_AUDIT_ROOT` 覆寫），每次執行會把選中的 root 印到 stderr——舊版無條件 cd 回腳本自己的 repo，`( cd 別處 && review_audit.sh )` 會靜默稽核錯的歷史（IMP-0049）。

固定模板（**優先軌**：`subagent_type: "code-reviewer"`，§3–§6 已內建，prompt 只給 commit hash + scope + 特別關注點；下方 general-purpose 為 fallback 軌，才需完整帶齊六項）：

```
Agent({
  subagent_type: "general-purpose",
  model: "opus",
  run_in_background: true,
  description: "Review <scope> commit <short-sha>",
  prompt: <self-contained>
})
```

`run_in_background: true` 是鐵律 5（長時操作背景執行），不可改同步。

### Prompt 必含元素

1. **commit hash** — `git log -1 --format=%H` 取，agent 跑 `git show <sha>` 拿到 diff
2. **scope / 目標** — 這個 commit 做什麼、為什麼、改了哪些檔
3. **審查重點** — 至少含：
   - 正確性（邏輯、邊界條件、race / nil / off-by-one）
   - 與既有 code 的契合（是否破壞既有 invariant、是否重造已存在的東西 — 對照 `docs/reference/product_surface.md`）
   - 是否引入 dead code / 半成品
   - 安全（鐵律 7 邊界、auth、PII、injection）
   - KG 專案規則：iOS raw 中文（鐵律 8）、SwiftData migration、provider registry not silent fallback
   - 雙態語意：Debug vs Release、feature flag on/off 兩態是否各自正確，是否只驗了單態
   - TDD 痕跡與測試品質：diff 是否附測試；測試是否鎖住「宣稱的語意」而非常數/實作細節（改個常數就能綠 = 假測試）
   - 風格契合：命名/分層/錯誤處理是否貼合該檔既有慣例，不引入新風格
   - 驗證證據：結論必附證據 — 親跑對應 gate（test/lint/build）貼當下輸出，或明示「本次為靜態審，未跑 gate」及原因
4. **下游 surface 同步檢查** — 若 commit 改了 user/agent-facing 介面（CLI 子指令、admin endpoint、env var、設定 schema、CSV schema），明確要 reviewer grep `.claude/skills/`、`docs/reference/product_surface.md`、`docs/reference/tech_index.md`、`docs/sop/`、`docs/policy/`、`docs/runbook/`，凡引用到舊清單但未在同 commit/PR 同步 → 標 **block**
5. **輸出格式約束** — `severity (block / nit) | file:line | issue` 條列，或 `PASS — no issues`
6. **限制** — 「只審這個 commit 的 diff，不要重寫 code，不要 propose 無關 refactor」

## PASS 判準

| 狀態 | 動作 |
|------|------|
| `PASS — no issues` | 進下一個 phase / 任務 |
| 全 `nit` | 進下一個 phase，nit 記入 todo「Phase N review feedback」延後修 |
| 任一 `block` | **暫停下一個 phase**，先決定處理路徑（見下） |

`nit` 不可滾雪球 — phase 結束前必須 batch 處理或明示 carry over 到下一 PR。`block` 不可無聲忽略。

## Block 處理路徑

| Block 與 phase N 關係 | 處理 |
|------------------------|------|
| 影響 phase N 正在改的檔 | 立即停 phase N，新 commit 修 phase N-1 問題（**不 amend** 已被 review 看過的 commit），再回頭做 phase N |
| 與 phase N 無關，但仍是 phase N-1 範圍內 | phase N 做完一起修，新 commit，再派一次 review |
| 跨多個歷史 phase 的系統性問題 | 在 PR body 標明、開 follow-up issue，不要在當前 PR 滾大 |

## Review 結果可見度

`run_in_background` 完成後系統會 push 一個 task-notification。主執行緒收到後**必須**：
1. 把 review 結論明示給使用者（PASS / 各 severity 條目）
2. 把處理決定明示給使用者（哪些立即修、哪些延後、哪些拒絕）

review 結果只在 task 工具的 internal output 不算數 — 沒在使用者面前露臉等於沒 review。

## 跟現有工具的關係

- **`phased` skill** — 多 phase 開發的入口，本 SOP 是它的詳細版手冊
- **`code-review` skill** — `/code-review` 全自動審本 branch；適合 **cutover 前**最後一道，不是每個 phase 的 inline check
- **`review` skill** — 審外部 PR（gh PR）；本 SOP 不適用
- **`/ultrareview`** — Claude Code harness 層級的 slash command（**不在** `.claude/skills/`，grep 找不到屬正常），雲端多 agent 重審本 branch / 指定 PR；user-triggered + 計費，agent **不可主動透過 Bash 或其他方式呼叫**

## 反例（要避免）

```
# 反例 1：全部寫完才 review
做 5 個 commit → 一次 dispatch reviewer → block 散落在不同 commit
→ 修正成本爆炸、commit 歷史污染
```

```
# 反例 2：同步等 review
Agent({ run_in_background: false })   # 違反鐵律 5
→ 主執行緒 blocked，phase N 該開始時還在等 N-1 review
```

```
# 反例 3：review 結果只看內部
Agent 跑完 → 主執行緒沒 surface 結論 → 直接進下一 phase
→ 使用者無從質疑 / 干預，等於沒審
```
