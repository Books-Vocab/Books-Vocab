<!-- doc-meta
tier: archive
authority: derived
update_trigger: manual
scope:
  - ios/BooksAndVocab/
  - ops/
verified_against: frozen
-->
# Build 可觀測性

基線日期: 2026-03-12

## 收集指令

量測規則：
- `xcodebuild` 本體必須維持 workspace SOP 指定的唯一合法指令
- 若要量時間，只能在外層包時間戳或 wrapper；不可改動 build 指令參數

執行以下方式收集 build 時間數據（從 repo root 執行）：

```bash
# 例：用外層 wrapper 量測兩次合法 build
python3 - <<'PY'
import subprocess, time
cmd = [
    'xcodebuild',
    '-project', 'ios/BooksAndVocab.xcodeproj',
    '-scheme', 'BooksAndVocab',
    '-destination', 'platform=iOS Simulator,name=iPhone 17 Pro Max',
    '-quiet', 'build'
]
for label in ('measured_build', 'warm_build'):
    start = time.time()
    proc = subprocess.run(cmd, cwd='.')
    print(label, round(time.time() - start, 2), proc.returncode)
    if proc.returncode != 0:
        break
PY
```

## Build 時間

| 類型 | 時間 |
|------|------|
| measured build | 4.95s |
| warm build | 2.89s |

## Bottleneck 分析

- 2026-03-12 本地量測未觀察到長時間卡住
- `xcodebuild` 兩次都穩定返回 `exit 0`
- 目前沒有明顯 compile / link / simulator bottleneck 訊號
- 若後續 build 明顯超過 30-60 秒，再另開慢建置調查並保留原始輸出

## 環境

| 項目 | 值 |
|------|----|
| Xcode 版本 | Xcode 26.3 (Build 17C529) |
| macOS 版本 | 15.6 (24G84) |
| 晶片 | Apple M4 |

## 更新紀錄

| 日期 | Incremental | Clean | 備註 |
|------|-------------|-------|------|
| 2026-03-12 | 4.95s | 2.89s（warm build） | 兩次 build 皆 `exit 0`，目前無明顯 bottleneck |

## 問題清單

### 環境問題

- 目前未觀察到穩定可重現的環境級阻塞

### 專案問題

- 目前未觀察到穩定可重現的 compile / link / simulator bottleneck
- 後續需在 build 顯著變慢時，再針對慢建置樣本補充問題清單
