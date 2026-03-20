# Network Layer Unification — Phase 1 技術債清償

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除網路層 15+ 處 401 檢查重複、統一 auth middleware、細緻化 KGError，將每個 API 方法從 ~20 行 boilerplate 降至 ~5 行。

**Architecture:** 新增 `authenticatedRequest` 高階方法，集中處理 auth token 取得、Bearer header 注入、HTTP response 驗證（401 → unauthorized、5xx → 重試、decode 包裝）。KGError 新增 `httpError(Int, String)` case 取代通用 `serverError`。KGUserConfigClient 改用同一 middleware。

**Tech Stack:** Swift, Foundation URLSession, @Observable, async/await

---

## File Structure

| 動作 | 路徑 | 責任 |
|------|------|------|
| **Modify** | `Services/NetworkUtils.swift` | 新增 `authenticatedRequest` 高階方法 |
| **Modify** | `Services/KGService.swift` | KGError 新增 `httpError` case；移除 `applyAuth` |
| **Modify** | `Services/KGService+VocabCRUD.swift` | 使用 `authenticatedRequest` 重寫 4 個方法 |
| **Modify** | `Services/KGService+Notebook.swift` | 使用 `authenticatedRequest` 重寫 4 個方法 |
| **Modify** | `Services/KGService+Stats.swift` | 使用 `authenticatedRequest` 重寫 2 個方法 |
| **Modify** | `Services/KGService+Graph.swift` | 使用 `authenticatedRequest` 重寫 1 個方法 |
| **Modify** | `Services/KGService+Sync.swift` | 重寫 `pushReviewStates`、`pullCardsToLocal` |
| **Modify** | `Services/KGService+UserConfig.swift` | 重寫 3 個直接 HTTP 方法 |
| **Modify** | `Services/KGUserConfigClient.swift` | 改用 `authenticatedRequest` 邏輯 |
| **Create** | `ios/BooksBrowserTests/NetworkMiddlewareTests.swift` | 測試 middleware 行為 |
| *(out-of-scope)* | `Services/TranslationService.swift` | 獨立 service，使用 `TranslationError`，非 KGService 體系，留待 Phase 2 |

**行為變更說明：**
- 多個方法（deleteNotebook, deleteCard, archiveCard, pullGraphLinks）從 `== 200` 放寬到 `200...299`，符合 REST 慣例（server 可回 204 No Content）
- `pullCardsToLocal` 的 token 獲取時機從函式最開頭延後到 progress 顯示之後（低風險：僅影響過期 token 時使用者先看到 loading 提示再報錯）

---

### Task 1: 細緻化 KGError

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService.swift:285-309`

- [ ] **Step 1: 替換整個 KGError enum（新增 `httpError` case + `isRetryable`）**

完整替換 `KGError` enum（第 285-309 行），因為 `errorDescription` 的 exhaustive switch 需要包含新 case：

```swift
enum KGError: LocalizedError {
    case serverError(String)
    case httpError(statusCode: Int, detail: String)
    case notConnected
    case unauthorized
    case offline
    case tokenExpired

    var errorDescription: String? {
        switch self {
        case .serverError(let msg): return L10n.format("KG 伺服器錯誤：%@", msg)
        case .httpError(let code, let detail): return L10n.format("HTTP %d：%@", code, detail)
        case .notConnected: return L10n.string("KG 伺服器未連線")
        case .unauthorized: return L10n.string("未登入帳號或身份已過期")
        case .offline: return L10n.string("目前沒有網路連線")
        case .tokenExpired: return L10n.string("登入已過期，請重新登入")
        }
    }

    var isNetworkRelated: Bool {
        switch self {
        case .offline, .notConnected: return true
        default: return false
        }
    }

    var isRetryable: Bool {
        switch self {
        case .httpError(let code, _): return (500...599).contains(code)
        case .offline, .notConnected: return true
        default: return false
        }
    }
}
```

- [ ] **Step 2: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0（新增的 case 尚無使用者，不影響現有 switch）

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Services/KGService.swift
git commit -m "api: KGError 新增 httpError case + isRetryable 屬性"
```

