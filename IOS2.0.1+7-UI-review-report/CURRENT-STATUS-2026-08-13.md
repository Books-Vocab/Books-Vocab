# iOS 2.0.1 (Build 7) UI review：重構收斂狀態

日期：2026-08-13  
來源：`IOS2.0.1+7-UI-review-report.pdf`、`p1.PNG`–`p15.PNG`、目前工作樹與 simulator evidence bundle  
工作樹：`feat/ios-ui-review-report-complete-20260813`；目前整合 code baseline：`70edb37fe`；dirty=`false`

## 結論

原報告要求的是「重新思考並重構」而非局部修飾。P1–P15 表面上是 15 張圖，實際上是 5 個跨頁系統問題：資料／狀態模型、元件共用、互動時序、長內容／極端狀態與 visual hierarchy 必須一起收斂。這不是一次 UI polish；必須以 UI World 注入、狀態矩陣、Simulator/UI-test、證據契約與視覺迭代形成閉環。只修單頁 padding、顏色或單一 selector，無法達到報告標準。

本輪已把報告轉成可執行控制面：5 clusters、15 requirements、16 個精確 XCTest selectors；採 build-once/run-many、每 selector 一個 stable evidence bundle、單一 batch source HEAD、契約驗證與視覺 attestation 分離。控制面驗證：`valid=true clusterCount=5 requirementCount=15 selectorCount=16`。需求證據層目前 14 個 requirement 已有有效 PASS 證據，P3 是唯一 requirement-level BLOCK，原因是 dependency/cache 無法完成 build，沒有執行到產品測試；P15 的 3 個 selectors 已在最新 Settings lifecycle 修正上重跑收斂。整合 branch 最新 affected unit regression 為 `11 passed / 0 failed`，但不把 unit PASS 升格成 P3 UI execution PASS。另以最終 clean integration HEAD `83f0d044c` 執行完整 36-gate：交付 verdict 仍為 BLOCK；這是 branch/Gate 層結果，不改寫上述 14/15 的既有需求證據。

## 原報告意圖與目前差距

| Cluster | 報告真正要求 | 目前已完成 | 尚差 | 狀態 |
|---|---|---|---|---|
| Dictionary P1–P2 | 詞典不可用、結果／詞義／來源不完整；需重做資料狀態與 typed surface，不是加一個按鈕 | explicit lookup state、canonical senses、provenance/materialization fixture、穩定 selector 已落地；source `39ef0b8e`；P1/P2 fresh bundle 已 PASS 並完成視覺 attestation | 無目前已知功能 blocker；仍是 simulator-only / 單一視覺 reviewer | PASS（範圍受限） |
| Reader Runtime P3–P7 | TOC 成功邊界、settings round-trip、P5 fixed-height/drag/scale、progress/loading/retry 狀態需同一 runtime 模型 | P4/P5、P6/P7 fresh bundle 已 PASS；P6/P7 source `c6ff48e0`/`e6630961` 已 hand-back | P3 build preflight 解析 `GoogleSignIn`、`Minizip` 失敗，沒有 execution；不可沿用舊 bundle | BLOCK（P3 infra） |
| Explore/Overview P8–P10 | loading/empty/retry/counterexample、calendar shared components、Overview 需整體重設資訊層次 | P8/P9/P10 契約與視覺 evidence 均 PASS | 無目前已知功能 blocker；仍是 simulator-only / main-agent visual review | PASS（範圍受限） |
| Vocabulary/Review Card P11–P13 | P11 role/review/search/CTA 需有完整資料世界；P12/P13 需消除留白、資訊隱藏與 toolbar 失控 | P11 rich world、facet union、CTA、dynamic type、counterexample PASS；P12/P13 PASS | P11 的 O(N) projection/AX scan 只完成靜態風險審查，未宣稱 production perf PASS | PASS（P11 perf 限制） |
| Settings/Sync P14–P15 | sync/error/retry 動畫與 settings IA 要可觀察、可回復；不可用 optimistic UI 假裝成功 | P14 PASS；P15 以 deferred locale mutation、root refresh boundary、native binding、intent/rollback 分離完成 3-selector batch | 無目前已知功能 blocker；仍是 simulator-only / 單一視覺 reviewer | PASS（範圍受限） |

## P1–P15 evidence 狀態

「PASS」只代表目前有契約有效、source HEAD 可追溯且完成視覺 attestation 的 bundle；程式已提交但尚未取證者不升格為 PASS。

