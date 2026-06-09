<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: manual
scope:
  - ios/BooksAndVocab/Views/Reader/
  - ios/BooksAndVocab/Models/ReaderSettings.swift
verified_against: 746dafaa
-->
# Reader 對標 Apple Books — 進度與接續計畫

> 由 8 維度 Workflow 深掃（16 agent）+ 根因核實產出。原始 plan：`~/.claude/plans/workflow-reader-apple-books-app-rustling-pebble.md`。

## 已完成（Phase 0-2① 已併入 main；原專屬 branch/worktree 已清理）

| commit | 內容 |
|---|---|
| `a3126e36` | **Phase 0** JS eval 異常盲區×8（新 `ReaderJSEval` 分流 spreadNotLoaded→debug / 真異常→error）+ `PerfLog.reader` 計時點×5 + `encodedLocatorJSON` 失敗 warning |
| `fe3b576d` | doc：`feature_boundary/reader.md` 補 ReaderJSEval |
| `128a70d4` | **Phase 1** 批量高亮 generation token（翻頁中止舊批次）+ `activateWordRange` surroundContents fallback |
| `b01fc1e4` | **Phase 2-①** 捲動↔翻頁切換（`EPUBPreferences.scroll` + 設定 UI tile + i18n×5） |

行為 / UI / log 建議**實機目視驗證**（單元/UI 測試走 `./ops/ios_test.sh`，視覺呈現以實機/sim 目視為準）。

## Phase 2 剩餘（做法已摸清）

**統一模式**（所有排版項走 Readium `EPUBPreferences`，原生支援；`BridgePlanner.commandsForPreferences` 自動偵測變更發 `applyPreferences`）：
`ReaderSettings` 加欄位(+KVS) → `viewConfiguration.epubPreferences` 加參數 → `ReaderSettingsPresenter.Bindings` + `ReaderSettingsPanel.presenterBindings` + 2 個 `#Preview` + `PreviewHarness` binding → `ReaderSettingsPresenter+Vocab` UI 控制項 → 5 `.strings` i18n。捲動模式（`b01fc1e4`）是完整樣板。

| 項 | EPUBPreferences | 注意 |
|---|---|---|
| **justify** | `textAlign`（`TextAlignment.justify/.start/.left/.center`，Types.swift:109） | ⚠️ **必須**改 `ReadiumNavigatorJS+BaseStyle.swift:41` `* { text-align: left !important }`（!important 覆蓋 preference 致無效）。預設 `.start`（=LTR left，無回歸） |
| **頁邊距** | `pageMargins`（Double） | ⚠️ 與 `ReaderContentStyle.swift:267` `pageGutterTop/Bottom`(76/52,上下) 不衝突；pageMargins 是左右倍數 |
| **亮度** | 非 EPUBPreferences，`UIScreen.main.brightness` | ⚠️ 系統全域，有副作用——存原始值 onAppear、onDisappear 還原 |
| **排版細節** | `hyphens`/`letterSpacing`/`wordSpacing`/`ligatures` | 純 preference 無 CSS 衝突，最低風險。行距 slider 可加命名預設（optional） |

## Phase 3/4/5（未動）

- **3 導航手勢**：中央 tap 顯隱 chrome（`ReadiumNavigatorView` `didTapAt:200` 未實現 → JS click listener 加中央區檢測 → `chromeState.header` toggle）；TOC 跳轉後浮動返回（`ReaderViewState` 加 `previousLocator`）；進度 scrubber（compact header 加 `Slider`+`DragGesture` → `publication.locate(progress:)`）。
- **4 效能**（依 Phase 0 基線**實機量測後**才做）：⚠️ `ReadiumService.extractUniqueWords:126` **已** `Task.detached(.background)`，非阻塞主線——原 finding「阻塞」前提需 PerfLog 數據修正；高亮 batchSize 動態 + `requestIdleCallback`。
- **5 架構**：拆巨型檔（`TranslationPanelPresenter` 581 行）；JS 抽 `.js` 資源檔；JS→Swift bridge Codable DTO（`Messages.swift:24` 既有 main-actor warning）；Interaction blocker 去 magic tag `9001`。

## 已驗證誤報 / 根因（不要重做）

- **Phase 0**：`ReaderProgressSaver`「從不 save」是誤讀註解（實際已 debounce+flush）；Locator 序列化靜默跳過是刻意設計（避免 `"{}"` 污染還原）。
- **Phase 1**：選字 race 由主執行緒 WKScriptMessage FIFO 防護（非路徑互斥），機率~nil 不加 nonce；字型變更 highlight reset 是誤報（Readium `needsInvalidation` allowlist 不含 font*/theme，CSS live 更新 DOM 不動、span 存活；強制 reset 反致調字級閃爍）；選詞正則 `don't`/`re-examine`/`co-op` 已覆蓋（僅缺重音字母）。
- **本次不做**（範圍外，列原始 plan 附錄）：書籤/全文搜尋/筆記/朗讀/無障礙(VoiceOver/Dynamic Type)/PDF 設定面板/跨裝置進度同步。

## 工作流

- Phase 0-2① 已併入 main（專屬 branch/worktree 已清理）；後續接續直接在 main-based worktree 進行。
- 編譯：`./ops/ios_build.sh`（shlock 多 worktree 安全）；測試：`./ops/ios_test.sh`（unit/UI/all-targets scope）；視覺呈現以實機/sim 目視為準。
- i18n：新字串 `L10n.string("中文key")`，5 `.strings`(en/zh-Hant/zh-Hans/ja/ko) 加翻譯，`./ops/i18n_lint.sh --strict` 驗（既有 `plural=3` baseline 非本工作）。
- 逐項 review：每項 dispatch `code-reviewer`(opus) PASS 才下一個（鐵律 4）；改實作前讀懂註解脈絡確認根因（鐵律 3）。
