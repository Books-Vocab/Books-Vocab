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
| IMP-0005 | 2026-06-13 | kaizen-loop review gate | cli | low | fixed | `docs_lint.sh` 不接受裸 doc 路徑當位置參數(`docs_lint.sh foo.md` → Unknown arg),已加可接受裸路徑並保留清楚提示 | `813356b1` |
| IMP-0006 | 2026-07-08 | iOS 2.0.0 發版檢討 | tool | low | fixed | `asc.sh`/`ios_release.sh` 靜默吞 ASC API 錯誤(403 agreement 無輸出 exit 1) | `ef5fcfb00`(fd3 透出+403 GUI 指引+test_asc §17) |
| IMP-0007 | 2026-07-08 | iOS 2.0.0 發版檢討 | arch | med | fixed | 升級觸發清單漏「執行中發現 human-only 動作」,blocker 批到 receipt 才告知(ASC 403 損失 40 min 可平行人工時間) | `9a8209a4c`(agent_org.md 補即時升級觸發)+`fbf2221cb`(review 修正) |
| IMP-0008 | 2026-07-08 | iOS 2.0.0 發版檢討 | arch | med | fixed | 委派無成本下限,trivial 工作也燒全套 agent+receipt | `9a8209a4c`(agent_org.md 補 trivial 門檻)+`fbf2221cb`(trivial vs 豁免釐清) |
| IMP-0009 | 2026-07-08 | iOS 2.0.0 發版檢討 | doc | low | fixed | 逐項 review 固定檢查項靠 GM 每次手寫 brief,重複且易漏 | `9a8209a4c`(code-reviewer.md 內建 checklist)+`fbf2221cb`(SoT 收斂:複述→指標) |
| IMP-0010 | 2026-07-08 | iOS 2.0.0 發版檢討 | cli | med | fixed | `release.sh bump` 跑了立即寫檔,違 dry-run 預設慣例(實際咬人:預覽即污染 pbxproj) | `34cd97866`+`9c88b55b2`(dry-run 預設+--yes+全面語意同步+迴歸) |
| IMP-0011 | 2026-07-08 | iOS 2.0.0 發版檢討 | cli | low | fixed | `ios_test.sh --ui` 缺 dataset 錯誤不列可用清單,需二次查找 | `27d61ecb5`+`d56efeabe`(錯誤附 ui_worlds 名單+set -e 防死+迴歸) |
| IMP-0012 | 2026-07-08 | iOS 2.0.0 發版檢討 | doc | low | open | `docs/sop/ios.md` §UI World dataset 契約為單行 ~4000 字牆,知識密度高但不可讀不可維護;候選:結構化為表格+分節 | — |
| IMP-0013 | 2026-07-08 | Phase 1 review(world-export) | tool | low | open | Card/Notebook schema 變更無 lint 抓「export/seed 未同 PR 對齊」→ roundtrip 靜默有損;現靠 ops_state_plane §1.1 紀律 + roundtrip 測試抓 export 側漏導。符合 gate 刻意延後政策([[ops-gate-enforcement-deferred-by-design]]),升級訊號=同錯第三次 | — |
