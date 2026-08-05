<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/BooksAndVocabUITests/
  - ios/BooksAndVocab/Support/
  - ops/
verified_against: 30df7f5f1
-->
# UI Flow Evidence Playbook — 真播放級 UITest 契約

每條重要 UI flow 都必須能回答：**現在在哪個畫面、為什麼到這裡、是否真的觸發核心行為、是否有 log 證據**。「只跑過 test」不是 UI 結論；完成標準必含視覺證據。Podcast 是活樣板（`PodcastPlaybackPerfUITests.swift`），所有新 flow 照抄此模型。

## 六件套（每 flow 必交付，缺一即未完成）

| # | 件 | 樣板 | 規則 |
|---|---|------|------|
| 1 | **Fixture provider** | `ios/BooksAndVocab/Support/UITestFixtureSeed+Podcast.swift` | 真資料（如 `lab/` 真音訊/字幕），**禁 mock 假資料**。新 flow = 新增 `UITestFixtureSeed+<Domain>.swift` + 在 `UITestFixtureSeed.swift` router switch **append 一個 case**（勿動他人 case）。未登入會擋路的 flow 用 isolated auth session fixture（見 `launchIsolatedApp(fixtures:)`）。 |
| 2 | **Page Object** | `ios/BooksAndVocabUITests/Pages/PodcastPage.swift` | 每 flow 一檔放 `Pages/`；selector 走 accessibility identifier（必要時在 production view 補 identifier，如 `PodcastControlsView` 的 `elapsedTime`/`seekBar`）。 |
| 3 | **Step screenshots** | `UITestDiagnostics.step()/captureStep()` | 每個語意步驟一張 `NN-name` 截圖；失敗路徑也截（`no-series-card`、`unexpected-login-sheet` 式防呆步）。 |
| 4 | **真行為斷言** | `elapsedTime` 真實前進、control 切 pause | 斷言核心行為**發生**（狀態/數值變化），不是「按了按鈕」。守門斷言要能戳破假測試：fixture 該已登入卻見 login gate = `XCTFail`，不是 skip。 |
| 5 | **KG_PERF log marks** | `ios/BooksAndVocab/Services/PerfLog.swift` | 核心行為打低頻 domain mark（如 `play.started`/`pause`/`seek`）。新常數 **append** 到 PerfLog，勿改既有 mark 名。驗證：`./ops/ios_ops.sh logs --simulator --device <udid> --debug --since 5m --predicate 'process == "BooksAndVocab" AND eventMessage CONTAINS "KG_PERF"'`。 |
| 6 | **視覺證據** | `test --json` 的 `uiVisualReview` | UI scope 自動產 full `contact_sheet.png` + `quick4_contact_sheet.png` + `review_manifest.json`（schema `kg.visual-review.sheet.v1`）+ standalone run `UIreview.html`，並同步更新常駐 `build/snapshots/uitest-runs/UIreview.html` workspace 導覽頁。沒有任何 run 時，workspace 仍會掃 `ios/BooksAndVocabUITests/*UITests.swift` 顯示 flow / test methods / run command，狀態為 `never-run`。收尾回報**必貼** quick4 / full sheet 或直接貼 `uiVisualReview.reviewHtml`，並親眼 Read 過（light/dark 都要看時用 `catalog_contact_sheet.py --appearance both`）。 |

## 執行契約

```bash
./ops/ios_ops.sh test --ui --file <Flow>UITests.swift --lease --json   # 一律 --lease（pool 預設 3 台，KG_IOS_SIM_POOL_SIZE 可調）
```

