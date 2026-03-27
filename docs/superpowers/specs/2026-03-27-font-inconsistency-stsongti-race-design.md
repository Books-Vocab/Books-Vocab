# 字體不一致問題：STSongti-TC 按需下載競態條件

**Date:** 2026-03-27
**Scope:** 全域 serif 字型 — 翻譯面板、標題、Navigation Bar
**Severity:** 視覺不一致，非 crash

## Problem

翻譯面板的中文翻譯文字有時顯示為**宋體（襯線）**，有時顯示為**黑體（無襯線）**。其他使用 serif token 的中文標題也有同樣的問題。行為不可預測，同一個單字在不同時刻顯示不同字體。

### Reproduction

1. 清除 iOS 字型快取（重裝 app 或重啟裝置）
2. 斷網後開 app → 翻譯文字一定是黑體
3. 聯網等幾秒後重新觸發翻譯 → 變回宋體

## Root Cause

### 核心問題：STSongti-TC 按需下載的競態條件

字型系統設計（`AppFonts.swift`）使用 `NSCTFontCascadeListAttribute` 建立 serif cascade：

```
Athelas (EN primary) → STSongti-TC (CJK fallback)
```

但 **STSongti-TC 不是 bundle 內建字型**，而是 iOS 按需下載的系統字型。

`BooksBrowserApp.swift:33` 在 app 啟動時呼叫：
```swift
AppFonts.ensureSerifCJKAvailable()
```

此函式使用 `CTFontDescriptorMatchFontDescriptorsWithProgressHandler`（**非同步、非阻塞**）觸發下載。下載完成後只寫了一行 log，**沒有通知 UI 重新渲染**。

### 時序分析

```
App 啟動
  ├─ ensureSerifCJKAvailable() → 觸發 async 下載
  ├─ configureGlobalAppearance() → 設定 navbar serif 字型
  └─ UI 開始渲染
      ↓
用戶打開翻譯面板 → translationTitle = AppFonts.serif(size: 21, bold: true)
  │
  ├─ 情境 A：STSongti-TC 已在快取 ✅ → 宋體（正確）
  └─ 情境 B：STSongti-TC 尚未下載 ❌ → 系統回退 PingFang TC（黑體）
```

**首次安裝、重啟裝置、或系統清理字型快取後**，情境 B 會穩定復現。之後因字型已快取，情境 A 佔多數，但不保證。

### 受影響的所有 UI 元件

所有使用 `AppFonts.serif()` / `AppFonts.uiSerif()` 且顯示 CJK 文字的位置：

| 元件 | Token | 檔案 | 正常 | 出問題時 |
|------|-------|------|------|---------|
| 翻譯文字 | `translationTitle` (21pt) | `TranslationVocabPresenter.swift:131` | STSongti-TC（宋體） | PingFang TC（黑體） |
| 長單字顯示 | `translationTitle` (21pt) | `TranslationVocabPresenter.swift:53` | STSongti-TC | PingFang TC |
| 頁面標題 | `displayTitle` (24pt) | VocabSkin baseTypography | STSongti-TC | PingFang TC |
| 區塊標題 | `sectionTitle` (18pt) | VocabSkin baseTypography | STSongti-TC | PingFang TC |
| 數字英雄 | `numericHero` (38pt) | VocabSkin baseTypography | STSongti-TC | PingFang TC |
| NavBar 大標題 | `uiSerif` (34pt) | `AppFonts.makeNavBarAppearances()` | STSongti-TC | PingFang TC |
| NavBar 小標題 | `uiSerif` (17pt) | `AppFonts.makeNavBarAppearances()` | STSongti-TC | PingFang TC |
| h1/h2 標題 | serif (28pt/22pt) | `AppFonts.h1()` / `.h2()` | STSongti-TC | PingFang TC |

### 次要問題：翻譯面板單字字型跳動

