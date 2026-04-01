<!-- doc-meta
tier: operational
scope:
  - ios/BooksBrowser
  - ops
verified_against: 05acfbf
-->
# BooksBrowser iOS 開發技能

## 核心資訊

- **專案路徑**: `ios/BooksBrowser.xcodeproj`
- **Scheme**: `BooksBrowser`
- **工作目錄**: `projects/kg/`
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



## 參考文件

- `docs/dev/ui-design.md` — Motion Contract + 設計系統規範
- `docs/dev/backend-dev.md` — backend 開發主入口；跨前後端資料流問題時一起看
- `docs/references/ui_component_pattern_inventory.md` — 現有 component / pattern inventory，開新 UI 前先查
- `docs/references/ui_state_matrix.md` — 各主畫面 state coverage matrix，補 UX 時先查有哪些狀態不能漏
- `docs/dev/architecture.md` — 完整 iOS ↔ 後端同步協議、認證架構、資料模型詳解