---

### Task 2: 新增 `authenticatedRequest` middleware

**Files:**
- Modify: `ios/BooksBrowser/Services/NetworkUtils.swift`
- Modify: `ios/BooksBrowser/Services/KGService.swift:142-162`

- [ ] **Step 1: 在 KGService 新增 `authenticatedRequest` 方法**

在 `KGService.swift` 的 `// MARK: - Auth Helper` 區段，`applyAuth` 方法之後新增：

```swift
// MARK: - Authenticated Request Middleware

/// 統一的認證請求方法 — 集中處理 token 取得、401 攔截、response 驗證
/// - Parameters:
///   - path: API 路徑（如 "api/vocab"），將附加到 baseURL
///   - method: HTTP method，預設 GET
///   - queryItems: URL 查詢參數
///   - body: 請求 body（已編碼的 Data）
///   - onRetry: 重試回呼（給 UI 顯示重試狀態用）
/// - Returns: (Data, HTTPURLResponse) tuple
func authenticatedRequest(
    path: String,
    method: String = "GET",
    queryItems: [URLQueryItem]? = nil,
    body: Data? = nil,
    onRetry: ((Int, Int) -> Void)? = nil
) async throws -> (Data, HTTPURLResponse) {
    let token = try await currentAuthToken()

    guard var components = URLComponents(
        url: baseURL.appendingPathComponent(path),
        resolvingAgainstBaseURL: false
    ) else {
        throw KGError.serverError("Invalid URL for \(path)")
    }
    if let queryItems, !queryItems.isEmpty {
        components.queryItems = queryItems
    }
    guard let url = components.url else {
        throw KGError.serverError("Invalid URL for \(path)")
    }

    var request = URLRequest(url: url)
    request.httpMethod = method
    request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    if body != nil {
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    request.httpBody = body

    let (data, response) = try await withRetry(onRetry: onRetry) {
        try await sharedURLSession.data(for: request)
    }

    guard let httpResponse = response as? HTTPURLResponse else {
        throw KGError.serverError("Invalid response from \(path)")
    }

    if httpResponse.statusCode == 401 {
        throw KGError.unauthorized
    }

    return (data, httpResponse)
}

/// authenticatedRequest + 自動驗證 2xx + JSON decode
func authenticatedDecode<T: Decodable>(
    _ type: T.Type,
    path: String,
    method: String = "GET",
    queryItems: [URLQueryItem]? = nil,
    body: Data? = nil,
    onRetry: ((Int, Int) -> Void)? = nil
) async throws -> T {
    let (data, httpResponse) = try await authenticatedRequest(
        path: path, method: method, queryItems: queryItems,
        body: body, onRetry: onRetry
    )
    guard (200...299).contains(httpResponse.statusCode) else {
        throw KGError.httpError(
            statusCode: httpResponse.statusCode,
            detail: "\(method) \(path) failed"
        )
    }
    return try JSONDecoder().decode(type, from: data)
}

/// authenticatedRequest + 自動驗證 2xx（無 decode，用於 DELETE 等）
func authenticatedVoid(
    path: String,
    method: String = "GET",
    queryItems: [URLQueryItem]? = nil,
    body: Data? = nil
) async throws {
    let (_, httpResponse) = try await authenticatedRequest(
        path: path, method: method, queryItems: queryItems, body: body
    )
    guard (200...299).contains(httpResponse.statusCode) else {
        throw KGError.httpError(
            statusCode: httpResponse.statusCode,
            detail: "\(method) \(path) failed"
        )
    }
}
```

- [ ] **Step 2: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Services/KGService.swift
git commit -m "api: 新增 authenticatedRequest / authenticatedDecode / authenticatedVoid middleware"
```

---

### Task 3: 遷移 KGService+Notebook.swift

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+Notebook.swift`

- [ ] **Step 1: 重寫 fetchNotebooks**