| ID | Selector | 程式／交接 | Evidence 狀態 |
|---|---|---|---|
| P1 | `DictionaryLookupFlowUITests/testDictionaryResultShowsCanonicalSensesProvenanceAndMaterialization` | `39ef0b8e` hand-back | PASS；fresh bundle `evidence/P1/20260813-151159-44623` |
| P2 | `DictionaryLookupFlowUITests/testP2DictionarySensesUsesIndependentTypedSurfaceSelector` | `39ef0b8e` hand-back | PASS；fresh bundle `evidence/P2/20260813-151305-48028` |
| P3 | `ReaderFlowUITests/testReaderTOCRequiredRealBookSelectionClosesOnlyAfterSuccess` | `722b92f` hand-back | BLOCK；build preflight 解析 `GoogleSignIn`/`Minizip` 失敗，0 executions |
| P4 | `ReaderSettingsUITests/testProductionReaderSettingsRoundTripAfterReaderReopen` | child bundle | PASS；contract valid，4 steps visual pass |
| P5 | 同 P4 selector，獨立 requirement | child bundle | PASS；以同一 shared flow 驗證不同 requirement，非重複 requirement |
| P6 | `ReaderFlowUITests/testReaderRuntimeProgressStatesArePreciselySelectableWithProvenance` | `c6ff48e0` hand-back | PASS；`evidence/P6/20260813-142032-69495` |
| P7 | `ReaderFlowUITests/testReaderRuntimeLoadingScenariosAreControllableAndRetryToSuccess` | `e6630961` hand-back | PASS；`evidence/P7/20260813-142940-99394` |
| P8 | `ExploreNavigationUITests/testExploreEvidenceMatrixCoversRequiredAndCounterexampleStates` | child bundle | PASS；contract valid，6 steps visual pass |
| P9 | `FixtureDatasetUITests/testReviewCalendarRequiredEvidenceUsesStableSelectors` | child bundle | PASS；contract valid，6 steps visual pass |
| P10 | `OverviewFlowUITests/testOverviewStatsRenderFromSeededReviewHistory` | child bundle | PASS；contract valid，10 steps visual pass |
| P11 | `VocabularyLibraryFlowUITests/testRichWorldProjectsRoleReviewSearchAndCTAConsistently` | parent `10cb1a0` | PASS；`evidence/P11/20260813-143617-16438`；首輪 rc=1 根因已確認並修正 |
| P12 | `ReviewCardLayoutEditorUITests/testToolbarEditorRelayoutsTheCardAndSharesOneProfileWithSettings` | child bundle | PASS；contract valid，3 steps visual pass |
| P13 | `ReviewCardLayoutEditorUITests/testGradingToolbarStaysOperableWithEveryFieldEnabled` | child bundle | PASS；contract valid，3 steps visual pass |
| P14 | `SettingsSyncLifecycleUITests/testSettingsSyncTerminalErrorRetriesToSuccess` | `e36b22a` hand-back | PASS；contract valid，2 steps visual pass |
| P15 | `SettingsFlowUITests/testSettingsFlowAppliesRealPreferenceChanges` | `51ea7178` hand-back | PASS；最新 batch，完成視覺 attestation |
| P15 | `SettingsFlowUITests/testSettingsLongContentCounterexampleResolvesProductionSelectors` | `51ea7178` hand-back | PASS；最新 batch，完成視覺 attestation |
| P15 | `SettingsFlowUITests/testSettingsResetCounterexampleShowsObservableBoundary` | `51ea7178` hand-back | PASS；`evidence/P15/20260813-154622-45782`，完成視覺 attestation |

## P11 首輪失敗的根因與修正

首輪 bundle `20260813-133155-99422` 的 contract 本身有效；唯一 assertion 是清除搜尋後要求 `row(p11-review-word-015).exists`。`visibleCount=644`、facet `14/503/127` 與搜尋投影均已通過。產品使用 `ScrollView + LazyVStack`，清除 query 會恢復完整 projection，但不保證指定 row 立即 materialize 在 viewport；失敗後的 accessibility teardown 才放大成 timeout。

修正 commit `790efe069` 保留 `visibleCount=644` 的完整 projection 判斷，改以「已 materialize 且不含前一個 query 的 row」驗證 query 清除，不修改 production UI。這是對驗收假設的最小根因修正，不是放寬產品行為。

## 已確認的根因與尚未能宣稱的部分

