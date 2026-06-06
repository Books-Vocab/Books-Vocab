<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: manual-audit
scope:
  - docs/
  - ops/docs_impact.py
  - ops/docs_lint.sh
verified_against: 9de624ce
-->
# Docs Dogfood Report — 2026-06-06

## Scope

本報告驗證 KG 文檔控制平面是否讓未參與設計的 agent 能低成本完成 doc-sync 判斷、gate 執行與維護定位。測試依 `docs/sop/docs_dogfood.md` 執行。

## Agent Findings

| role | result | high-signal findings |
|---|---|---|
| backend-change | partial | `backend/src/kg/routers/vocab.py` 能快速找到 registry / doc_sync / tech_index,但 broad `backend/` 曾過度提示 `policy.safety`、`sop.deploy`、`sop.backend` |
| ops-change | partial | `ops/devops_kg_safe.sh` 必要提示應集中於 safety / deploy / debug / tech_index；`tech_index` 對 safe wrapper 命令面描述過淺 |
| docs-tooling-change | pass | `ops/docs_lint.sh` 只提示 tech_index / doc_sync / dogfood protocol,未再誤觸 host/safety/deploy/debug/product docs |
| ios-feature-change | partial | `ios/BooksBrowser/Models/Book.swift` 未能直接提示 bookshelf feature boundary；`sop.ios`、`sync_lifecycle` 對一般 book model 過寬 |
| maintenance | partial | gate/audit/registry 可找到且全綠；docs tooling test changes 曾誤提示 tech_index；`--registry` summary `OK: 0` 不直覺 |

## Consolidated Issues

| priority | issue | evidence | fix |
|---|---|---|---|
| P1 | Feature boundary discoverability 不足 | iOS dogfood: `Book.swift` impact 沒有 `docs/reference/feature_boundary/bookshelf.md` | registry 新增 `reference.feature_boundary.bookshelf`,並補 bookshelf frontmatter scope |
| P1 | Broad backend hints 噪音 | backend dogfood: router change 提示 safety/deploy/backend SOP | registry 對 `backend/src/kg/routers/*.py` 排除 safety/deploy/backend workflow docs |
| P1 | Docs tooling test 噪音 | maintenance dogfood: `ops/tests/test_docs_lint.sh` 提示 tech_index | registry 對 tech_index 排除 `ops/tests/test_docs_*.sh` |
| P2 | Safe wrapper command surface 不好查 | ops dogfood: `devops_kg_safe.sh` row 只有「部署 / 維護 safe wrapper」 | tech_index 補 safe wrapper command surface 與 blocklist 摘要 |
| P2 | `--registry` summary 不直覺 | docs-tooling/maintenance dogfood: `REGISTRY OK` 但 summary `OK: 0` | registry validate 成功時計入 `OK: 1` |
| P2 | Hypothetical sample vs default gate 易混 | backend/ops dogfood: default gate 反映目前 dirty branch,非假設檔案 | dogfood SOP 明確區分 `docs_impact --files` 與 default gate |
| P2 | Generated snapshot hint 缺少處置入口 | iOS dogfood: `generated.ios_baseline` 出現時需另查 doc_sync 才知道 generator | `docs_impact.py` 對 generated docs 輸出 `generator` |

## Follow-up Changes

- `docs/registry.yml`:新增 `reference.feature_boundary.bookshelf`,並加上 backend/router、devops wrapper、docs tooling test 的精準排除。
- `ops/docs_lint.sh`:registry 驗證成功時計入 summary OK。
- `ops/tests/test_docs_impact.sh`:新增 dogfood regression 覆蓋 backend/router、devops wrapper、Book model、docs tooling tests。
- `ops/tests/test_docs_lint.sh`:audit/all 目前為健康 gate,要求 WARN/ERROR 皆為 0；registry summary 要 `OK: 1`。
- `ops/docs_impact.py`:generated impact 會輸出 `generator`。
- `docs/reference/tech_index.md`:補 `devops_kg_safe.sh` command surface。
- `docs/sop/docs_dogfood.md`:補 default gate 與 hypothetical impact 樣本的判讀差異。

## Validation

- `./ops/test_ops.sh docs-lint` → passed groups:1 / failed groups:0
- `./ops/docs_lint.sh` → `ERROR: 0`
- `./ops/docs_lint.sh --registry` → `REGISTRY OK: 14 documents`, `OK: 1`, `ERROR: 0`
- `./ops/docs_lint.sh --audit` → `OK: 56`, `WARN: 0`, `ERROR: 0`
- dogfood samples:
  - `./ops/docs_impact.py --files backend/src/kg/routers/vocab.py` → sync/card/product/tech only; no safety/deploy/backend SOP noise
  - `./ops/docs_impact.py --files ops/devops_kg_safe.sh` → safety/tech/deploy/debug
  - `./ops/docs_impact.py --files ops/docs_lint.sh` → tech/doc_sync/dogfood
  - `./ops/docs_impact.py --files ios/BooksBrowser/Models/Book.swift` → product/bookshelf boundary/ios baseline,其中 generated baseline 顯示 `generator=ops/gen_ios_baseline.sh`
  - `./ops/docs_impact.py --files ops/tests/test_docs_lint.sh` → no registry impacts