- JSON verdict 讀 `uiVisualReview{screenshotDir,contactSheet,quick4Sheet,visualReviewManifest,video,reviewRoot,reviewHtml}`；`null` = 沒有視覺證據 = 不算完成。`video` = 全程錄影（UI scope + 可解析 UDID 時自動錄，run 結束歸檔到 `build/snapshots/uitest-videos/`，verdict 指歸檔路徑）。`reviewHtml` = 本次 run 專屬 `build/snapshots/uitest-runs/<run>/UIreview.html`，直接把狀態、`lastRunAt`、step screenshots、contact sheets、video、log 與 manifest 收在同一頁；即使 0 screenshot 也會顯示 run metadata 與 artifact links。畫面行為爭議時先開它看整段流程，再抽幀看 tap 當下。每次 UI run 也會更新 workspace-level `build/snapshots/uitest-runs/index.json`（schema `kg.ios.uitest-review-workspace.v1`）與 `build/snapshots/uitest-runs/UIreview.html`，依 `flowId × variantId` 只保留最新一次 run、`lastRunAt`、log/video/run-page 連結；沒跑過的 flow 由 `uitest_review_workspace.py` 以 `never-run` pending card 呈現。`./start.sh` 會刷新並開這個 UITest workspace；catalog gallery 只能用 `./start.sh --catalog` 明確開啟，禁止 silent fallback。`flowId` 來自 `--file`/grep/scope，`variantId` 來自 dataset 或 launch profile。頂層 `device` = 本次 run 的 sim UDID（對 xcresult / log show 取證）。
- App Review journey 只能由 `app_review_evidence.py journey-run` 啟動：它固定委派 `ios_ops.sh test --ui --configuration Release`，並要求 pinned dataset/fixed clock/locale/timezone/appearance。`ios_test.sh` 自己把 producer identity、configuration、build/source/dataset 與 execution provenance 寫入 verdict `options`；consumer 不接受 caller 另塞的 `releaseEvidence`。Release 與 Debug 的 build-for-testing cache key 分離。
- Live demo access 只能由 `app_review_evidence.py demo-run --live-mirror-bundle <dir>` 啟動：destination 必須是 physical `platform=iOS,id=...`，底層 products 走 `Release-iphoneos`，不注入 UI World；producer 從 hash-closed ASC live mirror 的 normalized reviewer account 派生預期 SHA-256。`ios_test.sh` 先 sanitize/scan 所有 xctestrun configuration/target 的保留 live/fixture keys，再只對唯一 `BlueprintName=BooksAndVocabUITests` target 注入 live marker 與 account SHA（零個或多個匹配都 fail-closed）；host process 同時 unset 這些 keys，其他 test target 不得收到 live env。非-live run 若殘留或偽造 `KG_LIVE_DEMO_*` 會被拒絕。
- 固定測試 `LiveDemoAccessUITests.testLiveDemoAccountHasProEntitlement` 會拒絕 Debug、simulator、缺 marker/hash、fixture args/env、backend override、錯誤／缺失 account 與 Free entitlement；通過條件是 Settings 暴露的 account identity SHA 等於 live mirror 且 live backend 顯示 Pro，之後 `ios_test.sh` 才產生綁同一 SHA 的 `demoEvidence`。這份機器證據不宣稱 fresh credential SSO；重新登入與 credential 可用性由 root-bound human attestation 證明。caller 自填 nested JSON 不能成為 live-demo 證據。
- 同一個 flow 要補多個狀態/資料 variants 時，用 `./ops/uitest_flow_matrix.py --file <Flow>UITests.swift --profile ui-smoke --profile standard --dataset marketing_demo --lease --json`。它會展開 profile × dataset，多次呼叫 `ios_ops.sh test --ui` 且 keep-going；底層 `variantId` 會保留組合軸，例如 `dataset:marketing_demo+profile:standard`，因此新 run 不會覆蓋同 flow 的另一個狀態/資料 entry。
- 別 `cmd | tail` 後讀 `$?`；讀 verdict file 或 JSON。
- 測試檔放 `ios/BooksAndVocabUITests/`（pbxproj 是 file-system-synchronized group，加檔不碰 pbxproj）。

## 熱點所有權（多 agent 並行時）

| 檔案 | 規則 |
|------|------|
| `UITestFixtureSeed.swift`（router switch） | 只 append 自己 domain 的 case；衝突由收斂層解 |
| `PerfLog.swift`（mark 常數） | 只 append 自己 flow 的 mark |
| `BooksAndVocab.xcodeproj/project.pbxproj` | synchronized groups，正常加檔**零接觸**；若必須動（新 target 等）停下交收斂層 |
| `Pages/`、`UITestFixtureSeed+<Domain>.swift`、`<Flow>UITests.swift` | 每 flow 獨立檔，自由發揮 |

## 已知 seam（踩過的坑，新坑回寫此表）

