# iOS 2.0.1 (Build 7) UI review：重構收斂狀態

日期：2026-08-14（重驗證更新）
來源：`IOS2.0.1+7-UI-review-report.pdf`、`p1.PNG`–`p15.PNG`、目前工作樹與 simulator evidence bundle  
工作樹：`feat/ios-ui-review-report-complete-20260813`；產品 code baseline：`6d00945e1`；本報告更新尚未提交時曾使 batch `v13` 變 dirty，該 batch 已 fail-closed 作廢；提交本報告後會以乾淨 HEAD 重跑 `v14`。

## 結論

原報告要求的是「重新思考並重構」而非局部修飾。P1–P15 表面上是 15 張圖，實際上是 5 個跨頁系統問題：資料／狀態模型、元件共用、互動時序、長內容／極端狀態與 visual hierarchy 必須一起收斂。這不是一次 UI polish；必須以 UI World 注入、狀態矩陣、Simulator/UI-test、證據契約與視覺迭代形成閉環。只修單頁 padding、顏色或單一 selector，無法達到報告標準。

本輪已把報告轉成可執行控制面：5 clusters、15 requirements、16 個精確 XCTest selectors；採 build-once/run-many、每 selector 一個 stable evidence bundle、單一 batch source HEAD、契約驗證與視覺 attestation 分離。控制面驗證：`valid=true clusterCount=5 requirementCount=15 selectorCount=16`。目前最重要的差距已被實際暴露並修掉：P1/P2 先後發現 auth fixture 缺失、Page Object 過早做 cardinality 斷言、以及 graphLinks wrapper 吞掉子連結 AX identifier；P1/P2 targeted bundle 已 machine／contract／視覺 PASS，但仍不能冒充完整狀態矩陣。P3 的 package graph／cache BLOCK 也已解除，歷史失敗仍保留作診斷。

Reader P4/P5 的最新根因收斂是 iOS 26 XCTest Slider lower-bound seam：上一批 `v11` 在同一個 P4/P5 selector 於 `0→1` 端點失敗，並非產品 binding 失效；`6d00945e1` 將兩端都固化為 interior staging（lower `0.05→0.0`、upper `0.95→1.0`）並等待 AX value 變更。`v12` 在該最新 HEAD 重新跑 P4/P5，2/2 machine／contract／visual PASS。P9 仍保留從 auth、stale selector、父容器 AX shadowing、viewport readiness、空狀態 containment 到 AX materialization race 的完整根因鏈；P10 populated metrics/calendar/forecast 與 P15 English reset 也完成 targeted clean evidence。

最新完整 batch 的可核對狀態是：`v11` 綁定 `ecf6c72ae`、19 executions 中 17 machine/contract PASS，2 個失敗都集中在上述 Slider lower-bound seam；`v13` 曾綁定 `6d00945e1` 啟動，但因本報告在執行期間落地造成 source tree dirty，整批被 fail-closed 作廢，不代表產品失敗或成功。報告提交後的 `v14` 才是乾淨 HEAD batch；必須等 summary、逐 bundle visual attestation 與 aggregate state coverage 完成後才可作 final 判定。即使 `v14` 全部 selector 通過，仍需另過 P1–P15 required/counterexample state union；目前 matrix 已正確擋下「有 selector PASS 就等於全報告完成」的假綠。這裡的 PASS 仍明確限定為 Simulator／UI World／exact XCTest 證據，不升格為 physical device 或 production release。

## 原報告意圖與目前差距

