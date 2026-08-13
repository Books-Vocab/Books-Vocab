# iOS 2.0.1 (Build 7) UI review：重構收斂狀態

日期：2026-08-13  
來源：`IOS2.0.1+7-UI-review-report.pdf`、`p1.PNG`–`p15.PNG`、目前工作樹與 simulator evidence bundle  
工作樹：`feat/ios-ui-review-report-complete-20260812`  

## 結論

原報告要求的是「重新思考並重構」而非局部修飾。P1–P15 表面上是 15 張圖，實際上是 5 個跨頁系統問題：資料／狀態模型、元件共用、互動時序、長內容／極端狀態與 visual hierarchy 必須一起收斂。只修單頁 padding、顏色或單一 selector，無法達到報告標準。

本輪已把報告轉成可執行控制面：5 clusters、15 requirements、16 個精確 XCTest selectors；採 build-once/run-many、每 selector 一個 stable evidence bundle、單一 batch source HEAD、契約驗證與視覺 attestation 分離。控制面驗證：`valid=true clusterCount=5 requirementCount=15 selectorCount=16`。

## 原報告意圖與目前差距

| Cluster | 報告真正要求 | 目前已完成 | 尚差 | 狀態 |
|---|---|---|---|---|
| Dictionary P1–P2 | 詞典不可用、結果／詞義／來源不完整；需重做資料狀態與 typed surface，不是加一個按鈕 | explicit lookup state、canonical senses、provenance/materialization fixture、穩定 selector 已落地；P1 child `63b8d69a` 已 hand-back | fresh simulator P1/P2 evidence 尚未收斂 | IN_PROGRESS |
| Reader Runtime P3–P7 | TOC 成功邊界、settings round-trip、P5 fixed-height/drag/scale、progress/loading/retry 狀態需同一 runtime 模型 | P4/P5 fresh bundle 已 PASS；P3 child `722b92f`、P6/P7 child `020d5c1` 已 hand-back；P6/P7 已明確化 progress/loading state 與 provenance | P3、P6、P7 fresh simulator + visual attestation | IN_PROGRESS |
| Explore/Overview P8–P10 | loading/empty/retry/counterexample、calendar shared components、Overview 需整體重設資訊層次 | P8/P9/P10 契約與視覺 evidence 均 PASS | 無目前已知功能 blocker；仍是 simulator-only / main-agent visual review | PASS（範圍受限） |
| Vocabulary/Review Card P11–P13 | P11 role/review/search/CTA 需有完整資料世界；P12/P13 需消除留白、資訊隱藏與 toolbar 失控 | P12/P13 PASS；P11 fixture、facet union、CTA、dynamic type、counterexample 已落地 | P11 首輪失敗已修正 test 的 LazyVStack viewport 假設；fresh rerun 尚未完成 | IN_PROGRESS |
| Settings/Sync P14–P15 | sync/error/retry 動畫與 settings IA 要可觀察、可回復；不可用 optimistic UI 假裝成功 | P14 PASS；P15 native binding、intent/rollback 分離、mutation generation 已落地；主流程 fresh PASS | P15 兩個 counterexample selector 尚在 batch；需補視覺確認 | IN_PROGRESS |

## P1–P15 evidence 狀態

「PASS」只代表目前有契約有效、source HEAD 可追溯且完成視覺 attestation 的 bundle；程式已提交但尚未取證者不升格為 PASS。

| ID | Selector | 程式／交接 | Evidence 狀態 |
|---|---|---|---|
| P1 | `DictionaryLookupFlowUITests/testDictionaryResultShowsCanonicalSensesProvenanceAndMaterialization` | `63b8d69a` hand-back | fresh run 中 |
| P2 | `DictionaryLookupFlowUITests/testP2DictionarySensesUsesIndependentTypedSurfaceSelector` | `63b8d69a` hand-back | fresh run 中 |
| P3 | `ReaderFlowUITests/testReaderTOCRequiredRealBookSelectionClosesOnlyAfterSuccess` | `722b92f` hand-back | fresh run 中；先前曾被 dependency cache 擋住，不能沿用舊結論 |
| P4 | `ReaderSettingsUITests/testProductionReaderSettingsRoundTripAfterReaderReopen` | child bundle | PASS；contract valid，4 steps visual pass |
| P5 | 同 P4 selector，獨立 requirement | child bundle | PASS；以同一 shared flow 驗證不同 requirement，非重複 requirement |
| P6 | `ReaderFlowUITests/testReaderRuntimeProgressStatesArePreciselySelectableWithProvenance` | `020d5c1` hand-back | fresh run 中 |
| P7 | `ReaderFlowUITests/testReaderRuntimeLoadingScenariosAreControllableAndRetryToSuccess` | `020d5c1` hand-back | fresh run 中 |
| P8 | `ExploreNavigationUITests/testExploreEvidenceMatrixCoversRequiredAndCounterexampleStates` | child bundle | PASS；contract valid，6 steps visual pass |
| P9 | `FixtureDatasetUITests/testReviewCalendarRequiredEvidenceUsesStableSelectors` | child bundle | PASS；contract valid，6 steps visual pass |
| P10 | `OverviewFlowUITests/testOverviewStatsRenderFromSeededReviewHistory` | child bundle | PASS；contract valid，10 steps visual pass |
| P11 | `VocabularyLibraryFlowUITests/testRichWorldProjectsRoleReviewSearchAndCTAConsistently` | parent `790efe0` | fresh rerun 中；首輪 rc=1 根因已確認並修正 |
| P12 | `ReviewCardLayoutEditorUITests/testToolbarEditorRelayoutsTheCardAndSharesOneProfileWithSettings` | child bundle | PASS；contract valid，3 steps visual pass |
| P13 | `ReviewCardLayoutEditorUITests/testGradingToolbarStaysOperableWithEveryFieldEnabled` | child bundle | PASS；contract valid，3 steps visual pass |
| P14 | `SettingsSyncLifecycleUITests/testSettingsSyncTerminalErrorRetriesToSuccess` | `e36b22a` hand-back | PASS；contract valid，2 steps visual pass |
| P15 | `SettingsFlowUITests/testSettingsFlowAppliesRealPreferenceChanges` | `078569c6f` hand-back | PASS；contract valid，18 steps visual pass |
| P15 | `SettingsFlowUITests/testSettingsLongContentCounterexampleResolvesProductionSelectors` | `078569c6f` hand-back | batch 中 |
| P15 | `SettingsFlowUITests/testSettingsResetCounterexampleShowsObservableBoundary` | `078569c6f` hand-back | batch 中 |

