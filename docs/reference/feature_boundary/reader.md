<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Models/ReaderSettings.swift
  - ios/BooksAndVocab/Models/VocabHighlightPreferences.swift
  - ios/BooksAndVocab/Views/Reader/
verified_against: 07130a3a1
-->
# Reader Feature Boundary

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReaderView.swift` | 211 | 主容器，持有 @State/@Environment，組裝 body。**單字本綁定 seed**：`seedNotebookBindingIfNeeded`（`.task` + `liveNotebooks` settle 的 `onChange` 觸發）在書未綁定時以全域 active 為 seed 經 `Book.canSeedBinding` gate（須 live 清單內已 settle 的真實本）固化 `book.preferredNotebookId` 並 `safeSave` + `BookManifestStore.writeBestEffort`；`sanitizeStaleBoundNotebook` 清除已刪綁定本。固化後 scope 認綁定本、不隨全域漂移 |
| `ReaderView+Panels.swift` | 115 | panel content builders |
| `ReaderView+Handlers.swift` | 94 | callback handlers |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReaderViewPresenter.swift` | 57 | 主佈局 `struct ReaderViewPresenter<...>: View` |
| `ReaderViewPresenter+Headers.swift` | 207 | header 區域 extension |
| `ReaderViewPresenter+Overlays.swift` | 126 | overlay 區域 extension；translation / settings panel 依 `ReaderOverlayPanelPlacement` 分流：compact 底部居中，regular / Catalyst 右下 inspector |
| `ReaderViewPresenter+Preview.swift` | 207 | preview 資料 |
| `QuotaBar.swift` | 51 | `struct QuotaBar: View`，quota 顯示列 |

### State Layer（狀態定義）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReaderViewState.swift` | 19 | `@Observable final class ReaderViewState`，UI 狀態容器 |
| `ReaderChromeState.swift` | 36 | `HeaderState` + `ReaderChromeOverlay` + `ReaderChromeState` + `ReaderViewPresenterState` |

### Domain Layer（業務邏輯）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReaderTranslationHandler.swift` | 66 | `@Observable final class ReaderTranslationHandler`，翻譯狀態管理 |
| `ReaderTranslationHandler+Flows.swift` | 289 | 翻譯/查詞/解釋流程 |
| `ReaderTranslationHandler+Persistence.swift` | 88 | 詞彙存儲 |
| `ReaderVocabularyContext.swift` | 70 | `struct ReaderVocabularyContext`，詞彙查找上下文 |
| `ReaderDOMExecutor.swift` | 57 | `struct ReaderDOMExecutor`，DOM 操作執行器 |

### Integration Layer（Readium 整合）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReadiumNavigatorView.swift` | 225 | Readium WebView 封裝 |
| `ReadiumNavigatorJS.swift` | 25 | JavaScript 橋接腳本 entry（`buildInjectionScript` 組合入口）|
| `ReadiumNavigatorJS+BaseStyle.swift` | 80 | `buildBaseStyleScript`（@font-face + base CSS + debug overlay styles）|
| `ReadiumNavigatorJS+ContentStyle.swift` | 32 | `buildContentStyleScript`（內容樣式注入 / 動態更新）|
| `ReadiumNavigatorJS+Highlight.swift` | 173 | `buildHighlightScript`（`__markVocabWord` / `__markVocabWords` / `__removeVocabWord`）|
| `ReadiumNavigatorJS+Debug.swift` | 76 | `buildDebugScript`（`__toggleDebugBoxes` Token Calculator 黑盒）|
| `ReadiumNavigatorJS+Selection.swift` | 266 | `buildSelectionScript`（`selectionchange` 監聽 + 單字 caret 點擊偵測）|
| `ReadiumNavigatorCoordinator+Commands.swift` | 98 | `BridgeCommand` / `HostCommand` / `NavigatorCommand` / `DOMCommand` |
| `ReadiumNavigatorCoordinator+Planner.swift` | 166 | `struct BridgePlanner`，指令排程。換綁定單字本時以 **set-diff 權威重畫** highlight（比對舊/新命中集合 add/remove 底線指令），取代舊的 count-gating |
| `ReadiumNavigatorCoordinator+Messages.swift` | 104 | 訊息解析 extension |
| `ReadiumNavigatorCoordinator+Highlighting.swift` | 132 | 高亮 extension |
| `ReadiumNavigatorSupport.swift` | 99 | `actor GlobalDebouncer` + `final class NavigatorHostViewController` |
| `ReaderJSEval.swift` | 50 | `enum ReaderJSEval`，fire-and-forget `evaluateJavaScript` 結果可觀測性：`classify` 純分流（`.ok` / `.spreadNotLoaded` benign / `.failed`）+ `log` 落 `AppLog.reader`，預期 race 降 debug、真異常升 error |
| `ReaderContentStyle.swift` | 278 | `ReaderContentStyle` + `ReaderContentStyleFactory` + `ReaderPresentationMetrics` + `ReaderOverlayPanelPlacement` + `ReaderPanelChromeStyle` + `ReaderTOCPresentation` + `ReaderNotebookPickerPresentation` |
| `VocabHighlightPreferences.swift` | ~70 | `VocabHighlightColorPreset` + `VocabHighlightPreferences`；Reader / Podcast 共用詞庫 highlight 顏色 preset、opacity、band fraction。`ReaderSettings` 持久化 `vocab_highlight_colorPreset` / `vocab_highlight_opacity`，並保留舊 `reader_settings_underlineOpacity` fallback。 |

### Feature Panels

