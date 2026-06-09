<!-- doc-meta
tier: reference
authority: source-of-truth
update_trigger: manual
scope:
  - ops/ios_build.sh
  - ops/ios_test.sh
  - ops/ios_clean_derived_data.sh
verified_against: 2026-06-09
-->
# iOS DerivedData 政策（多 worktree 環境）

事件日期: 2026-06-09 · 對應 commit: `03f6f913`

給在 worktree 內跑 iOS build/test 的 agent：**這份說明為什麼 DerivedData 不放 Xcode 預設位置，以及你不該怎麼破壞它。**

## TL;DR
- iOS build 的 DerivedData 一律走 **單一共享快取**：`<主repo>/.cache/ios-build-derived-data`，由 `git-common-dir` 錨定，所有 worktree 解析到同一路徑。
- **不要**自己呼叫不帶 `-derivedDataPath` 的 `xcodebuild`，也不要改 `ops/ios_build.sh` 移除該旗標。那會讓快取掉回 Xcode 全域預設位置，每個 worktree 路徑生一份孤兒。
- build / test 共用 `/tmp/kg-ios-build.lock` 序列化，共享快取**不會**並行寫壞。

## 問題：110G 孤兒洩漏

`xcodebuild` 不帶 `-derivedDataPath` 時，產物落在
`~/Library/Developer/Xcode/DerivedData/<scheme>-<路徑雜湊>/`。
這個雜湊**只取決於 `.xcodeproj` 的絕對路徑**（[pewpewthespells: DerivedData Hashes](https://pewpewthespells.com/blog/xcode_deriveddata_hashes.html)）。

我們的工作流會在 `.claude/worktrees/<name>/` 大量開後即丟的 worktree，每個都是新路徑：

```
/Users/.../project/kg/.claude/worktrees/podcast-highlight-align/ios/BooksBrowser.xcodeproj  → BooksBrowser-aahl...
/Users/.../project/kg/.claude/worktrees/ios-word-capture-normalize/ios/...                   → BooksBrowser-acbg...
... ×252
```

`git worktree remove` 砍掉 worktree，但全域 DerivedData 的那份**留下來變孤兒**。實測 9 天（6/1–6/9）累積 **252 份 / 110G**，全是同一個 BooksBrowser 專案。

### 附帶誤導：`XCTestDevices` 的 155G 是假的
`du` 報 `~/Library/Developer/XCTestDevices` 155G，但刪光只釋出約 5G。原因是 UI test 的 runner 模擬器是系統 runtime 的 **APFS clone（copy-on-write）**，多份共享同一批磁碟 block，`du` 對每份重複計算（[APFS clone 機制](https://eclecticlight.co/2025/04/07/how-robust-are-apfs-clone-and-sparse-files/)）。**判讀 Xcode 空間時，clone 目錄的 `du` 數字不可信，以實際 `df` 釋出量為準。**

## 為什麼選「共享」而非「worktree-local」

兩種結構性消除孤兒的方案：

| | worktree-local（`$PROJECT_ROOT/.cache`） | **共享固定路徑（採用）** |
|---|---|---|
| 孤兒 | 無（隨 worktree 刪） | 無（單一固定目錄，名字不隨路徑變） |
| 磁碟 | 每 worktree 一份，短期暴增 | 一份，有界 |
| ModuleCache / incremental | 每 worktree 從零重建 | 跨 worktree 重用 |
| 並行安全 | 天然隔離 | 靠既有 `/tmp/kg-ios-build.lock` 序列化 |
| 代價 | 大量冗餘編譯 | 連續兩次 build 跨差異大 branch 時局部 incremental 失效（自癒、有界） |

關鍵：build 本來就被 `/tmp/kg-ios-build.lock` **全域序列化**，所以「並行寫壞共享快取」的疑慮不存在——共享在磁碟與速度上同時勝出。worktree-local 只有在「同一 worktree 反覆 build 很多次且彼此不互通」時才划算，與我們「開很多、各 build 幾次」的模式相反。

## 實作（`ops/ios_build.sh`）

```bash
if [[ -n "${KG_IOS_BUILD_DERIVED_DATA_ROOT:-}" ]]; then
  DERIVED_DATA_ROOT="$KG_IOS_BUILD_DERIVED_DATA_ROOT"
else
  GIT_COMMON_DIR="$(git -C "$PROJECT_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON_DIR" && -d "$GIT_COMMON_DIR" ]]; then
    DERIVED_DATA_ROOT="$(dirname "$GIT_COMMON_DIR")/.cache/ios-build-derived-data"
  else
    DERIVED_DATA_ROOT="$PROJECT_ROOT/.cache/ios-build-derived-data"   # fallback：解析失敗退回 worktree-local，不讓 build 壞
  fi
fi
xcodebuild ... -derivedDataPath "$DERIVED_DATA_ROOT" ...
```

`git-common-dir` 從主 repo 或任何 worktree 都解析到同一個 `kg/.git`，`dirname` 後即主 repo 根；`.cache/` 已 gitignore。

### 全腳本覆蓋（2026-06-09 稽核：每個會編譯的 xcodebuild 都須釘 `-derivedDataPath`）
| 腳本 / 指令 | DerivedData | 備註 |
|---|---|---|
| `ios_build.sh` build | `.cache/ios-build-derived-data`（共享） | 主修點 |
| `ios_test.sh` build-for-testing | `.cache/ios-test-derived-data/<content-key>` | content-keyed warm cache |
| `ios_test.sh` `test`（cache-miss 後備） | 同上 | 2026-06-09 補釘，原本漏到全域 |
| `ios_test.sh` test-without-building | 走 `-xctestrun`（不編譯） | 免釘 |
| `ios_release.sh` archive | `.cache/ios-release-derived-data`（共享） | 2026-06-09 補釘；與 Debug 分開避免互相 invalidate |
| `ios_ops_catalog.sh` build-for-testing | 已釘 `-derivedDataPath` | catalog snapshot |

三份共享快取(build / test / release)都靠 `/tmp/kg-ios-build.lock` 同一把鎖序列化,不會並行寫壞。

## 驗證證據（2026-06-09）
- 冷編 **88.6s** → 二次無改動 incremental **4.96s（18× 加速）**：共享快取確實重用。
- 產物落在 `kg/.cache/ios-build-derived-data`（1.3G）；全域預設**零新孤兒**。
- 主 repo 與 worktree 解析到同一路徑。
- 清掉舊孤兒後可用空間 24Gi → **124Gi**。

## 維運
- 清舊孤兒 / 壞模擬器：`./ops/ios_clean_derived_data.sh`（預設 dry-run，`--apply` 才刪，`--days N` 控年齡門檻）。
- 換 Xcode 版本後若 incremental 行為異常：刪 `kg/.cache/ios-build-derived-data` 重新冷編即可（純可重建）。

## Agent 守則
1. 跑 iOS build 一律經 `./ops/ios_build.sh`，**不要**自己拼 `xcodebuild`。
2. 不要把 `-derivedDataPath` 從 build/test 指令拿掉。
3. 看到 `~/Library/Developer/Xcode/DerivedData/BooksBrowser-*` 又開始增生 = 有人繞過了腳本，回頭查。