| Cluster | 報告真正要求 | 目前已完成 | 尚差 | 狀態 |
|---|---|---|---|---|
| Dictionary P1–P2 | 詞典不可用、結果／詞義／來源不完整；需重做資料狀態與 typed surface，不是加一個按鈕 | explicit lookup state、canonical senses、provenance/materialization fixture、穩定 selector 已落地；targeted bundles machine／contract／visual PASS | selector-level 證據尚未覆蓋 idle/loading/error/retry 與所有 counterexample state；仍是 simulator-only、單一 reviewer | targeted PASS／matrix pending |
| Reader Runtime P3–P7 | TOC 成功邊界、settings round-trip、P5 fixed-height/drag/scale、progress/loading/retry 狀態需同一 runtime 模型 | P3 success + invalid-destination counterexample、P4/P5、P6/P7 均有 contract-valid evidence；P4/P5 最新 HEAD focused `v12` 2/2 PASS | `v11` 暴露 Slider lower endpoint；P3/P4/P5/P6/P7 的 full state union 尚未收斂，`v13` 正在重跑 | focused/targeted PASS／matrix pending |
| Explore/Overview P8–P10 | loading/empty/retry/counterexample、calendar shared components、Overview 需整體重設資訊層次 | P8 已有 evidence；P9 已在 `8694fa4e8` 完成 6 steps；P10 primary 與 populated metrics/calendar/forecast 第二 selector 均 targeted PASS | P8/P9/P10 需綁定 `6d00945e1`，且 aggregate 尚缺 Overview/forecast-zero 等必要 state 的 exact union | targeted PASS／matrix pending |
| Vocabulary/Review Card P11–P13 | P11 role/review/search/CTA 需有完整資料世界；P12/P13 需消除留白、資訊隱藏與 toolbar 失控 | P11 rich world、facet union、CTA、dynamic type、counterexample targeted PASS；P12/P13 有 contract-valid targeted bundles | P11 的 O(N) projection/AX scan 只完成靜態風險審查；P12/P13 的 state labels 尚未與 matrix required/counterexample exact union 完成對齊 | targeted PASS／matrix pending |
| Settings/Sync P14–P15 | sync/error/retry 動畫與 settings IA 要可觀察、可回復；不可用 optimistic UI 假裝成功 | P14 已以 session-scoped transport ledger 完成 fresh evidence；P15 main/long/reset 三個 selector 均已 targeted PASS，且 reset 以 English locale 驗證 stable dismiss ID、before/failed/succeeded boundary | P14/P15 需綁定最新 HEAD；P14 尚缺 idle/syncing/terminal-success 的完整 aggregate union；仍是 simulator-only / 單一 reviewer | targeted PASS／matrix pending |

## P1–P15 selector-level evidence（非完整矩陣 verdict）

「PASS」只代表該 selector 有契約有效、source HEAD 可追溯且完成視覺 attestation 的 bundle；它不代表該 requirement 的 required/counterexample state 已完整覆蓋。程式已提交但尚未取證者不升格為 PASS。下表的既有 bundle 是 selector-level 歷史／targeted 證據，不等於報告提交後的 final current-head verdict。

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
| P10 | `OverviewFlowUITests/testOverviewStatsSelectorsExposePopulatedMetricsCalendarAndForecast` | `45f3bddc5` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-045144-93420-18405`；Overview metrics 207/18/8、26/41、calendar/forecast、graph retry counterexample；contract + visual attestation |
| P11 | `VocabularyLibraryFlowUITests/testRichWorldProjectsRoleReviewSearchAndCTAConsistently` | parent `10cb1a0` | PASS；`evidence/P11/20260813-143617-16438`；首輪 rc=1 根因已確認並修正 |
| P12 | `ReviewCardLayoutEditorUITests/testToolbarEditorRelayoutsTheCardAndSharesOneProfileWithSettings` | child bundle | PASS；contract valid，3 steps visual pass |
| P13 | `ReviewCardLayoutEditorUITests/testGradingToolbarStaysOperableWithEveryFieldEnabled` | `ffbd15324` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-035646-39139-25148`；3 steps、natural front/scroll back、contract + visual attestation |
| P14 | `SettingsSyncLifecycleUITests/testSettingsSyncTerminalErrorRetriesToSuccess` | `8d4ada5ff` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-035046-25459-3678`；2 steps、session-scoped event ledger、contract + visual attestation |
| P15 | `SettingsFlowUITests/testSettingsFlowAppliesRealPreferenceChanges` | `45f3bddc5` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-045254-96406-13671`；18 steps、contract + visual attestation |
| P15 | `SettingsFlowUITests/testSettingsLongContentCounterexampleResolvesProductionSelectors` | `45f3bddc5` | PASS；fresh bundle `build/snapshots/uitest-evidence/20260814-045641-3800-4728`；long identity/email wrapping、danger section、back navigation；contract + visual attestation |
| P15 | `SettingsFlowUITests/testSettingsResetCounterexampleShowsObservableBoundary` | `a12b53a7a` | PASS；clean fresh bundle `build/snapshots/uitest-evidence/20260814-060148-66357-4488`；English Settings presentation、3→failure boundary→0 cards、contract + visual attestation；video SHA `b1ab90d44c08a02af32f55ce46897a3fa2a2fcb90915c066921ff3c74e0262ab` |

