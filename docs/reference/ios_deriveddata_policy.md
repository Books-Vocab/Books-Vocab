<!-- doc-meta
tier: reference
authority: source-of-truth
update_trigger: manual
scope:
  - ops/ios_build.sh
  - ops/ios_test.sh
  - ops/lib/ios_swiftpm_cache.sh
  - ops/lib/ios_ops_catalog.sh
  - ops/lib/ios_xctestrun_cache.sh
  - ops/ios_clean_derived_data.sh
  - ops/kg_disk_guard.sh
  - ops/lib/ios_cache_evict.sh
  - ops/lib/ios_disk_budget.sh
  - ops/launchd/com.kg.disk-guard.plist
  - ops/tests/test_kg_disk_guard.sh
  - ops/tests/test_ios_cache_evict.sh
  - ops/tests/test_ios_disk_budget.sh
  - ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved
  - .github/workflows/ios-quality.yml
verified_against: 8210e47aa53f8a2b03aafefadb7494098fa22cb1
-->
# iOS DerivedData 政策（多 worktree 環境）

事件日期: 2026-06-09 · 對應 commit: `03f6f913`

給在 worktree 內跑 iOS build/test 的 agent：**這份說明為什麼 DerivedData 不放 Xcode 預設位置，以及你不該怎麼破壞它。**

## TL;DR
- iOS build 的 DerivedData 一律走 **單一共享快取**：`<主repo>/.cache/ios-build-derived-data`，由 `git-common-dir` 錨定，所有 worktree 解析到同一路徑；release archive/export 固定落在 `<主repo>/ios/build/`，每次 release 取代上一代。
- **不要**自己呼叫不帶 `-derivedDataPath` 的 `xcodebuild`，也不要改 `ops/ios_build.sh` 移除該旗標。那會讓快取掉回 Xcode 全域預設位置，每個 worktree 路徑生一份孤兒。
- build / test 共用 `/tmp/kg-ios-build.lock` 序列化，共享快取**不會**並行寫壞。
- `com.kg.disk-guard` 每 5 分鐘檢查並維持每個 keyed root 最多 1 個可重建世代；所有受管理 iOS writer cache 合計以 **16 GiB** 為硬預算，且每次新建前保留 **6 GiB** headroom。Xcode 全域 `BooksAndVocab-*` DerivedData 另以 **4 GiB** 固定 byte cap 管理，不混入上述 aggregate；活躍／未知 iOS 工作或 lock contention 會先延後清理，安全時按最舊優先收斂可重建目錄。預算或可用空間不足時，新的 build/archive 以 exit 75 fail-closed。
- UITest 的截圖、video、UIreview、xcresult 是 agent 觀察產物，不是 DerivedData：視覺 run 預設進系統暫存的 run bundle 並帶 TTL；只有顯式 `--retain` 才進 `build/ios-report/retained/`。source tree 只保存 fixture、契約與小型 receipt。
- GitHub-hosted iOS CI 另有**唯讀的 SwiftPM source cache**；它不是 DerivedData，也不與本機 `.cache/` 共用。PR 可還原，只有成功的 `main` push 會寫入。

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

