<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: 74bf32da
-->
# BooksBrowser iOS 開發技能

## 核心資訊

- **專案路徑**: `ios/BooksBrowser.xcodeproj`
- **Scheme**: `BooksBrowser`
- **工作目錄**: repo root（`~/kg/`）
- **Destinations**: iOS 17+ / iPadOS 17+ / Mac Catalyst（macOS 15.0+，非原生 macOS）
- **平台抽象**: `Platform/PlatformRepresentable.swift`、`Platform/PlatformCompatibility.swift`

---

## 最高指導原則

**Exit Code `0` = 編譯成功，任務結束。不用懷疑。**

---

## Mac Catalyst 雷區（編譯過 ≠ 不崩）

Catalyst 是正式 target（Mac 走 Catalyst，非原生 macOS）。以下寫法**編譯通過但在 Catalyst runtime crash**，CI 由 `ops/catalyst_lint.sh` 擋：

- **`.popover` 掛在 `.toolbar` / `ToolbarItem` 的 Button 上** → present 過場走 UIKit `_pinInputViewsForKeyboardSceneDelegate`，scene 未就緒時 trap（`EXC_BREAKPOINT`，backtrace 全在 UIKitCore、無 app frame）。**改用 `.sheet`**（不同 presentation controller，亦免疫 popover resize 時的 willReposition recursion crash）。豁免：同行 `// catalyst-allow: <reason>`。
- 判讀法：`brk #1` + backtrace 唯一 app frame 是 `main` = framework trap，非 app force-unwrap；務必先取 lldb `bt`。

`ops/catalyst_lint.sh [--report|--strict]`，baseline 0 命中。

---

## iOS 編譯 3 步驟 SOP

### Step 1：靜默編譯，直擊錯誤

```bash
./ops/ios_build.sh                 # 預設 iPhone Simulator
./ops/ios_build.sh --catalyst      # Mac Catalyst（platform=macOS,variant=Mac Catalyst）
./ops/ios_build.sh --destination '<xcodebuild destination>'  # 自訂 destination
```

- Exit Code `0` → 完成，停止
- Exit Code 非 `0` → 畫面殘留的就是純淨錯誤清單，進 Step 2
- 動到三平台 navigation / Catalyst 專屬路徑時，`--catalyst` 與預設各跑一次驗證（`--timeout` 預設 600s）

### Step 2：還原案發現場

**不要只看單行錯誤就動手改。** 根據錯誤的**檔名 + 行號**，讀取該行**上下至少 20 行**原始碼，結合 Swift/SwiftUI 語法特性完整分析脈絡。

常見需要讀上下文的場景：
- `@ViewBuilder` 限制（return type、條件分支問題）
- Optional unwrap 導致的型別不符
- `@State` / `@Binding` / `@ObservableObject` 使用錯誤
- `async/await` 上下文缺失

### Step 3：對症下藥並驗證

修復後立刻重跑 Step 1。反覆「編譯 → 讀上下文 → 修改」直到 Exit Code 歸零。

## 發版 / TestFlight（`ops/ios_release.sh`）

App Store / TestFlight 出 `.ipa`。用 App Store Connect API key 的簽章基建，**無需手動匯入 Apple Distribution 憑證**（cert/profile 已一次性建置，含重建步驟見 `~/.secrets/apple/README.md`）。

```bash
./ops/ios_release.sh                  # archive + export 出 .ipa（無對外副作用，預設）
./ops/ios_release.sh --upload         # 額外上傳 → TestFlight（對外副作用，需明示）
./ops/ios_release.sh --key 6Y7DC88RUY # 換 ASC API key（預設 TCXVHFRXMS / App Manager）
./ops/ios_release.sh --timeout 900    # 自訂 build lock 等待秒數
```

- **產物**：`ios/build/export/BooksBrowser.ipa`（git-ignored）。
- **簽章**：manual signing — Apple Distribution cert（keychain）+ `KG App Store` profile（`ios/ExportOptions.plist`）。`method=app-store`（Xcode 26 印 deprecated 警告但可用；新式 `app-store-connect` 即使 manual 仍強制 Xcode 內登入 ASC account，純 CLI 不適用）。
- **build-number guard**：`--upload` 前比對本機 `CURRENT_PROJECT_VERSION`（`-target BooksBrowser`）與 TestFlight 最新 build，重複即中止 — 須先 bump 版號。archive/export 不受此限。
- **keychain 免互動**：codesign 存取私鑰需 partition list 授權（一次性 `security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <登入密碼> ~/Library/Keychains/login.keychain-db`）；未設則互動 terminal 彈授權框、背景/CI 會 hang。
- **key 選擇**：`TCXVHFRXMS`(App Manager) 可送審;`6Y7DC88RUY`(Developer) 僅 TestFlight。後端訂閱驗簽用 `6Y7DC88RUY`，**勿 revoke**。
- 共用 `ios_build.sh` 的 `/tmp/kg-ios-build.lock`，多 worktree 安全。