## 最新 batch 與完整矩陣判定

| Batch | Source HEAD | 執行結果 | 可宣稱範圍 |
|---|---|---|---|
| `final-head-batch-v11` | `ecf6c72ae` | 19 executions；17 machine/contract PASS；P4/P5 各一個 selector 在 iOS 26 Slider lower endpoint 失敗 | 歷史診斷；不能當 final |
| `reader-settings-endpoint-v12` | `6d00945e1` | P4/P5 focused 2/2 machine/contract PASS，兩 bundle 已完成具名 visual attestation | 只證明最新 endpoint fix；不能代替 P1–P15 |
| `final-head-batch-v13` | `6d00945e1` | 因報告在執行期間修改造成 source tree dirty，19-selector batch fail-closed 作廢 | 不作產品 verdict |
| `final-head-batch-v14` | 報告提交後乾淨 HEAD | 將重跑完整 19-selector batch | 未完成前不宣稱；即使 19/19 PASS，仍須通過 aggregate state union |

目前 matrix 的 fail-closed 意義很重要：P1/P2 的 targeted selector 已能展示 canonical result/materialization，但尚未留下 idle/loading/error/retry、missing-example 等全部要求資產；P4/P5 的 focused bundle 已證明端點與 theme/preview 視覺，但 P4 的 change-theme/change-highlight/reset 與 P5 的 exact counterexample labels 仍需 aggregate 對齊；P6/P7/P10/P14 亦有同類「selector 有畫面、狀態矩陣尚未完備」差距。P12/P13 則主要是實際 step label 與矩陣語意仍未完成明確 aliases／額外 capture。這些是目前報告與實作的真實差距，不用 PASS 字樣掩蓋。

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
4. P4 round-trip 與 P5 preview/theme counterexamples 在最新 `6d00945e1`、同一 `marketing_demo` SHA、同一 pinned Simulator 上重新執行並完成 machine verdict、evidence contract、full contact sheet 檢視與具名 visual attestation。v12 的 P4 bundle 為 `20260814-080041-36647-20382`，P5 bundle 為 `20260814-080210-40342-2773`。這才是目前 Reader endpoint fix 的證據，不是沿用舊報告截圖；但它仍只覆蓋 P4/P5 focused selectors。

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
  --output-dir build/snapshots/uitest-evidence/final-head-batch-v14 \
  --publish-root build/snapshots/uitest-evidence/final-head-batch-v14-bundles \
  --summary-out build/snapshots/uitest-evidence/final-head-batch-v14-summary.json

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
- `.claude/skills/ios-simulator-verification/SKILL.md`：另固化 iOS 26 SwiftUI Slider 兩端 endpoint 的 lower `0.05→0.0`、upper `0.95→1.0` staged action、AX value 驗證與 coordinate-drag inconclusive 分類。
- `ops/ios_ui_run_many.py` + `ops/ios_ui_review_matrix.py`：將「一次 selector PASS」與「完整 requirement state coverage」拆開；這個差異正是本輪抓到的主要假綠來源。
- `docs/sop/ui_flow_evidence.md`、`docs/reference/tech_index.md`、`docs/registry.yml`：已同步控制面入口；`docs_lint --registry` PASS（45 documents）。

