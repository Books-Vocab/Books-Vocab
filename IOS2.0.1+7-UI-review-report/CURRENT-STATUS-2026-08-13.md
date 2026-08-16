# iOS 2.0.1 (Build 7) UI review：重構收斂狀態

日期：2026-08-16（final evidence 前的 canonical convergence checkpoint）
來源：`IOS2.0.1+7-UI-review-report.pdf`、`p1.PNG`–`p15.PNG`、目前 canonical worktree 與 pinned Simulator evidence。
canonical 工作樹：`/Users/chenliangyu/project/kg/.claude/worktrees/ios-ui-review-report-complete-20260813`；branch=`feat/ios-ui-review-report-complete-20260813`。exact source HEAD 只由 final summary 與每個 bundle 的 machine provenance 提供；本檔不重複自指的 Git SHA。v36 已標記 abandoned；P10 focused repair v42 已通過 machine/visual，但 final batch 預定為 `final-head-batch-v43`。Simulator：`F068B3D8-9E0B-475B-85C3-97BC61748A8F`；UI World：`marketing_demo`，SHA=`609f35f300df7a2d340f2799625b8ff50486bda835cafb05b72a6b7396abfced`。

## 2026-08-16 convergence checkpoint（取代前一版未更新的 current 描述）

本 checkpoint 已完成既有 canonical integration tree 內的 source/test/control-plane 收斂，尚未產生新的 P1–P15 exact-head UI evidence；因此不可把任何舊 bundle 或 selector PASS 升格為目前 requirement PASS。

- Reader lifecycle／runtime 修正已提交並通過 reviewer：navigator callback、preferences apply task、recovery task 均以 navigator generation、identity 與 task token 設防；同一 canonical working tree 的 focused run 為 `51/51`，但這是 commit 前同內容的 focused validation，不是 final exact-head evidence。
- P2 已把 scope 從錯誤的 Dictionary detail 描述校正為 Add Link initial/detail/selection/materialization surface；sense/example selection 以 accessibility `.isSelected` 暴露，failure 後保留選取狀態；focused unit 為 `49/49`。P2 matrix 維持 `pending`，因尚未在最終 exact HEAD 取得 initial、result、selection-preservation 與 materialization-failure 的 UI bundle。
- cluster 控制面將 P2 run-plan 標為 `in_progress`，matrix 才標 `pending`：`expand-run-plan` 會排除 `pending/blocked`，保留 `in_progress` 以確保待取證 selector 不會從批次清單消失；這不是 verified。
- strict localization、cluster validate、P2/Reader focused tests 均已跑過；現存 evidence 仍綁舊 source commit，不能重用作這輪 exact-head receipt。
- 穩定工作流已固化於 `.claude/skills/ios-simulator-verification/` 與 `.claude/skills/ios-visual-report-workflow/`：唯一 helper、pinned Simulator/UI World、run manifest/PID/HEAD/TTL、build-once/run-many、failure cleanup、visual attestation、matrix strict-complete 與 canonical convergence 均以 fail-closed 契約執行。

目前唯一尚未完成的交付阻塞是：在所有 source/test/docs 固定後，對 P1–P15 required/counterexample state 重新執行同一 exact HEAD 的 Simulator/UI-test evidence，完成逐 bundle visual attestation，並由 `record-many --strict-complete` 寫入 matrix receipt；在此之前不可宣稱可合併。

## 2026-08-15 canonical freeze（歷史 freeze contract；目前以 2026-08-16 checkpoint 為準）

本輪不新增 worktree、branch、ticket、cluster 或 scope；只在既有 integration worktree 收斂。source/test/docs 已在 evidence 前固定；此檔與 `evidence-manifest-2026-08-13.json` 在 final batch 完成後不得再修改，避免把 post-evidence 報告編輯誤認成 source receipt。v34（source=`d3f2d0e32199a9f13d7c8e6eace32bbe773217be`、matrix receipt=`f6edc9d52`）降格為歷史證據，不能證明目前 canonical HEAD。

唯一 current evidence contract：以凍結 HEAD 執行 `final-head-batch-v43`，run-plan 的 31 executions 對應 28 個 unique exact methods，共用一次 build-for-testing；每個 execution 必須有 machine contract、source/dataset/device provenance、stable screenshots/contact sheet/quick4/UIreview/video、逐步 visual attestation。之後 `record-many --strict-complete` 才能寫入 matrix receipt；selector PASS 不等於 requirement state union PASS。current verdict 的唯一真相是：

- summary：`build/snapshots/uitest-evidence/final-head-batch-v43-summary.json`
- bundles：`build/snapshots/uitest-evidence/final-head-batch-v43-bundles/`
- matrix：`ops/fixtures/ios_ui_review_matrix.json`（只允許這個 tracked receipt path 在 evidence 後變動）
- cluster contract：`ops/fixtures/ios_ui_review_clusters.json`
- workflow／docs lint／Gate／review receipt：以 final hand-back receipt 與 orchestrator state 內相同 exact HEAD 為準；任何與該 HEAD 不一致的舊 receipt 均為歷史診斷。