### 歷史附帶誤導：舊 `XCTestDevices` 的 155G APFS-clone 事件（非目前 accounting 規則）
在該次 155G 事件中，`du` 報 `~/Library/Developer/XCTestDevices` 155G，但刪光只釋出約 5G；原因是 UI test 的 runner 模擬器是系統 runtime 的 **APFS clone（copy-on-write）**，多份共享同一批磁碟 block，`du` 對每份重複計算（[APFS clone 機制](https://eclecticlight.co/2025/04/07/how-robust-are-apfs-clone-and-sparse-files/)）。這個結論只適用於該次歷史事件，**不表示目前的 `XCTestDevices` 裝置用量可視為假的**：現在的 disk guard 會量測每個裝置樹的 `allocated_bytes`，並以共享 16 GiB 預算判斷；超額、證據缺失或無法安全回收時 fail-closed 進入 manual review，active／non-ephemeral／不在 `simctl list` 的裝置一律不刪除（詳見下節）。

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
| `ios_ops_catalog.sh` `catalog list|open|capture` | 委派 `ios_build.sh` 的共享 DerivedData | Agent UI 工作台；不擁有 xctestrun/test cache lifecycle |
| `run_ui_evidence.sh` / `ios_ui_run_many.py` 視覺產物 | 系統暫存的 run-scoped root（TTL）；顯式 `--retain` 才進 `build/ios-report/retained/` | Agent 觀察工具；永久狀態只保留小型 verdict、provenance 與必要 receipt |

三份共享快取(build / test / release)都靠 `/tmp/kg-ios-build.lock` 同一把帶 FIFO ticket queue 的鎖序列化,不會並行寫壞；後到 waiter 不得繞過已排隊 predecessor，timeout/訊號會清理自己的 ticket，abandoned ticket 只在 PID 已死亡時由後續 waiter 清理。

## GitHub-hosted SwiftPM source cache（2026-08-19）

GitHub-hosted macOS runner 每次都是新的 VM；本機長存的 DerivedData 不能安全地搬過去，也不能拿它當 CI cache。為了只消掉可重用的依賴下載，`ios-quality` 將 SwiftPM 的 cloned sources 與 package cache 放在 `$RUNNER_TEMP/kg-ios-swiftpm`，並由 `ops/lib/ios_swiftpm_cache.sh` 透過下列 xcodebuild 旗標接入 build 與 `build-for-testing`：

```text
-clonedSourcePackagesDirPath <runner-temp>/kg-ios-swiftpm
-packageCachePath <runner-temp>/kg-ios-swiftpm/package-cache
-onlyUsePackageVersionsFromResolvedFile
```

`ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved` 是版本真相，必須提交；缺檔或 cache root 落在專案內時 helper 直接 fail-closed。cache key 精確包含 cache schema、runner OS、arch、Xcode 指紋與該 lockfile 的 hash，**沒有** restore key，避免跨 Xcode／架構吃到不相容來源。每個 iOS job 都 restore；只有可信的、成功的 `main` push 中 `ios-build` job 可 save，PR 和測試 matrix 永遠不寫 cache。

這個 cache 只保存公開套件的可重建原始碼與下載內容，不能放 token、簽署資料或 DerivedData。cold miss 仍是正確路徑，首次 PR 不得因尚未命中 cache 宣稱變快；要等 main 建立 cache 後，以後續 GitHub Actions run 的 `cache-hit` 與實際 timing 比較。

## 並行測試(2026-06-09 細粒度鎖 + 模擬器 pool)

**量測動機**:舊版 `ios_test.sh` 持鎖跑完整段測試執行,實測 3 併發時第 2/3 個 agent 等 246s/309s(資料在 `.cache/ios-run-metrics.jsonl`,每次 build/test/release append 一行 timings)。

**改動**:
- **FIFO shared lock queue**:`ios_build.sh`、`ios_test.sh`、`ios_release.sh` 共用的 lock helper 先以原子單調 ticket 排定到達順序；只有 queue head 能嘗試 `shlock`，waiter timeout 或 INT/TERM/HUP 會移除自己的 ticket。
- **細粒度鎖**:`/tmp/kg-ios-build.lock` 只在 `build-for-testing`(共享 DerivedData 唯一寫者)期間持有;`test-without-building` 執行階段**不持鎖**。`release_build_lock` 為 ownership-guarded(鎖檔內容 == `$$` 才刪),`rebuild_test_cache` 內 double-checked locking(取鎖後重驗 ready 則跳過),避免重複建與覆寫他人正讀的產物。
- **同裝置執行鎖**:`test-without-building` 另會經 `/tmp/kg-ios-test-device-<selector-hash>.lock` 序列化同一台 simulator。這層不是保護 DerivedData，而是保護 simulator runtime/app state：兩個 warm-cache run 若都瞄準同一台預設機器，現在會在 `deviceRunLockWaitMs` 排隊，而不是互撞。
- **agent/CI 預設拒絕共享 simulator**:在 `/.codex/worktrees/`、`WORKTREE_BRANCH` 或 `CI` 上，若測試 run 仍打共享預設 simulator，`ios_test.sh` 會直接 fail-fast，要求 `--lease` / `--device` / `--destination`。只有單機除錯才可用 `KG_IOS_TEST_ALLOW_SHARED_SIM=1` 明示 opt-out；目的不是功能限制，而是把原本隱性序列化與共享 state 風險前置成明確操作契約。
- **完成 sentinel** `.kg-test-cache-complete`:build 成功才在持鎖下寫;hit 偵測(`ios_test_cache_is_complete`)與 double-check 都要求它。`-d` 目錄檢查無法區分「完整」與「中斷留下的 half-written bundle」,sentinel 是 build 真完成的證明——中斷的 build 不寫 sentinel,下個 agent 重建而非吃毒化 cache。
- **platform/arch/signing cache key**:test cache key 用 platform token + arch + signing mode(非具體裝置名),pool 各模擬器共享一份暖 build cache；`generic/platform=iOS` 的 unsigned compile-only 產物與 exact-device 的 signed/installable 產物必須分開，禁止跨模式重用。
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

**動機**：`ios-test-derived-data/<content-key>` 是 content-keyed——source 一改 key 就換，舊 key 永不重用也從未清理，2026-06-10 累積 94G 兩度塞爆磁碟（xcodebuild exit=73 `No space left on device`）。Catalog 現為 agent UI 工作台，沒有獨立的 snapshot/xctestrun keyed cache。build / release 共享快取仍保留增量重用，但現在與 keyed cache 一起納入 aggregate budget；build / release 的 Xcode 內部目錄仍不交給 keyed evictor。

**機制**（`ops/lib/ios_cache_evict.sh`，`kg_ios_cache_evict <root> <current_key>`）：
- 保留 = mtime 最新 `KG_IOS_CACHE_KEEP`（預設 3）條 ∪ current key ∪ `KG_IOS_CACHE_EVICT_MIN_AGE_HOURS`（預設 6h）內用過的條目；其餘按最舊優先 `rm -rf`。
- `ops/kg_disk_guard.sh` 只把 `.cache/ios-test-derived-data` 與 `.cache/ios-catalog-derived-data` 視為 keyed root；`.cache/ios-build-derived-data`、`.cache/ios-release-derived-data` 的 Xcode 內部目錄不是 key，絕不交給這個 evictor，但它們仍計入 16 GiB aggregate budget。guard 即使設定 `KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0`，仍會套用預設 `KG_DISK_GUARD_CACHE_READER_WINDOW_HOURS=1` 的讀者安全窗；因此最近一小時內被讀取或觸碰的 key 不會因快照排序而被刪除。另以 `derived_data_kb`、`derived_data_budget_kb`、`derived_data_overflow_kb` 在同一份 atomic receipt 記錄 global `BooksAndVocab-*` byte cap；`KG_DISK_GUARD_DERIVED_DATA_BUDGET_GIB` 預設 4，超額且 healthy free space 也會觸發 `reason=derived-data-budget-exceeded`，在 process probe clear 且持有同一 build lock 時按 mtime／path deterministic oldest-first 淘汰。`KG_DISK_GUARD_DERIVED_DATA_MIN_AGE_HOURS` 預設 `6h` 的安全窗仍保留；active consumer、未知 process、FIFO ticket 或 lock contention 時只記錄 `deferred-*`，不刪目錄。
- guard 每次 tick 都計算 `cache_overflow_keys` 與 `cache_budget_overflow_kb`。即使磁碟仍健康，只要 keyed root 超過 1 個世代或 aggregate budget 超標，就會在 build lock 下淘汰最舊且已離開 reader window 的 key；共享 `ios-build-derived-data`、release/catalyst 與 `ios/build` 下的 archive/export 這類可重建產物，也會在無 consumer、持有 writer lock 且 aggregate budget/headroom 超標時移除。這不是 keyed eviction，而是整個可重建 build cache 的 bounded cold-rebuild fallback。若只剩正在使用的 build cache 仍超標，guard 只留下證據，下一個 build/archive 不得繼續寫入。
- 只動 cache root 第一層**目錄**；log 全走 **stderr**（catalog caller stdout 是純 JSON）。
- `KG_IOS_CACHE_EVICT_DRY_RUN=1` 只報告不刪。
- `ios_clean_derived_data.sh --apply` 先確認 `xcodebuild`／runner／evidence
  consumer 與已知 iOS lock 都不存在；任何 active/invalid lock 都會以 exit 75
  fail-closed，不進入刪除階段。
- 每次 manual sweep 產生一個小型 `kg.ios.cache-cleanup.v1` receipt，記錄
  `runID`、mode、before/after allocated bytes 與 `/` free bytes；receipt 放在
  `build/ios-report/retained/receipts/`，不把 cache 內容本身當 receipt。

**接點與並發安全**：
| caller | 時機 | 並發保護 |
|---|---|---|
| `ios_test.sh` `rebuild_test_cache` | 取得 build lock 後、build 前 | 持鎖互斥寫者；無鎖讀者（test-without-building）靠 resolve 時 `touch` 續命 + reader window |
| `ios_clean_derived_data.sh` | 手動 sweep（dry-run 預設，`--apply` 才刪） | active consumer/lock guard；通過後 current_key 留空，靠 keep-N + min-age；保留 cleanup receipt |

**不變式**：所有會刪除共享產物的路徑先確認沒有活躍 consumer；guard 再取得 `/tmp/kg-ios-build.lock`，才會清理共享 keyed root 或 global `BooksAndVocab-*` DerivedData。若 iOS FIFO lock queue 已有等待中的 `ticket-*`，guard 直接延後，不插隊；`.next` 等持久化序號 metadata 不代表等待者，不會阻止安全清理。活躍 build、未知 process state 或 lock contention 都 fail-closed 延後，不刪產物。`kg_ios_cache_evict` 仍保留 current key 與刪除前 mtime 重驗；global DD 只依 exact `BooksAndVocab-*` first-level directories、cap、mtime/path 與既有 age guard，自動清理不會碰其他 Xcode project。guard 另以 `KG_DISK_GUARD_CACHE_READER_WINDOW_HOURS`（預設 `1h`）保護無鎖讀者，手動 sweep 的 6h min-age 也不變；`KG_DISK_GUARD_DRY_RUN=1` 仍只記錄 intended eviction、不刪任何目錄。讀者續命點：`ios_test.sh` 在 resolve 後 touch、builder 由 lib 進場 touch——並行 run（即使讀的是舊 key）不會被別人的 build 中途抽走產物。16 GiB 是 aggregate writer budget，不是對整台 APFS 或 global DD 的 filesystem quota；global DD 另有 4 GiB guard cap。若不可安全淘汰的 active build cache 仍超標，入口以 exit 75 阻止新 writer，避免繼續膨脹。回歸測試：`./ops/tests/test_kg_disk_guard.sh`、`./ops/tests/test_ios_disk_budget.sh` 與 `./ops/test_ops.sh ios-cache-evict`。

## Per-lane 磁碟歸戶與閉環（2026-08-28）

共享 cache 預算不能回答「是哪一條 lane 佔用空間」。`ops/disk_usage.py` 每次產生一份原子替換的 `kg.disk.lane-usage.v1` 報告，列出 registry 中的 live／terminal lane、Git 實際 worktree、canonical main，以及每個路徑的 `logical_bytes`、`allocated_bytes`、files、ownership、physical／lifecycle state 與 aggregate accounting；terminal residue 仍以 terminal identity 可追蹤，但不會被冒充成 active，也不會由 guard 自動刪除。`accounting.lane_accounting` 對每條 product lane 都保留 deterministic row；physical path 缺失或尚未完成檢查時，row 會帶 `exists=false` 或明確的 `measurement_error`，不會因只投影已存在的 physical path 而靜默漏掉 registered active lane。只有 `physical_lane_*` totals 與 `accounted_in_aggregate=true` 的 row 進入 bytes aggregate。歷史 registry path 缺失且沒有 physical bytes 時只保留 `missing-registered-lane` warning，不把零 bytes 當成未歸因空間或硬 quota blocker。

已知但不屬於 delivery lane 的 supervision checkout，只能由 caller 重複傳入 exact path：

```bash
./ops/disk_usage.py \
  --workspace /Users/chenliangyu/project/kg \
  --state /Users/chenliangyu/project/kg/.cache/worktree_registry.json \
  --supervision-worktree /absolute/path/to/supervision-checkout \
  --output "$HOME/Library/Application Support/KG/lane_disk_usage.json"
```

`--supervision-worktree` 不接受 wildcard，也沒有預設排除；未列出的 physical worktree 一律仍算 delivery／unknown。報告的 `exclusions` 與 guard state 的 `lane_usage_exclusions` 都保留 caller requested／applied path，且 registered active／terminal path 或 canonical main 不可藉此隱藏。unregistered、unknown、malformed、branch identity mismatch、registry unreadable、measurement failure、per-lane／aggregate budget breach，以及非 `active` registered lane 的 dirty worktree（`published`、`cleanup_pending`、`merged`、`abandoned`）仍是 hard block。唯一例外是 exact registered `active` implementation lane 的 dirty worktree：它是正常 in-progress 狀態，必須保留 dirty observation 與完整 bytes 歸戶，並繼續接受其他 policy gate；在沒有其他 blocker 時 verdict 可為 `pass`／`warning`。

```bash
./ops/disk_usage.py \
  --workspace /Users/chenliangyu/project/kg \
  --state /Users/chenliangyu/project/kg/.cache/worktree_registry.json \
  --output "$HOME/Library/Application Support/KG/lane_disk_usage.json"
```

`ops/kg_disk_guard.sh` 每個 tick 同步更新這個小型狀態檔；它不建立 append-only log，也不在 active、unknown 或 terminal residue worktree 上做破壞性清理。可用重複的 `--supervision-worktree <exact-path>` 將 caller 明確提供的 supervision checkout 傳給 attribution scan；這個排除只影響 disk quota accounting，不改 registry lifecycle 的 fail-closed 規則。預設每條 physical lane 上限 2 GiB、所有未排除 physical lanes 合計上限 8 GiB，可用 `KG_DISK_GUARD_LANE_BUDGET_GIB` 與 `KG_DISK_GUARD_LANE_TOTAL_BUDGET_GIB` 明確調整。超限、無法量測、registry 不可讀、真正 unknown／dirty／unregistered physical worktree，以及非 `active` registered dirty lane 時，報告為 `verdict=block`，且 guard state 會保留 `lane_usage_verdict=block` 與 `lane_usage_rc=75` 供 admission／writer fail-closed；registered active dirty implementation lane 仍完整計入 per-lane／aggregate bytes，只有 budget／identity／measurement 等其他 gate 失敗才 block。只有既有 cache guard 在確認無 consumer 且持有 build lock 後才可自動淘汰可重建產物。missing registered path 本身若沒有 physical bytes 則為 `verdict=warning`、guard lane exit 0，讓可安全計量的新 lane 不被歷史紀錄誤擋。

歸戶掃描本身也有固定時間上限：`kg_disk_guard.sh` 預設以 240 秒呼叫
`disk_usage.py --time-budget-seconds 240`，且任何 caller 提供的值都會被硬性封頂在 240 秒。guard 同時在 shell 邊界監督外部掃描程序；期限到達時會終止該程序及其子程序樹，並以結構化 `lane_usage_rc=75` fail closed，不會讓卡住的 attribution process 無限佔用 CPU、鎖或工作階段。時間到了仍會原子寫出報告，保留已量到的
當 caller 為 `0` 以測試立即超時時，guard 仍保留最多 1 秒的 process-startup grace，讓這份 timeout evidence 能先原子落盤；內部 report 仍精確記錄 `budget_seconds=0`，真正卡住的程序仍會被終止。
partial bytes，但在 `measurement.budget_exhausted=true`、各受影響 lane 的
`measurement_complete=false` 與 `policy.verdict=block` 中明確標示；partial 或 timeout
絕不會被當成零 bytes，也不會授權清理或新的 writer。需要手動調整時只能透過
`KG_DISK_GUARD_LANE_USAGE_BUDGET_SECONDS`，無效值回到 240 秒，超過 240 秒也會被截斷。這使 guard 不會因為
大型 workspace／DerivedData 遞迴掃描而永久佔住 lock；外部終止的短暫收尾時間不會改變這個 caller budget。`ops/kg_disk_guard.sh --help`
是純說明命令，不會啟動 guard tick、改狀態或刪 cache。

每個 iOS writer 也會消費 guard 的 atomic state：若 state 明確報告
`xctest_devices_verdict=block` 或 global `verdict=block`，build/test/release 立即以 exit 75
停止，不會繼續製造新的 XCTestDevices 或 DerivedData。需要 shared-state freshness 的 caller
可設定 `KG_IOS_DISK_GUARD_ENFORCE_XCTEST=1`；此時缺失、格式錯誤或超過
`KG_IOS_DISK_GUARD_MAX_AGE_SECONDS`（預設 900 秒）的 state 同樣 fail-closed。這只阻止新的
writer，不會自動刪除 active、non-ephemeral 或無法證明可回收的 XCTestDevices；它們仍須經
支援的 Xcode／Simulator 手動處置並留下 readback。

報告把 canonical project 的 worktree 子樹排除後再加回每條 physical lane，並將 exact supervision exclusion 的 bytes 另列為 observed、排除於 managed aggregate，避免同一份檔案被重複計算。`managed_allocated_bytes` 是 KG 受管理範圍的 accounting，不等於整台 Mac 的 filesystem usage：APFS snapshots、Git shared object、Xcode global DerivedData、Docker 與其他使用者資料另列在 `filesystem` 或既有 cache metrics；global `BooksAndVocab-*` DerivedData 的固定 cap 由 `kg_disk_guard.sh` 另行觀測與修復。故「每條 lane 相加」是可驗證的 lane reservoir 總量，不應冒充整顆磁碟的唯一總量。

閉環固定為：guard 觀測 → `lane_disk_usage.json` 歸戶 → 超限／遺失證據 fail-closed → active lane 由 owner 完成交接或 terminal cleanup → 再次觀測確認 worktree／branch／registry 狀態。測試入口為 `uv run --no-project --python 3.13 --with pytest pytest -q ops/tests/test_disk_usage.py` 與 `./ops/tests/test_kg_disk_guard.sh`。

## Shared XCTestDevices platform store（2026-09-02）

`~/Library/Developer/XCTestDevices` is shared Xcode test-device storage, not a
delivery lane and not user data owned by any product worktree. The disk report
observes only the root's immediate device directories in deterministic name
order, reads each direct `device.plist`, and measures each device tree under
the caller's existing time budget. It never treats a missing, malformed,
identity-mismatched, active, or non-ephemeral plist as reclaimable.

The additive report field is
`accounting.shared_platform_storage.xctest_devices`. It records the exact
root, logical/raw allocated bytes, device count, metadata and measurement
status, the shared budget, overflow, and per-device reclaim evidence. On
Darwin, the budget uses the union of APFS physical extents, so APFS-cloned
files shared by multiple XCTestDevices are counted once. The compatibility
`allocated_bytes` field remains the raw per-file `st_blocks` observation for
audit; `budget_allocated_bytes` is the value used for the fixed quota, and
`allocation_method` records whether it used APFS extents or the conservative
`st_blocks` fallback. An incomplete physical or tree observation is never
treated as within budget. The default shared budget is 16 GiB and is configurable with
`KG_DISK_GUARD_XCTEST_DEVICES_BUDGET_GIB` or
`--xctest-devices-budget-gib`. Exceeding it is always a blocking policy result;
the guard cannot report `within-bounds` while the store is over budget.

Automatic reclaim is opt-in with
`KG_DISK_GUARD_XCTEST_DEVICES_AUTO_RECLAIM=1` (or the disk report flag). The
only candidate is an exact UUID whose plist proves `isEphemeral=true`,
`isDeleted=true`, a known inactive state, and matching `UDID`. Reclaim uses
only `xcrun simctl delete` after the UUID is also present in `simctl list`; the
root is remeasured afterward. If no supported command or exact proof exists,
the guard emits `xctest-devices-manual-review-required` and leaves the store
untouched. Unknown, active, non-ephemeral, and user-data paths are never
deleted.

## Shared Simulator runtime images（2026-09-02）

Mounted iOS Simulator runtimes under `/Library/Developer/CoreSimulator/` are
shared host-platform assets, not product lanes. `ops/disk_usage.py` discovers
them through the read-only `hdiutil info` command and records the additive
bucket `accounting.shared_platform_storage.simulator_runtimes`. Each mounted
runtime keeps its mount path, source image path, image size, filesystem
usage, measurement status, and deterministic allocation key. Repeated views of
the same source image count once toward the shared budget; these bytes are
never added to a product lane or used to make a lane look smaller.

The default shared runtime budget is 56 GiB and can be changed only through
`KG_DISK_GUARD_SIMULATOR_RUNTIME_BUDGET_GIB` or
`--simulator-runtime-budget-gib`. Discovery or filesystem measurement failure,
or an exceeded budget, is a blocking disk-guard result with explicit manual
review evidence. The guard never deletes or unmounts Simulator runtime
images: they are platform assets and have no safe per-lane owner. A blocked
result therefore stops new iOS disk writers until an operator performs a
supported platform-level cleanup and the next readback is within budget.

The recurring guard also uses a conservative free-space floor: 50 GiB is a
warning and 36 GiB (inclusive) is critical. At or below the critical floor,
the guard records the block and only performs its existing bounded cleanup of
rebuildable caches when the active-build, process, and build-lock checks allow
it. It never removes active, unknown, user-owned, or unverified worktree data.
The tracked LaunchAgent configuration carries the same 50/36 GiB floor and
56 GiB runtime budget; reload it through the normal launchd maintenance path
after the change is merged.

## 驗證證據（2026-06-09）
- 冷編 **88.6s** → 二次無改動 incremental **4.96s（18× 加速）**：共享快取確實重用。
- 產物落在 `kg/.cache/ios-build-derived-data`（1.3G）；全域預設**零新孤兒**。
- 主 repo 與 worktree 解析到同一路徑。
- 清掉舊孤兒後可用空間 24Gi → **124Gi**。

## 維運
- 清舊孤兒 / keyed cache / 壞模擬器：`./ops/ios_clean_derived_data.sh`（預設 dry-run，`--apply` 才刪，`--days N` 控全域孤兒年齡門檻；keyed cache 淘汰參數見上節 env var）。
- 查詢自動 guard 狀態：`$HOME/Library/Application Support/KG/disk_guard.json`；`cache_overflow_keys>0` 代表下一個無活躍 iOS consumer 的 tick 會收斂到保留上限，`derived_data_overflow_kb>0` 代表 global `BooksAndVocab-*` 超過固定 cap，`action=deferred-*` 代表 guard 正確選擇等待，不是直接刪除。
- 換 Xcode 版本後若 incremental 行為異常：刪 `kg/.cache/ios-build-derived-data` 重新冷編即可（純可重建）。

## Agent 守則
1. 跑 iOS build 一律經 `./ops/ios_build.sh`，**不要**自己拼 `xcodebuild`。
2. 不要把 `-derivedDataPath` 從 build/test 指令拿掉。
3. 看到 `~/Library/Developer/Xcode/DerivedData/BooksAndVocab-*` 又開始增生 = 有人繞過了腳本，回頭查。
