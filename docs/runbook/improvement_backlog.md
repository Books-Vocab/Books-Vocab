<!-- doc-meta
tier: runbook
authority: SoT
update_trigger: manual
scope:
  - .claude/agents/platform-steward.md
  - .claude/skills/kg-receipt/
verified_against: d5542a1
-->
# 改善 Backlog（kaizen ledger）

> 自我提升迴圈的 **SoT**:所有「工具 / CLI / 文檔 / 架構」摩擦的 open 問題單一登記處。
> 原則見**鐵律9**(摩擦優先修工具)、分級見 `kg-router`「Tool Friction」、表態見 `kg-receipt`「Tooling Debt」——本文**不複述**,只負責**持久化、追蹤、收斂**。

## 為什麼存在

receipt 裡的 tooling debt 會隨 transcript 蒸發。本 ledger 讓每個 raised 問題**進 git、可回溯、有 owner、追到 resolved**,杜絕 agent 無聲妥協(硬幹)。owner = `platform-steward`(Staff)。

## Andon — 任何節點怎麼提一筆

1. 撞到摩擦 → 先第一性原理判根因(鐵律9),分級(kg-router「Tool Friction」)。
2. 在 receipt 表態(規則見 `kg-receipt`「Tooling Debt」)。
3. 非 trivial 且未當場修掉 → 由上一階 / `platform-steward` 追加一列到下表。
4. 中大型 / 結構級 → 不只登記:停手修工具,或升級上一階(鐵律9 + `docs/sop/agent_org.md`「反硬幹升級階梯」)。

## Entry schema

- `status`: `open` → `triaged` → `in-progress` → `fixed` / `wont-fix`(附理由)
- `category`: `tool` / `cli` / `doc` / `arch`
- `severity`: `low` / `med` / `high`
- `resolution`: 解決 commit hash,或 wont-fix 理由(這是「可回溯」的關鍵欄)
- resolution hash 慣例:PR 合併前為 branch-local;若該 PR 採 **squash merge**,合併後由 `platform-steward` 更新為 squashed hash,維持 audit trail 不斷。

## Ledger

| id | date | source | category | severity | status | detail | resolution |
|---|---|---|---|---|---|---|---|
| IMP-0001 | 2026-06-13 | docs-steward 首測 | doc | low | fixed | agent 檔寫「依 kg-receipt 格式」但未給欄位指標,靠 brief 餵 | `7c95a02`(補欄位指標) |
| IMP-0002 | 2026-06-13 | review gate | doc | low | fixed | agent_org.md 3 處 borderline 複述鐵律判準 | `3671b89`(收斂為純指標) |
| IMP-0003 | 2026-06-13 | docs-steward 首測 | cli | low | triaged | `docs_impact.py` 對 CLAUDE.md 純政策段新增穩定產生 5 條 exact 誤報(`via=CLAUDE.md`);hint≠命令故不阻擋,但每次需人工判讀 | open — 候選 enhancement:registry 對 CLAUDE.md source 加 section-anchor 機制 |
| IMP-0004 | 2026-06-13 | backend-engineer smoke | tool | low | wont-fix | 首次 `uv run` 觸發 .venv bootstrap(~100MB),新 worktree / CI 首跑有感 | 正常行為,快取後即解;不修 |
| IMP-0005 | 2026-06-13 | kaizen-loop review gate | cli | low | in-progress | `docs_lint.sh` 不接受裸 doc 路徑當位置參數(`docs_lint.sh foo.md` → Unknown arg),已加可接受裸路徑路徑模式(等待驗證 commit hash 鎖定) | in-progress |