本檔刻意不預填 final batch 的 PASS；完成後由上述 summary、每個 bundle 的 `review_state.json`、matrix receipt、fresh Gate 與 registry/clean-tree audit 共同定讞。這是 provenance 保護，不是把未跑的測試宣稱通過。

## 歷史分析與修正脈絡（非 current verdict）

原報告要求的是「重新思考並重構」而非局部修飾。P1–P15 表面上是 15 張圖，實際上是 5 個跨頁系統問題：資料／狀態模型、元件共用、互動時序、長內容／極端狀態與 visual hierarchy 必須一起收斂。這不是一次 UI polish；必須以 UI World 注入、狀態矩陣、Simulator/UI-test、證據契約與視覺迭代形成閉環。只修單頁 padding、顏色或單一 selector，無法達到報告標準。

本輪已把報告轉成可執行控制面：5 clusters、15 requirements、16 個 selector bindings；final run-plan 展開 31 executions／28 個 unique exact methods。採 build-once/run-many、每 execution 一個 stable evidence bundle、單一 batch source HEAD、契約驗證與視覺 attestation 分離。控制面驗證：`valid=true clusterCount=5 requirementCount=15 selectorCount=16`。P10 focused v42 綁定 `088e9c1863cf0b83285b74f7564b2450467f859f`，populated 與 empty forecast counterexample 均 machine PASS、all-steps visual attestation PASS；但它不是 P1–P15 final batch，也沒有寫 matrix。`record-many` 仍依 exact state union fail-closed，不能把 selector-level PASS 冒充完整矩陣。P1/P2 的 auth、cardinality、graphLinks AX 結構問題，以及 P3 package graph/cache BLOCK 均已實際修掉，歷史失敗仍保留作診斷。

Reader P4/P5 有兩層已收斂根因。第一層是 P3→P4 連續行程中 UI World overlay 只改 persistence，已初始化的 `ReaderSettings.shared` 沒有 reload，造成 P4 讀到舊 line-height；`05e74c94b` 加入 injectable stores、`reloadFromPersistence()` 與 fixture overlay 後 reload，unit 2/2 PASS，v17 P3→P4 2/2 PASS。第二層是 iOS 26 XCTest Slider endpoint seam：`4c872d3e2` 將 lower/upper 都固化為有限次 semantic interior staging（`0.05/0.15/0.25` 與 `0.95/0.85/0.75`），每次先等 AX interior value 變更，再確認 endpoint exact value；v18 P5 與 v19 P5 均 PASS。P9 仍保留從 auth、stale selector、父容器 AX shadowing、viewport readiness、空狀態 containment 到 AX materialization race 的完整根因鏈；P10 populated metrics/calendar/forecast 與 P15 English reset 也完成 current-head evidence。

最新完整 batch 的可核對狀態是：`v11` 的 2 個 Slider failure、`v13` 的 dirty fail-closed、`v14` 的 P4 sequence failure、`v16` 的 P3→P4 stale preference failure 都保留；`v17` 修正後 P3→P4 2/2 PASS，`v18` P5 endpoint retry 5/5 PASS，`v19` 綁定目前 HEAD 且 19/19 machine/contract PASS、19/19 visual attestation PASS。`record-many` 先後以工具拒絕 unattended / 不完整 state union；目前最後一次拒絕具體指出 P1 缺少 `idle/loading/success/retry/error/partial-result` 的 exact union，其他 P2/P4/P6/P7/P10/P12/P13/P14 也仍有同類缺口。這裡的 PASS 仍明確限定為 pinned Simulator／UI World／exact XCTest／視覺 bundle 證據，不升格為 physical device 或 production release。

## 原報告意圖與目前差距

