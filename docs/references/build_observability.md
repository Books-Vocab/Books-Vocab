# Build 可觀測性

基線日期: 2026-03-12

## 收集指令

執行以下指令收集 build 時間數據（從 `projects/kg/` 目錄執行）：

```bash
# Incremental build
time xcodebuild \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -quiet build 2>&1

# Clean build
xcodebuild \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser clean 2>&1 > /dev/null

time xcodebuild \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -quiet build 2>&1

# Bottleneck 分析（build time > 60s 時使用）
xcodebuild \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -showBuildTimingSummary \
  -quiet build 2>&1
```

## Build 時間

| 類型 | 時間 |
|------|------|
| Incremental | — |
| Clean | — |

*填入實際執行結果*

## Bottleneck 分析

（執行 `-showBuildTimingSummary` 後填入）

## 環境

| 項目 | 值 |
|------|----|
| Xcode 版本 | Xcode 26.3 (Build 17C529) |
| macOS 版本 | 15.6 (24G84) |
| 晶片 | Apple M4 |

## 更新紀錄

| 日期 | Incremental | Clean | 備註 |
|------|-------------|-------|------|
| 2026-03-12 | — | — | 基線建立，待首次執行填入 |
