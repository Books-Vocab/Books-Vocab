<!-- doc-meta
tier: reference
authority: source-of-truth
update_trigger: manual
scope:
  - ops/ios_build.sh
  - ops/ios_test.sh
  - ops/ios_clean_derived_data.sh
verified_against: 9f4b94637
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
/Users/.../project/kg/.claude/worktrees/podcast-highlight-align/ios/BooksAndVocab.xcodeproj  → BooksAndVocab-aahl...
/Users/.../project/kg/.claude/worktrees/ios-word-capture-normalize/ios/...                   → BooksAndVocab-acbg...
... ×252
```

`git worktree remove` 砍掉 worktree，但全域 DerivedData 的那份**留下來變孤兒**。實測 9 天（6/1–6/9）累積 **252 份 / 110G**，全是同一個 Books & Vocab iOS 專案。

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
| `ios_test.sh` build-for-testing | `.cache/ios-test-derived-data/<content-key>` | content-keyed warm cache；key 明確包含 Debug/Release configuration，兩者不可共用 products |
| `ios_test.sh` `test`（cache-miss 後備） | 同上 | 2026-06-09 補釘，原本漏到全域 |
| `ios_test.sh` test-without-building | 走 `-xctestrun`（不編譯） | 免釘 |
| `ios_release.sh` archive | `.cache/ios-release-derived-data`（共享） | 2026-06-09 補釘；與 Debug 分開避免互相 invalidate |
| `ios_ops_catalog.sh` build-for-testing | 已釘 `-derivedDataPath` | catalog snapshot |

三份共享快取(build / test / release)都靠 `/tmp/kg-ios-build.lock` 同一把鎖序列化,不會並行寫壞。

## 並行測試(2026-06-09 細粒度鎖 + 模擬器 pool)

**量測動機**:舊版 `ios_test.sh` 持鎖跑完整段測試執行,實測 3 併發時第 2/3 個 agent 等 246s/309s(資料在 `.cache/ios-run-metrics.jsonl`,每次 build/test/release append 一行 timings)。

**改動**:
- **細粒度鎖**:`/tmp/kg-ios-build.lock` 只在 `build-for-testing`(共享 DerivedData 唯一寫者)期間持有;`test-without-building` 執行階段**不持鎖**。`release_build_lock` 為 ownership-guarded(鎖檔內容 == `$$` 才刪),`rebuild_test_cache` 內 double-checked locking(取鎖後重驗 ready 則跳過),避免重複建與覆寫他人正讀的產物。
- **同裝置執行鎖**:`test-without-building` 另會經 `/tmp/kg-ios-test-device-<selector-hash>.lock` 序列化同一台 simulator。這層不是保護 DerivedData，而是保護 simulator runtime/app state：兩個 warm-cache run 若都瞄準同一台預設機器，現在會在 `deviceRunLockWaitMs` 排隊，而不是互撞。
- **agent/CI 預設拒絕共享 simulator**:在 `/.codex/worktrees/`、`WORKTREE_BRANCH` 或 `CI` 上，若測試 run 仍打共享預設 simulator，`ios_test.sh` 會直接 fail-fast，要求 `--lease` / `--device` / `--destination`。只有單機除錯才可用 `KG_IOS_TEST_ALLOW_SHARED_SIM=1` 明示 opt-out；目的不是功能限制，而是把原本隱性序列化與共享 state 風險前置成明確操作契約。
- **完成 sentinel** `.kg-test-cache-complete`:build 成功才在持鎖下寫;hit 偵測(`ios_test_cache_is_complete`)與 double-check 都要求它。`-d` 目錄檢查無法區分「完整」與「中斷留下的 half-written bundle」,sentinel 是 build 真完成的證明——中斷的 build 不寫 sentinel,下個 agent 重建而非吃毒化 cache。
- **platform/arch cache key**:test cache key 用 platform token + arch(非具體裝置名),pool 各模擬器共享一份暖 build cache。
- **模擬器 pool**:`./ops/ios_ops.sh simulator lease`/`release`,有界 pool `kg-pool-1..N`(env `KG_IOS_SIM_POOL_SIZE` 預設 3)。mkdir 原子租借 + `mv` 原子回收 stale(TTL `KG_IOS_SIM_LEASE_TTL` 預設 1800s)；**stale 判斷先看 owner pid 是否仍存活**，live run 不會因 TTL 被回收。lease 另帶 owner token，cleanup release 只會刪自己的 slot，不會因為知道同一個 UDID 就清掉別人的 lease。這是當初失控的 155G XCTestDevices clone 的**有界、有生命週期**對應物——租借會重用與回收。
- **用法**:`./ops/ios_test.sh --unit --lease`(自動租/釋)或 `--device <udid|name>` / `--destination '<...>'`。

不變式:同一 content-key 的 test 產物建一次、就緒後不覆寫(sentinel + double-check 保證),故無鎖的並行 test 執行讀唯讀產物安全。build 仍全域序列化(CPU-bound,單機正解)。

### 並行硬化(2026-06-09 dogfood 揪出並修)
1. **退出碼可區分**:建置失敗保留 xcodebuild 原生 `65`(原本被 inconclusive 分支無條件 normalize 成 `1`,且 verdict 檔寫 65 行程卻 exit 1,自相矛盾)。現在 `65`=建置/編譯失敗、`1`=測試紅、`0`=綠。
2. **`cacheStatus` 對等待者誠實**:等鎖後 double-check 命中、跳過重建的並行等待者標 `hit`(原本誤標 `prepared`,與真建置者混淆)。靠 `REBUILD_DID_BUILD` 旗標判別,非靠 `buildForTestingMs`。
3. **並行 metrics 歸戶無 race**:verdict JSON 固定路徑為多 agent 共用,`append_run_metric` 讀回時會被並行 run 覆寫(實測:緊密並發下同一 caller 兩筆、另一 caller 零筆)。改為 metric 取 **per-process 私有快照**(`$$`),固定路徑仍更新給 `ios_ops runs`。
4. **同裝置 warm-cache run 不再互撞**:舊版在 `cache=hit` 時若兩個 agent 都打同一台預設 simulator，`test-without-building` 會直接重疊；現在同裝置 execution lock 會把這種 case 顯式序列化，時間會反映在 `deviceRunLockWaitMs`。
5. **lease reclaim / cleanup 有 ownership**:舊版只看 TTL，且 cleanup 只要知道 UDID 就能刪 lease dir；現在 stale reclaim 先看 live owner pid，release 要帶 owner token 才能刪除自己的 lease。
6. **`rebuild-after-failure` 收窄**:warm-cache 命中後若第一輪出現真 `** TEST FAILED **`，現在直接保留紅燈；只有 `.xctestrun` / test-runner 這類 cache 或 infrastructure failure 才回頭 rebuild，避免把污染或 flake 洗成綠燈。
7. **高碰撞環境不再默默共享預設 simulator**:agent/worktree/CI 若沒顯式隔離裝置，舊版只會靠同裝置 lock 悄悄排隊；現在直接 fail-fast，讓「要並行就租/指定不同裝置」成為顯式契約。

### 並行 dogfood 實證(2026-06-09)
4 並發冷啟(共用空 cache):恰 1 個建置(`cache=prepared`,build 78827ms,`lockWaitMs=11`)+ 3 個等待者(`lockWaitMs` 78661/81679/81770 ≈ 建置時間,`buildForTestingMs=0`,sentinel 跳過重建);4/4 不同模擬器。4 並發暖快取:全 `hit`、`lockWaitMs=0`、`totalMs` 差 2666ms(真重疊)。8 並發寫 metrics 零交錯損壞。退出碼/cacheStatus/歸戶三項修正均經實機重驗。秒數基準與退出碼/cacheStatus 對照表見 [`docs/sop/ios.md`](../sop/ios.md) 「何謂正常」小節。

## Keyed cache 自動 eviction（2026-06-10）

**動機**：`ios-test-derived-data/<content-key>` 與 `ios-catalog-derived-data/<key>` 是 content-keyed——source 一改 key 就換，舊 key 永不重用也從未清理，2026-06-10 累積 94G+31G 兩度塞爆磁碟（xcodebuild exit=73 `No space left on device`）。單一共享快取（build / release）是增量重用、不增長，**不在此政策範圍**。

**機制**（`ops/lib/ios_cache_evict.sh`，`kg_ios_cache_evict <root> <current_key>`）：
- 保留 = mtime 最新 `KG_IOS_CACHE_KEEP`（預設 3）條 ∪ current key ∪ `KG_IOS_CACHE_EVICT_MIN_AGE_HOURS`（預設 6h）內用過的條目；其餘按最舊優先 `rm -rf`。
- 只動 cache root 第一層**目錄**；log 全走 **stderr**（catalog caller stdout 是純 JSON）。
- `KG_IOS_CACHE_EVICT_DRY_RUN=1` 只報告不刪。

**接點與並發安全**：
| caller | 時機 | 並發保護 |
|---|---|---|
| `ios_test.sh` `rebuild_test_cache` | 取得 build lock 後、build 前 | 持鎖互斥寫者；無鎖讀者（test-without-building）靠 resolve 時 `touch` 續命 + min-age 視窗 |
| `ios_ops_catalog.sh` `catalog_rebuild_scoped_cache` | scoped rebuild 的 mkdir 後、build 前 | 無共用鎖；靠各 run 自己 key 被 touch + min-age 視窗 |
| `ios_clean_derived_data.sh` | 手動 sweep（dry-run 預設，`--apply` 才刪） | current_key 留空，靠 keep-N + min-age |

**不變式**：current key 永不被淘汰；任何 6 小時內活動過的 key 永不被淘汰。讀者續命點：`ios_test.sh` 在 resolve 後 touch、catalog 兩條 cache-hit 路徑在 hit 判定時 touch、builder 由 lib 進場 touch——並行 run（即使讀的是舊 key）不會被別人的 build 中途抽走產物。另有刪除前 mtime 重驗（stale-snapshot guard）：快照後才被 touch 的 key 一律放過。回歸測試：`./ops/test_ops.sh ios-cache-evict`。

## 驗證證據（2026-06-09）
- 冷編 **88.6s** → 二次無改動 incremental **4.96s（18× 加速）**：共享快取確實重用。
- 產物落在 `kg/.cache/ios-build-derived-data`（1.3G）；全域預設**零新孤兒**。
- 主 repo 與 worktree 解析到同一路徑。
- 清掉舊孤兒後可用空間 24Gi → **124Gi**。

## 維運
- 清舊孤兒 / keyed cache / 壞模擬器：`./ops/ios_clean_derived_data.sh`（預設 dry-run，`--apply` 才刪，`--days N` 控全域孤兒年齡門檻；keyed cache 淘汰參數見上節 env var）。
- 換 Xcode 版本後若 incremental 行為異常：刪 `kg/.cache/ios-build-derived-data` 重新冷編即可（純可重建）。

## Agent 守則
1. 跑 iOS build 一律經 `./ops/ios_build.sh`，**不要**自己拼 `xcodebuild`。
2. 不要把 `-derivedDataPath` 從 build/test 指令拿掉。
3. 看到 `~/Library/Developer/Xcode/DerivedData/BooksAndVocab-*` 又開始增生 = 有人繞過了腳本，回頭查。