## P11 首輪失敗的根因與修正

首輪 bundle `20260813-133155-99422` 的 contract 本身有效；唯一 assertion 是清除搜尋後要求 `row(p11-review-word-015).exists`。`visibleCount=644`、facet `14/503/127` 與搜尋投影均已通過。產品使用 `ScrollView + LazyVStack`，清除 query 會恢復完整 projection，但不保證指定 row 立即 materialize 在 viewport；失敗後的 accessibility teardown 才放大成 timeout。

修正 commit `790efe069` 保留 `visibleCount=644` 的完整 projection 判斷，改以「已 materialize 且不含前一個 query 的 row」驗證 query 清除，不修改 production UI。這是對驗收假設的最小根因修正，不是放寬產品行為。

## 可重跑的穩定工作流

```bash
# 1. 驗證 5 cluster / 15 requirement / 16 selector
UV_CACHE_DIR=/private/tmp/kg-uv-cache uv run --python 3.13 \
  python ops/ios_ui_review_clusters.py validate \
  ops/fixtures/ios_ui_review_clusters.json --root .

# 2. 一次 build、依精確 selector 執行多個 UI flow
UV_CACHE_DIR=/private/tmp/kg-uv-cache \
  KG_IOS_TEST_MAX_EXECUTION_TIME_ALLOWANCE=420 \
  uv run --python 3.13 python ops/ios_ui_run_many.py run \
  --root . \
  --helper .claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --methods-file <exact-runs.json> \
  --device <pinned-simulator-udid> \
  --output-dir build/snapshots/uitest-evidence/<batch> \
  --summary-out <batch-summary.json>

# 3. 每個 bundle 必須先完成主流程 verdict + evidence contract，
#    再逐張檢視 contact sheet / screenshot，最後才寫 visual attestation。
uv run --python 3.13 python ops/uitest_review_attest.py \
  <bundle>/artifacts/ui-review \
  --reviewer <named-reviewer> --status pass --all-steps \
  --visual-check '<check-1>' --visual-check '<check-2>'

# 4. 只有 batch summary=passed_unattested 且所有 bundle 已 attested，
#    才可 atomic record-many；任一 requirement 失敗則零寫入。
UV_CACHE_DIR=/private/tmp/kg-uv-cache uv run --python 3.13 \
  python ops/ios_ui_review_matrix.py record-many \
  ops/fixtures/ios_ui_review_matrix.json --root . \
  --summary <batch-summary.json>
```

固定規則：不把 `should work` 當結果；不以單一畫面代替狀態矩陣；不把 runner PASS 當 visual PASS；不把不同 source HEAD 的 bundle 混進同一批；長命令必須有 PID/elapsed/alive heartbeat；build lock、simulator identity、dataset SHA、bundle basename/runId 都要能回溯。

## 已完成的控制面與 skill

- `ops/fixtures/ios_ui_review_clusters.json`：P1–P15 對應 5 clusters、exact selectors、dataset、source module 與 visual references。
- `ops/ios_ui_review_clusters.py`：schema、requirement、selector、source module、matrix 對齊驗證與 run-plan 展開。
- `ops/ios_ui_run_many.py`：build-once/run-many、精確 selector、stable bundle、source HEAD preflight、heartbeat、continue-on-failure、summary。
- `ops/ios_ui_review_matrix.py record-many`：契約與視覺 attestation 完成後的 atomic bulk recording。
- `.claude/skills/ios-simulator-verification/SKILL.md`：已固化 simulator/UI-test/evidence contract、visual attestation、cluster batch、長命令不閒置與 fail-closed handoff。
- `docs/sop/ui_flow_evidence.md`、`docs/reference/tech_index.md`、`docs/registry.yml`：已同步控制面入口；`docs_lint --registry` PASS（45 documents）。

## 驗證與偏離

- 已通過：cluster/run-many/matrix targeted tests `27 passed`；`bash -n ops/ios_test.sh`；`docs_lint --registry`；P4/P5/P8/P9/P10/P12/P13/P14/P15 主流程 simulator evidence。
- 平台：本輪是 iOS Simulator 驗證，不是 physical device；報告中的「實機操作」在此以 pinned simulator + exact XCTest + stable visual artifact 實現，不能誤報成真機 PASS。
- 視覺審查：目前 attestation reviewer 是 `main-agent-visual-review`；沒有第二位獨立視覺 reviewer，因此這是已揭露的 assurance limitation，不升格為雙人審查。
- P1/P2、P3、P6/P7 與 P11/P15 counterexample 的 fresh batch 完成後，才可把本文件的 IN_PROGRESS 改成 PASS；未完成前保留 fail-closed 狀態。

## 工作樹邊界

本輪只完成 child commit + registry hand-back 與本工作樹內的報告／工具變更；沒有執行 integrate、cutover、resolve、sync、deploy，也沒有宣稱 local main、origin/main 或 production 已收斂。
