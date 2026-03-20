# RetryPolicy Retry-After Header 支援

Branch: `worktree-retry-after`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 問題

RetryPolicy 收到 HTTP 429 時用固定指數退避（1s→2s），忽略伺服器的 Retry-After header。

## Tasks

### Task 1: 讀取現有 RetryPolicy
讀取 `ios/BooksBrowser/Services/KGService.swift`，找到 RetryPolicy struct 和 authenticatedRequest 的 retry 迴圈。

### Task 2: 修改 retry 迴圈支援 Retry-After
在 retry 迴圈中，當 status code 為 429 時：
1. 檢查 response header `Retry-After`
2. 如果有值且可解析為秒數，用該值作為延遲（cap 在 60 秒以內，避免伺服器要求過長等待）
3. 如果無 Retry-After header，fallback 到原有指數退避

不需要改 RetryPolicy struct，只改 retry 迴圈內的延遲計算。

### Task 3: 編譯驗證
- `./ops/ios_build.sh`

## Files Modified
- `ios/BooksBrowser/Services/KGService.swift`
