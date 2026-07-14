<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Views/Settings/
verified_against: 30df7f5f1
-->
# Settings Feature Boundary

## 檔案清冊

> 行數為 `wc -l` 快照，僅供定位；以 2026-06-11 全 28 檔逐檔讀檔重建。

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsView.swift` | 143 | 主容器 `struct SettingsView: View`：環境注入、coordinator 初始化、body 組裝、task、sheet、alert wiring；body 頂部掛 `RenderStormProbe.shared.tick` |
| `SettingsView+State.swift` | 192 | `presenterState` / `presenterActions` 組裝（融合 authManager / subscriptionManager / kgService / 各設定 store）；含 `bookSync` 投影與複習節奏摘要（progress freeze 狀態）|
| `SettingsView+Bindings.swift` | 44 | 翻譯語言雙向綁定 + DEBUG 手動登入 / 本地伺服器 URL 綁定 |

### Coordinator Layer（導航協調）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsCoordinator.swift` | 413 | `@Observable @MainActor final class SettingsCoordinator: SettingsCoordinating`。導航 / sheet 狀態（paywall、刪帳確認、翻譯語言）+ 非同步協調（loadData、resync、deleteAccount、後端切換、樂觀寫＋後端推送＋失敗回滾）+ connectionPulse / iconBreathing 動畫脈搏 + 觀測事件預覽緩衝 |

### Presenter Layer（純 UI 呈現）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsPresenter.swift` | 146 | `struct SettingsPresenter: View`，主佈局；`otherSection` 委派 `SettingsOtherSection`、debug 區委派 `SettingsDebugBackendSection`。**Stack 約束**：section 一律 child View struct，不得寫成 computed property 內聯回 body（真機 Debug 1MB main stack overflow，2026-06-11 定讞；見 `SettingsOtherSection.swift` 檔頭）|
| `SettingsPresenter+Actions.swift` | 438 | 複合互動元件庫（最大檔案）：`SettingsNavigationRow` / `SettingsCardNavigationRow` / `SettingsActionRowLabel` / `SettingsFeaturePanel` / `SettingsPlanComparisonTable` / `SettingsSubscriptionFeatureList` / `SettingsSelectableRow` / `SettingsSelectionTile` / `SettingsCompactActionButton` |
| `SettingsPresenter+Components.swift` | 192 | 微元件庫：`SettingsSectionHeader` / SectionFooter / 分隔線 / MenuValue / TitleSubtitleStack / StatusBadge / StatusValue / StatusSummaryValue（純展示，零互動邏輯）|
| `SettingsPresenter+Controls.swift` | 116 | 控件樣式層：StepperIconButton、card / button chrome / text input 修飾符、LabeledInputField |
| `SettingsPresenter+Preview.swift` | 84 | preview 資料與場景（登出 / 訂閱啟用 / 載入中 / 刪除中 / 價格不可用 / DEBUG 後端）|

### Presentation Models（UI 資料轉換）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsPresentation.swift` | 188 | `struct SettingsPresenterState` + `enum SubscriptionBadgeTone` + `struct SettingsPresenterActions`；`AccountIdentityFingerprint` 將 reviewer email 正規化（trim + NFC + POSIX lowercase）後做單向 SHA-256，供 exact-account UI evidence 使用；`PreferencesSection.reviewModeDisplayName(for:)` 組裝首頁複習節奏顯示；`BookSyncState.from(phase:)` 投影 CloudKitMirroringMonitor.phase（localOnly→nil 隱藏；failed 帶錯誤描述）|
| `SubscriptionPresentation.swift` | 149 | `enum SubscriptionPresentation`：KGSubscriptionStatus → badge / tone / 摘要 / 詳情 / CTA / permissions UI 模型；`summary(podcastEnabled:)` 依 `KGFeatureFlags.podcastEnabled` 切換 active 摘要文案（Release 用不含 Podcast 的版本）|
| `SubscriptionPaywallFeatureCatalog.swift` | 123 | Free vs Pro 功能對照目錄（EPUB/PDF、AI 翻譯、同步、知識圖譜、複習、Podcast）；`descriptors(podcastEnabled:)` 於 gate off（Release，`KGFeatureFlags.podcastEnabled`）時移除 Podcast row（quota row 恆末位）；計算屬性支援語言即時切換 |
| `SettingsMetrics.swift` | 14 | `enum AppSettingsMetrics`，Settings 專用版面常數（帳號 / 複習區塊間距與大小）|