```swift
func fetchNotebooks() async throws -> [KGNotebook] {
    try await authenticatedDecode([KGNotebook].self, path: "api/notebooks")
}
```

- [ ] **Step 2: 重寫 createNotebook**

```swift
func createNotebook(name: String, color: String? = nil) async throws -> KGNotebook {
    var body: [String: String] = ["name": name]
    if let color { body["color"] = color }
    return try await authenticatedDecode(
        KGNotebook.self,
        path: "api/notebooks",
        method: "POST",
        body: try JSONEncoder().encode(body)
    )
}
```

- [ ] **Step 3: 重寫 updateNotebook**

```swift
func updateNotebook(id: String, name: String? = nil, color: String? = nil) async throws -> KGNotebook {
    var body: [String: String] = [:]
    if let name { body["name"] = name }
    if let color { body["color"] = color }
    return try await authenticatedDecode(
        KGNotebook.self,
        path: "api/notebooks/\(id)",
        method: "PATCH",
        body: try JSONEncoder().encode(body)
    )
}
```

- [ ] **Step 4: 重寫 deleteNotebook**

```swift
func deleteNotebook(id: String) async throws {
    try await authenticatedVoid(path: "api/notebooks/\(id)", method: "DELETE")
}
```

- [ ] **Step 5: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 6: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+Notebook.swift
git commit -m "api: KGService+Notebook 遷移至 authenticatedRequest middleware"
```

---

### Task 4: 遷移 KGService+VocabCRUD.swift

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+VocabCRUD.swift`

- [ ] **Step 1: 重寫 deleteCard**

```swift
func deleteCard(word: String, notebookId: String) async throws {
    let encoded = word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word
    try await authenticatedVoid(
        path: "api/vocab/\(encoded)",
        method: "DELETE",
        queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
    )
}
```

- [ ] **Step 2: 重寫 archiveCard**

```swift
func archiveCard(word: String, archived: Bool, notebookId: String) async throws {
    let encoded = word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word
    try await authenticatedVoid(
        path: "api/vocab/\(encoded)/archive",
        method: "PATCH",
        queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
        body: try JSONEncoder().encode(["archived": archived])
    )
}
```

- [ ] **Step 3: 重寫 batchAdd**

```swift
func batchAdd(entries: [VocabularyEntry], notebookId: String = "default") async throws -> KGAddResponse {
    let payload = entries.map { entry in
        KGVocabEntry(
            word: entry.word,
            translation: entry.translation,
            context: entry.context,
            root_form: entry.rootForm
        )
    }
    return try await authenticatedDecode(
        KGAddResponse.self,
        path: "api/vocab",
        method: "POST",
        queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
        body: try JSONEncoder().encode(payload)
    )
}
```

- [ ] **Step 4: 重寫 triggerPipeline**

```swift
func triggerPipeline(notebookId: String = "default") async throws {
    try await authenticatedVoid(
        path: "api/pipeline",
        method: "POST",
        queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
    )
}
```

- [ ] **Step 5: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 6: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+VocabCRUD.swift
git commit -m "api: KGService+VocabCRUD 遷移至 authenticatedRequest middleware"
```

---

### Task 5: 遷移 KGService+Graph.swift 和 KGService+Stats.swift

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+Graph.swift`
- Modify: `ios/BooksBrowser/Services/KGService+Stats.swift`

- [ ] **Step 1: 重寫 pullGraphLinks**

```swift
func pullGraphLinks() async throws -> [KGGraphLink] {
    try await authenticatedDecode([KGGraphLink].self, path: "api/graph/links")
}
```

- [ ] **Step 2: 重寫 pushDailyStats**

```swift
func pushDailyStats(container: ModelContainer) async throws -> Int {
    let actor = BackgroundSyncActor(modelContainer: container)
    let payload = try await actor.buildDailyStatsPushPayload()
    guard !payload.isEmpty else { return 0 }

    struct PushResponse: Decodable { let upserted: Int }
    let result = try await authenticatedDecode(
        PushResponse.self,
        path: "api/vocab/daily-stats",
        method: "PATCH",
        body: try JSONSerialization.data(withJSONObject: ["entries": payload])
    )
    AppLog.kg.info("pushDailyStats: upserted=\(result.upserted)")
    return result.upserted
}
```