| Cluster | 報告真正要求 | 目前已完成 | 尚差 | 狀態 |
|---|---|---|---|---|
| Dictionary P1–P2 | 詞典不可用、結果／詞義／來源不完整；需重做資料狀態與 typed surface，不是加一個按鈕 | v19 P1/P2 current-head bundles machine／contract／visual PASS；canonical result、typed senses、provenance/materialization 均可重現 | P1/P2 selector-level 仍未覆蓋矩陣要求的全部 idle/loading/retry/error/partial、missing-example/materialize-error；仍是 simulator-only、單一 reviewer | current selector PASS／matrix pending |
| Reader Runtime P3–P7 | TOC 成功邊界、settings round-trip、P5 fixed-height/drag/scale、progress/loading/retry 狀態需同一 runtime 模型 | v17 P3→P4 sequence、v19 P3/P4/P5/P6/P7 current-head bundles 全部 machine／contract／visual PASS；P4 stale singleton 與 P5 endpoint seam 已修正 | P6/P7 的 repeated state labels、P4 change-highlight/reset、以及 P3–P7 完整 required/counterexample union 尚未收斂 | current selector PASS／matrix pending |
| Explore/Overview P8–P10 | loading/empty/retry/counterexample、calendar shared components、Overview 需整體重設資訊層次 | v19 P8/P9/P10 兩 selector 均 current-head machine／contract／visual PASS；P9 6 steps、P10 populated metrics 207/18/8、26/41 可重現 | P10 forecast-zero/counterexample 與其他語意 state 尚未完成 aggregate exact union | current selector PASS／matrix pending |
| Vocabulary/Review Card P11–P13 | P11 role/review/search/CTA 需有完整資料世界；P12/P13 需消除留白、資訊隱藏與 toolbar 失控 | v19 P11/P12/P13 current-head bundles machine／contract／visual PASS；P11 644 rows/facet/CTA、P13 natural front/scroll back 可重現 | P12/P13 實際 capture labels 與矩陣 required/counterexample 語意尚未完全對齊；P11 O(N) projection/AX scan 仍只完成靜態風險審查 | current selector PASS／matrix pending |
| Settings/Sync P14–P15 | sync/error/retry 動畫與 settings IA 要可觀察、可回復；不可用 optimistic UI 假裝成功 | v19 P14/P15 current-head bundles machine／contract／visual PASS；P14 session-scoped ledger、P15 main/long/reset 與 English reset boundary 均可重現 | P14 idle/syncing/terminal-success exact union 尚未留下；P15 selector-level 已完整但仍未通過全矩陣聚合；仍是 simulator-only / 單一 reviewer | current selector PASS／matrix pending |

## P1–P15 selector-level evidence（非完整矩陣 verdict）

「PASS」只代表該 selector 有契約有效、source HEAD 可追溯且完成視覺 attestation 的 bundle；它不代表該 requirement 的 required/counterexample state 已完整覆蓋。程式已提交但尚未取證者不升格為 PASS。下表的既有 bundle 是 selector-level 歷史／targeted 證據，不等於報告提交後的 final current-head verdict。

### Historical current-head v19

`final-head-batch-v19-summary.json` 綁定 source=`4c872d3e2c70abcf005cc0041671f0af9e7a7b3f`、clean tree、同一 Simulator、同一 `marketing_demo` SHA。19/19 selector executions 均 `exit=0`、machine contract valid；19/19 published bundles 均已用 `--all-steps` 完成視覺 attestation，包含 P3 success/invalid、P4/P5 sequence/preview、P10 第二 selector、P15 long/reset 三個 counterexample。這是目前最完整的 selector-level current-head 證據，但不是完整矩陣 verdict。

主要 bundle 根目錄：`build/snapshots/uitest-evidence/final-head-batch-v19-bundles/`；summary：`build/snapshots/uitest-evidence/final-head-batch-v19-summary.json`。每個 bundle 的 `review_manifest.json`、`review_state.json`、`ui-evidence-contract.json`、contact sheet、quick4、UIreview HTML、XCTest result 與影片均保留。