### Section Views（各設定區塊）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SettingsAccountSection.swift` | 424 | `struct SettingsAccountSection: View` + `SettingsAuthSummary`，帳號卡片區塊（Google / Apple / 手動登入、Pro 標籤、驗證中遮蔽層）；summary row 的 accessibility identifier 只用 `settings.account.identity.<sha256>`（缺 identity 時為 `.unavailable`）。畫面仍可顯示可存取的 email；live evidence 不註冊完整 app tree，也不把 raw account 寫入 attachment/log |
| `SettingsSubscriptionSection.swift` | 139 | `struct SettingsSubscriptionSection: View`，訂閱方案詳情區塊（方案 / 徽章 / 來源 / 管理方式 / 恢復購買）；card 以 `settings.subscription.pro.active|inactive` 暴露實際 presenter entitlement，供 exact-device App Review probe 判讀 |
| `SettingsReviewSection.swift` | 334 | `struct SettingsReviewSection: View`，複習節奏詳情頁：progress pause/freeze toggle、複習模式、自訂 SRS 參數；樂觀寫＋後端推送＋失敗回滾 |
| `SettingsPreferencesSection.swift` | 145 | `struct SettingsPreferencesSection: View`，偏好設定區塊；含「自動連結」toggle（登入顯示，串後端 `auto_link` config group，控制 judge pipeline 自動建立連結）|
| `SettingsOtherSection.swift` | 227 | `struct SettingsOtherSection: View`，「其他」區塊：sync status 摘要 row + **iCloud 書庫同步狀態列**（綁 Apple ID 不掛登入 gate）+ quota row + external action row（吸收原 `SettingsPresenter+Quota.swift`）|
| `SettingsDebugBackendSection.swift` | 128 | `struct SettingsDebugBackendSection: View`（DEBUG only），debug backend 切換區塊（前身 `SettingsPresenter+Debug.swift`，改 inline extension → 獨立 struct）|

### Sheet / Detail Views

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SubscriptionPaywallSheet.swift` | 296 | `struct SubscriptionPaywallSheet: View`，paywall sheet：已啟用（確認式）/ 未啟用（升級式）雙佈局、產品載入、恢復購買、StoreKit 整合 |
| `SettingsAccountDetailView.swift` | 151 | `struct SettingsAccountDetailView: View`，帳號詳情（CSV 匯出、刪除帳號入口）|
| `SettingsDeleteAccountSheet.swift` | 316 | `struct SettingsDeleteAccountSheet: View`，多步驟刪帳確認 sheet：三項勾選 + 輸入確認字串 + 5 秒倒數冷卻 |
| `TranslationLanguageSettingsView.swift` | 168 | `struct TranslationLanguageSettingsView: View`，翻譯語言設定（閱讀語言 → 翻譯語言）；樂觀寫＋後端推送＋失敗回滾 |

### Copy（純文案常數）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `SubscriptionPaywallCopy.swift` | 115 | paywall 文案解析（帳單金額 / 試用 / CTA / footer）；對齊 App Store 3.1.2(c) 合規敏感字串 |
| `SettingsDeleteAccountCopy.swift` | 53 | 刪帳工作流文案（後果列表 / 確認勾選 / 倒數 / 確認字串）|
| `SettingsAccountCopy.swift` | 25 | 帳號區塊文案常數（登入 / 驗證 / 訂閱狀態 / Pro 標籤）|

### Debug 工具

| 檔案 | 行數 | 說明 |
|------|------|------|
| `RenderStormProbe.swift` | 53 | `#if DEBUG` body 重評估風暴偵測：計數每秒 body evals，>5/sec 記 STORM 警告；`SETTINGS_RENDER_DEBUG=1` 加開 `_printChanges()`；log category `RenderStorm` |