`TranslationVocabPresenter.swift:52-54`：
```swift
.font(state.word.count > 12
      ? vocabSkin.typography.translationTitle    // 21pt serif (Athelas)
      : vocabSkin.typography.detailWord)         // 27pt system monospaced
```

這是 intentional design，但用戶體驗上：
- 短單字如 "run" → 27pt monospaced
- 長短語如 "run out of steam" → 21pt serif

字型家族和大小同時跳變，視覺不連貫。

## Fix Plan

### Fix A：下載完成後觸發 UI 刷新（最小改動）

**File:** `AppFonts.swift`

在 `ensureSerifCJKAvailable()` 的 `.didFinish` callback 中，發送通知或設定 `@Published` 屬性，觸發依賴 serif 字型的 view 重新渲染。

```swift
// 方案 A1：用 NotificationCenter
case .didFinish:
    AppLog.fonts.info("STSongti-TC download completed")
    DispatchQueue.main.async {
        NotificationCenter.default.post(name: .serifCJKFontDidBecomeAvailable, object: nil)
    }
```

配合 view 端監聽並觸發 `@State` 變更（例如 `fontVersion += 1`），讓 SwiftUI 重新解析字型。

**優點：** 最小改動，不影響設計系統架構
**缺點：** 首次渲染仍然是黑體，下載完成後會閃一下字型切換

### Fix B：改用 bundle 內建的襯線 CJK 字型（根治）

**File:** `AppFonts.swift`

將 CJK serif fallback 從 `STSongti-TC`（按需下載）改為**已 bundle 的字型**。選項：

| 方案 | 字型 | 大小 | 備註 |
|------|------|------|------|
| B1 | Bundle 一套 CJK serif（如 Noto Serif CJK TC） | +5-15 MB | 最穩定，零下載依賴 |
| B2 | 改用 PingFang TC（系統內建，無襯線） | 0 MB | 放棄 CJK serif 風格 |
| B3 | 改用 `.serif` design 的系統字型 | 0 MB | `Font.system(.body, design: .serif)` 但無法和 Athelas cascade |

**推薦 B1**：Bundle Noto Serif CJK TC（Subset），只包含常用 CJK 字元（~5MB），徹底消除按需下載問題。

**推薦 B2 作為退路**：如果不想增加 app 體積，接受中文用無襯線字型。

### Fix C：統一翻譯面板單字字型（可選）

**File:** `TranslationVocabPresenter.swift:52-54`

移除 word count 條件判斷，統一使用同一字型家族（例如都用 monospaced，用 `minimumScaleFactor` 處理過長單字）：

```swift
Text(state.word)
    .font(vocabSkin.typography.detailWord)  // 統一 27pt monospaced
    .minimumScaleFactor(0.6)                // 過長時自動縮小
    .lineLimit(1)
```

或反過來都用 serif：
```swift
Text(state.word)
    .font(vocabSkin.typography.translationTitle)  // 統一 21pt serif
```

**取決於設計偏好**，這是風格決定而非 bug fix。

## Implementation Order

1. **Fix B**（選 B1 或 B2）— 根治字型下載競態，消滅所有間歇性問題
2. **Fix A** — 如果選 B1 但 bundle 尚未就緒，Fix A 可作為臨時過渡
3. **Fix C** — 可選，視設計偏好決定

## Files Affected

| File | Fixes |
|------|-------|
| `ios/BooksBrowser/Models/AppFonts.swift` | A, B |
| `ios/BooksBrowser/BooksBrowserApp.swift` | A (listener setup) |
| `ios/BooksBrowser/Views/Reader/TranslationVocabPresenter.swift` | C |
| `ios/BooksBrowser/Views/Vocabulary/Skin/VocabSkin.swift` | B (if cascade changes) |

## Verification

- 重裝 app（清除字型快取）→ 斷網啟動 → 翻譯面板文字應顯示正確字型
- 聯網啟動 → 翻譯面板文字應一致顯示正確字型
- 檢查所有 serif 標題在 CJK 文字下是否一致
- 切換 Light / Sepia / Dark 主題，確認字型不變