- [ ] **Step 3: 重寫 pullDailyStats**

```swift
func pullDailyStats(container: ModelContainer) async throws {
    struct StatsResponse: Decodable {
        struct Entry: Decodable {
            let day_key: String
            let total: Int
            let remembered: Int
            let forgot: Int
        }
        let entries: [Entry]
    }

    let decoded = try await authenticatedDecode(
        StatsResponse.self,
        path: "api/vocab/daily-stats"
    )
    guard !decoded.entries.isEmpty else { return }

    let remoteStats: [[String: Any]] = decoded.entries.map {
        ["day_key": $0.day_key, "total": $0.total, "remembered": $0.remembered, "forgot": $0.forgot]
    }
    let actor = BackgroundSyncActor(modelContainer: container)
    try await actor.mergeDailyStats(remoteStats)
    AppLog.kg.info("pullDailyStats: merged \(decoded.entries.count) remote entries")
}
```

- [ ] **Step 4: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+Graph.swift ios/BooksBrowser/Services/KGService+Stats.swift
git commit -m "api: KGService+Graph & +Stats 遷移至 authenticatedRequest middleware"
```

---

### Task 6: 遷移 KGService+Sync.swift（pushReviewStates + pullCardsToLocal）

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+Sync.swift:11-46, 51-131`

- [ ] **Step 1: 重寫 pushReviewStates**

```swift
func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) {
    let actor = BackgroundSyncActor(modelContainer: container)
    let payload = try await actor.buildReviewStatePushPayload()
    guard !payload.isEmpty else { return (0, 0) }

    struct PushResponse: Decodable {
        let updated: Int
        let skipped: Int
    }
    let result = try await authenticatedDecode(
        PushResponse.self,
        path: "api/vocab/review",
        method: "PATCH",
        body: try JSONSerialization.data(withJSONObject: ["entries": payload])
    )
    AppLog.kg.info("pushReviewStates: updated=\(result.updated), skipped=\(result.skipped)")
    return (result.updated, result.skipped)
}
```

- [ ] **Step 2: 重寫 pullCardsToLocal**

`pullCardsToLocal` 比較特殊 — 需要讀取 response header (`X-Pipeline-Pending`) 和複雜的 query 參數建構。使用 `authenticatedRequest` 而非 `authenticatedDecode`：

```swift
@discardableResult
func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)? = nil, notebookId: String? = nil) async throws -> Bool {
    progress?(L10n.string("從遠端下載知識庫..."), 0, 0)

    let defaults = UserDefaults.standard
    let storedPayloadVersion = defaults.integer(forKey: SyncKeys.payloadVersion)
    if storedPayloadVersion < SyncKeys.currentPayloadVersion {
        defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
        progress?(L10n.string("升級卡片資料格式，重新同步全部卡片..."), 0, 0)
    }

    let lastSyncMillis = defaults.double(forKey: SyncKeys.incrementalBoundary)
    let isIncremental = lastSyncMillis > 0

    var queryItems: [URLQueryItem] = []
    if let notebookId {
        queryItems.append(URLQueryItem(name: "notebook_id", value: notebookId))
    }
    if isIncremental {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let dateString = formatter.string(from: Date(timeIntervalSince1970: lastSyncMillis))
        queryItems.append(URLQueryItem(name: "since", value: dateString))
        AppLog.kg.info("Performing incremental sync since: \(dateString)")
    } else {
        AppLog.kg.info("Performing full sync")
    }

    // Bug A fix: 記錄邊界在發起請求前，避免 pull 期間新增的卡片被跳過
    let pullBoundary = Date().timeIntervalSince1970

    let (data, httpResponse) = try await authenticatedRequest(
        path: "api/vocab",
        queryItems: queryItems.isEmpty ? nil : queryItems
    )

    guard httpResponse.statusCode == 200 else {
        throw KGError.httpError(statusCode: httpResponse.statusCode, detail: "GET api/vocab failed")
    }

    progress?(L10n.string("解析資料..."), 0, 0)
    let fetchedCards: [KGCard]
    do {
        fetchedCards = try JSONDecoder().decode([KGCard].self, from: data)
    } catch {
        AppLog.kg.error("Failed to decode KG cards: \(error.localizedDescription)")
        throw KGError.serverError("Parse error: \(error.localizedDescription)")
    }

    let actor = BackgroundSyncActor(modelContainer: container)
    try await actor.pullCardsToLocal(
        fetchedCards: fetchedCards,
        isIncremental: isIncremental,
        progress: { detail, current, total in
            progress?(detail, current, total)
        },
        notebookId: notebookId ?? "default"
    )

    defaults.set(pullBoundary, forKey: SyncKeys.incrementalBoundary)
    defaults.set(SyncKeys.currentPayloadVersion, forKey: SyncKeys.payloadVersion)

    return httpResponse.value(forHTTPHeaderField: "X-Pipeline-Pending") == "true"
}
```

