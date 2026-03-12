# iOS Frontend Baseline

基線日期: 2026-03-12

---

## 1. 檔案規模 Top 10

| 行數 | 路徑 |
|------|------|
| 645 | `ios/BooksBrowser/Views/Settings/SettingsPresenter+Components.swift` |
| 617 | `ios/BooksBrowser/UIComponents/AppShellComponents.swift` |
| 601 | `ios/BooksBrowser/Views/Vocabulary/Skin/VocabSkin.swift` |
| 587 | `ios/BooksBrowser/Views/Vocabulary/Components/VocabShellComponents.swift` |
| 581 | `ios/BooksBrowser/Views/Reader/TranslationPanelPresenter.swift` |
| 502 | `ios/BooksBrowser/Views/Reader/ReadiumNavigatorJS.swift` |
| 449 | `ios/BooksBrowser/Services/DemoDataProvider.swift` |
| 445 | `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift` |
| 414 | `ios/BooksBrowser/Views/Reader/ReaderSettingsVocabPresenter.swift` |
| 400 | `ios/BooksBrowser/Views/Reader/ReaderView.swift` |

總 Swift 行數: 27,459 / 175 檔案

---

## 2. Preview 覆蓋率

| 範圍 | 數量 |
|------|------|
| Views/ + UIComponents/ 檔案總數 | 115 |
| 含 `#Preview` 的檔案數 | 28 |
| 覆蓋率 | 24.3% |

全專案含 `#Preview` 的 .swift 檔: 29

---

## 3. 設計系統 Token 清冊

| 識別子 | 類型 | 檔案 |
|--------|------|------|
| `AppColors` | enum | `Models/AppColors.swift` |
| `AppBrandColors` | enum | `Models/AppColors.swift` |
| `AppTheme` | struct | `Models/AppTheme.swift` |
| `AppFonts` | enum | `Models/AppFonts.swift` |
| `AppMetrics` | enum | `Models/AppMetrics.swift` |
| `AppTagMetrics` | enum | `Models/AppMetrics.swift` |
| `AppGhostButtonMetrics` | enum | `Models/AppMetrics.swift` |
| `AppBannerMetrics` | enum | `Models/AppMetrics.swift` |
| `AppMotion` | enum | `Models/AppMetrics.swift` |
| `TodayReviewMetrics` | enum | `Models/AppMetrics.swift` |
| `AppShadows` | enum | `Models/AppMetrics.swift` |
| `AnyTransition` (extension) | extension | `Models/AppMetrics.swift` |
| `VocabSkin` | struct | `Views/Vocabulary/Skin/VocabSkin.swift` |

---

## 4. 狀態覆蓋矩陣

| Surface | loading | empty | error | success |
|---------|---------|-------|-------|---------|
| Reader (Views/Reader/) | 10 | 9 | 7 | 5 |
| Vocabulary (Views/Vocabulary/) | 8 | 30 | 10 | 15 |
| Settings (Views/Settings/) | 5 | 7 | 1 | 7 |

數字為含對應狀態 pattern 的檔案數（grep 掃描）。

---

## 5. Token 合規度

掃描腳本: `scripts/ios_token_lint.sh`

排除定義檔: `AppColors.swift`, `AppTheme.swift`, `VocabSkin.swift`, `AppMetrics.swift`, `AppFonts.swift`

| 類型 | 違規數 |
|------|--------|
| raw-color | 0 |
| raw-font | 0 |
| raw-animation | 0 |
| raw-transition | 0 |

結果: `[OK] No violations found.` — Exit 0