### App Store Connect 查詢 / 改文案（`ops/asc.sh`）

`ios_release.sh` 出 build；`asc.sh` 補「版本/審查狀態查詢 + 文案 metadata 讀寫」。純 codemagic CLI 包裝（同 `ios_release.sh` 的 `asc()` wrapper），無手刻 JWT。

```bash
./ops/asc.sh versions                    # 列 App Store 版本 + 審查 state（id）
./ops/asc.sh builds                      # TestFlight 最新 build number
./ops/asc.sh metadata --locale zh-Hant   # 讀某版本某語系文案（description/keywords/urls/…）
./ops/asc.sh info                        # app 層級唯讀（name/bundle/sku/primaryLocale）
./ops/asc.sh review-status               # 審查提交 state（最新=被拒會見 UNRESOLVED_ISSUES）
./ops/asc.sh set keywords "a,b,c"        # 改文案：預設 dry-run（印舊→新，不送出）
./ops/asc.sh set keywords "a,b,c" --yes  # 確認後真寫正式版本（對外副作用，須 --yes）
```

- **set 可寫 field**：`description / keywords / whats-new / marketing-url / support-url / promotional-text`。空值被擋（避免清空正式文案）。
- **dry-run gate**：`set` 預設只印 payload，`--yes` 才送 `app-store-version-localizations modify`（對齊 `--upload` 的明示原則）。
- **key**：預設 `TCXVHFRXMS`（App Manager，可寫 metadata）；`.p8` 路徑 `${ASC_KEY_DIR:-~/.secrets/apple}/AuthKey_<KEY_ID>.p8`（CI/部署機可覆寫 `ASC_KEY_DIR`）。

#### GUI 可讀 vs API 可讀

| GUI 區塊 | API/`asc.sh` 可讀? |
|---|---|
| 版本 / 審查 state / build / 文案 metadata / IAP / 分析數字 | ✅ |
| **被拒原因（Resolution Center 對話文字）** | ❌ public API 不提供，**只能 GUI 看** |
| category / 內容版權宣告 / 年齡分級（App 資訊頁） | ⚠ codemagic 未暴露，須 GUI 或 raw API（`asc.sh` 未實作） |

#### 被拒處理 SOP

1. `./ops/asc.sh review-status` 確認最新提交為 `UNRESOLVED_ISSUES`。
2. 到 ASC GUI「App 審查 → 解決中心」讀 Apple 的拒絕理由（API 讀不到）。
3. 改 code/文案（`asc.sh set …` 或改 app 碼）→ bump `CURRENT_PROJECT_VERSION` → `ios_release.sh --upload` → 重送。
4. 加密合規可順手：`ios/BooksBrowser/Info.plist` 設 `ITSAppUsesNonExemptEncryption=NO`（多數 app 免出口加密，省每次上傳被問）。

#### 已知缺口（待辦，本輪未工具化）

screenshots / app preview 上傳（codemagic 無此命令，須 GUI 或 Transporter）、IAP/訂閱 metadata（KG 有訂閱，審查常卡此）、**多語 localizations**（現僅 `zh-Hant`，缺 `en-US` 易被拒）、`appStoreVersions create`（重送下一版前須先建版本 row）、submit-for-review 自動化（刻意不做）。

## App 架構速查

### 主要 Services

| Service | 職責 |
|---------|------|
| `AuthManager.swift` | 單例，Apple/Google SSO、Keychain token、登入狀態 |
| `KGService.swift` | 後端 API 呼叫（拆 10 個 extension：+Graph / +Health / +Models / +Notebook / +Request / +ServerURL / +Stats / +Sync / +UserConfig / +VocabCRUD） |
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
- `Views/**/*.swift` 下所有 non-private `struct X: View`(排除 Debug/Scenarios、Readium/PDFReader bridging、ViewModifier、`#Preview` 內)已**全面注入三件套**(`import Inject` / `@ObserveInjection` / `.enableInjection()`)— 改任一 leaf view body 都能熱重載
- **可注入**：view body / modifier / layout / 文案 / `AppTheme` 色票 / padding / spacing / radius / shadow / opacity
- **不可注入(仍需 full build)**：stored property 增減、`@State` 初始值、function signature 改動、`enum` case 新增、`@Observable` macro 生成的 code(偶有時延)、Readium C++/ObjC++ bridging 改動、`UIViewRepresentable`