| ID | Selector | 程式／交接 | Evidence 狀態 |
|---|---|---|---|
| P1 | `DictionaryLookupFlowUITests/testDictionaryResultShowsCanonicalSensesProvenanceAndMaterialization` | `ac9d8d5cd` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-015145-40210-3471`；contract + contact sheet + visual attestation |
| P2 | `DictionaryLookupFlowUITests/testP2DictionarySensesUsesIndependentTypedSurfaceSelector` | `ac9d8d5cd` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-015252-43021-17083`；contract + contact sheet + visual attestation |
| P3 | `ReaderFlowUITests/testReaderTOCRequiredRealBookSelectionClosesOnlyAfterSuccess` | `cbcdc1c60` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-010206-42406-8652`，XCTest 1/1、contract pass、5 steps visual attested |
| P3 counterexample | `ReaderFlowUITests/testReaderTOCInvalidRealBookKeepsSheetOpenAndRetryable` | `cbcdc1c60` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-005911-21688-3165`，真實 invalid EPUB、sheet-open、error/retry、retry-after-failure 均通過 |
| P4 | `ReaderSettingsUITests/testProductionReaderSettingsRoundTripAfterReaderReopen` | `d5f62e7f8` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-024058-53481-18176`；4 steps、contract PASS、visual attestation PASS；驗證 2.1 round-trip 與 1.0 套用 |
| P5 | 同 P4 selector，獨立 requirement | `d5f62e7f8`；另以 `ReaderSettingsUITests/testReaderPreviewKeepsViewportAcrossDarkAndSepiaCounterexamples` 驗證 slider/preview | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-023749-45555-17880`；5 steps、2.1→1.0→2.5、dark/sepia counterexamples、contract PASS、visual attestation PASS；非重複 requirement |
| P6 | `ReaderFlowUITests/testReaderRuntimeProgressStatesArePreciselySelectableWithProvenance` | `c6ff48e0` hand-back | PASS；`evidence/P6/20260813-142032-69495` |
| P7 | `ReaderFlowUITests/testReaderRuntimeLoadingScenariosAreControllableAndRetryToSuccess` | `e6630961` hand-back | PASS；`evidence/P7/20260813-142940-99394` |
| P8 | `ExploreNavigationUITests/testExploreEvidenceMatrixCoversRequiredAndCounterexampleStates` | child bundle | PASS；contract valid，6 steps visual pass |
| P9 | `FixtureDatasetUITests/testReviewCalendarRequiredEvidenceUsesStableSelectors` | `8694fa4e8` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-044312-76504-30610`；6 steps、machine/contract PASS、contact/quick4/UIreview/video 檢查、`codex/pass` attestation；300 秒 XCTest allowance |
| P10 | `OverviewFlowUITests/testOverviewStatsRenderFromSeededReviewHistory` | `1f5359ec4` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-033236-72441-28187`；10 steps visual attested |
| P10 | `OverviewFlowUITests/testOverviewStatsRenderFromSeededReviewHistory` | `1f5359ec4` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-033236-72441-28187`；10 steps visual attested；populated metrics/calendar/forecast、re-entry、large-count counterexample |
| P11 | `VocabularyLibraryFlowUITests/testRichWorldProjectsRoleReviewSearchAndCTAConsistently` | parent `10cb1a0` | PASS；`evidence/P11/20260813-143617-16438`；首輪 rc=1 根因已確認並修正 |
| P12 | `ReviewCardLayoutEditorUITests/testToolbarEditorRelayoutsTheCardAndSharesOneProfileWithSettings` | child bundle | PASS；contract valid，3 steps visual pass |
| P13 | `ReviewCardLayoutEditorUITests/testGradingToolbarStaysOperableWithEveryFieldEnabled` | `ffbd15324` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-035646-39139-25148`；3 steps、natural front/scroll back、contract + visual attestation |
| P14 | `SettingsSyncLifecycleUITests/testSettingsSyncTerminalErrorRetriesToSuccess` | `8d4ada5ff` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-035046-25459-3678`；2 steps、session-scoped event ledger、contract + visual attestation |
| P15 | `SettingsFlowUITests/testSettingsFlowAppliesRealPreferenceChanges` | `45f3bddc5` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-045254-96406-13671`；18 steps、contract + visual attestation |
| P15 | `SettingsFlowUITests/testSettingsLongContentCounterexampleResolvesProductionSelectors` | `45f3bddc5` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-045641-3800-4728`；long identity/email wrapping、danger section、back navigation；contract + visual attestation |
| P15 | `SettingsFlowUITests/testSettingsResetCounterexampleShowsObservableBoundary` | `a12b53a7a` | PASS；clean fresh bundle `build/snapshots/uitest-evidence/20260814-060148-66357-4488`；English Settings presentation、3→failure boundary→0 cards、contract + visual attestation；video SHA `b1ab90d44c08a02af32f55ce46897a3fa2a2fcb90915c066921ff3c74e0262ab` |

## 歷史 batch 與完整矩陣判定（非 current verdict）

| Batch | Source HEAD | 執行結果 | 可宣稱範圍 |
|---|---|---|---|
| `final-head-batch-v11` | `ecf6c72ae` | 19 executions；17 machine/contract PASS；P4/P5 各一個 selector 在 iOS 26 Slider lower endpoint 失敗 | 歷史診斷；不能當 final |
| `reader-settings-endpoint-v12` | `6d00945e1` | P4/P5 focused 2/2 machine/contract PASS，兩 bundle 已完成具名 visual attestation | 只證明最新 endpoint fix；不能代替 P1–P15 |
| `final-head-batch-v13` | `6d00945e1` | 因報告在執行期間修改造成 source tree dirty，19-selector batch fail-closed 作廢 | 不作產品 verdict |
| `final-head-batch-v14` | `9e229239b` | 19 executions；18 machine/contract PASS；P4 在完整序列於 `ReaderSettingsUITests.swift:67` 失敗；其餘成功 bundles 已完成具名 visual attestation | batch failed；不能 record-many |
| `reader-settings-p4-v15` | `9e229239b` | P4 isolated 1/1 machine/contract PASS；4 steps 已完成具名 visual attestation | 證明可重現 focused PASS，但不能清除 v14 的 sequence-stability blocker |
| `p3-p4-sequence-v17` | `05e74c94b` | P3→P4 連續行程 2/2 machine/contract/visual PASS；證明 UI World overlay 後 live ReaderSettings 已同步 | 修正 stale singleton 根因；不能代替 P1–P15 矩陣 |
| `reader-settings-endpoint-v18` | `4c872d3e2` | P5 independent 5 steps machine/contract/visual PASS；2.1→1.0→2.5、dark/sepia viewport | 修正 iOS 26 endpoint timing seam；不能代替矩陣 |
| `final-head-batch-v19` | `4c872d3e2` | 19/19 machine/contract PASS；19/19 full-step visual attestation PASS；clean source/dataset/device/video provenance | selector-level final；`record-many` 仍因 exact state union 缺口拒絕寫入 |

目前 matrix 的 fail-closed 意義很重要：v19 不是失敗，而是成功地把「selector 可跑」與「requirement state 完整」分開。`record-many` 已實際拒絕 P1 的 missing/duplicate exact state coverage；其餘 P2/P4/P6/P7/P10/P12/P13/P14 也仍需補足或明確定義 state aliases／額外 capture。這些是目前報告與實作的真實差距，不用 PASS 字樣掩蓋，也不能拿舊 HEAD bundle 混入最新 HEAD。

## v16–v19 新增的順序穩定性根因

1. **P3→P4 stale persistence**：P3 在同一 process sequence 先透過 UI World overlay 寫入 Reader preferences；`ReaderSettings.shared` 已在 app 啟動時初始化，後續只更新 UserDefaults/iCloud KVS，SwiftUI live object 仍保留舊值，故 P4 開 settings 讀到 `1.5` 而非 fixture 的 `2.1`。這不是測試順序偶然性，也不是把 assertion 改寬即可接受的問題。
2. **修法**：`ReaderSettings` 改成可注入 defaults/cloud stores，新增 `reloadFromPersistence()` 與 loading guard，`UITestFixtureSeed.applyPreferencesFromWorld()` 在 overlay 完成後 reload live singleton；unit `ReaderSettingsFixtureTests` 2/2 PASS。v17 同一 P3→P4 sequence 2/2 PASS，P4 initial/changed/reopened 均顯示正確狀態。
3. **P5 第二個 seam**：preview 在 Form swipe 後使用 iOS 26 SwiftUI Slider 的 endpoint API，直接 `0` 偶爾回傳但 AX value 停在 `1.5`；coordinate drag 曾出現長時間無輸出，故不納入 fallback。`4c872d3e2` 改為有限候選 interior staging + bounded AX wait + endpoint exact wait，仍只走 semantic Slider API。v18 與 v19 P5 均以 5 steps PASS。

## P15 reset counterexample 最終狀態

English `reset_counterexample` 的資料 seed、live snapshot、projection 都是 reset 前 3 cards；失敗根因是 `SettingsSheetPage.assertIsPresented()` 以繁中 `完成` 做 cardinality 斷言，English UI 實際是 `Done`，測試在 account detail 之前中止。修正為 production-stable `settings.dismissButton` 後，v19 current-head reset bundle 視覺上確認 account detail、3 cards → injected failure boundary → 0 cards；不是把 0 當成空資料，也不是刪除 assertion。

## P1/P2 這一輪重新審查發現的根因與修正

1. `DictionaryLookupFlowUITests` 原本只注入 dictionary fixture，沒有注入 `.authSignedIn`；因此 notebook review flow 可能被 auth guard 擋住。`755f09453` 將 authentication、dictionary payload、review deck 綁成同一個 UI World 啟動契約。
2. `TodayReviewPage.addLinkButton` 與 projected link 的 Page Object 曾在等待前同步讀 `count`，把合法的 main-actor state transition 誤判成 selector 缺失。`7c35d2103`、`7dee6a6c8` 將 getter 改成純查詢，先 `waitUntilExists`，再做 cardinality／frame 驗證。
3. materialize 實際成功後，AX label 已顯示 `engraved`，但 `todayReview.card.back.field.graphLinks` 外層 identifier 吞掉了子 Button 的 `todayReview.card.link.fixture-dictionary-card`。`76c950dcb` 先修 add-link wrapper；`ac9d8d5cd` 再讓 graphLinks field 成為真正的 `.accessibilityElement(children: .contain)` container。這是 production accessibility tree 的結構問題，不是放寬測試。

`ac9d8d5cd` 的 P1/P2 bundle 已證明 materialize 後 graph link 真的出現在畫面、AX selector 唯一且尺寸為正；contact sheet 也確認深色介面中的 link hierarchy、對比與間距沒有因修 selector 而退化。

## Reader P4/P5 第二輪深度審查：不是把 1.2 改成通過

這一輪特別重看報告中的 P5 圖與現行 UI World，確認原報告要求的是「固定 viewport 下觀察極值與 theme counterexample」，不是把測試斷言改成某個容易通過的數字。

1. canonical `marketing_demo` 同時在 UserDefaults 與 iCloud KVS 注入 `reader_settings_lineHeight=2.1`；P5 若期待 `1.2`，測到的是 test／fixture drift，不是產品正確性。`d68d697f0` 將 baseline 重新綁回 `2.1`，並保留 `2.1→1.0→2.5` 的行為鏈。
2. `ReaderPage.webViewElement()` 與 settings state query 曾把 iOS 26 Readium/WebKit 的多層 AX projection 當成多個產品元素；`e5b2ad49d`、`9e165ef36` 將 query 限定在正確型別／代表節點，沒有放寬 selector cardinality。
3. P5 在 `1.0` 直接呼叫 `adjust(toNormalizedSliderPosition: 0)` 時，XCTest 可回傳但 Slider value 保持 `1.0`；上端也存在 `1.0` 已經在端點時不產生可觀察 AX transition 的 seam。實際產品 binding 可正常改值，因而排除 production Slider 根因。`6d00945e1` 將 Page Object 固化為 lower `0.05→0.0`、upper `0.95→1.0` staged adjustment，兩段都等待 AX value 變更再確認最終值；coordinate press/drag 實測會讓 XCTest 長時間無輸出，已保留為 inconclusive 診斷，不作 workflow fallback。
4. P4 round-trip 與 P5 preview/theme counterexamples 在同一 `marketing_demo` SHA、同一 pinned Simulator 上重新執行並完成 machine verdict、evidence contract、full contact sheet 檢視與具名 visual attestation。最新 v14 的 P5 bundle 為 `20260814-083748-25075-18345`；P4 v14 完整序列 bundle `20260814-081206-64062-6870` 在 line 67 失敗，只有 launch/settings-open；同一 HEAD 的 isolated P4 v15 bundle `20260814-083941-29354-30740` 4/4 PASS。這組對照揭露的是序列穩定性差距，不是沿用舊報告截圖，也不是可以只看 focused PASS 的理由。

## P11 首輪失敗的根因與修正

首輪 bundle `20260813-133155-99422` 的 contract 本身有效；唯一 assertion 是清除搜尋後要求 `row(p11-review-word-015).exists`。`visibleCount=644`、facet `14/503/127` 與搜尋投影均已通過。產品使用 `ScrollView + LazyVStack`，清除 query 會恢復完整 projection，但不保證指定 row 立即 materialize 在 viewport；失敗後的 accessibility teardown 才放大成 timeout。

修正 commit `790efe069` 保留 `visibleCount=644` 的完整 projection 判斷，改以「已 materialize 且不含前一個 query 的 row」驗證 query 清除，不修改 production UI。這是對驗收假設的最小根因修正，不是放寬產品行為。

## P9 第七輪重構收斂：calendar 不是單一 selector 問題

P9 的七輪 fresh run 保留了完整 failure chain，最後不是把 assertion 改寬，而是依 runtime 證據逐層修正：

1. required fixture 原先缺 `.authSignedIn`，Overview 被 login gate 擋住；後來又發現 Page Object 依賴已移除的 `overview.statsContent`，改成 production `overview` hierarchy + dynamic metrics contract。
2. `reviewCalendar.open` 先在 source 存在但 runtime AX 為 0；根因是 `calendar` 父 `VStack` 的 identifier shadowing 子 Button，production 加 `.accessibilityElement(children: .contain)` 後 selector 才唯一。
3. selector 唯一後仍不可點，因日曆 header 在 Overview ScrollView viewport 外；Page Object 改成只對 production `overview` scroll view 做 bounded up/down scroll，直到 exact selector `exists ∧ hittable`，不使用座標點擊。
4. 空日卡的父 identifier 曾傳播到 Image/Text 造成 3 個 `emptyDayDetail`；修正 containment。現行視覺仍是報告中的空狀態卡，0 計數以 1×1 semantic receipt 暴露，不新增可見數字。
5. SwiftUI AX materialize 期間 summary 可能先以 `Other` 出現而非 `StaticText`，Page Object 改 any-descendant + wait-before-cardinality；完整雙 launch/6 steps 的 XCTest allowance 固定 300 秒。

最終 P9 bundle `20260814-044312-76504-30610` 的 source=`8694fa4e8`、dataset SHA=`609f35f3…6abfced`、Simulator=`F068B3D8-9E0B-475B-85C3-97BC61748A8F`，machine/contract/visual 均 PASS；這是 targeted current evidence，仍不代替 final-head batch。

## 已確認的根因與尚未能宣稱的部分

- **P1/P2**：舊問題不是字典卡片少一個欄位，而是 lookup、typed sense、provenance、materialization 與 review graph projection 沒有共同狀態模型；UI World 現在注入 rich payload，驗收固定 idle/loading/success/error/retry、選定 sense、來源鏈與 materialize 後的 graph link。`ac9d8d5cd` 已完成 P1/P2 fresh machine／contract／visual PASS；其中 AX containment 修正的是 production view tree，不是測試繞過。
- **P3**：初輪 `run_ui_evidence` 在 build preflight 無法解析 `GoogleSignIn` 與 `Minizip`，因此沒有 execution；這份 failure bundle 保留為歷史診斷，不偷升格。後續 package product declarations、xctestrun target contract、cache rebuild 與 Reader AX 時序修正後，`cbcdc1c60` 的 success selector 在 pinned Simulator 真執行 1/1 並產出 contract-valid visual evidence；invalid EPUB selector 也確認 failure 只停在 TOC、保留 Retry，不誤報成功。
- **上一輪 Fresh integration Gate（run_id=`83f0d044c193-13364-201231652442125`）**：36/36 gates 已執行；該 run 的 `ios-build`、`ios-build-catalyst` 與 UI-test scopes 因當時 `GoogleSignIn`/`Minizip` package resolution 失敗而 BLOCK，完整 unit scope 是 infrastructure `inconclusive`（`keychain-unavailable-osstatus-25291`）。這是已修復前的歷史 gate，不能代表目前 P3；本次收尾仍需以 final HEAD 重新跑 fresh Gate，並把 keychain infrastructure inconclusive 與產品測試 verdict 分開記錄。
- **P6/P7**：P6 首輪把 production normalized progress ID 與測試 ID 混用，後續又把 transient restore-warning 當成穩定終態；P7 則錯誤要求 Readium preload web view 數量與全域內容計數。修正為 typed progress state + provenance、等待 stable runtime state；移除受合法 Readium preload 影響的虛假全域假設，保留 content/loading/retry/error 轉換驗收。P6 source `c6ff48e0`、P7 source `e6630961` 的 fresh bundles 已 PASS。
- **P11**：LazyVStack 的 viewport materialization 被誤當成 projection 不完整；修正驗收 oracle 後 `644` 筆 projection、facet union、搜尋與 CTA 均通過。靜態檢視仍看到 O(N) projection/sort 與 AX teardown 掃描，這是待 profiling 的風險，不足以宣稱 production performance 已證明。
- **P15**：真正根因是 reset 偏好時 `setLanguage(.system)` 觸發 app root `.id(selection)` 重建，先摧毀 Settings navigation，再讓 locale 變更污染同一個 reset boundary 的 AX 文案。修正分三層：`rootRefreshID` 將一般語言刷新與 root identity 分離；Settings active 時把 reset 的 locale mutation 存成 `deferredSelection`，只持久化 default、保留當前 rendered locale；Settings 離場才一次 apply selection + root refresh。最後將測試 oracle 從 `isHittable` 改成語意正確的 `isEnabled == false`。
- **P15 reset counterexample 的第二層根因**：UI World `reset_counterexample` 明確選 English，但 `SettingsSheetPage.assertIsPresented()` 仍以繁中 toolbar label `完成` 做 cardinality 斷言，導致測試在 account detail 之前中止，失敗截圖只剩 Settings home；KG_DIAG 同時證實 fixture seed、live snapshot 與 projection 都是 3 cards，排除了「reset 資料為 0」的錯誤假說。`cb1095e0d` 將入口改為唯一 production ID `settings.dismissButton` 並要求 visible+hittable；`a12b53a7a` 移除診斷碼。clean rerun 已驗證 English account detail 的 3 cards → injected failure boundary → 0 cards，非放寬 assertion。
- **整合後的 fixture／service 根因**：Xcode 在部分 build context 會把 `#filePath` 解析成 `<checkout>/ios/ios/...`，造成 asset 找不到；`FixtureDatasetStore.repositoryRootURL` 已改為以 `ios/BooksAndVocab` 與 `ops/fixtures/assets` marker 向上尋根。另將 absolute／traversal／symlink escape 驗證固定在 decode/materialization 邊界；KGService 的 explicit DEBUG fixture injection 現在優先於不一定能跨 coordinator child task 繼承的 ambient TaskLocal。這批修正以 `70edb37fe` 提交，11 個 affected unit selectors 全綠。

