# KGError Legacy Case 清理

Branch: `worktree-kgerror-cleanup`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 問題

KGError 有重複的 case（notAuthenticated ≡ unauthorized、networkError ≡ notConnected 等），造成呼叫端 catch 混亂。

## Tasks

### Task 1: 分析 KGError 使用
讀取 `ios/BooksBrowser/Services/KGService.swift`，找到 KGError enum 的完整定義。

然後搜尋所有 `KGError.` 使用點，了解：
- 哪些 case 被 throw
- 哪些 case 被 catch
- 哪些 case 從未使用

### Task 2: 合併重複 case
根據 Task 1 的分析：
- 如果 `unauthorized` 和 `notAuthenticated` 都被使用，保留 `notAuthenticated`，將所有 `unauthorized` 替換
- 如果 `notConnected` 和 `offline` 和 `networkError` 重複，統一為 `networkError`
- 如果 `tokenExpired` 等已被新的 authenticatedRequest 流程取代，移除

### Task 3: 移除 KGAPIError typealias
如果 `typealias KGAPIError = KGError` 存在且無人直接使用 KGAPIError，移除。
如果有使用，保留。

### Task 4: 編譯驗證
- `./ops/ios_build.sh`

## 注意
- 不要改變錯誤的語意，只是合併重複
- 如果某個 case 在 catch 端被明確匹配，確保替換後的 case 仍被捕獲

## Files Modified
- `ios/BooksBrowser/Services/KGService.swift`
- 可能的 catch 端檔案