---

## 改動規則

- **新增設定項目** → 對應 Section View（`SettingsAccountSection` / `SettingsReviewSection` / `SettingsPreferencesSection`）
- **新增設定區塊** → 新增 `Settings*Section.swift`（child View struct，stack 約束）+ 在 `SettingsPresenter.swift` 加入
- **新增可復用 UI 元件** → 依性質三選一：純展示微元件 → `+Components`；複合互動元件（row / panel / table）→ `+Actions`；控件樣式 / 修飾符 → `+Controls`
- **section body 一律拆獨立 `View` struct，不要 inline 回 `SettingsPresenter.body`** → 真機 main thread stack 僅 1MB，Debug `-Onone` 下 inline section 會把 body 型別尺寸撐爆觸 `EXC_BAD_ACCESS`；`SettingsStackBudgetTests`（`MemoryLayout<Body>.size` 門檻 20KB/16KB）為 re-inline 回歸防線
- **新增 sheet** → 新增 `*Sheet.swift` + 在 `SettingsCoordinator` 加 navigation state + 在 `SettingsView` 加 `.sheet` modifier
- **新增 Presentation model** → `SettingsPresentation.swift` 擴充，或新增專屬 Presentation 檔案
- **新增訂閱相關 UI** → `SubscriptionPresentation.swift` + `SettingsSubscriptionSection.swift`；paywall 文案改 `SubscriptionPaywallCopy.swift`（注意 App Store 合規字串）、對照表內容改 `SubscriptionPaywallFeatureCatalog.swift`
- **新增 user-facing 文案常數** → 對應 `*Copy.swift`，不要内聯進 View

## State 邊界

- `SettingsCoordinator`：Settings 的導航與 side-effect state（optional integration sheet、subscription paywall、delete confirm、translation config、debug backend）；由 `SettingsView` 持有，不外洩
- `SettingsPresenterState`：Presenter 接收的 UI 狀態快照，純值類型，可跨 layer 傳遞
- `SettingsPresenterState.AuthSection.identityFingerprint`：只由 `authManager.userEmail` 派生；原始帳號不進 accessibility identifier 或 evidence attachment/log，UITest 以同一正規化規則的 SHA-256 驗證裝置登入者是否等於 ASC reviewer account（畫面可見 email 仍保有一般 accessibility）
- `SettingsPresenterState.PreferencesSection.reviewModeDisplayName(for:)`：偏好首頁「複習節奏」摘要的單一組裝入口；未凍結顯示模式名，凍結時顯示 `已凍結 · <模式>`
- `SettingsPresenterActions`：callback closure 集合，由 Container 注入，不持有 mutable state
- 帳號刪除確認與 paywall 開關目前由 `SettingsCoordinator` / `SettingsView` 一起驅動；不直接散落到 section view

## 現況判讀

- `SettingsView` 已從單檔主容器拆成 `View + State + Bindings` 三檔；主檔 143 行，保留組裝、task、sheet、alert 與 RenderStormProbe wiring
- 原 645 行 `+Components` 已拆三檔：微元件留 `+Components`（192）、複合互動元件進 `+Actions`（438，現為最大檔案）、控件樣式進 `+Controls`（116）
- `SettingsCoordinator` 已從純導航狀態機（190 行）長成「狀態 + 非同步協調」混合職責（413 行）；再長大時優先考慮把樂觀寫＋回滾協調抽 service，而不是繼續堆 coordinator
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
