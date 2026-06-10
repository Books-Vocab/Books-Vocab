<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/BooksAndVocabUITests/
  - ios/BooksAndVocab/Support/
  - ops/
verified_against: 655dea9c
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
- **Subagent 等待紀律**：把 build/test 丟 `run_in_background` 後結束 turn = 永遠收不到完成通知（三個 fan-out agent 全踩過）。長命令一律前景跑（timeout 拉滿）或前景 `until [[ -f <verdict> ]]; do sleep 5; done` 等；工作未完不准結束 turn。

## 驗收（收斂層對抗驗證）

1. flow UI test `--lease --json` 綠 + `uiVisualReview` 非 null。
2. 獨立 reviewer **親 Read** 每張 step PNG 與 quick4，對照 KG_PERF log——不信 agent 自稱通過。
3. `./ops/test_ios_ops.sh` 與 `./ops/docs_lint.sh` 綠。
4. playbook 有新 seam 就回寫本檔。