## 驗證與偏離

- 已通過：cluster validator `valid=true clusterCount=5 requirementCount=15 selectorCount=16`；run-many/matrix tests `27 passed`；最新 affected unit regression `11 passed / 0 failed`；`./ops/test_ios_ops.sh` `362 passed / 0 failed`；`bash -n ops/ios_test.sh`；`bash .claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh`；`docs_lint --registry`（45 documents）；P1/P2 source `ac9d8d5cd` targeted Simulator evidence（machine PASS、contract PASS、contact sheet 視覺檢查、reviewer=`codex` attestation）；P3 success 與 invalid-destination counterexample 的既有 fresh evidence均 machine PASS、video hash 綁定、full/quick4/UIreview/video 完成視覺 attestation；P4/P5 source `6d00945e1` focused v12（P4 4 steps、P5 5 steps、machine／contract／visual PASS）；P9 source `8694fa4e8` targeted Simulator evidence（6 steps、machine／contract／visual PASS、`codex` attestation）；P10 second selector source `45f3bddc5` targeted PASS；P15 clean reset source `a12b53a7a` machine／contract／visual PASS；skill/SOP helper regression PASS。`final-head-batch-v11` 已明確記錄 17/19 PASS + 2 個 Slider seam failure；`final-head-batch-v13` 因報告中途修改而 fail-closed 作廢；提交後再以乾淨 HEAD 執行 `final-head-batch-v14`，須讀 summary、逐 bundle attestation 與 aggregate state coverage，未完成前不寫入 final matrix。
- 平台：本輪是 iOS Simulator 驗證，不是 physical device；報告中的「實機操作」在此以 pinned simulator + exact XCTest + stable visual artifact 實現，不能誤報成真機 PASS。
- 視覺審查：目前 attestation reviewer 是 `codex`；沒有第二位獨立視覺 reviewer，因此這是已揭露的 assurance limitation，不升格為雙人審查。
- P3 的歷史 dependency/cache BLOCK 已解除；目前仍需由 final HEAD fresh Gate 確認整合層結果。完整 unit scope若再次出現 keychain OSStatus 25291，應標為 infrastructure inconclusive，不得改寫已成功的 UI／product verdict。P11 的 static performance risk 同樣不是已證明的 performance PASS；各 cluster 的視覺 attestation 仍由單一主線 reviewer 完成，沒有第二位獨立 reviewer。更重要的是，`v14` 即使全 selector 綠，也必須再確認 P1–P15 的 required/counterexample exact union；未覆蓋的狀態是待辦，不是可以用 selector PASS 代換的完成。

## 工作樹邊界

本輪 child 已完成 commit + registry hand-back，並已 fan-in 至目前 integration branch `feat/ios-ui-review-report-complete-20260813`；P1/P2 已在 `ac9d8d5cd`、P4/P5 最新 focused evidence 已在 `6d00945e1`、P9 已在 `8694fa4e8` 完成 targeted Simulator evidence。本狀態報告提交後仍須完成乾淨 HEAD 的 `final-head-batch-v14`、fresh Gate、逐 bundle visual attestation 與 aggregate state union；只有取得明示 delivery-loop 授權後，才由 worktree-flow 做 cutover local `main`、同步 `origin/main`、清理 scoped worktree/branch；目前不觸碰 local `main`、`origin/main` 或 `origin/prod`。歷史 failure bundle、v13 dirty fail-closed、keychain infrastructure inconclusive、P11 perf risk 與 matrix state gaps 都會保留，不用 partial PASS 蓋掉它們。
