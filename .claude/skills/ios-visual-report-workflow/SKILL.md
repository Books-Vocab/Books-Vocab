---
name: ios-visual-report-workflow
description: "把 active P3–P15 iOS visual work 以四個 cluster、exact selector、UI World 與 PR evidence 收斂；不建立本地工作項目或 merge 狀態。"
---

# iOS visual report route

這是 `ios-simulator-verification` 的高階 orchestration skill，不是另一套 UI evidence
技術規格。技術細節唯一讀 [`docs/sop/ui_flow_evidence.md`](../../../docs/sop/ui_flow_evidence.md)、
[`docs/sop/ios.md`](../../../docs/sop/ios.md) 與 machine fixtures：

- `ops/fixtures/ios_ui_review_clusters.json`
- `ops/fixtures/ios_ui_review_matrix.json`
- `ops/fixtures/ui_worlds/`

## 觸發與不可變邊界

只有 report-driven P3–P15 rebuild／visual review／matrix closure 才使用。先完成
Worker／Issue Solver onboarding、branch/worktree、Scope 與 PR assignment；CM／IM 不在
此 skill 內做 local merge。四個 cluster 必須由 fixture manifest 決定，不能由 agent 重新
命名、拆分或自行補一份 status ledger。

## 固定閉環

```text
audit report + current source
  → validate cluster/matrix/UI World contract
  → one cluster: source + test + fixture + exact selector
  → focused build/test
  → isolated Simulator evidence
  → machine verdict + explicit visual attestation
  → retained evidence → strict matrix record/validate
  → CR + DS + Actions + PR hand-back
```

每個 cluster 的實作 ownership 必須不重疊；一個 selector 只在 matrix 明確保存多個
requirement mapping 時重用。selector pass 不等於 requirement pass；缺 fixture、
counterexample、machine contract、visual attestation、provenance 或 docs gate 任一項，
都只能是 pending／blocked。

## 操作入口

先做唯讀輸入稽核：

```bash
uv run --python 3.13 python .claude/skills/ios-visual-report-workflow/scripts/audit_report_inputs.py \
  --root . --report-dir <report-dir> \
  --clusters ops/fixtures/ios_ui_review_clusters.json \
  --matrix ops/fixtures/ios_ui_review_matrix.json --json
```

接著依 `ui_flow_evidence.md` 的 exact selector plan，委派
`ios-simulator-verification/scripts/run_ui_evidence.sh` 或
`ops/ios_ui_run_many.py`；視覺二進位只在明確需要時 retain，cleanup 先 dry-run 再提交。
不要在 skill 內硬編 selector、UDID、dataset、artifact path 或過時報告截圖。

只有所有 run 都已用同一 source／dataset／device provenance 完成 machine contract 與
人工 attestation，才可使用 `ops/ios_ui_review_matrix.py record-many --strict-complete`；
若 source HEAD、dirty state、fixture SHA、evidence root 或 reviewer 不一致，停止並重跑，
不要改寫 provenance 來消除 mismatch。

## PR hand-back

receipt 必須包含 cluster map、active input、source/test/docs changed paths、branch／exact
HEAD、UI World／dataset、selector／device、verdict／attestation、matrix result、docs
impact、deviation、blocker 與下一步。CR 檢查 code／test，DS 檢查 docs／registry，CM 只在
GitHub PR、Actions required checks、review 與安全條件滿足後合併。這個 skill 不管理 Issue、
Project、PR lifecycle，也不保存本地 backlog。
