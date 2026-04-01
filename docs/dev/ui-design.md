<!-- doc-meta
tier: structural
scope:
  - ios/BooksBrowser
verified_against: 05acfbf
-->
# BooksBrowser UI Design System

> 文檔網絡：
> - 開發入口與編譯流程：`docs/dev/ios-dev.md`
> - App 架構與 UI 脈絡：`docs/dev/architecture.md`
> - 元件 / pattern 現況清單：`docs/references/ui_component_pattern_inventory.md`
> - 狀態覆蓋矩陣：`docs/references/ui_state_matrix.md`
> - UI Review Checklist：`docs/references/ui_review_checklist.md`

## 設計系統概覽

BooksBrowser 使用莫蘭迪色調的 design token 系統：

| 層級 | Token 來源 | 適用範圍 |
|------|-----------|---------|
| App Shell | `AppTheme` / `AppColors` / `AppFonts` / `AppMetrics` | 全 app chrome（toolbar、tab、banner、toast） |
| Vocabulary Skin | `VocabSkin`（Palette / Typography / Spacing） | Vocabulary feature 所有 View |
| Reader | `ReaderContentStyle` | EPUB/PDF reader 內容樣式 |

### 環境注入

- `@Environment(\.appTheme)` — App Shell 層
- `@Environment(\.vocabSkin)` — Vocabulary 層
- 不可硬建 instance

### macOS 平台適配

- `Platform/PlatformRepresentable.swift`：跨平台 typealias（PlatformView / Color / Image / Font）
- `Platform/PlatformCompatibility.swift`：iOS-only modifier 的 macOS fallback
- Reader 系列以 `#if os(iOS)` 整檔隔離，macOS 暫不啟用
- 其餘 View 共用，平台差異以條件編譯處理

---

## Motion Contract

BooksBrowser 的 motion system 不接受各頁自由書寫 `.spring(...)` / `.easeOut(...)`。
動畫必須優先走 `BooksBrowser/Models/AppMetrics.swift` 中的 `AppMotion` 與共享 `AnyTransition` 語意 token。

### 核心原則

1. 先選語意，再選數值。
2. 同一類互動跨 feature 必須共用同一 token。
3. feedback 要成對出現：
   視覺 feedback 與 haptic feedback 應一起設計。
4. 不為了「有在動」而加動畫。
   animation 只服務於 state change、hierarchy、feedback、continuity。

### AppMotion 語意層

| Token | 用途 | 目前主要路徑 |
|------|------|-------------|
| `panelState` | panel / drawer / settings 開合 | Reader、Translation、Graph Settings |
| `panelSnapBack` | drag release 回位 | TranslationPanel |
| `headerState` | compact / expanded header 切換 | Reader header |
| `phaseChange` | 流程狀態切換 | Sync、Settings 狀態卡 |
| `feedbackPulse` | 成功保存、數字跳動、局部確認 | Translation save、Sync step、Review feedback、Toast |
| `contentFade` | 短暫內容淡出 | Reader progress / transient overlay |
| `loadingState` | loading 文案、loading overlay 的 state swap | Reader loading |
| `reviewRevealSpring` | review front/back/details 展開 | Today Review |
| `reviewNavigationSpring` | review 上一張 / 下一張 / 洗牌 | Today Review |
| `reviewCardSwapSpring` | review 回答後換卡 | Today Review |
| `toastPresent` | toast capsule 進出 | AppToast（全 app） |

### Transition 語意層

| Token | 用途 |
|------|------|
| `overlayFade` | scrim、暫時性 overlay、toolbar 進出 |
| `readerPanelReveal` | 底部 panel / drawer 進出 |
| `headerSwap` | header compact / expanded swap |
| `feedbackBadge` | saved / success 類 badge |
| `linkedOverlayCard` | linked card 疊層卡片 |
| `modalSwap` | 同區塊登入/登出、模式切換 |
| `statusRowReveal` | Settings / status row 延伸顯示 |

### 禁止事項

- 不要在 feature 檔案裡直接寫新的 `.spring(response:...)`，除非先把它提升為 `AppMotion` 語意 token。
- 不要為相似 overlay 各自定義不同 transition。
- 不要把 loading、success、error 都混用同一個動畫。
- 不要用 `.default` 當正式產品互動動畫。

### Feature Mapping

- Reader：
  `panelState`、`panelSnapBack`、`headerState`、`loadingState`、`feedbackBadge`
- Review：
  `reviewRevealSpring`、`reviewNavigationSpring`、`reviewCardSwapSpring`、`overlayFade`
- Sync：
  `phaseChange`、`feedbackPulse`、`blurReplace`
- Settings：
  `modalSwap`、`statusRowReveal`
- Toast：
  `toastPresent`、`feedbackPulse`
- Graph：
  `panelState`（settings panel）、`linkedOverlayCard`

### 文件責任

- 若是要改 token 定義：
  先更新 `BooksBrowser/Models/AppMetrics.swift`
- 若是要改互動規則：
  先更新本頁，再改程式
- 若是要排查編譯或 SwiftUI 實作錯誤：
  回到 `docs/dev/ios-dev.md`
- 若是要理解 UI 為何出現在某個資料流程中：
  回到 `docs/dev/architecture.md`
