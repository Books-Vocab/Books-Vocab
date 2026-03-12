# Reader Feature Boundary

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReaderView.swift` | 190 | 主容器，持有 @State/@Environment，組裝 body |
| `ReaderView+Panels.swift` | 115 | panel content builders |
| `ReaderView+Handlers.swift` | 94 | callback handlers |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `ReaderViewPresenter.swift` | 57 | 主佈局 `struct ReaderViewPresenter<...>: View` |
| `ReaderViewPresenter+Headers.swift` | 207 | header 區域 extension |
| `ReaderViewPresenter+Overlays.swift` | 154 | overlay 區域 extension |
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
| `ReadiumNavigatorJS.swift` | 502 | JavaScript 橋接腳本 |
| `ReadiumNavigatorCoordinator+Commands.swift` | 98 | `BridgeCommand` / `HostCommand` / `NavigatorCommand` / `DOMCommand` |
| `ReadiumNavigatorCoordinator+Planner.swift` | 166 | `struct BridgePlanner`，指令排程 |
| `ReadiumNavigatorCoordinator+Messages.swift` | 104 | 訊息解析 extension |
| `ReadiumNavigatorCoordinator+Highlighting.swift` | 132 | 高亮 extension |
| `ReadiumNavigatorSupport.swift` | 99 | `actor GlobalDebouncer` + `final class NavigatorHostViewController` |
| `ReaderContentStyle.swift` | 260 | `ReaderContentStyle` + `ReaderContentStyleFactory` + `ReaderGlassTypography` + `ReaderPresentationMetrics` |

### Feature Panels

| 檔案 | 行數 | 說明 |
|------|------|------|
| `TranslationPanel.swift` | 240 | `struct TranslationPanel: View`，翻譯面板 UI |
| `TranslationPanelPresenter.swift` | 581 | 翻譯面板佈局（最大檔案）|
| `TranslationVocabPresenter.swift` | 295 | 翻譯詞彙呈現 |
| `ReaderSettingsPanel.swift` | 184 | `struct ReaderSettingsPanel: View`，閱讀設定面板 |
| `ReaderSettingsPanelPresenter.swift` | 290 | 設定面板佈局 |
| `ReaderSettingsVocabPresenter.swift` | 414 | 設定詞彙呈現 |
| `TOCView.swift` | 203 | `struct TOCView: View`，目錄 |

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