- **P1/P2**：舊問題不是字典卡片少一個欄位，而是 lookup、typed sense、provenance 與 materialization 沒有共同狀態模型；UI World 現在注入 rich payload，驗收固定 idle/loading/success/error/retry、選定 sense 與來源鏈。舊測試另曾把 runner 注入資料的 SHA 寫成舊常數，source `39ef0b8e` 改成由 runner bytes 計算，避免測試自相矛盾。
- **P3**：`run_ui_evidence` 在 build preflight 無法解析 `GoogleSignIn` 與 `Minizip`，因此沒有 execution、沒有產品畫面 verdict。這是 dependency/cache infrastructure BLOCK，不是把舊 bundle 偷升格成 PASS。
- **Fresh integration Gate（run_id=`83f0d044c193-13364-201231652442125`）**：36/36 gates 已執行；`ios-build`、`ios-build-catalyst` 與 12 個 UI-test scope 都因同一組 `GoogleSignIn`/`Minizip` module dependency resolution 失敗而 BLOCK；完整 unit scope 是 infrastructure `inconclusive`（`keychain-unavailable-osstatus-25291`）；ops pytest、backend pytest、design-system、docs conflict/verified、shell harness、baseline 與 backlog checks 均 PASS。Gate warnings 為既有 docs lint、slow UI pending、未測 shell/coverage，不是新的產品 PASS。
- **P6/P7**：P6 首輪把 production normalized progress ID 與測試 ID 混用，後續又把 transient restore-warning 當成穩定終態；P7 則錯誤要求 Readium preload web view 數量與全域內容計數。修正為 typed progress state + provenance、等待 stable runtime state；移除受合法 Readium preload 影響的虛假全域假設，保留 content/loading/retry/error 轉換驗收。P6 source `c6ff48e0`、P7 source `e6630961` 的 fresh bundles 已 PASS。
- **P11**：LazyVStack 的 viewport materialization 被誤當成 projection 不完整；修正驗收 oracle 後 `644` 筆 projection、facet union、搜尋與 CTA 均通過。靜態檢視仍看到 O(N) projection/sort 與 AX teardown 掃描，這是待 profiling 的風險，不足以宣稱 production performance 已證明。
- **P15**：真正根因是 reset 偏好時 `setLanguage(.system)` 觸發 app root `.id(selection)` 重建，先摧毀 Settings navigation，再讓 locale 變更污染同一個 reset boundary 的 AX 文案。修正分三層：`rootRefreshID` 將一般語言刷新與 root identity 分離；Settings active 時把 reset 的 locale mutation 存成 `deferredSelection`，只持久化 default、保留當前 rendered locale；Settings 離場才一次 apply selection + root refresh。最後將測試 oracle 從 `isHittable` 改成語意正確的 `isEnabled == false`。最新 source `51ea71787` 的主流程、長內容與 reset counterexample 全部 PASS。
- **整合後的 fixture／service 根因**：Xcode 在部分 build context 會把 `#filePath` 解析成 `<checkout>/ios/ios/...`，造成 asset 找不到；`FixtureDatasetStore.repositoryRootURL` 已改為以 `ios/BooksAndVocab` 與 `ops/fixtures/assets` marker 向上尋根。另將 absolute／traversal／symlink escape 驗證固定在 decode/materialization 邊界；KGService 的 explicit DEBUG fixture injection 現在優先於不一定能跨 coordinator child task 繼承的 ambient TaskLocal。這批修正以 `70edb37fe` 提交，11 個 affected unit selectors 全綠。

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

- 已通過：cluster validator `valid=true clusterCount=5 requirementCount=15 selectorCount=16`；run-many/matrix targeted tests `27 passed`；最新 affected unit regression `11 passed / 0 failed`；`bash -n ops/ios_test.sh`；`bash .claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh`；`docs_lint --registry`（45 documents）；P1/P2/P4/P5/P6/P7/P8/P9/P10/P11/P12/P13/P14/P15 simulator evidence。P15 最新 batch source `51ea71787`，3 selectors 均 machine PASS、bundle contract PASS、contact sheet 已逐項視覺 attestation。
- 平台：本輪是 iOS Simulator 驗證，不是 physical device；報告中的「實機操作」在此以 pinned simulator + exact XCTest + stable visual artifact 實現，不能誤報成真機 PASS。
- 視覺審查：目前 attestation reviewer 是 `main-agent-visual-review`；沒有第二位獨立視覺 reviewer，因此這是已揭露的 assurance limitation，不升格為雙人審查。
- P3 仍是唯一 requirement-level BLOCK：dependency/cache preflight 失敗且 0 executions；需恢復 Xcode package resolution/cache 後，依同一 pinned device、dataset 與 exact selector 重跑。Fresh integration Gate 另外確認所有 UI-test scope 都在相同 build blocker fail-closed，完整 unit scope 則受 keychain OSStatus 25291 影響而 inconclusive。P11 的 static performance risk 同樣不是已證明的 performance PASS。

## 工作樹邊界

本輪 child 已完成 commit + registry hand-back，並已 fan-in 至目前 integration branch `feat/ios-ui-review-report-complete-20260813`；整合 code baseline 為 `70edb37fe`，本狀態報告另有後續 docs-only 更新。尚未完成 close-wave：fresh Gate 的 P3 dependency/cache preflight 仍 fail-closed，且 unit infrastructure 不可用，故沒有 cutover local `main`、同步 `origin/main`、清理 worktree，亦未觸碰 `origin/prod`。這是目前與原方案「全部收斂」之間的唯一交付級阻塞；不能以舊 UI bundle、unit PASS 或 partial Gate 取代 P3 execution evidence。
