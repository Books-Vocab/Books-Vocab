# BooksBrowser iOS 開發技能

## 核心資訊

- **專案路徑**: `booksbrowser_ios/BooksBrowser.xcodeproj`
- **Scheme**: `BooksBrowser`
- **工作目錄**: `/Users/chenliangyu/Desktop/MultiProjectServerOps/projects/booksbrowser_workspace/`
- **最低支援**: iOS（參考 Info.plist，當前目標為現代 iOS）

---

## 最高指導原則

**Exit Code `0` = 編譯成功，任務結束。不用懷疑。**

---

## iOS 編譯 3 步驟 SOP

### Step 1：靜默編譯，直擊錯誤

```bash
xcodebuild \
  -project booksbrowser_ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -quiet build
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

---

## 常見 Swift/SwiftUI 錯誤模式

### 錯誤 1：`Type () cannot conform to View`
**原因**：`@ViewBuilder` 中 if/else 分支之一沒有回傳 View，或 `forEach`/`map` 被誤用為 `ForEach`
```swift
// ❌ 錯誤：ForEach 用了 Array.map
children.map { item in SomeView(item) }

// ✅ 正確
ForEach(children) { item in SomeView(item) }
```

### 錯誤 2：`Value of optional type 'X?' must be unwrapped`
```swift
// ❌
Text(user.name)  // user 是 Optional

// ✅ 用 if let 或 ?? 預設值
if let name = user?.name { Text(name) }
Text(user?.name ?? "Unknown")
```

### 錯誤 3：`Cannot convert value of type 'X' to expected argument type 'Binding<X>'`
```swift
// ❌ 傳了 var 而不是 $binding
TextField("Name", text: user.name)

// ✅
TextField("Name", text: $user.name)
```

### 錯誤 4：`actor-isolated property cannot be referenced from main actor`
```swift
// ✅ 加 @MainActor 或用 await MainActor.run { }
await MainActor.run { self.someUIState = newValue }
```

### 錯誤 5：`Missing return in closure expected to return 'some View'`
```swift
// ❌ ViewBuilder 中 if 沒有 else
var body: some View {
    if condition { Text("A") }
    // 少了 else 分支
}

// ✅
var body: some View {
    if condition { Text("A") } else { EmptyView() }
}
```

---

## App 架構速查

### 主要 Services

| Service | 職責 |
|---------|------|
| `AuthManager.swift` | 單例，Apple/Google SSO、Keychain token、登入狀態 |
| `KGService.swift` | 所有後端 API 呼叫（vocab CRUD、pipeline、config） |
| `BackgroundSyncActor` | Swift actor，把遠端單字寫入 SwiftData（增量/全量） |

### 主要 Views

| View | 說明 |
|------|------|
| `Settings/SettingsView` | 登入登出、伺服器設定、Mochi key 設定 |
| `Reader/ReaderView` | EPUB 閱讀器，查詞 → batchAdd → triggerPipeline |
| `Vocabulary/` | 單字瀏覽、知識圖譜視覺化、手動同步 |

### iOS 資料同步流程

```
Reader 查詞
  → 暫存 VocabularyEntry（syncStatus=0, pending）
  → POST /api/vocab（batchAdd）→ 伺服器生成 embedding
  → POST /api/pipeline（fire-and-forget）→ 伺服器背景 Enrich/Link/Mochi
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

---

## UI 設計

任何 Liquid Glass / SwiftUI UI 設計需求 → 使用 **`bb-ui-design`** skill（已獨立為 UI 設計技能）。

---

## 常用調試技巧

### 確認 API 連線（模擬器中）
App 的 `KGService` 透過 `Settings → Knowledge Graph → 伺服器位址` 設定。
確認設定的是 `https://wordnexus.lol`，Info.plist 的 `NSExceptionDomains` 包含該域名。

### 確認 SwiftData 狀態
在 `BackgroundSyncActor` 加 print，觀察 `kg_last_incremental_sync` 時間戳與 `syncStatus` 狀態。

### 模擬器快取問題
```bash
# 刪除模擬器 App（清除本地 SwiftData）
# 在 Simulator → 長按 App → Delete App，然後重新 build
```

---

## 參考文件

- **UI 設計相關** → `bb-ui-design` skill（iOS 26 Liquid Glass 完整 API）
- `booksbrowser_ios/Architecture.md` — 完整 iOS ↔ 後端同步協議、認證架構、資料模型詳解

