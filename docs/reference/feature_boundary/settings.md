<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Views/Settings/
verified_against: dfc5401f
-->
# Settings Feature Boundary

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsView.swift` | 96 | 主容器 `struct SettingsView: View`，保留 body 組裝、task、sheet、alert wiring |
| `SettingsView+State.swift` | 177 | `presenterState` / `presenterActions` / 派生狀態組裝；偏好區複習節奏摘要含 progress freeze 狀態 |
| `SettingsView+Bindings.swift` | 51 | Binding 與 debug/local server wiring |

### Coordinator Layer（導航協調）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsCoordinator.swift` | 190 | `@Observable @MainActor final class SettingsCoordinator: SettingsCoordinating`，導航與 sheet 狀態 |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsPresenter.swift` | 196 | `struct SettingsPresenter: View`，主佈局 |
| `SettingsPresenter+Components.swift` | 645 | 可復用元件庫：`SettingsSectionHeader` / `SettingsRow` / `SettingsNavigationRow` / `SettingsCardNavigationRow` / `SettingsActionRowLabel` 等（最大檔案）|
| `SettingsPresenter+Quota.swift` | 52 | quota 相關 UI extension |
| `SettingsPresenter+Preview.swift` | 352 | preview 資料 |

### Presentation Models（UI 資料轉換）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsPresentation.swift` | 124 | `struct SettingsPresenterState` + `enum SubscriptionBadgeTone` + `struct SettingsPresenterActions`；`PreferencesSection.reviewModeDisplayName(for:)` 組裝首頁複習節奏顯示 |
| `SubscriptionPresentation.swift` | 142 | `enum SubscriptionPresentation`，訂閱狀態 UI 模型 |

### Section Views（各設定區塊）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsAccountSection.swift` | 376 | `struct SettingsAccountSection: View` + `SettingsAuthSummary`，帳號區塊 |
| `SettingsSubscriptionSection.swift` | 126 | `struct SettingsSubscriptionSection: View`，訂閱區塊 |
| `SettingsReviewSection.swift` | 332 | `struct SettingsReviewSection: View`，複習設定區塊；含 review progress pause/freeze toggle |
| `SettingsPreferencesSection.swift` | 92 | `struct SettingsPreferencesSection: View`，偏好設定區塊；含「自動連結」toggle（登入顯示，串後端 `auto_link` config group，控制 judge pipeline 自動建立連結）|

### Sheet / Detail Views

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SubscriptionPaywallSheet.swift` | 376 | `struct SubscriptionPaywallSheet: View`，訂閱付費 sheet |
| `SettingsAccountDetailView.swift` | 126 | `struct SettingsAccountDetailView: View`，帳號詳情（含刪除帳號入口）|
| `TranslationLanguageSettingsView.swift` | 101 | `struct TranslationLanguageSettingsView: View`，翻譯語言設定 |

---

## 改動規則

- **新增設定項目** → 對應 Section View（`SettingsAccountSection` / `SettingsReviewSection` / `SettingsPreferencesSection`）
- **新增設定區塊** → 新增 `Settings*Section.swift` + 在 `SettingsPresenter.swift` 加入
- **新增可復用 UI 元件** → `SettingsPresenter+Components.swift`
- **新增 sheet** → 新增 `*Sheet.swift` + 在 `SettingsCoordinator` 加 navigation state + 在 `SettingsView` 加 `.sheet` modifier
- **新增 Presentation model** → `SettingsPresentation.swift` 擴充，或新增專屬 Presentation 檔案
- **新增訂閱相關 UI** → `SubscriptionPresentation.swift` + `SettingsSubscriptionSection.swift`

## State 邊界

- `SettingsCoordinator`：Settings 的導航與 side-effect state（optional integration sheet、subscription paywall、delete confirm、translation config、debug backend）；由 `SettingsView` 持有，不外洩
- `SettingsPresenterState`：Presenter 接收的 UI 狀態快照，純值類型，可跨 layer 傳遞
- `SettingsPresenterState.PreferencesSection.reviewModeDisplayName(for:)`：偏好首頁「複習節奏」摘要的單一組裝入口；未凍結顯示模式名，凍結時顯示 `已凍結 · <模式>`
- `SettingsPresenterActions`：callback closure 集合，由 Container 注入，不持有 mutable state
- 帳號刪除確認與 paywall 開關目前由 `SettingsCoordinator` / `SettingsView` 一起驅動；不直接散落到 section view

## 現況判讀

- `SettingsView` 已從單檔主容器拆成 `View + State + Bindings` 三檔
- 主檔已縮到 100 行內，主要保留組裝、task、sheet、alert
- 後續若再新增設定區塊，優先擴充 `SettingsView+State.swift` 或對應 section view，而不是把狀態組裝塞回主檔

## 共用依賴

| Token | 用途 |
|-------|------|
| `AppTheme` | 色彩，`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token |
| `AppFonts` | 字型 |
| `SubscriptionPresentation` | 訂閱狀態 UI 模型，Settings 內部共用 |

## 未來路標

- `AppSkin.Spacing` 內 `sheet*`（`sheetSectionSpacing` / `sheetPadding` / `sheetPaddingCompact`）目前 3 欄位、Settings / Subscription / Podcast 三 feature 共用 → 留 AppSkin。**若 Settings sheet 演化出 ≥5 個 feature-local 欄位**，套同模式建 `SettingsSheetMetrics`（參考 boundary rectify 2026-05 的 `ReaderMetrics` / `TodayReviewMetrics` 範式）。