- podcast player 用 `catalogReadyPreview` 式 ready 狀態避開 loading spinner；word-level SRT 避免 follow-underline overshoot；靜態 snapshot 不 auto-scroll，current 句須首屏可見。
- 未登入不能播 → fixture 層解（isolated auth session + playable preview seed），不是測試裡點登入。
- `ios_test --file` 多檔語法有 footgun（見 notebook-binding 修復），單檔最穩。
- UI smoke 預設 `--ui-launch-profile ui-smoke`；要完整 startup baseline 明示 `standard`。
- 全螢幕 podcast player **蓋住 tab bar**：從 player 進入其他 flow 前必須先 back out（見 `AuthFlowUITests` 的 `signedin-player-back` 步驟），否則 tab 點擊 silently 失敗。
- **`launchIsolatedApp` 預設網路封閉**（hermetic）：自動注入不可達 `KG_UI_TEST_SERVER_URL`，否則 catalog sync 會打真生產 server 把 seeded series reconcile-tombstone 掉（Auth flow 紅燈根因）、假 token 的 401 會 wipe local data。真的需要 server 的測試自帶該 env var 覆蓋。
- Pro gate UITest 走 entitlement-only fixture：`.entitlementsProAccess` 只由 App root 用 `UITestSubscriptionManager` 消費，`UITestFixtureSeed` router 對 `entitlements` domain 必須 no-op，避免誤導 warning。若測 gated episode 的正向 player path，fixture 裡被 Pro 解鎖的 episode 必須有真 `localAudioPath`/subtitle；否則測到的是 player audio-error，不是 entitlement gate。
- Podcast access matrix 的 SoT 是 `PodcastAccessScenario`：`guest = [.authTieredCatalog]`、`free = [.authTieredCatalog, .authSignedIn]`、`pro = [.authTieredCatalog, .authSignedIn, .entitlementsProAccess]`。不要在新測試手刻 fixture 組合；fixture 組合只選狀態路徑，資料形狀、登入 token、Pro entitlement 值與 file-backed 音訊/字幕/text asset 都由 `kg.fixture.dataset.v2` / `FixtureDatasetStore.require*Seed` / `requireInstalledAssetURL` 管。guest 的正確期望是 LoginSheet / gate，不是播放；free 播 preview ep1；pro 播 gated ep2/full。
- **Subagent 等待紀律**：把 build/test 丟 `run_in_background` 後結束 turn = 永遠收不到完成通知（三個 fan-out agent 全踩過）。長命令一律前景跑（timeout 拉滿）或前景 `until [[ -f <verdict> ]]; do sleep 5; done` 等；工作未完不准結束 turn。
- **`.plain` Button 中段透明死區 = 真陽性**：`buttonStyle(.plain)` 的 hit-test 會穿透透明像素，row 內 `Spacer()` 空白區點了沒反應；XCUITest `tap()` 永遠打 AX activation point（row 正中），剛好踩死區 → 決定性紅燈（Settings flow 抓到的 production bug）。修法 = Button label 加 `.contentShape(Rectangle())`，不是改測試去點文字。鑑別流程：AX frame + activation point（Session log）疊到截圖上驗座標 → 座標正確仍零反應 → 手動點同位置重現 → 死區即 app bug。此 bug class 已由 `ops/plain_deadzone_lint.sh` 守門（baseline 為空，新增即 regress）；遇疑似死區先跑 `--report`。
- 登入閘門後的 UI（如詞庫搜尋框）→ fixture 注入 signed-in session，且 `KG_UI_TEST_SERVER_URL` 指向不可達位址（connection refused 不登出；真 backend 401 會 logout + clearLocalData 清掉 fixture 世界，同 auth flow seam）。
- `typeText` 逐字輸入碰 debounce（搜尋 300ms）：字間隔偶爾 > debounce 會 commit 中間查詢（`complemen`→`complement` 各一發 mark）——斷言最終結果集，勿斷言 perf mark 次數。
- LazyVStack 列表 fold 以下的 row 不在 a11y 樹：未過濾長列表的 baseline 斷言用 prefix `anyRow`（`identifier BEGINSWITH`），指定 row 斷言只用在過濾後的短結果集。
- Reader 翻譯面板對訪客**刻意走 guest 模式**（`TranslationPanelContentMode` 先檢查 `!isLoggedIn`，遮蔽詞庫翻譯內容）→ 詞庫命中（零網路）的翻譯 flow 必須組合 `.authSignedIn` fixture，不是測試裡登入。
- Reader 選詞的確定性 tap target：Readium WebView 內多詞段落的 staticText 中心點落在哪個詞不可控；UI World 的 `reader.*` seed 必須同時宣告 `textAssetRef`（來源文字/對照 provenance）、`bookAssetRef`（完整 EPUB 書本 asset）、book metadata、notebook identity/sync state 與 entry row state，且不得帶未知 wrapper key；`bookAssetRef` 必須指向 `assets.books.*` 並安裝為 `Books/<bookFileName>`。Reader UITest 只從已物化的 EPUB 建 `Book` row，禁止在 seed runtime 把文字轉成書本；EPUB fixture 內容必須足夠長，讓 Readium paginated flow 能實際翻頁並驗 progress。
- Reader 詞庫 highlight / 翻譯 scope 認 `book.preferredNotebookId` 綁定本：fixture 須同時種 notebook（synced）+ `book.preferredNotebookId` + `entry.notebookId` 三者一致，缺一則 library-hit / 底線不出現。
- Today Review 翻卡狀態訊號：back identifier 必須放在 `backContentMounted` 的真內容分支（`TodayReviewPresenter+CardContent.swift` 的 `todayReview.card.back`）。answer fold surface 連同其 `accessibilityLabel("翻譯：…")` 在正面/摺疊（height 0）時仍常駐 view tree——identifier 放 surface/Group 上會讓 `.exists` 對翻卡狀態說謊。動畫中變動的 label（評分後 progress、計數 badge）**勿用** `waitUntilLabelContains`——`XCTNSPredicateExpectation` 會持續讀 stale accessibility snapshot 直到 timeout（實測 label 已是 "3 / 8" 仍判 fail）；改用顯式 RunLoop polling 每迭代重解析 query（`TodayReviewPage.waitUntilLabel(of:contains:)`，同 Podcast probe 讀 elapsed clock 的模式）。badge 斷言用「·1」避免裸 `1` 誤配。
- Today Review 是純本地 flow，fixture 免登入即可走完（notebook 卡片 + CTA + session）；仍設 `KG_UI_TEST_SERVER_URL` 指向不可達位址保持 hermetic（同 AuthFlow seam）。
- ⛔ **UI World 自 2026-08-05 起 FROZEN（停止擴張，不停止運作）**：以下 seam 全部照常可用，但 world 內容凍結、不再隨 iOS seed 演進。紅線與復業條件見 `docs/reference/catalog_scope.md` §FROZEN。
- **UI World seam**（`ios_test.sh --dataset <name>` / `--dataset-file <path>`，限 `--ui`）：把 `ops/fixtures/ui_worlds/<name>.json`（`kg.fixture.dataset.v2`）deflate 壓縮後 base64 注入 runner 的 `KG_FIXTURE_DATASET_DEFLATE_B64`（plaintext base64 的大 world 會超過 spawn env 上限而靜默失效；plaintext `KG_FIXTURE_DATASET_B64` 僅為外部向後相容），再經 `UITestLaunchConfiguration` 轉發進 app。UI World 是 Catalog / UITest / capture 共用 SoT，同時管理畫面資料、auth session、Keychain token state、entitlement、UserDefaults/iCloud KVS preferences、SwiftData row state 與 file-backed asset manifest；v2 schema 必須正好是 `kg.fixture.dataset.v2`，`datasetID` 必填非空，且所有 top-level domain 都必須明確宣告，空也要寫成空物件，不能靠 decoder 缺省補空；malformed seed arg、舊 schema、缺 schema、空 datasetID、未知 fixture domain/id、`FixtureDatasetStore.require*Seed` 缺 world / 缺 key、seed 過程拋錯都直接 fail hard，auth fixture 必須明示 isLoggedIn/userId/token/keychainTokenState/displayName/email/authError/isAuthenticating/provider/providerUserId；settings fixture 必須明示 authFixtureRef/entitlementsFixtureRef/auth/preferences/reviewSettings/kg/subscription/syncSummary/bookSync/about/danger/manualLoginUserId/debugLocalServerURL，nullable slice/欄位也要寫 null，authFixtureRef 必須指向同一 UI World 的 `auth.*`，entitlementsFixtureRef 必須指向同一 UI World 的 `entitlements.*` 或明示 null，且 repo contract 會驗 settings auth/pro UI state 與引用目標一致。auth keychainTokenState 只能是 `available` / `readFailed` / `absent`，preferences 在 seed 前寫入標準 UserDefaults + iCloud KVS seam，Notebook / VocabularyEntry 的 sync/action/archive/reader-exclusion 狀態必須由 manifest 明示，notebook row 的 `isDefault` / `sortOrder`、notebook entry 的 `context` / `explanation` / `partOfSpeech` / `bookTitle` / `chapterTitle`、review/vocabulary/reader entry 的 `bookTitle`、`chapterTitle`、`kgCardId`、`difficultyTier`、`reviewMode`、`reviewExamples`、`collocations`、`rootForm`、`inflections`、review scheduling counters、`graphLinksByKind`、reviewHistory-to-entry references、vocabulary/reviewDeck unique entry words 與 reviewDeck 的 `notebookRemoteId` / `notebookName` 也必須由 manifest 明示，nullable 欄位也要寫 `null`，`FixtureDatasetStore.requireInstalledAssetURL` 會驗 asset ref、來源檔存在、byteSize、sha256、contentType，安裝後再驗 installed byteSize + sha256，並依 `installAs` materialize 到 app Documents。Bookshelf seed 不再只建立 `Book` metadata row：repo UI World 的每本書必須明示 title/author/fileName/format/bookAssetRef/progression/preferredNotebookId/dateAdded/dateLastRead，非空 preferredNotebookId 必須 resolve 到同一 UI World notebook domain，且 `bookAssetRef` 指向 `assets.books.*`，Book.format/fileName 必須對齊 asset contentType/installAs，並安裝到 `Documents/Books/<fileName>`。Reader seed 必須明示 `textAssetRef` 與 `bookAssetRef`，其中 `bookAssetRef` 指向 `assets.books.*`、`installAs` 必須對齊 `Books/<bookFileName>`，Reader fixture 只能 seed 已物化 EPUB，不能 runtime 轉檔。Catalog podcast series 的 `colorHex` / `coverPattern`、episode 的 `durationSec` / nullable `lastPlayedTime` 必須由 manifest 明示；Runtime podcast series 的 `preferredNotebookId`、`color`、`coverPattern`、`sortOrder`、每集 `durationSec` / `previewDurationSec` 與 `download` 都必須由 manifest 明示，非空 `preferredNotebookId` 必須 resolve 到同一 UI World notebook domain；`download` 有值時其 `audioAssetRef` 與 `subtitleAssetRef` 也必須明示，nullable 欄位要寫 `null`；`download` 有值才物化 audio/subtitle 到 `PodcastEpisode.localAudioPath` / `localSubtitlePath`，沒有值就是未下載。`--ui` 實際執行未帶 world 會被 runner 擋下；`--list`/cache action 不執行注入。
- Host-side UI World 入口也 fail-fast：`ios_test.sh` 與 `catalog snapshots` 在 base64 / staged xctestrun / snapshot 前先跑 `ops/ui_world_manifest.py validate`；`ui_quality_gate.py` 與 `uitest_flow_matrix.py` 即使 dry-run 也會先驗 explicit dataset，invalid world 不會產生可執行命令。
- UI World decode 階段會先驗跨引用：每個 top-level domain key 必須屬於 v2 schema，asset manifest 只能宣告已知 bucket 且每個 asset 只能宣告已知 property，每個 domain 內 key 必須是已知 fixture id，`preferences.userDefaults` / `preferences.ubiquitousKeyValueStore` key 必須非空，auth `keychainTokenState` 必須和登入/token/userId 狀態自洽，settings 的 `authFixtureRef` / nullable `entitlementsFixtureRef` 必須 resolve 到同一 world 的 `auth.*` / `entitlements.*` 且 UI auth/subscription state 對齊；Reader / Notebook / Vocabulary / ReviewDeck 的 notebook sync status、VocabularyEntry `syncStatus/actionType`、entry word uniqueness 與 `reviewHistory.word` 必須在同一 seed 內自洽；Runtime podcast series/download 只能指 `assets.audio.*` / `assets.subtitles.*`，Reader 只能指 `assets.text.*` / `assets.books.*`，Bookshelf 非空 `bookAssetRef` 只能指 `assets.books.*`；ref 不存在、bucket 不對、未知 top-level domain、未知 asset bucket/property、未知 fixture id、空 preference key、登入/Pro 狀態漂移或 SwiftData row 狀態不合法直接 `DecodingError`，不是 seed/install 時的 late failure。

## 驗收（收斂層對抗驗證）

1. flow UI test `--lease --json` 綠 + `uiVisualReview` 非 null + `uiVisualReview.reviewHtmlExists == true`。
2. 獨立 reviewer **親 Read** 每張 step PNG 與 quick4，對照 KG_PERF log——不信 agent 自稱通過。
3. workspace `build/snapshots/uitest-runs/UIreview.html` 能從該 flow 導到本次 run page / video / log。
4. `./ops/test_ios_ops.sh` 與 `./ops/docs_lint.sh` 綠。
5. playbook 有新 seam 就回寫本檔。
