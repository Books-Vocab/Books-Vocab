<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: 7c7a23b
-->
# BooksBrowser iOS 開發技能

## 核心資訊

- **專案路徑**: `ios/BooksBrowser.xcodeproj`
- **Scheme**: `BooksBrowser`
- **工作目錄**: repo root（`~/kg/`）
- **Destinations**: iOS 17+ / macOS 15.0+（macOS Reader 暫不啟用）
- **平台抽象**: `Platform/PlatformRepresentable.swift`、`Platform/PlatformCompatibility.swift`

---

## 最高指導原則

**Exit Code `0` = 編譯成功，任務結束。不用懷疑。**

---

## iOS 編譯 3 步驟 SOP

### Step 1：靜默編譯，直擊錯誤

```bash
./ops/ios_build.sh
```

- Exit Code `0` → 完成，停止
- Exit Code 非 `0` → 畫面殘留的就是純淨錯誤清單，進 Step 2

### Step 2：還原案發現場

**不要只看單行錯誤就動手改。** 根據錯誤的**檔名 + 行號**，讀取該行**上下至少 20 行**原始碼，結合 Swift/SwiftUI 語法特性完整分析脈絡。

常見需要讀上下文的場景：
- `@ViewBuilder` 限制（return type、條件分支問題）
- Optional unwrap 導致的型別不符
- `@State` / `@Binding` / `@ObservableObject` 使用錯誤
- `async/await` 上下文缺失

### Step 3：對症下藥並驗證

修復後立刻重跑 Step 1。反覆「編譯 → 讀上下文 → 修改」直到 Exit Code 歸零。

## App 架構速查

### 主要 Services

| Service | 職責 |
|---------|------|
| `AuthManager.swift` | 單例，Apple/Google SSO、Keychain token、登入狀態 |
| `KGService.swift` | 後端 API 呼叫（分拆為 +Graph/+Notebook/+Stats/+Sync/+UserConfig/+VocabCRUD） |
| `BackgroundSyncActor` | `@ModelActor`，背景同步（push review/stats、pull cards、flush bilateral ops） |
| `SyncCoordinator` | 同步協調（手動同步入口、orphan cleanup） |
| `BookshelfImportService` | Multi-format import（EPUB/TXT/MD/PDF） |
| `AppToastCoordinator` | Toast notification 管理（EnvironmentKey 注入） |
| `AppCrashReporting` | Sentry bootstrap；opt-in via `Info.plist` `SentryDSN`；`bootstrap()` 於 `BooksBrowserApp.init()` 第一步呼叫；`setUser(id:)` 連動 `authManager.isLoggedIn` 變化；`record(_:context:)` 手動 capture |

### 主要 Views

| View | 說明 |
|------|------|
| `Settings/SettingsView` | 登入登出、伺服器設定、第三方整合 |
| `Reader/ReaderView` | EPUB 閱讀器（iOS only），查詞 → batchAdd → triggerPipeline |
| `Reader/PDFReaderView` | PDF 閱讀器（iOS only） |
| `Vocabulary/` | 單字瀏覽、知識圖譜視覺化、手動同步、hide/unhide links |
| `Vocabulary/Scenes/StatsPresenter` | 統計總覽 + graph thumbnail + health blob |
| `Vocabulary/Scenes/TodayReviewPresenter` | 每日複習 |
| `Bookshelf/BookshelfView` | 書架 + multi-format import |
| `Welcome/WelcomeView` | 首次啟動 / guest 引導（含 login entry points） |

### iOS 資料同步流程

```
Reader 查詞
  → 暫存 VocabularyEntry（syncStatus=0, pending）
  → POST /api/vocab（batchAdd）→ 伺服器生成 embedding
  → POST /api/pipeline（fire-and-forget）→ 伺服器背景 Enrich/Link/Difficulty/Optional External Sync
  → GET /api/vocab?since=<上次同步>（pullCardsToLocal）→ 更新 SwiftData
```

### 認證流程

```
Apple/Google SSO
  → Google User ID 或自訂密語（存 Keychain）
  → 作為 Authorization: Bearer <token> 發給後端
  → 後端建立 data/users/<user_id>/ 隔離目錄
  → HTTP 401 → iOS 自動登出 + 清空 SwiftData
```

### Crash Reporting（Sentry）

**iOS env / Info.plist key / 取樣率（SoT）**：`docs/sop/deploy.md §Sentry 錯誤追蹤 → iOS env / Info.plist`。本段僅寫 iOS-side 程式碼層 wiring。

實作要點（`Services/AppCrashReporting.swift`）：
- SPM dep `sentry-cocoa` 透過 `canImport(Sentry)` 守門 — 缺套件即 pure no-op，dev / PR build 不卡編譯
- Bootstrap 順序：`AppCrashReporting.bootstrap()` 在 `BooksBrowserApp.init()` 第一步執行（早於 `ModelContainer` init，捕捉儲存初始化失敗）
- User 追蹤：`AppCrashReporting.setUser(id:)` 連動 `authManager.isLoggedIn` onChange — 登出時清除，避免多帳戶污染
- `beforeSend` 過濾：丟棄 `CancellationError` / `NSURLErrorCancelled` 噪音；HTTP breadcrumb 自動 strip query string

### Hot Reload（InjectionNext + Inject）

開發時免 build 即時更新 SwiftUI，把「改一行等 30 秒 build」縮到秒級。Debug-only，Release builds LLVM-strip 為 no-op，**production 零影響**。

