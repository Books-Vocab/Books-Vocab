<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: manual-audit
scope:
  - docs/
  - ops/docs_impact.py
  - ops/docs_lint.sh
verified_against: b14385b76
-->
# Docs Dogfood Report — 2026-06-06

> 歷史快照:本報告保留 2026-06-06 dogfood 結果作為控制面演進記錄；後續 registry / gate 數量若有成長,不回寫覆蓋當日觀測值。

## Scope

本報告驗證 KG 文檔控制平面是否讓未參與設計的 agent 能低成本完成 doc-sync 判斷、gate 執行與維護定位。測試依 `docs/sop/docs_dogfood.md` 執行。

## Agent Findings

| role | result | high-signal findings |
|---|---|---|
| backend-change | partial | `backend/src/kg/routers/vocab.py` 能快速找到 registry / doc_sync / tech_index,但 broad `backend/` 曾過度提示 `policy.safety`、`sop.deploy`、`sop.backend` |
| ops-change | partial | `ops/devops_kg_safe.sh` 必要提示應集中於 safety / deploy / debug / tech_index；`tech_index` 對 safe wrapper 命令面描述過淺 |
| docs-tooling-change | pass | `ops/docs_lint.sh` 只提示 tech_index / doc_sync / dogfood protocol,未再誤觸 host/safety/deploy/debug/product docs |
| ios-feature-change | partial | `ios/BooksAndVocab/Models/Book.swift` 未能直接提示 bookshelf feature boundary；`sop.ios`、`sync_lifecycle` 曾對一般 iOS change 過寬 |
| maintenance | partial | gate/audit/registry 可找到且全綠；docs tooling test changes 曾誤提示 tech_index；`--registry` summary `OK: 0` 不直覺 |

## Consolidated Issues

| priority | issue | evidence | fix |
|---|---|---|---|
| P1 | Feature boundary discoverability 不足 | iOS dogfood: `Book.swift` impact 沒有 `docs/reference/feature_boundary/bookshelf.md` | registry 新增 `reference.feature_boundary.bookshelf`,並補 bookshelf frontmatter scope |
| P1 | Sync lifecycle source 過寬 | iOS dogfood: 一般 Reader/Settings/Book model change 會提示 `contract.sync_lifecycle` | registry 與 `sync_lifecycle.md` frontmatter scope 收斂到 sync 狀態機、payload schema、收斂流程檔案；Reader/Settings 一般 view change 改由 feature boundary docs 承接 |
| P1 | Broad backend hints 噪音 | backend dogfood: router change 提示 safety/deploy/backend SOP | registry 對 `backend/src/kg/routers/*.py` 排除 safety/deploy/backend workflow docs |
| P1 | Docs tooling test 噪音 | maintenance dogfood: `ops/tests/test_docs_lint.sh` 提示 tech_index | registry 對 tech_index 排除 `ops/tests/test_docs_*.sh` |
| P2 | Safe wrapper command surface 不好查 | ops dogfood: `devops_kg_safe.sh` row 只有「部署 / 維護 safe wrapper」 | tech_index 補 safe wrapper command surface 與 blocklist 摘要 |
| P2 | `--registry` summary 不直覺 | docs-tooling/maintenance dogfood: `REGISTRY OK` 但 summary `OK: 0` | registry validate 成功時計入 `OK: 1` |
| P2 | Hypothetical sample vs default gate 易混 | backend/ops dogfood: default gate 反映目前 dirty branch,非假設檔案 | dogfood SOP 明確區分 `docs_impact --files` 與 default gate |
| P2 | Generated snapshot hint 缺少處置入口 | iOS dogfood: `generated.ios_baseline` 出現時需另查 doc_sync 才知道 generator | `docs_impact.py` 對 generated docs 輸出 `generator` |
| P2 | Registry 覆蓋率不可見 | 手動盤點發現 55 份 linted docs 只有 14 份在 registry；feature boundary / UI / agent-routed operational docs 原先多數未登記 | 新增 `ops/docs_registry_coverage.py` 與 regression test；輸出 active/backlog 分桶,`--strict` 只追 active-doc coverage debt；feature boundary、UI、backend testing、smoke、cost、runbook、review discipline、architecture、backup、i18n、podcast pipeline、LLM eval、Figma token workflow docs 已登記 |
| P2 | UI tooling impact 噪音 | `ops/ui_token_lint.sh` 曾因 broad `ops/` source 誤觸 host/safety/deploy/backend/debug/product docs | 將 UI token tooling 從 broad ops workflow docs 排除,只保留 tech index + UI design/checklist hints |
| P2 | Agent 入口沒有控制面用法 | 新 agent 只讀 `CLAUDE.md` 時能看到傳統路由表,但不一定知道 registry / impact / gate / coverage 的實際操作順序 | `CLAUDE.md` 新增 Docs Control Plane 快速用法；registry 將 `CLAUDE.md` 納入 doc_sync / dogfood source |
| P2 | Operational docs impact 噪音 | backend tests / provider pricing / iOS release script 曾透過 broad backend/ops source 誤觸 safety/product/deploy/backend/host/debug docs | 將 backend tests、provider pricing、iOS release script 從不相關 broad docs 排除,保留 backend testing / cost / iOS / smoke / tech hints |
| P2 | Specialized tooling impact 噪音 | i18n lint / podcast upload 曾透過 broad ops source 誤觸 host/safety/product/backend/deploy/debug docs | 將 i18n 與 podcast tooling 從不相關 broad docs 排除,保留 i18n / podcast pipeline / tech hints |

