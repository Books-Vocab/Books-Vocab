# Auto-Sync — Design Spec

## Goal

讓 sync 對用戶「隱形化」— 開啟後，待收錄單字累積到閾值自動觸發完整 sync pipeline，用戶無需手動操作。

## 行為規格

```
用戶收詞/刪詞
    ↓
pendingCount 變化（SwiftData @Query）
    ↓
AutoSyncMonitor（ViewModifier on ContentView）
    ↓ debounce 2s
pendingCount >= 5 ?
    AND autoSyncEnabled ?
    AND syncCoordinator.phase != .running ?
    AND authManager.isLoggedIn && !isDemoMode ?
    AND networkMonitor.isConnected ?
    ↓ 全部滿足
syncCoordinator.startSync(pendingEntries:modelContext:kgService:)
    ↓ 完整 pipeline
push adds/deletes → trigger AI → push review → pull cards
    ↓ 靜默完成（失敗時用現有 toast）
```

## 元件拆解

### 1. `AutoSyncSettingsStore`

`@Observable` singleton + `UserDefaults`，遵循 `ReviewSettingsStore` 慣例。

```swift
@Observable
final class AutoSyncSettingsStore {
    static let shared = AutoSyncSettingsStore()
    
    private(set) var isEnabled: Bool  // UserDefaults key: "auto_sync_enabled", default: false
    
    func setEnabled(_ value: Bool)
}
```

- EnvironmentKey：`\.autoSyncSettingsStore`
- 閾值 hardcode `5`，以 `static let threshold = 5` 定義
- 預設關閉（`false`）— 不改變現有用戶行為

### 2. `AutoSyncMonitor`（ViewModifier）

```swift
struct AutoSyncMonitor: ViewModifier {
    @Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 })
    private var pendingEntries: [VocabularyEntry]
    
    @Environment(\.syncCoordinator) private var syncCoordinator
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService
    @Environment(\.modelContext) private var modelContext
    @Environment(\.autoSyncSettingsStore) private var autoSyncStore
    @Environment(\.toastCoordinator) private var toastCoordinator
    
    // NetworkMonitor is a singleton, accessed directly
    private let networkMonitor = NetworkMonitor.shared
    
    // onChange(of: pendingEntries.count) → debounce 2s → check all conditions → startSync
}
```

**掛載位置**：`BooksBrowserApp.rootView` 的 `ContentView()` 上。

**防抖**：`onChange` 觸發後 `Task.sleep(.seconds(2))`，期間若 count 再變化則重置 timer。debounce 結束後重新檢查所有條件（含 threshold），任一不滿足則不觸發。

**buildSteps**：呼叫 `startSync` 前須先呼叫 `syncCoordinator.buildSteps(deleteCount:addCount:)`，否則 pipeline steps 陣列為空。

**靜默**：成功不通知，失敗走現有 `toastCoordinator.warning()` 路徑。

### 3. Settings UI

在「偏好」section（`SettingsPreferencesSection`）的「複習節奏」下方新增一行：

```
┌──────────────────────────────────┐
│ 🔄 自動同步              [Toggle] │
└──────────────────────────────────┘
  收錄滿 5 個單字時自動同步到雲端。
```

- 只在 `isLoggedIn` 時顯示
- Toggle binding 到 `autoSyncStore.isEnabled`

## State 傳遞

`SettingsPresenterState.PreferencesSection` 新增：

```swift
var autoSyncEnabled: Bool
var showAutoSync: Bool  // isLoggedIn
```

`SettingsPresenterActions` 新增：

```swift
var toggleAutoSync: (Bool) -> Void
```

## 不做的事

- 可調閾值 — hardcode 5
- auto-sync 完成通知 — 靜默
- auto-sync 歷史紀錄 — 不需要
- iCloud KVS 同步設定 — 純本機偏好