**前置一次性設定**：
1. SPM dep：`https://github.com/krzysztofzablocki/Inject`（已加進 `BooksBrowser.xcodeproj`）
2. Build Settings → Debug → Other Linker Flags 含 `-Xlinker -interposable`（**只 Debug**）
3. 下載 [InjectionNext.app](https://github.com/johnno1962/InjectionNext) 放 `/Applications/`

**使用方式**：
1. 啟動 InjectionNext.app（menu bar 出現 icon）→ menu bar 點 **Launch Xcode** 開啟 BooksBrowser.xcworkspace
2. ⌘R 跑 Debug build 到 simulator，console 應出現 `💉 InjectionNext connected`
3. 改任何已加 `.enableInjection()` 的 SwiftUI view → 存檔 → simulator 1-2 秒內重渲染

**hot reload 範圍**：
- `ContentView` 已掛 `@ObserveInjection` + `.enableInjection()` → 整棵 tree 預設可注入
- 要對個別 view 啟用更精確的注入，於該 view 加同樣兩行
- **可注入**：view body / modifier / layout / 文案 / `AppTheme` 色票
- **不可注入（仍需 full build）**：stored property 增減、function signature 改動、`enum` case 新增、Readium C++/ObjC++ bridging 改動

**故障排除**：
- console 無 `💉` 訊息 → InjectionNext.app 未啟、或 Xcode 不是從 menu bar 「Launch Xcode」開的
- 改 file 後 simulator 沒反應 → 看 console 是否報 `cannot inject ...`（多半是改到 stored property），需 ⌘R 重 build
- Release archive 報錯 → 確認 `-interposable` flag **只在 Debug 配置**，Release 維持原狀

### Playbook Catalog（SwiftUI 元件目錄）

DEBUG-only 元件 catalog，讓 simulator 啟動時直接進入「狀態矩陣牆」而非正常 app UI，給 CLI 截圖協作（Claude / simctl）用。Phase 1 hot reload + Phase 3 catalog 組合 = 視覺迭代閉環：你改 `AppTheme.swift` 色票 → InjectionNext 秒級重渲染 catalog → simctl 截圖讓 Claude 看到結果。

**啟用方式**：
1. Xcode → Product → Scheme → Edit Scheme → Run → Arguments → **Launch Arguments** → 加 `-catalog`
2. ⌘R 跑 Debug build，app 啟動時 `BooksBrowserApp` 偵測到 `-catalog` 改用 `CatalogScene()` 為 root view（取代正常 `ContentView`）
3. simulator 開啟即見 Playbook catalog 列表，左側分類 / 右側渲染

要回正常 app：scheme 移除 `-catalog` 即可（建議**保留兩個 scheme**：`BooksBrowser` 正常、`BooksBrowser-Catalog` 含 launch arg）。

**目錄結構**：
- `ios/BooksBrowser/Debug/CatalogScene.swift` — 入口 view，註冊所有 surfaces 進 `Playbook.default`
- `ios/BooksBrowser/Debug/Scenarios/*Scenarios.swift` — 每個 surface 一檔，通過 `register(in:)` 加 scenarios

**目前涵蓋**（Phase 3 / 19 scenarios）：
- Settings × 6（Logged Out / Subscribed Active / Subscription Loading / Deleting Account / Pricing Unavailable / Debug Backend Local）
- Today Review × 4（Front / Back / Completed / Autoplay）
- Bookshelf × 5（Card Progress / Card Placeholder / Empty / With Books / Loading）
- Welcome × 4（Step 1 Capture / Step 2 Link / Step 3 Review / Step 3 Dark）

**未涵蓋**（留待 future phase）：
- Reader 本體（Readium SDK runtime 太重，需先抽 `ReaderViewPresenter` chrome layer）
- Podcast Player（需先拆 `PodcastPlayerPresenter`）
- Auth 多狀態（authenticating / error，需先把 `AuthManager` 抽 protocol）
- Vocab WordDetail（無現成 preview factory，待補 stub）

**新增 surface scenarios 範本**：

```swift
// ios/BooksBrowser/Debug/Scenarios/FooScenarios.swift
#if DEBUG
import Playbook
import SwiftUI

enum FooScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Foo") {
            Scenario("Loading", layout: .fill) {
                AppThemeContainer { FooView(state: .loading) }
                    .environmentObject(AppAppearanceStore.preview)
            }
            // ...
        }
    }
}
#endif
```

寫完別忘了在 `CatalogScene.playbook` 的 static initializer 加一行 `FooScenarios.register(in: pb)`。

**simctl 截圖協作**：

```bash
xcrun simctl io booted screenshot /tmp/kg-catalog-page.png
```

把 PNG 路徑貼給 Claude 即可協作視覺迭代。所有 catalog 程式碼都包在 `#if DEBUG` 內，**production binary 不包含**。



## 參考文件

- `docs/sop/ui-design.md` — Motion Contract + 設計系統規範
- `docs/sop/backend.md` — backend 開發主入口；跨前後端資料流問題時一起看
- `docs/reference/ui/components.md` — 現有 component / pattern inventory，開新 UI 前先查
- `docs/reference/ui/state_matrix.md` — 各主畫面 state coverage matrix，補 UX 時先查有哪些狀態不能漏
- `docs/sop/architecture.md` — 完整 iOS ↔ 後端同步協議、認證架構、資料模型詳解
