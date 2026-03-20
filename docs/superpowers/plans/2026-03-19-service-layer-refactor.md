# Service 層重構 — authenticatedRequest + RetryPolicy + 錯誤統一

Branch: `worktree-service-refactor`
Depends on: none
Commit Prefix: `ios:`
## Model: opus

## 目標

提取泛型 `authenticatedRequest<T: Decodable>` 方法，統一錯誤類型為 `KGAPIError`，加入 `RetryPolicy` 指數退避。預估可減少 ~300 行重複 API 呼叫模板。

## Tasks

### Task 1: 分析現有 API 模式

讀取以下檔案，理解 API 呼叫的完整模式：
- `ios/BooksBrowser/Services/KGService.swift`（主檔案）
- `ios/BooksBrowser/Services/KGService+VocabCRUD.swift`
- `ios/BooksBrowser/Services/KGService+Sync.swift`
- `ios/BooksBrowser/Services/KGService+Notebook.swift`
- `ios/BooksBrowser/Services/KGService+UserConfig.swift`
- `ios/BooksBrowser/Services/KGService+Stats.swift`
- `ios/BooksBrowser/Services/TranslationService.swift`

記錄：
1. 每個方法的 URL 構建方式
2. HTTP method (GET/POST/PUT/DELETE)
3. Request body 格式
4. Response 解碼方式
5. 錯誤處理方式
6. 哪些方法已有重試邏輯

### Task 2: 定義 KGAPIError

在 KGService.swift 或獨立檔案中定義：
```swift
enum KGAPIError: LocalizedError {
    case notAuthenticated
    case httpError(statusCode: Int, body: String?)
    case decodingError(underlying: Error)
    case networkError(underlying: Error)
    case serverError(message: String)
}
```

### Task 3: 實作 authenticatedRequest

在 KGService 中新增核心方法：
```swift
func authenticatedRequest<T: Decodable>(
    path: String,
    method: String = "GET",
    body: (any Encodable)? = nil,
    retryPolicy: RetryPolicy = .default
) async throws -> T
```

此方法統一處理：
- token 取得
- URLRequest 構建
- Authorization header
- JSON encode/decode
- HTTP status 檢查
- 錯誤包裝為 KGAPIError

另外新增 void 版本（用於不需要 response body 的 DELETE/PUT）：
```swift
func authenticatedVoidRequest(
    path: String,
    method: String,
    body: (any Encodable)? = nil,
    retryPolicy: RetryPolicy = .none
) async throws
```

### Task 4: 實作 RetryPolicy

```swift
struct RetryPolicy {
    let maxAttempts: Int
    let baseDelay: TimeInterval
    let retryableStatusCodes: Set<Int>

    static let none = RetryPolicy(maxAttempts: 1, baseDelay: 0, retryableStatusCodes: [])
    static let `default` = RetryPolicy(maxAttempts: 3, baseDelay: 1.0, retryableStatusCodes: [429, 500, 502, 503])
    static let aggressive = RetryPolicy(maxAttempts: 5, baseDelay: 0.5, retryableStatusCodes: [429, 500, 502, 503])
}
```

### Task 5: 遷移現有 API 方法

逐步將每個 KGService extension 中的方法改為使用 `authenticatedRequest`。

**關鍵原則**：
- 保持所有方法的外部 API 不變（方法名、參數、返回值）
- 只改內部實作
- 每改一個 extension 就確認編譯通過
- TranslationService 的 withRetry 移除，改用 RetryPolicy

### Task 6: 編譯驗證
- `./ops/ios_build.sh`

## Acceptance Criteria
- 所有 KGService API 方法使用 authenticatedRequest
- 錯誤統一為 KGAPIError
- RetryPolicy 可配置
- 外部 API 不變（呼叫端零改動）
- 編譯通過

## Files Modified
- `ios/BooksBrowser/Services/KGService.swift`
- `ios/BooksBrowser/Services/KGService+VocabCRUD.swift`
- `ios/BooksBrowser/Services/KGService+Sync.swift`
- `ios/BooksBrowser/Services/KGService+Notebook.swift`
- `ios/BooksBrowser/Services/KGService+UserConfig.swift`
- `ios/BooksBrowser/Services/KGService+Stats.swift`
- `ios/BooksBrowser/Services/TranslationService.swift`
