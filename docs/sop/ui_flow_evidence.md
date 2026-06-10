<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/BooksAndVocabUITests/
  - ios/BooksAndVocab/Support/
  - ops/
verified_against: 448f66d9
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
| 6 | **視覺證據** | `test --json` 的 `uiVisualReview` | UI scope 自動產 full `contact_sheet.png` + `quick4_contact_sheet.png` + `review_manifest.json`（schema `kg.visual-review.sheet.v1`）。收尾回報**必貼** quick4 或 full sheet 並親眼 Read 過（light/dark 都要看時用 `catalog_contact_sheet.py --appearance both`）。 |

## 執行契約

```bash
./ops/ios_ops.sh test --ui --file <Flow>UITests.swift --lease --json   # 一律 --lease（pool 預設 3 台，KG_IOS_SIM_POOL_SIZE 可調）
```

- JSON verdict 讀 `uiVisualReview{screenshotDir,contactSheet,quick4Sheet,visualReviewManifest}`；`null` = 沒有視覺證據 = 不算完成。
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
- **Subagent 等待紀律**：把 build/test 丟 `run_in_background` 後結束 turn = 永遠收不到完成通知（三個 fan-out agent 全踩過）。長命令一律前景跑（timeout 拉滿）或前景 `until [[ -f <verdict> ]]; do sleep 5; done` 等；工作未完不准結束 turn。
- **`.plain` Button 中段透明死區 = 真陽性**：`buttonStyle(.plain)` 的 hit-test 會穿透透明像素，row 內 `Spacer()` 空白區點了沒反應；XCUITest `tap()` 永遠打 AX activation point（row 正中），剛好踩死區 → 決定性紅燈（Settings flow 抓到的 production bug）。修法 = Button label 加 `.contentShape(Rectangle())`，不是改測試去點文字。鑑別流程：AX frame + activation point（Session log）疊到截圖上驗座標 → 座標正確仍零反應 → 手動點同位置重現 → 死區即 app bug。
- 登入閘門後的 UI（如詞庫搜尋框）→ fixture 注入 signed-in session，且 `KG_UI_TEST_SERVER_URL` 指向不可達位址（connection refused 不登出；真 backend 401 會 logout + clearLocalData 清掉 fixture 世界，同 auth flow seam）。
- `typeText` 逐字輸入碰 debounce（搜尋 300ms）：字間隔偶爾 > debounce 會 commit 中間查詢（`complemen`→`complement` 各一發 mark）——斷言最終結果集，勿斷言 perf mark 次數。
- LazyVStack 列表 fold 以下的 row 不在 a11y 樹：未過濾長列表的 baseline 斷言用 prefix `anyRow`（`identifier BEGINSWITH`），指定 row 斷言只用在過濾後的短結果集。
- Reader 翻譯面板對訪客**刻意走 guest 模式**（`TranslationPanelContentMode` 先檢查 `!isLoggedIn`，遮蔽詞庫翻譯內容）→ 詞庫命中（零網路）的翻譯 flow 必須組合 `.authSignedIn` fixture，不是測試裡登入。
- Reader 選詞的確定性 tap target：Readium WebView 內多詞段落的 staticText 中心點落在哪個詞不可控；用 `EPUBConverter().convertTXT`（每行一個 `<p>`）讓真實章節的**單字行**（如章首 "Introduction"）成為 exact-label staticText，tap 中心即該詞（`UITestFixtureSeed+Reader.swift`）。
- Reader 詞庫 highlight / 翻譯 scope 認 `book.preferredNotebookId` 綁定本：fixture 須同時種 notebook（synced）+ `book.preferredNotebookId` + `entry.notebookId` 三者一致，缺一則 library-hit / 底線不出現。
- Today Review 翻卡狀態訊號：back identifier 必須放在 `backContentMounted` 的真內容分支（`TodayReviewPresenter+CardContent.swift` 的 `todayReview.card.back`）。answer fold surface 連同其 `accessibilityLabel("翻譯：…")` 在正面/摺疊（height 0）時仍常駐 view tree——identifier 放 surface/Group 上會讓 `.exists` 對翻卡狀態說謊。動畫中變動的 label（評分後 progress、計數 badge）**勿用** `waitUntilLabelContains`——`XCTNSPredicateExpectation` 會持續讀 stale accessibility snapshot 直到 timeout（實測 label 已是 "3 / 8" 仍判 fail）；改用顯式 RunLoop polling 每迭代重解析 query（`TodayReviewPage.waitUntilLabel(of:contains:)`，同 Podcast probe 讀 elapsed clock 的模式）。badge 斷言用「·1」避免裸 `1` 誤配。
- Today Review 是純本地 flow，fixture 免登入即可走完（notebook 卡片 + CTA + session）；仍設 `KG_UI_TEST_SERVER_URL` 指向不可達位址保持 hermetic（同 AuthFlow seam）。

## 驗收（收斂層對抗驗證）

1. flow UI test `--lease --json` 綠 + `uiVisualReview` 非 null。
2. 獨立 reviewer **親 Read** 每張 step PNG 與 quick4，對照 KG_PERF log——不信 agent 自稱通過。
3. `./ops/test_ios_ops.sh` 與 `./ops/docs_lint.sh` 綠。
4. playbook 有新 seam 就回寫本檔。