| 檔案 | 行數 | 說明 |
|------|------|------|
| `TranslationPanel.swift` | 255 | `struct TranslationPanel: View`，翻譯面板 UI；compact 支援拖曳關閉，regular / Catalyst 關閉 bottom-sheet 拖曳語意 |
| `TranslationPanelPresenter.swift` | 581 | 翻譯面板佈局（最大檔案）|
| `TranslationVocabPresenter.swift` | 337 | 翻譯詞彙呈現；依 `ReaderPanelChromeStyle` 切換手機 handle 與桌面 inspector 上緣內距 |
| `ReaderSettingsPanel.swift` | 184 | `struct ReaderSettingsPanel: View`，閱讀設定面板 |
| `ReaderSettingsPresenter.swift` | 111 | 設定面板 presenter facade，持有設定狀態與 layout environment |
| `ReaderSettingsPresenter+Vocab.swift` | ~260 | 設定詞彙呈現；依 `ReaderPanelChromeStyle` 切換手機 handle 與桌面 inspector 上緣內距；「生字標記」區控制 highlight 顏色與濃度 |
| `VocabHighlightColorPresetPicker.swift` | ~55 | Reader / Podcast 共用 highlight 顏色 swatch picker；寫回 `ReaderSettings.vocabHighlightColorPreset` |
| `TOCView.swift` | 222 | `struct TOCView: View`，目錄；regular / Catalyst 收斂內容寬度，compact 維持 full-width sheet |
| `ReaderNotebookPicker.swift` | 133 | Reader 內為**本書綁定**單字本（`book.preferredNotebookId`，`Book: NotebookBindable`）；每本書綁定恰好一本真實單字本，**已移除「跟隨全域設定」**列、改用共用 presentational `NotebookBindingList`（Vocabulary/，不標示「預設」）；選詞 / highlight / cache scope 認 `book.resolvedNotebookId` 綁定本、**不隨全域 active 漂移**；綁定本被刪 → `sanitizeStaleBoundNotebook` 清 nil（下次開啟由 `ReaderView` re-seed）。regular / Catalyst 收斂短選單寬度，compact 維持 full-width sheet |

### PDF Reader（原生 PDFKit 路徑）

EPUB/TXT/MD 走 `ReaderView`（Readium），`.pdf` 走獨立 `PDFReaderView`（`BookshelfView` 依 `book.format` 路由）。PDF 為原生 `PDFView`（無 WebView/DOM/JS），但**共用** `ReaderTranslationHandler` 與 `TranslationPanel`，選詞→翻譯/解釋/儲存行為與 EPUB 對齊。

| 檔案 | 說明 |
|------|------|
| `PDFReaderView.swift` | PDFKit 渲染 + 選詞捕捉；`UIEditMenuInteraction` 提供「翻譯」「解釋」。「翻譯」依 token 數分流 word（`handleWordSelected`）/ phrase（`handlePhraseSelected`），「解釋」走 `handleExplainSelected`。已對齊：已收藏詞顯示「查看詳情」(`WordDetailSheet`)、`canUseProReaderFeature` 閘、開啟 bump `dateLastRead`。進度存 `PDFPosition{pageIndex}`（頁級，非 Locator），翻頁同步存。 |
| `ReaderWordCapture.swift` | 選詞層 sanitize（去頭尾 `'`/`-`、丟 <2 字元）+ `isPhraseSelection` 分類；鏡像 EPUB JS 選詞層，與 `normalizeWord` capture 契約分離、組合使用。 |
| `PDFReaderContext.swift` | 純函式 context 視窗抽取（plain / marked `before**highlight**after`），對齊 EPUB 兩種 context 形狀；可單元測試。 |
| `ReaderEntitlement.swift` | Reader pro-feature 閘單一真相，EPUB（`ReaderView`）與 PDF 共用委派。 |

**刻意不對齊（格式本質）**：PDF 無字型/行距/主題（固定排版）、無已收藏詞自動畫底線（PDFKit 無可靠渲染完成訊號 + 無按詞搜全頁 API）、無章節 TOC（PDFKit 無 outline API）。

---

## 改動規則

- **新增 UI 元素** → Presenter Layer（`ReaderViewPresenter+*.swift`）
- **新增業務邏輯** → Domain Layer（`ReaderTranslationHandler+*.swift`），禁止放在 View 裡
- **新增 Readium 功能** → Integration Layer（`ReadiumNavigatorCoordinator+*.swift`）
- **新增面板** → Feature Panels 新增檔案 + 在 `ReaderView+Panels.swift` 加 slot
- **新增 callback** → `ReaderView+Handlers.swift`

## State 邊界

- `ReaderViewState`：Reader 畫面 UI 狀態，不外洩到 Vocabulary / Settings
- `ReaderChromeState` / `ReaderViewPresenterState`：chrome overlay 狀態，僅 ReaderViewPresenter 使用
- `ReaderTranslationHandler`：翻譯/詞彙互動狀態，由 ReaderView 持有，不共用給其他 feature
- `ReaderVocabularyContext`：詞彙查找上下文，透過 handler 傳遞，不直接暴露到 Container 外

## 共用依賴

| Token | 用途 |
|-------|------|
| `AppTheme` | 色彩、`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token |
| `AppTransition` | 過渡動畫 |
| `ReaderPresentationMetrics` | Reader 專屬尺寸常數（定義於 `ReaderContentStyle.swift`）|
| `ReaderMetrics` | Reader feature-local 版面參數（panel handle / settings sheet inset / option padding，25 個 static let，定義於 `ReaderMetrics.swift`）。從 `AppSkin.Metrics` 遷出（boundary rectify 2026-05）。跨 feature 借用者：`UIComponents/AppShellComponents.swift`、`Views/Vocabulary/Components/CollocationExplainSheet.swift` |
| `VocabHighlightPreferences` | Reader / Podcast 共用詞庫 highlight 偏好；Reader 透過 Readium content style CSS var 更新，Podcast 透過 SwiftUI background layer 渲染 |