**自動化工具**：
- 新增 leaf view 後若忘加三件套,跑 `python3 ops/inject_codemod.py --apply` 自動補(idempotent)
- `ops/injection_lint.sh --strict` 守門:三規則 — (R1) 合格 View 必有 `@ObserveInjection`;(R2) 同檔 `@ObserveInjection` 數 == `.enableInjection()` 數;(R3) 有 `@ObserveInjection` 必有 `import Inject`
- 已知例外:body 為 `if` / `switch` 根 expression 時,codemod 跳過 — 手工包 `Group { ... }.enableInjection()`(現有 9 個 case 已處理完)

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
- `ios/BooksBrowser/Debug/CatalogScene.swift` — 入口 view + `static func buildPlaybook()`(BooksBrowserTests 也 reuse 同一份 surface registration)
- `ios/BooksBrowser/Debug/Scenarios/*Scenarios.swift` — 每個 surface 一檔，通過 `register(in:)` 加 scenarios

**目前涵蓋**（9 groups / 60 scenarios — 數字由 `CatalogCoverageTests` 把關，新增 surface 漏掉 `register(in:)` 會紅）：
- Settings × 6（Logged Out / Subscribed Active / Subscription Loading / Deleting Account / Pricing Unavailable / Debug Backend Local）
- Today Review × 4（Front / Back / Completed / Autoplay）
- Bookshelf × 5（Card Progress / Card Placeholder / Empty / With Books / Loading）
- Welcome × 4（Step 1 Capture / Step 2 Link / Step 3 Review / Step 3 Dark）
- Notebooks · Card × 4（Hero heavy / Hero fresh / Grid two-up / Hero long-name truncate）
- Notebooks · Stack × 22（stress / depth 1-4 層 / active·inactive × light·dark state / a11y / editorial seeds / cover composition）
- Notebook Detail · Row × 6（happy / long word truncate / long translation / 4-digit numbers / 320pt narrow / accessibility3）
- Notebook Detail · CTA Pill × 5（due only / unlearned only / both / large numbers / no-CTA）
- Design Tokens × 4（Palette light·dark / Typography / Radii & Spacing）

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

寫完別忘了在 `CatalogScene.buildPlaybook()` 加一行 `FooScenarios.register(in: pb)`，並把新 group 名加進 `CatalogCoverageTests.expectedGroups`（漏 register 會被該 test 擋紅）。

**simctl 截圖協作**：

```bash
xcrun simctl io booted screenshot /tmp/kg-catalog-page.png
```

把 PNG 路徑貼給 Claude 即可協作視覺迭代。所有 catalog 程式碼都包在 `#if DEBUG` 內，**production binary 不包含**。

### Catalog Snapshot Export（PlaybookSnapshot → PNG batch）

`BooksBrowserTests/CatalogSnapshotTests.swift` 提供 `generateAllScenarioPNGs` test，跑一次把 60 scenarios × 2 devices（iPhone15Pro portrait light/dark）渲染成 PNG，**不用人工逐頁截**。

**執行方式**（manual，**不要主動跑** — 遵守 CLAUDE.md 鐵律 7 `ios_test.sh` 規則）：

```bash
# 由使用者明確要求才跑：
xcodebuild test \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -only-testing:BooksBrowserTests/CatalogSnapshotTests
```

**從 simulator sandbox 撈 PNG**：

```bash
# 找 BooksBrowserTests host app 的 data container
container=$(xcrun simctl get_app_container booted com.Max0228.BooksBrowser data 2>/dev/null)
# PNG 在 NSTemporaryDirectory → tmp/kg-catalog-snapshots/<device>/<category>/<scenario>.png
find "$container/tmp/kg-catalog-snapshots" -name "*.png" 2>/dev/null
# 或直接複製到專案下供 Claude 讀
mkdir -p build/snapshots && cp -R "$container/tmp/kg-catalog-snapshots/." build/snapshots/
```

**為什麼 PlaybookSnapshot 而非 EmergeTools/SnapshotPreviews**：原本計畫用 EmergeTools 套件直接 snapshot 既有 `#Preview`，但 `playbook-ios` 內建 `PlaybookSnapshot` product 已能對 catalog scenarios 做同樣工作，且 catalog scenarios 明確、命名整齊、能注入 stub envObject — 比 raw `#Preview` 更可靠（後者常因缺 EnvironmentObject crash）。`#Preview` snapshot 留待 Phase 5 評估。

**閉環 demo**：
1. 你改 `AppTheme.swift` 一個 hue 值 + InjectionNext 秒級重渲染
2. 確認 catalog 樣式可接受後跑上述 `xcodebuild test`
3. 撈 PNG → 貼給 Claude → Claude 跨 scenario 比對找出視覺 regression
4. 不滿意回 step 1



## 參考文件

- `docs/sop/ui-design.md` — Motion Contract + 設計系統規範
- `docs/sop/backend.md` — backend 開發主入口；跨前後端資料流問題時一起看
- `docs/reference/ui/components.md` — 現有 component / pattern inventory，開新 UI 前先查
- `docs/reference/ui/state_matrix.md` — 各主畫面 state coverage matrix，補 UX 時先查有哪些狀態不能漏
- `docs/sop/architecture.md` — 完整 iOS ↔ 後端同步協議、認證架構、資料模型詳解