## Follow-up Changes

- `docs/registry.yml`:新增 `reference.feature_boundary.bookshelf` / `chrome` / `notebook` / `podcast` / `reader` / `settings` / `vocabulary`,並加上 backend/router、devops wrapper、docs tooling test、UI token tooling 的精準排除；`contract.sync_lifecycle` 從 iOS/backend 全目錄收斂為 sync-specific source set。
- `docs/registry.yml`:新增 `sop.ui_design`、`reference.ui_components`、`reference.ui_review_checklist`、`reference.ui_state_matrix`,讓 UI design docs 進控制平面。
- `docs/registry.yml`:新增 `reference.testing_backend_strategy`、`reference.testing_smoke_checklist`、`reference.cost_baseline`、`sop.cost_review`、`runbook.system`、`sop.review_discipline`,讓 `CLAUDE.md` 路由表與 skills 已引用的 operational docs 進控制平面。
- `docs/registry.yml`:排除 backend tests、provider pricing、iOS release script 在不相關 broad backend/ops docs 下的誤報。
- `docs/registry.yml`:新增 `sop.architecture`、`sop.backup`、`sop.backup_restore`、`sop.i18n_lint`、`sop.i18n_plural_keys`、`sop.podcast_pipeline`、`reference.llm_eval`、`sop.llm_eval`,讓剩餘高頻 SOP/reference 文檔進控制平面。
- `docs/registry.yml`:排除 i18n/podcast tooling 在不相關 broad ops docs 下的誤報。
- `docs/registry.yml`:新增 `sop.figma_token_workflow`,讓設計 token sidecar、round-trip、drift gate workflow 進控制平面。
- `CLAUDE.md`:新增 Docs Control Plane 快速用法,一載入即知道 registry、impact detector、日常 gate、audit、coverage 與 doc-sync SOP 怎麼用。
- `docs/registry.yml`:將 `CLAUDE.md` / PR template 納入 `sop.doc_sync` source,並將 `CLAUDE.md` 納入 `sop.docs_dogfood` source。
- `docs/reference/sync_lifecycle.md`:frontmatter scope 對齊 registry,避免文檔宣稱與控制面不同步。
- `ops/docs_lint.sh`:registry 驗證成功時計入 summary OK。
- `ops/tests/test_docs_impact.sh`:新增 dogfood regression 覆蓋 backend/router、devops wrapper、Book model、docs tooling tests、UI token tooling、backend tests、provider pricing、iOS release script、architecture、backup、i18n、podcast pipeline、LLM eval；Reader/Settings 一般 view change 不再提示 sync lifecycle,而 `KGService+Sync` / `SyncCoordinator` 仍提示 sync contract。
- `ops/tests/test_docs_lint.sh`:audit/all 目前為健康 gate,要求 WARN/ERROR 皆為 0；registry summary 要 `OK: 1`；`CLAUDE.md` 必須明列 registry / impact / lint / coverage 入口命令。
- `ops/docs_impact.py`:generated impact 會輸出 `generator`。
- `ops/docs_registry_coverage.py`:新增 registry coverage report / strict mode；coverage regression 要求所有 feature boundary、UI design、agent-routed operational docs、architecture/i18n/podcast/eval、Figma token workflow docs 必須登記；未登記項分成 active/backlog,避免 dated plans/specs/snapshots 被誤讀為日常 gate debt。
- `ops/test_ops.sh`:docs-lint group 納入 coverage regression。
- `docs/reference/tech_index.md`:補 `devops_kg_safe.sh` command surface。
- `docs/sop/docs_dogfood.md`:補 default gate 與 hypothetical impact 樣本的判讀差異。