- [ ] **Step 3: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+Sync.swift
git commit -m "api: KGService+Sync 遷移至 authenticatedRequest middleware"
```

---

### Task 7: 遷移 KGService+UserConfig.swift

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+UserConfig.swift:93-187`

- [ ] **Step 1: 重寫 fetchEntitlements、syncAppStoreSubscription、deleteAccount**

```swift
func fetchEntitlements() async throws -> KGEntitlements {
    let result = try await authenticatedDecode(KGEntitlements.self, path: "api/user/entitlements")
    AppLog.kg.info("Fetched entitlements successfully")
    return result
}

func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements {
    let result = try await authenticatedDecode(
        KGEntitlements.self,
        path: "api/billing/app-store/sync",
        method: "POST",
        body: try JSONEncoder().encode(snapshot)
    )
    AppLog.kg.info("Synced App Store subscription successfully")
    return result
}

func deleteAccount() async throws {
    try await authenticatedVoid(path: "api/user/account", method: "DELETE")
}
```

注意：`fetchUserConfig`、`updateOptionalIntegrationKey`、`updateTranslationConfig` 透過 `userConfigClient` 委派，暫不修改。

- [ ] **Step 2: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+UserConfig.swift
git commit -m "api: KGService+UserConfig 遷移至 authenticatedRequest middleware"
```

---

### Task 8: 遷移 KGUserConfigClient

**Files:**
- Modify: `ios/BooksBrowser/Services/KGUserConfigClient.swift`

- [ ] **Step 1: 重寫 perform 方法使用共用邏輯**

KGUserConfigClient 是獨立物件（非 KGService extension），無法直接用 `authenticatedRequest`。但可以統一 response 處理邏輯。保持其獨立性，但消除手動 `Bearer` 設定：

```swift
final class KGUserConfigClient: KGUserConfigRemoteHandling {
    func fetchUserConfig(baseURL: URL, token: String) async throws -> KGUserConfig {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/user/config"))
        Self.applyAuth(to: &request, token: token)
        return try await perform(request)
    }

    func updateOptionalIntegrationKey(baseURL: URL, token: String, apiKey: String) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(
            integrations: KGUserIntegrationsConfig(
                mochi: KGOptionalIntegrationProviderConfig(api_key: apiKey)
            ),
            translation: nil
        )
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    func updateTranslationConfig(baseURL: URL, token: String, translation: KGTranslationConfig) async throws -> KGUserConfig {
        let patch = KGUserConfigPatch(integrations: nil, translation: translation)
        return try await update(baseURL: baseURL, token: token, patch: patch)
    }