## 可重跑的穩定工作流

```bash
# 1. 驗證 5 cluster / 15 requirement / 16 selector
UV_CACHE_DIR=/private/tmp/kg-uv-cache uv run --python 3.13 \
  python ops/ios_ui_review_clusters.py validate \
  ops/fixtures/ios_ui_review_clusters.json --root .

# 2. 一次 build、依精確 selector 執行多個 UI flow（final current-head batch）
UV_CACHE_DIR=/private/tmp/kg-uv-cache \
  KG_IOS_TEST_MAX_EXECUTION_TIME_ALLOWANCE=420 \
  uv run --python 3.13 python ops/ios_ui_run_many.py run \
  --root . \
  --helper .claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --methods-file <exact-runs.json> \
  --device <pinned-simulator-udid> \
  --output-dir build/snapshots/uitest-evidence/final-head-batch-v43 \
  --publish-root build/snapshots/uitest-evidence/final-head-batch-v43-bundles \
  --summary-out build/snapshots/uitest-evidence/final-head-batch-v43-summary.json

# 3. 每個 bundle 必須先完成主流程 verdict + evidence contract，
#    再逐張檢視 contact sheet / screenshot，最後才寫 visual attestation。
uv run --python 3.13 python ops/uitest_review_attest.py \
  <bundle>/artifacts/ui-review \
  --reviewer <named-reviewer> --status pass --all-steps \
  --visual-check '<check-1>' --visual-check '<check-2>'

# 4. 每個 requirement 可由多個 exact selector bundle 組成 aggregate，
#    但每個 bundle 都必須獨立通過 machine/source/dataset/device/visual gate；
#    record-many 會對 state label 做 exact union，缺任一 required/counterexample
#    或重複／共用 asset 都拒絕寫入。未達條件時不要執行 record-many 來製造假完成。
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
- `ops/ios_ui_review_matrix.py record-many`：契約與視覺 attestation 完成後的 atomic bulk recording；支援同一 requirement 的多 bundle exact state union，拒絕缺漏、重複與共用 asset。
- `.claude/skills/ios-simulator-verification/SKILL.md`：已固化 simulator/UI-test/evidence contract、visual attestation、cluster batch、長命令不閒置與 fail-closed handoff。
- `.claude/skills/ios-simulator-verification/SKILL.md`：另固化 iOS 26 SwiftUI Slider 兩端 endpoint 的有限候選 lower `0.05/0.15/0.25→0.0`、upper `0.95/0.85/0.75→1.0` staged action、AX value 驗證與 coordinate-drag inconclusive 分類。
- `ops/ios_ui_run_many.py` + `ops/ios_ui_review_matrix.py`：將「一次 selector PASS」與「完整 requirement state coverage」拆開；這個差異正是本輪抓到的主要假綠來源。
- `docs/sop/ui_flow_evidence.md`、`docs/reference/tech_index.md`、`docs/registry.yml`：已同步控制面入口；`docs_lint --registry` PASS（45 documents）。

## 歷史驗證與偏離（final batch 以前）

- 已通過：cluster validator `valid=true clusterCount=5 requirementCount=15 selectorCount=16`；run-many/matrix tests `27 passed`；最新 affected unit regression `11 passed / 0 failed`；`./ops/test_ios_ops.sh` `362 passed / 0 failed`；`bash -n ops/ios_test.sh`；`bash .claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh`；`docs_lint --registry`（45 documents）；v19 19/19 current-head Simulator executions machine／contract PASS；v19 19/19 bundle full-step visual attestation PASS；P3→P4 v17 sequence 2/2 PASS；P5 v18 independent 5 steps PASS；P15 English reset v19 PASS。`final-head-batch-v11` 已明確記錄 17/19 PASS + 2 個 Slider seam failure；`final-head-batch-v13` 因報告中途修改而 fail-closed 作廢；`final-head-batch-v14` 為 18/19 PASS、P4 sequence failure；`p3-p4-sequence-v16` 捕捉到 stale live singleton；`record-many` 仍依 exact state union 正確拒絕，尚未寫入 final matrix。
- 平台：本輪是 iOS Simulator 驗證，不是 physical device；報告中的「實機操作」在此以 pinned simulator + exact XCTest + stable visual artifact 實現，不能誤報成真機 PASS。
- 視覺審查：目前 attestation reviewer 是 `codex`；沒有第二位獨立視覺 reviewer，因此這是已揭露的 assurance limitation，不升格為雙人審查。
- P3 的歷史 dependency/cache BLOCK 已解除；目前未取得 delivery-loop 授權，因此沒有 cutover local `main`、同步 `origin/main` 或碰 `origin/prod`。完整 unit scope若再次出現 keychain OSStatus 25291，應標為 infrastructure inconclusive，不得改寫已成功的 UI／product verdict。P11 的 static performance risk 同樣不是已證明的 performance PASS；各 cluster 的視覺 attestation 仍由單一主線 reviewer 完成，沒有第二位獨立 reviewer。v17/v18 已清除 P4 sequence 與 Slider endpoint blocker，但 P1–P15 required/counterexample exact union 仍未完成；selector PASS 不能代替未覆蓋狀態。

## 工作樹邊界（final convergence 以前的歷史 receipt）

本輪 child 已完成 commit + registry hand-back，並已 fan-in 至目前 integration branch `feat/ios-ui-review-report-complete-20260813`；本次 final freeze HEAD 為 `088e9c1863cf0b83285b74f7564b2450467f859f`，已包含 P10 forecast AX containment 修正與 v42 focused evidence。尚未取得明示 delivery-loop 授權，因此不觸碰 local `main`、`origin/main` 或 `origin/prod`。歷史 failure bundle、v13 dirty fail-closed、v14/v16 sequence failure、keychain infrastructure inconclusive、P11 perf risk 與 matrix state gaps 都會保留，不用 partial PASS 蓋掉它們。