## Validation

- `./ops/test_ops.sh docs-lint` → passed groups:1 / failed groups:0
- `./ops/docs_lint.sh` → `ERROR: 0`
- `./ops/docs_lint.sh --registry` → `REGISTRY OK: 39 documents`, `OK: 1`, `ERROR: 0`
- `./ops/docs_lint.sh --audit` → `OK: 56`, `WARN: 0`, `ERROR: 0`
- `./ops/docs_registry_coverage.py` → `total=55`, `registered=39`, `unregistered=16`, `active_unregistered=0`, `backlog_unregistered=16`
- dogfood samples:
  - `./ops/docs_impact.py --files backend/src/kg/routers/vocab.py` → sync/card/product/tech only; no safety/deploy/backend SOP noise
  - `./ops/docs_impact.py --files ops/devops_kg_safe.sh` → safety/tech/deploy/debug
  - `./ops/docs_impact.py --files ops/docs_lint.sh` → tech/doc_sync/dogfood
  - `./ops/docs_impact.py --files ios/BooksAndVocab/Models/Book.swift` → product/bookshelf boundary/ios baseline,其中 generated baseline 顯示 `generator=ops/gen_ios_baseline.sh`
  - `./ops/docs_impact.py --files ios/BooksAndVocab/Views/Reader/ReaderView.swift chrome-extension/background.js ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookListView.swift ios/BooksAndVocab/Views/Vocabulary/Scenes/KGVocabPresenter.swift` → chrome/notebook/reader/vocabulary feature boundary docs 分別命中
  - `./ops/docs_impact.py --files ios/BooksAndVocab/Views/Reader/ReaderView.swift ios/BooksAndVocab/Views/Settings/SettingsView.swift ios/BooksAndVocab/Services/KGService+Sync.swift ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncCoordinator.swift chrome-extension/shared/vocab-outbox.js backend/src/kg/vocab_intake.py` → sync contract 只由 sync/outbox/backend vocab paths 命中,Reader/Settings view 只走 feature boundary docs
  - `./ops/docs_impact.py --files ios/BooksAndVocab/UIComponents/AppShellComponents.swift ios/BooksAndVocab/Models/AppMetrics.swift ops/ui_token_lint.sh` → UI component/state/design/checklist docs 命中,且 UI token tooling 不再誤觸 host/safety/deploy/backend/debug/product docs
  - `./ops/docs_impact.py --files CLAUDE.md` → doc_sync / dogfood / UI checklist,確保 agent 入口變更不會繞過控制面
  - `./ops/docs_impact.py --files backend/tests/test_api.py backend/src/kg/llm/providers.py .claude/skills/billing/SKILL.md ops/ios_release.sh ops/devops_kg_safe.sh` → backend testing / cost / smoke / runbook docs 命中,且 backend tests/provider pricing/iOS release script 不再誤觸不相關 broad docs
  - `./ops/docs_impact.py --files ops/i18n_lint.sh ops/podcast_upload.sh lab/podcast/pipeline.py lab/llm_eval/prompts/manifest.yaml` → i18n / podcast pipeline / LLM eval docs 命中,且 i18n/podcast tooling 不再誤觸不相關 broad docs
  - `./ops/docs_impact.py --files ops/tests/test_docs_lint.sh` → no registry impacts