    private func update(baseURL: URL, token: String, patch: KGUserConfigPatch) async throws -> KGUserConfig {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/user/config"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        Self.applyAuth(to: &request, token: token)
        request.httpBody = try JSONEncoder().encode(patch)
        return try await perform(request)
    }

    private static func applyAuth(to request: inout URLRequest, token: String) {
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    private func perform(_ request: URLRequest) async throws -> KGUserConfig {
        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }
        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.httpError(statusCode: httpResponse.statusCode, detail: "user config request failed")
        }
        return try JSONDecoder().decode(KGUserConfig.self, from: data)
    }
}
```

- [ ] **Step 2: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Services/KGUserConfigClient.swift
git commit -m "api: KGUserConfigClient 統一使用 httpError + applyAuth helper"
```

---

### Task 9: 遷移 healthCheck 並清理 applyAuth

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService.swift:160-221`

- [ ] **Step 1: 重寫 healthCheck 使用 authenticatedRequest**

```swift
func healthCheck() async {
    guard NetworkMonitor.shared.isConnected else {
        isConnected = false
        return
    }
    guard await authSession.isLoggedIn else {
        isConnected = false
        return
    }
    do {
        let (data, httpResponse) = try await authenticatedRequest(path: "api/health")

        if httpResponse.statusCode != 200 {
            isConnected = false
            return
        }

        let health = try JSONDecoder().decode(KGHealthResponse.self, from: data)
        isConnected = health.status == "ok"
        serverCardCount = health.cards

        if let lastModStr = health.lastModified {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            lastSyncDate = formatter.date(from: lastModStr)
        }
    } catch KGError.unauthorized {
        AppLog.kg.error("Health check failed: 401 Unauthorized")
        await handleUnauthorized(modelContainer: nil, reason: "healthcheck_401")
        isConnected = false
    } catch {
        isConnected = false
        AppLog.kg.error("Health check failed: \(error.localizedDescription)")
    }
}
```

- [ ] **Step 2: 移除 `applyAuth` 方法**

從 KGService.swift 刪除第 160-162 行的 `applyAuth(to:token:)` 方法。此方法已無使用者。

- [ ] **Step 3: 編譯確認**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/KGService.swift
git commit -m "api: healthCheck 遷移至 authenticatedRequest，移除 applyAuth"
```

---

### Task 10: 驗證 & 最終清理

**Files:**
- All modified files

- [ ] **Step 1: 全專案編譯**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 2: 搜尋殘留的直接 401 檢查**

確認所有 `statusCode == 401` 已從 KGService extension 檔案中移除，僅剩 middleware 和 KGUserConfigClient 中的集中處理：

```bash
grep -n "statusCode == 401" ios/BooksBrowser/Services/KG*.swift
```

Expected: 2 處 — `KGService.swift` 的 `authenticatedRequest` middleware + `KGUserConfigClient.swift` 的 `perform` 方法。

- [ ] **Step 3: 搜尋殘留的直接 Bearer token 設定**

```bash
grep -n '"Bearer ' ios/BooksBrowser/Services/*.swift
```

Expected: 3 處 — `KGService.swift` 的 `authenticatedRequest` + `KGUserConfigClient.swift` 的 `applyAuth` + `TranslationService.swift`（out-of-scope，留待 Phase 2）。

- [ ] **Step 4: 行數對比**

統計遷移前後的總行數變化，確認 boilerplate 有效減少。

- [ ] **Step 5: Commit（如有清理）**

```bash
git add -A
git commit -m "api: network middleware 遷移完成，清理殘留 boilerplate"
```

---

## 預期成果

| 指標 | 遷移前 | 遷移後 |
|------|--------|--------|
| `statusCode == 401` 檢查 | 15+ 處 | 2 處（middleware + KGUserConfigClient） |
| `Bearer \(token)` 設定 | 17+ 處 | 2 處 |
| `guard let httpResponse` 檢查 | 15+ 處 | 2 處 |
| 每個 API 方法行數 | ~15-20 行 | ~3-8 行 |
| KGError 粒度 | 通用 serverError | httpError(statusCode, detail) |
