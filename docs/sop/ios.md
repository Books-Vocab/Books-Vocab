<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: a281cba6
-->
# BooksBrowser iOS 開發技能

## 核心資訊

- **專案路徑**: `ios/BooksBrowser.xcodeproj`
- **Scheme**: `BooksBrowser`
- **工作目錄**: repo root（`~/kg/`）
- **Destinations**: iOS 17+ / iPadOS 17+ / Mac Catalyst（macOS 15.0+，非原生 macOS）
- **平台抽象**: `Platform/PlatformRepresentable.swift`、`Platform/PlatformCompatibility.swift`

---

## 最高指導原則

**Exit Code `0` = 編譯成功；release 前仍需看第一屏 diagnostics summary 的 warnings。**

---

## Mac Catalyst 雷區（編譯過 ≠ 不崩）

Catalyst 是正式 target（Mac 走 Catalyst，非原生 macOS）。以下寫法**編譯通過但在 Catalyst runtime crash**，CI 由 `ops/catalyst_lint.sh` 擋：

- **`.popover` 掛在 `.toolbar` / `ToolbarItem` 的 Button 上** → present 過場走 UIKit `_pinInputViewsForKeyboardSceneDelegate`，scene 未就緒時 trap（`EXC_BREAKPOINT`，backtrace 全在 UIKitCore、無 app frame）。**改用 `.sheet`**（不同 presentation controller，亦免疫 popover resize 時的 willReposition recursion crash）。豁免：同行 `// catalyst-allow: <reason>`。
- 判讀法：`brk #1` + backtrace 唯一 app frame 是 `main` = framework trap，非 app force-unwrap；務必先取 lldb `bt`。

`ops/catalyst_lint.sh [--report|--strict]`，baseline 0 命中。

---

## iOS ops 統一入口（agent 優先）

新工作流優先走 `ops/ios_ops.sh`，底層 `ios_build.sh` / `ios_test.sh` / `ios_release.sh` 仍保留為 primitives。

```bash
./ops/ios_ops.sh status                 # project version/build + Organizer latest + TestFlight latest
./ops/ios_ops.sh doctor                 # release readiness: project/Organizer/TestFlight/signing/StoreKit/Sentry
./ops/ios_ops.sh doctor --json          # 同上，輸出 kg.ios.doctor.v1 結構化 JSON
./ops/ios_ops.sh build                  # 委派 ios_build.sh，結束即列 warnings/errors diagnostics
./ops/ios_ops.sh test --file FooTests.swift
./ops/ios_ops.sh archive                # archive + export，預設不上傳
./ops/ios_ops.sh archive --json         # machine-readable archive/export/upload report:kg.ios.archive.v1
./ops/ios_ops.sh archive --upload       # 明示才上傳 TestFlight
./ops/ios_ops.sh archives latest        # 本機 Organizer latest archive
./ops/ios_ops.sh issues --log <log>     # 解析既有 xcodebuild log
./ops/ios_ops.sh logs --since 5m        # runtime log 回溯快照（log show），過濾常見 Apple framework 噪音
./ops/ios_ops.sh logs --json --limit 200 # 同上，輸出 kg.ios.logs.v1 結構化 JSON
./ops/ios_ops.sh logs --follow          # 即時串流（log stream）；--limit N 為 stop-after-N gate
./ops/ios_ops.sh logs --follow --json   # 即時串流，逐行輸出 kg.ios.log-stream.v1（一行一物件）
./ops/ios_ops.sh sentry [--json]        # iOS Sentry wiring 摘要 / schema=kg.ios.sentry.v1
./ops/ios_ops.sh workflow release       # read-only 發版工作流：下一步命令 + todo/ready/block/warn/manual
./ops/ios_ops.sh workflow release --json # 同上，輸出 kg.ios.workflow.v1 結構化 JSON
./ops/ios_ops.sh gate release --json    # release hard-stop verdict:0 pass / 1 warn / 2 block
./ops/ios_ops.sh xcode --json           # Xcode/project/destination/simulator inventory:kg.ios.xcode.v1
./ops/ios_ops.sh simulator status --json # booted simulator + app data container/process:kg.ios.simulator.v1
./ops/ios_ops.sh simulator ensure-booted --json # 若 simulator 已 booted 就重用，否則 boot 預設裝置並等待 bootstatus
./ops/ios_ops.sh simulator launch --json # launch installed app, then re-check process state
./ops/ios_ops.sh simulator terminate --json # stop installed app, then re-check process state
./ops/ios_ops.sh simulator screenshot --out build/sim/current.png --json # 本機截圖 artifact，不上傳
./ops/ios_ops.sh runs --json            # 最近 build/test verdict + log/xcresult artifact path + diagnostics
./ops/ios_ops.sh snapshot --json        # 一次拉 project/Organizer/TestFlight/readiness/workflow/gate/xcode/simulator/runs
./ops/ios_ops.sh snapshot --json --skip-xcode # 快速模式:不拉 Xcode destination/simulator inventory
./ops/ios_ops.sh snapshot --json --skip-simulator # 快速模式:不拉 booted simulator/app process
./ops/ios_ops.sh snapshot --json --include-logs --log-limit 50 # 同上,再內嵌 runtime logs
./ops/ios_ops.sh commands --json        # 自描述 CLI catalog:side-effect / schema / delegate
```

輸出契約:第一屏固定優先看 `[ios][issues]` / `[ios][summary]` / `[ios][next]` 類摘要;需要原始資料時再開 log path。

原則:優先組合 Xcode 官方 CLI,不重造輪子。`ios_build.sh`/`ios_ops.sh build` 與 `ios_release.sh` archive 會產生 `-resultBundlePath <*.xcresult>`,再用 `xcrun xcresulttool get build-results` 抽 warnings/errors;`ios_test.sh` 會用 `xcrun xcresulttool get test-results summary/tests` 抽 executed/failures。raw xcodebuild log parser 只作 fallback。

`ios_ops.sh doctor` 是 release readiness 儀表板:read-only 彙總 project `MARKETING_VERSION(CURRENT_PROJECT_VERSION)`、Organizer latest archive、TestFlight latest build、ASC version state、manual signing export options、StoreKit scheme/file、Sentry release wiring。ASC version-state 查詢有短 deadline，逾時只會 `status=warn`，不阻塞本機 readiness。`status=block` 代表發版前必修（例如 build number 未增加），`status=warn` 代表資訊缺失或 local artifact 落後。agent/CI 要少調用工具時用 `--json`，schema 為 `kg.ios.doctor.v1`，核心陣列是 `readiness[]`，且頂層直接內嵌同一份 `sentry: kg.ios.sentry.v1`，讓 readiness 與 wiring 摘要共用單一路徑。現在另外有 `summary.verdict` 與 `summary.counts.ok|warn|block|total`，文字模式也會固定印 `[ios][doctor] summary ...`，不必每次自己掃完整列 readiness item 才知道整體狀態。

`ios_ops.sh status --json` 是更輕量的 quick summary：只回 `kg.ios.status.v1`，含 project version/build、Organizer latest archive 與 TestFlight latest build，不做 readiness/gate 判斷。適合 agent 第一輪只想知道「現在 local/Organizer/TestFlight 各是多少」時使用。

`ios_ops.sh workflow release` 是 read-only 發版操作編排:輸出 `[ios][workflow] step=N key=... status=todo|ready|block|warn|manual command="..." note="..."`。它不跑測試/編譯/archive/upload,只根據目前 project/Organizer/TestFlight/ASC state 列下一步命令;submit/resubmit 邊界仍標 `manual`，因為 ASC submit-for-review / 撤回送審刻意不做 CLI 寫入。現在文字模式也會固定印 `[ios][workflow] summary verdict=... ready=... todo=... block=... warn=... manual=... total=...`；`--json` schema 為 `kg.ios.workflow.v1`，除 `steps[]` 外另有 `summary.verdict` 與 `summary.counts.ready|todo|block|warn|manual|total`。

`ios_ops.sh gate release --json` 是 release hard-stop verdict:schema 為 `kg.ios.gate.v1`,重用 `doctor --json` + `workflow release --json`。exit code 固定為 `0=pass`、`1=warn`、`2=block`;`todo`/`manual` 會列入 `todos[]`/`manual[]` 供 agent 排下一步,但不讓 gate 永遠失敗。`block` 只來自 readiness/workflow 的 `status=block`（例如 TestFlight build number 未增加）。

`ios_ops.sh xcode --json` 是 Xcode Project Navigator / destination selector / Devices 視角的 read-only inventory:schema 為 `kg.ios.xcode.v1`,組合 `xcodebuild -version`、`xcode-select -p`、`xcodebuild -list -json`、`xcodebuild -showdestinations` 與 `xcrun simctl list devices --json`。輸出包含 Xcode 版本、DeveloperDir、project configurations/schemes/targets、destinations `available[]`/`ineligible[]`、simulator runtimes/devices 與 booted/available summary。各來源都有 `sources.*.status/exitCode/error`,頂層 `errors[]` 保留 CLI failure 診斷;來源失敗時仍輸出可解析 JSON。文字 alias `environment` 供人掃第一屏;agent 要選 `--destination` 或確認 booted simulator 時讀 JSON。

`ios_ops.sh simulator status --json` / `sim status --json` 是 Simulator GUI 狀態的窄面:schema 為 `kg.ios.simulator.v1`,組合 `xcrun simctl list devices --json`、`xcrun simctl get_app_container booted com.Max0228.BooksBrowser data` 與 host-side `ps -axo pid,command` probe（以 device UDID + `BooksBrowser.app/BooksBrowser` 鎖定 simulator app process），回傳 booted device、app data container、app process `running|stopped|skipped|unknown` 與 errors[]。app 沒在跑是觀測狀態(`process.status=stopped`,probe exit 1),不讓整體 status 失敗;沒有 booted simulator 才回穩定 JSON + exit 1。每個 simulator action 現在都會帶 `timings`：`status` 含 `simctlDevicesMs/appContainerMs/appProcessMs/totalMs`，`ensure-booted` 含 `resolveMs/bootMs/bootstatusMs/totalMs`，`launch|terminate` 含 `statusMs/lifecycleMs/appProcessMs/totalMs`，`screenshot` 含 `statusMs/screenshotMs/totalMs`；文字模式也會印對應 `[ios][simulator] timings ...`。`ios_ops.sh simulator launch --json` / `terminate --json` 對齊 Xcode Run/Stop toolbar 的窄面:底層只呼叫官方 `xcrun simctl launch|terminate`,然後重新讀 BooksBrowser process,回傳 `app.lifecycle` 與 `app.process`。它不 build、不 install、不 boot、不改 ASC;launch 需要 app 已安裝。`ios_ops.sh simulator screenshot --out <png> --json` 只做本機 artifact side effect,底層是 `xcrun simctl io <device> screenshot <png>`。

`ios_ops.sh runs --json` 是 Xcode Report Navigator + Issue Navigator 的輕量對應面:schema 為 `kg.ios.runs.v1`,讀最近 `ios_build.sh` / `ios_test.sh` / `ios_release.sh` 寫出的 verdict file,回傳 build/test/archive result、caller、elapsed、executed tests、log path、xcresult path、artifact 是否仍存在,並在每個 run 內嵌 `diagnostics`:`kg.ios.diagnostics.v1`。頂層另外有 `summary.verdict` 與 `summary.counts.errors|warnings|failedTests|missing|malformed|failing`，文字模式第一行固定印 `[ios][runs] summary ...`，讓 agent/human 不必逐個 run 自己聚合。diagnostics 優先讀官方 `.xcresult`,不可讀時用 raw log fallback;缺 artifact 時給穩定 `source:"missing-artifacts"` 空摘要,不讓 `runs`/`snapshot` 中斷。新 verdict 優先讀 `.json`（避免含空白 path 被 legacy `KEY=value` 格式截斷）,舊單行 verdict 只作相容 fallback；含空白 path 的準確 artifact 判定以 JSON verdict 為準。archive run 另外保留 `timings.lockWaitMs/archiveMs/exportMs/uploadMs/totalMs`，可直接判斷發版成本花在哪一段。它不重跑 build/test/archive。

`ios_ops.sh logs --json` 是 Xcode Console 的輕量對應面:schema 為 `kg.ios.logs.v1`,資料源是 Apple Unified Logging 官方 CLI `/usr/bin/log show --style ndjson`（回溯快照）。輸出包含 `summary.rawCount` / `filteredCount` / `emittedCount` / `byEventType` 與 `entries[]`（timestamp、eventType、processID、subsystem、category、message、sender）；常見 RunningBoard/WebKit assertion 噪音會先過濾。`--limit` 只限制輸出的 entries 數量,不重跑 app。

`ios_ops.sh logs --follow` 是同一面的即時串流變體,改走 `/usr/bin/log stream`（compact 文字;`--json` 改 `log stream --style ndjson`,逐行輸出 `kg.ios.log-stream.v1`,一行一 JSON 物件便於串流消費）。沿用同一份 noise 過濾;`--limit N` 在 follow 模式是 stop-after-N gate（預設無界）,`--since` 不適用。串流長駐,適合 `simulator launch` 後即時盯 log;主線請用鐵律 5 的背景執行(`run_in_background`),由 notification 取增量。底層 producer 被 `head` 關閉(達 limit)收 SIGPIPE 視為正常終止,真實 `log stream` 失敗才傳遞非零 exit。

`ios_ops.sh snapshot --json` 是 agent 第一輪狀態入口:schema 為 `kg.ios.snapshot.v1`,合併 project、Organizer latest、TestFlight latest、`readiness[]`、release `workflow.steps[]`、release `gate` verdict、Xcode `xcode` inventory、Simulator `simulator` 狀態與最近 `runs`。頂層 `summary` 是第一屏判讀層:`summary.verdict=pass|warn|block`,`summary.counts` 不只聚合 gate/build/test/archive/xcode/simulator/runtime counts,也直接提升 `doctor.summary.counts` 與 `workflow.summary.counts` 成 `readinessOk|readinessWarns|readinessBlocks|workflowReady|workflowTodos|workflowWarns|workflowBlocks|workflowManual`,讓 agent 不必再下鑽 `.readiness[]` / `.workflow.steps[]` 才知道 release 管理面狀態。`summary.nextActions[]` 會把 gate hard-stop/todo/manual、build/test/archive diagnostics、xcode/simulator observation errors 轉成可直接執行或檢查的 action。非 JSON 文字模式也共用同一份 snapshot JSON formatter,第一行固定是 `[ios][summary]`,後續先列 `[ios][next]`,不再輸出舊式 `phase=doctor` dump。`runs.build.diagnostics` / `runs.test.diagnostics` / `runs.archive.diagnostics` 仍保留完整 `kg.ios.diagnostics.v1`,讓第一輪 payload 就有可行動問題,不用再二次跑 `issues` 或 grep log。預設不查 unified log,所以 `logs` 欄位為 `null`;需要 Xcode Console 視角時加 `--include-logs --log-since 5m --log-limit 200`,snapshot 會內嵌同一份 `kg.ios.logs.v1`。預設會查 `kg.ios.xcode.v1` 讓 agent 第一輪就有 scheme/destination/simulator inventory 視角;需要快速 dashboard 時加 `--skip-xcode`,此時 `xcode:null`。預設也會查 `kg.ios.simulator.v1` 讓 agent 第一輪知道 booted device、app container 與 BooksBrowser process `running|stopped|skipped|unknown`;需要跳過 Simulator GUI 狀態時加 `--skip-simulator`,此時 `simulator:null`。沒有 booted simulator 時 snapshot 仍回 0 並把 `.simulator.status` 設為 `error`,避免 dashboard 因觀測缺口中斷;log provider 失敗則仍傳遞非零 exit。snapshot 只做觀測並回傳 gate 物件,不因 gate warn/block 自己失敗;需要 hard-stop exit code 時跑 `ios_ops.sh gate release --json`。它仍是 read-only，只組合既有 `doctor --json`、`workflow release --json`、gate helper、`xcode --json`、`simulator status --json`、`runs --json` 與可選 `logs --json`;人要看文字 dashboard 可用 `ios_ops.sh snapshot` 或 alias `dashboard`。

`ios_ops.sh commands --json` 是 agent capability catalog:schema 為 `kg.ios.commands.v1`,列每個 subcommand 的 `key`、`aliases`、`sideEffect`、固定 `delegate` 欄位（無委派為 `null`）、用途與輸出 JSON schema。`jsonSchemas[]` 不只列 top-level schema，也必須包含 payload 內穩定內嵌的 child schema（例如 `build/test/archive/runs` 內的 `kg.ios.diagnostics.v1`、`doctor` 內的 `kg.ios.sentry.v1`、`snapshot` 內的 `kg.ios.workflow.v1` / `kg.ios.runs.v1` / `kg.ios.sentry.v1`）。新 agent 不確定能不能寫入或該讀哪個 schema 時先查這個,不要解析 help 文字。

## iOS 編譯 3 步驟 SOP

### Step 1：靜默編譯，直擊錯誤

```bash
./ops/ios_ops.sh build                 # 預設 iPhone Simulator
./ops/ios_ops.sh build --catalyst      # Mac Catalyst（platform=macOS,variant=Mac Catalyst）
./ops/ios_ops.sh build --destination '<xcodebuild destination>'  # 自訂 destination
```

- Exit Code `0` → 編譯成功;仍看 `[ios][issues] warnings=...`，release 前不可無視新增 warnings
- Exit Code 非 `0` → 第一屏 diagnostics 會列官方 `.xcresult` top errors/warnings + raw log path，進 Step 2
- 動到三平台 navigation / Catalyst 專屬路徑時，`--catalyst` 與預設各跑一次驗證（`--timeout` 預設 600s）

### Step 2：還原案發現場

**不要只看單行錯誤就動手改。** 根據錯誤的**檔名 + 行號**，讀取該行**上下至少 20 行**原始碼，結合 Swift/SwiftUI 語法特性完整分析脈絡。

常見需要讀上下文的場景：
- `@ViewBuilder` 限制（return type、條件分支問題）
- Optional unwrap 導致的型別不符
- `@State` / `@Binding` / `@ObservableObject` 使用錯誤
- `async/await` 上下文缺失

### Step 3：對症下藥並驗證

修復後立刻重跑 Step 1。反覆「編譯 → 讀上下文 → 修改」直到 Exit Code 歸零。

## iOS 測試入口（`ops/ios_ops.sh test` / `ops/ios_test.sh`）

`ops/ios_test.sh` 與 `ios_build.sh` 共用 `/tmp/kg-ios-build.lock`。**鎖是細粒度的**：只在 `build-for-testing`（共享 DerivedData 的唯一寫者）期間持有，`test-without-building` 執行階段**不持鎖**。test 產物為 content-keyed 且寫入完成後加 `.kg-test-cache-complete` sentinel（hit 偵測與 double-check 都要求 sentinel，擋住中斷留下的 half-written cache），故並行 agent 可各自在獨立模擬器上同時跑測試而不互相排隊。build 走 `<主repo>/.cache/ios-build-derived-data`（`git-common-dir` 錨定，所有 worktree 同一路徑，禁止改用 Xcode 全域預設位置否則洩漏路徑雜湊孤兒）；test 走 `.cache/ios-test-derived-data`（platform/arch keyed，pool 各 sim 共享暖快取）。政策與根因詳見 [`docs/reference/ios_deriveddata_policy.md`](../reference/ios_deriveddata_policy.md)。

**並行測試（多 agent）**：`./ops/ios_ops.sh simulator lease`/`release` 提供有界的 per-agent 模擬器 pool（`kg-pool-1..N`，env `KG_IOS_SIM_POOL_SIZE` 預設 3）。最簡用法：`./ops/ios_test.sh --unit --lease` 自動租一台 pool 模擬器、結束釋放；或手動 `--device <udid|name>` / `--destination '<xcodebuild destination>'` 指定。`--file` 的 `.swift` 後綴可省（裸型別名亦可，多檔同名會報錯列候選）。test runner 的 unit scope 走 dedicated `BooksBrowserUnitTests` scheme，UI scope 走 dedicated `BooksBrowserUITests` scheme，先走 `simulator ensure-booted`，再採 cache-first `build-for-testing` / `test-without-building` 重用 `.cache/ios-test-derived-data`；`./ops/ios_ops.sh test --cache-status|--prepare-cache|--clean-cache [--unit|--ui|--all-targets] [--json]` 可顯式管理這層 warm cache。verdict JSON 會寫 `timings.lockWaitMs/bootMs/buildForTestingMs/testInvocationMs/testBodyMs/xcresultSessionMs/xcresultHarnessOverheadMs/appLaunchAverageMs/appLaunchSamples/invocationOverheadMs/xcodebuildMs/totalMs` 與 `cache.status`(`lockWaitMs` = 等 `/tmp/kg-ios-build.lock` 排隊時間,與 build/archive 同義;先用它排除「排隊久」再談「執行久」)；stdout 第一屏也會有 `[ios][test-timing] ...` 與 `lockWaitMs=` 取鎖行，若 xcresult 含 `XCTApplicationLaunchMetric` 另會印 `[ios][perf] metric=AppLaunch averageMs=...`。長 UI 測試會每 30 秒輸出 heartbeat（elapsed / xcodebuild pid / log path / 最近 test event），不要讓 6 分鐘以上的 launch permutations 變黑盒。

**第一性原理流程**：測試系統已具備 scope、heartbeat、log preserve、false-green 防護與 DB lock retry；因此 iOS 開發不再採「不主動跑測試」的保守規則，而是採**最小足夠驗證**。

```bash
./ops/ios_ops.sh build --json                              # machine-readable kg.ios.run.v1
./ops/ios_ops.sh test --timeout 1200                       # 預設只跑 BooksBrowserTests unit target
./ops/ios_ops.sh test --json                               # machine-readable kg.ios.run.v1
./ops/ios_ops.sh test --file NotebookCoverContrastTests.swift
./ops/ios_ops.sh test -g "sanitizeOutbox"
./ops/ios_ops.sh test --ui --file BooksBrowserUITests.swift # 只跑 UI test 檔案
./ops/ios_ops.sh test --ui testLaunchShowsPrimaryTabs       # 只跑 UI test method
./ops/ios_ops.sh test --launch-benchmark
./ops/ios_ops.sh test --ui --ui-launch-profile standard testLaunchShowsPrimaryTabs
./ops/ios_ops.sh test --all-targets --timeout 1200          # scheme 全量：unit + UI
./ops/ios_ops.sh test --file FooTests.swift --list          # 只列 resolved -only-testing selectors
```

- 預設 scope 是 `unit`，會自動加 `-only-testing:BooksBrowserTests`；UI tests 不會被誤混進 unit full。
- `./ops/ios_ops.sh build --json` / 一般 `test --json` 會把 delegate stdout/stderr 導到 stderr，stdout 保留單一 `kg.ios.run.v1` payload；已存在原生 JSON 契約的 `test --cache-status|--prepare-cache|--clean-cache --json` 維持原 schema，不再包一層 run report。
- `--ui` 會把 discovery target 切到 `BooksBrowserUITests`，支援 `--file` / method selector；未明示時會自動帶 `--ui-launch-profile ui-smoke`，把 UI smoke 驗證切到較輕的 app launch profile。若要回到完整 startup 行為做 baseline / A/B，明示 `--ui-launch-profile standard`。
- `--launch-benchmark` 是正式的 UI launch perf 入口，固定跑 `BooksBrowserUITests/testLaunchPerformance`；目前以 XCTest 內建 `XCTApplicationLaunchMetric` 預設行為為準，會在第一屏輸出 `appLaunchAverageMs` / `appLaunchSamples` 供比較。
- `--all-targets` 跑整個 scheme TestAction，不能和 `--file` / `-g` / specific method 混用。
- 測試結束第一屏會列 `[ios][issues] source=xcresult-test-results` 與 `[ios][tests] tests=... passed=... failed=...`；false-green 執行數優先取官方 `.xcresult`，raw log 只作 fallback。
- 失敗或 inconclusive 時保留完整 xcodebuild log 與 `.xcresult`，stdout 會印出 log / xcresult path；成功時 verdict 也記錄 log / xcresult path。
- 若 Xcode 回 `build.db database is locked` / `unable to attach DB`，runner 會在同一把 repo lock 內短暫等待並重試，避免把 infrastructure lock 誤判成測試失敗。
- 若要把 build-for-testing 成本拆出日常迭代回路，先跑 `./ops/ios_ops.sh test --prepare-cache --unit` 或 `--ui`，後續 scoped `test` 會優先重用 `.xctestrun`；`--cache-status --json` 會回 `kg.ios.test-cache.v1`，含 `productsReady` / `xctestrunPath` / `timings.bootMs/buildForTestingMs`。
- 若要讓 agent/human 在第一屏就看懂時間分布與 release readiness，不要只翻 raw log：`./ops/ios_ops.sh runs --json` 會保留每次 build/test/archive 的 `options` / `cache` / `timings`；`./ops/ios_ops.sh snapshot --json` 會再把它們收斂成 `summary.timings.build|test|archive|simulator`，並把 `doctor/workflow` 聚合成 `summary.counts.readiness*` / `workflow*`；文字模式固定在 `[ios][summary]` 後緊接 `[ios][timing] build ...` / `[ios][timing] test ...` / `[ios][timing] archive ...` / `[ios][timing] simulator ...`。

### iOS 測試效能經驗固化

- `simulator ensure-booted` 很重要，但它只吃掉 cold boot 那層；若 warm path 仍慢，下一個嫌疑通常是 `test-without-building` 的 host/session，而不是 simulator 本身。
- 要判斷「是不是 simulator lifecycle 在吞時間」，先看 `kg.ios.simulator.v1.timings`：`bootMs/bootstatusMs` 高代表 cold boot，`statusMs` 高代表你在 launch/terminate/screenshot 前就花在狀態探測，`lifecycleMs` 高才是 `simctl launch|terminate` 本體慢。
- 不要再依賴 simulator 內 `pgrep` 類工具做 app process probe：iOS 26.4 runtime 上 `pgrep` 會卡 `sysmond service not found`，而且 `simctl spawn` 對 bare command name 的 PATH 行為也不穩。現行做法改成 host-side `ps` + device UDID + app executable path，穩定性更高。
- `build-for-testing` 要顯式拆出日常回路；不先做 cache reuse，就會把每次 scoped test 的固定成本看錯成 render 成本。
- `XCTApplicationLaunchMetric` 的 `appLaunchAverageMs` 是單次 app launch 平均，不是整個 UI benchmark wall time；判讀時要同時看 `testBodyMs`、`xcresultSessionMs`、`invocationOverheadMs`。
- 任何「好像有變快」都不算結論，除非 timing 已回寫到 verdict JSON / `runs` / `snapshot`；沒有進控制面的數字，下一輪 agent 就無法延續判讀。
- 若某個優化旗標沒有在 xcresult sample count 或 timing 上留下可驗證差異，就不要把它留成表面功能。
- **先分「排隊」再分「執行」**:build/test/archive verdict 都有 `timings.lockWaitMs`(共享 `/tmp/kg-ios-build.lock` 的排隊等待,三者同義)。一個 run 看起來慢,先看 `lockWaitMs` 是不是卡在別的 worktree 後面,再看 `xcodebuildMs`/`testInvocationMs` 等執行段;沒有 lock-wait 數字時,排隊延遲會偽裝成執行慢。
- **catalog 長任務不是黑盒**:`catalog snapshots` 的 build-for-testing / test-without-building / full-test 階段會發 `[ios][catalog] phase=<label> start/running/done` 到 **stderr**(預設開,每 ~20s 帶 elapsed/pid/last log line),`stdout` 維持純 `kg.ios.catalog.v1` JSON。執行期沒輸出別急著 `ps`/xcresult 旁路觀測,先看 stderr heartbeat;細粒度 phase trace 仍由 `KG_IOS_OPS_CATALOG_TRACE=1` 開。
- **cache-miss 不是 test failure**:`catalog snapshots --reuse-build` 命中 stale/缺失 cache 時頂層 `status:"cache-miss"`(非 `error`)、`errors[].catalog-cache` 帶可行動 hint、stderr 印一行提示。看到 `cache-miss` 就跑 `catalog prepare` 或拿掉 `--reuse-build`,不要當成程式碼壞掉去追。
- **uniform image 改走 warning 語意**:`uniform-image-detected` 現在只會讓 `validation.status:"warn"` 與頂層 `status:"warn"`，不再把已成功產出的 PNG 誤判成 fatal `error`。真正 fatal 的仍是 `png-count-mismatch`、degenerate dimensions、xcodebuild/test/copy 失敗。
- **失敗也會搶救 PNG**:full run 失敗時 wrapper 仍把 simulator container 內已生成的截圖 salvage 回本地。`artifacts.containerPngCount` = container 內實際張數,`copy.salvaged=true` + `errors[].catalog-salvage`(info note)代表「有生成但 run 失敗已救回」;`containerPngCount==0` 才是真的沒生成。別再手動進 container 撈圖。
- **snapshot 會順手生 atlas sidecar**:`catalog snapshots` 成功複製 PNG 後，會在同一個 `out_root` 自動生成 `catalog.html`（自由縮放 SVG 心智圖，與 CLI `tree/node/node-url` 共用 `nodePath`）與 `review_manifest.json`（含 `tree` 欄位）；JSON payload 的 `review.canvasHtml` / `review.reviewManifest` 與文字輸出都會帶路徑。sidecar 生成失敗只記 warning，不會遮蔽 raw PNG 已成功落地。

### 日常 warm-loop 建議

- 日常局部迭代先做兩件事：`./ops/ios_ops.sh simulator ensure-booted --json`、`./ops/ios_ops.sh test --prepare-cache --unit` 或 `--ui`。這會把 cold boot 與 `build-for-testing` 從主回路拆出去。
- 接著才跑 scoped test：`./ops/ios_ops.sh test --file FooTests.swift`、`./ops/ios_ops.sh test --ui testLaunchShowsPrimaryTabs`。看 `cache.status` 是否為 `hit`，以及 `timings.testInvocationMs` / `xcresultSessionMs` 是否仍然偏高。
- 若要看整條回路花在哪，不要自己猜：先跑 `./ops/ios_ops.sh snapshot --json --skip-xcode`，讀 `summary.timings.build|test|simulator`；若只想看測試暖機層，跑 `./ops/ios_ops.sh test --cache-status --json` 與 `./ops/ios_ops.sh runs --json`。
- 只有在 scoped 回路已 warm、仍有異常延遲時，才去懷疑 UI host / XCUI harness / app launch profile。不要在 cold path 上討論 render 成本。

### iOS 開發驗證梯度

| 變更 / 狀態 | 必跑 |
|---|---|
| 純註解 / doc-only | 不跑 iOS test;跑 docs gate 即可 |
| iOS 編譯面或簡單型別修正 | `./ops/ios_ops.sh build` |
| iOS model/service/presenter/test 邏輯 | `./ops/ios_ops.sh test --file <相關Tests.swift>` 或 `-g <pattern>` + `./ops/ios_ops.sh build` |
| UI / navigation / accessibility / app launch | 相關 unit test + `./ops/ios_ops.sh test --ui ...` + `./ops/ios_ops.sh build` |
| test runner / scheme / SwiftData model / sync lifecycle / 跨 feature 共用面 | `./ops/ios_ops.sh test --all-targets --timeout 1200` + `./ops/ios_ops.sh build` |
| 多個 test 失敗或原因不清 | `./ops/ios_test_matrix.sh --timeout 300 [--start-at File.swift]`,逐檔定位後再修 |
| release / cleanup all / 宣稱 iOS 全綠 | `./ops/ios_ops.sh test --all-targets --timeout 1200` + `./ops/ios_ops.sh build` |

原則:
- 不用 `--all-targets` 當第一反應;先跑最小可證明範圍,避免把多個根因混在一起。
- 不用 build 代替 test;build 只證明可編譯,不證明行為。
- 看到 tool failure / inconclusive / false green 先修 runner 或 invocation,不要將就。
- 長 UI permutations 正常會跑數分鐘;依 heartbeat 判斷進度,不要因短期無 test case output 就殺掉。

## 發版 / TestFlight（`ops/ios_release.sh`）

App Store / TestFlight 出 `.ipa`。用 App Store Connect API key 的簽章基建，**無需手動匯入 Apple Distribution 憑證**（cert/profile 已一次性建置，含重建步驟見 `~/.secrets/apple/README.md`）。

> 版號 bump / `ios/x.y.z` tag / changelog 走 **`ops/release.sh`**（`status`/`bump`/`changelog`/`publish`，單一入口；`publish` dry-run 預設、`--yes` 才 commit+tag+push）。本節的 `ios_release.sh`（出 build）與 `asc.sh`（App Store 文案/查詢）是**正交**設施——版號 tag 與出 build 互不依賴。注意目前無 tag-triggered CI，tag 僅為版本標記。

```bash
./ops/ios_ops.sh archive              # archive + export 出 .ipa（無對外副作用，預設）
./ops/ios_ops.sh archive --json       # machine-readable kg.ios.archive.v1
./ops/ios_ops.sh archive --upload     # 額外上傳 → TestFlight（對外副作用，需明示）
./ops/ios_release.sh                  # primitive:同 archive
./ops/ios_release.sh --upload         # primitive:同 archive --upload
./ops/ios_release.sh --key 6Y7DC88RUY # 換 ASC API key（預設 TCXVHFRXMS / App Manager）
./ops/ios_release.sh --timeout 900    # 自訂 build lock 等待秒數
```

- **產物**：`ios/build/export/BooksBrowser.ipa`（git-ignored）。
- **JSON façade**：`./ops/ios_ops.sh archive --json` 會把 delegate stdout/stderr 導到 stderr，stdout 保留單一 `kg.ios.archive.v1` payload；語意分成 `archive` / `export` / `upload` 三段，不與一般 `kg.ios.run.v1` 混用。
- **diagnostics**：archive 階段保留 raw log 與 `Archive.xcresult`，並在第一屏用 `ios_diagnostics.py` 列 warnings/errors；archive 失敗時先看 `[ios][issues]` 與 `xcresult=` path。
- **簽章**：manual signing — Apple Distribution cert（keychain）+ `KG App Store` profile（`ios/ExportOptions.plist`）。`method=app-store`（Xcode 26 印 deprecated 警告但可用；新式 `app-store-connect` 即使 manual 仍強制 Xcode 內登入 ASC account，純 CLI 不適用）。
- **build-number guard**：`--upload` 前比對本機 `CURRENT_PROJECT_VERSION`（`-target BooksBrowser`）與 TestFlight 最新 build，重複即中止 — 須先 bump 版號。archive/export 不受此限。
- **keychain 免互動**：codesign 存取私鑰需 partition list 授權（一次性 `security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <登入密碼> ~/Library/Keychains/login.keychain-db`）；未設則互動 terminal 彈授權框、背景/CI 會 hang。
- **key 選擇**：`TCXVHFRXMS`(App Manager) 可送審;`6Y7DC88RUY`(Developer) 僅 TestFlight。後端訂閱驗簽用 `6Y7DC88RUY`，**勿 revoke**。
- 共用 `ios_build.sh` 的 `/tmp/kg-ios-build.lock`，多 worktree 安全。

### App Store Connect 控制台（`ops/asc.sh`）

`ios_release.sh` 出 build；`asc.sh` 補「ASC 全表面查詢 + metadata/結構讀寫」——近乎完整的 ASC 控制台（App 資訊 / 版本文案 / 審查資訊 / 評論回覆 / 無障礙 / 營利 / 發布控制 / 送審佇列）。主體是 codemagic CLI 包裝（同 `ios_release.sh` 的 `asc()` wrapper），無手刻 JWT；codemagic 暴露不到的物件由旁路 helper 補、JWT 只活在 helper、不污染主檔：唯讀走 `ops/asc_get.py`（GET），**寫入**走 `ops/asc_write.py`（一般化 PATCH/POST/DELETE，body 由 stdin 餵 JSON；4xx/5xx 回 `{_httpError,_detail}`、204 回 `{_ok}`，不裸 crash）。所有寫入經單一 `emit_write` gate：**預設 dry-run**（印舊→新 + copy-paste 指令），`--yes` 才真送。

批次審文案 / 重寫 / 上傳走 `ops/asc_text_bundle.py`: `dump --output asc.json` 一次拉 App 層文案、版本文案、版本 copyright、審查資訊、訂閱文字、截圖/價格/評論摘要；編輯 JSON 後 `apply asc.json` 先 dry-run diff，`apply asc.json --yes` 才 PATCH 低風險文字欄位。它不送審、不撤回、不上傳截圖、不改價格 / 發布控制。

```bash
# ── 唯讀查詢 ──
./ops/asc.sh versions / builds / info             # 版本+審查 state / TestFlight build / app 層級
./ops/asc_text_bundle.py dump -o asc.json         # 整包文案/審查資料 JSON
./ops/asc.sh metadata --locale zh-Hant            # 某版本某語系文案
./ops/asc.sh review-status / review-detail        # 審查提交 state / 審查聯絡+demo+送審備註
./ops/asc.sh submissions [N]                      # 送審佇列 reviewSubmissions + 每筆打包項目數
./ops/asc.sh screenshots / categories             # 截圖逐張 state / 可用分類 ID
./ops/asc.sh reviews [N] / accessibility          # 用戶評論+是否已回覆 / 無障礙宣告
./ops/asc.sh subscriptions / iap / pricing        # 訂閱群組→方案 / 一次性購買 / 基礎定價+供應
./ops/asc.sh sub-offers <subId>                   # 訂閱優惠：介紹性/促銷/兌換碼
./ops/asc.sh release-plan                         # 發布方式 releaseType + 分階段發布狀態
# ── 寫入（皆 dry-run 預設，--yes 才送）──
./ops/asc.sh set <field> <value>                  # 版本文案 appStoreVersionLocalization
./ops/asc.sh set-review <field> <value>           # 審查資訊 appStoreReviewDetail
./ops/asc.sh set-appinfo <field> <value>          # App 層本地化：name/subtitle/privacy-url
./ops/asc.sh set-eula <text> / set-content-rights <uses|none>
./ops/asc.sh set-category <primary|secondary> <ID> / set-rating <attr> <value>
./ops/asc.sh reply-review <reviewId> <text>       # 回覆用戶評論（POST/PATCH upsert）
./ops/asc.sh set-sub-name|set-sub-desc|set-sub-review-note <subId> <value>
./ops/asc.sh set-sub-price <subId> <territory> <customerPrice>   # ⚠ 動真實計費
./ops/asc.sh set-release-type <manual|auto|scheduled> [ISO8601]  # auto=審核過自動上架
./ops/asc.sh phased <start|pause|resume|complete|cancel>         # 分階段發布7天ramp
./ops/asc_text_bundle.py apply asc.json [--yes]   # 整包文案 diff / PATCH（dry-run 預設）
```

**物件邊界**（用錯子命令會互相指路）：`set`→`appStoreVersionLocalization`（逐語系版本文案）；`set-review`→`appStoreReviewDetail`（整版一份審查資訊）；`set-appinfo`→`appInfoLocalization`（App 層逐語系 name/subtitle/privacy-url）；另有 App 層結構寫入（EULA/內容版權/分類/年齡分級）、營利寫入（`set-sub-*` → subscriptionLocalization/Price，`set-sub-price` 用 `preserveCurrentPrice:true` 保護既有訂戶 + 印三重 ⚠，後端以 key `6Y7DC88RUY` 驗訂閱權益）、發布控制（`set-release-type` PATCH appStoreVersions、`phased` POST/PATCH/DELETE appStoreVersionPhasedReleases，complete/cancel 不可逆會警告）。dry-run header 印目標版本字串+state（如 `1.6 (REJECTED)`）避免誤寫。

- **set 可寫 field**：`description / keywords / whats-new / marketing-url / support-url / promotional-text`，空值被擋。
- **刻意不做**：submit-for-review / 撤回送審（避免誤送誤撤，走 GUI）；IAP 寫面（KG `inAppPurchasesV2=0` 無對象）；訂閱優惠建立/刪除（逐地區 price point 繁瑣高風險且罕見，走 GUI）。
- **key**：預設 `TCXVHFRXMS`（App Manager，可寫）；`.p8` 路徑 `${ASC_KEY_DIR:-~/.secrets/apple}/AuthKey_<KEY_ID>.p8`（CI/部署機可覆寫 `ASC_KEY_DIR`）。

#### GUI 可讀 vs API 可讀/可寫

| GUI 區塊 | `asc.sh` 能力 |
|---|---|
| 版本 / 審查 state / build / 文案 metadata / IAP / 分析數字 | ✅ codemagic 讀；文案 `set` 可寫 |
| App 副標/名稱/隱私URL、分類、年齡分級、EULA、內容版權 | ✅ raw 讀寫（set-appinfo/set-category/set-rating/set-eula/set-content-rights） |
| 審查聯絡/demo/送審備註、截圖逐張 state | ✅ raw 讀（review-detail/screenshots）；審查資訊另可寫（set-review） |
| 用戶評論、無障礙宣告 | ✅ 讀（reviews/accessibility）；評論可回覆（reply-review）；無障礙建立走 GUI |
| 訂閱方案/價格/優惠、基礎定價、發布方式、分階段發布、送審佇列 | ✅ raw 讀（subscriptions/pricing/sub-offers/release-plan/submissions）；訂閱名/描述/備註/價格、發布方式、分階段發布可寫 |
| **App 隱私權營養標**（資料蒐集/追蹤宣告） | ❌ public API 不提供，**只能 GUI** |
| **截圖/preview 上傳**、**供應地區設定** | ❌ 無 API/codemagic 命令，**GUI 或 Transporter** |
| **被拒原因（Resolution Center 對話文字）** | ❌ public API 不提供，**只能 GUI 看** |
| 截圖圖檔「內容」是否含已移除功能 | ⚠ API 只給 fileName/state，須 fetch 縮圖目視 |

#### App Store 改動的審核成本判斷

| 想改什麼 | 審核成本 / 流程 |
|---|---|
| `promotionalText` 促銷文 | 低。可不提交新版更新；仍需保持真實、不可宣稱未實作功能。 |
| 價格、供應地區、分階段發布、release type | 不走一般 App Review，但屬真實商務/發布控制；一律先 dry-run，價格變更須確認訂戶影響。 |
| support URL、privacy URL、review notes、demo account | 低到中。依當前 version/submission state 可改；review notes/demo 是審查員資訊，重送前必查是否過期。 |
| description、keywords、subtitle、marketing URL、copyright | 中。屬 metadata；`REJECTED` / `METADATA_REJECTED` / `PREPARE_FOR_SUBMISSION` 通常可修後重送同版，同一輪不可寫欄位以 ASC API 回 `STATE_ERROR` 為準。 |
| screenshots / app previews | 中高。送審中通常不能改；已上架版本核准後，主產品頁截圖/preview 更新通常要建下一個 app version 再送審。API 目前只列 state，不負責上傳。 |
| 訂閱名稱、描述、review note、review screenshot、intro offer | 中高。訂閱物件本身可能進 subscription review；文案必須和 paywall / StoreKit 顯示一致。價格/優惠尤其高風險，逐地區 GUI 檢查。 |
| app binary、功能、UI、權限、登入/IAP 實作 | 高。必須新 build + App Review；同 `MARKETING_VERSION` 重送也要 bump `CURRENT_PROJECT_VERSION`，並重新綁新 build。 |
| App Privacy nutrition labels、Resolution Center 對話 | GUI-only。public API 讀不到/寫不到；被拒原因一定要人工進 ASC GUI 看。 |

#### 被拒處理 SOP（resubmit-readiness 演練，每次重送跑一遍）

1. `./ops/asc.sh review-status` 確認最新提交為 `UNRESOLVED_ISSUES`。
2. 到 ASC GUI「App 審查 → 解決中心」讀 Apple 的拒絕理由（API 讀不到）。
3. **掃殘留**：被拒功能名若已移除，`asc.sh metadata` + `review-detail` + app 副標全 grep 一遍確認 0 命中；`asc.sh screenshots` 列出截圖、fetch 縮圖目視無殘影。
4. **查備註是否過期**：`asc.sh review-detail` 的 notes 常沿用上一輪舊文（KG 實例曾停在 3.1.2(c) EULA 而非當輪原因）；重送時若需更新送審備註，直接 `asc.sh set-review notes "..."`（dry-run 看舊→新，`--yes` 才寫）對應「本輪」原因；向審查員對話回覆仍須 GUI 解決中心。
5. 改 code/文案（`asc.sh set …` 或改 app 碼）→ bump `CURRENT_PROJECT_VERSION`（同 `MARKETING_VERSION` 重送只 bump build；`asc.sh builds` 確認新 build > TestFlight 現值即無衝突）→ `ios_release.sh --upload` → GUI 把新 build 綁上該版本 → 重送。
6. 加密合規順手：本專案 `GENERATE_INFOPLIST_FILE = YES`（無 source Info.plist），故設 build setting `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = NO`（多數 app 免出口加密，省每次上傳被問）。

#### 已知缺口（待辦，本輪未工具化）

screenshots / app preview **上傳**（list 已做；上傳 codemagic 無命令，須 GUI 或 Transporter + raw multipart）、**多語 localizations**（現僅 `zh-Hant`，缺 `en-US` 易被拒）、`appStoreVersions create`（重送下一版前須先建版本 row）、App 隱私權營養標（無 public API，GUI-only）。submit-for-review / 撤回送審、IAP 寫面、訂閱優惠建立為**刻意不做**（非缺口，理由見上「刻意不做」）。

## App 架構速查

### 主要 Services

| Service | 職責 |
|---------|------|
| `AuthManager.swift` | 單例，Apple/Google SSO、Keychain token、登入狀態 |
| `KGService.swift` | 後端 API 呼叫（拆 10 個 extension：+Graph / +Health / +Models / +Notebook / +Request / +ServerURL / +Stats / +Sync / +UserConfig / +VocabCRUD） |
| `BackgroundSyncActor` | `@ModelActor`，背景同步（push review/stats、pull cards、flush bilateral ops） |
| `SyncCoordinator` | 同步協調（手動同步入口、orphan cleanup） |
| `BookshelfImportService` | Multi-format import（EPUB/TXT/MD/PDF） |
| `AppToastCoordinator` | Toast notification 管理（EnvironmentKey 注入） |
| `AppCrashReporting` | Sentry bootstrap；opt-in via `Info.plist` `SentryDSN`；`bootstrap()` 於 `BooksBrowserApp.init()` 第一步呼叫；`setUser(id:)` 連動 `authManager.isLoggedIn` 變化；`record(_:context:)` 手動 capture |

### 主要 Views

| View | 說明 |
|------|------|
| `Settings/SettingsView` | 登入登出、伺服器設定、第三方整合 |
| `Reader/ReaderView` | EPUB 閱讀器（iOS only），查詞 → batchAdd → triggerPipeline |
| `Reader/PDFReaderView` | PDF 閱讀器（iOS only） |
| `Vocabulary/` | 單字瀏覽、知識圖譜視覺化、手動同步、hide/unhide links |
| `Vocabulary/Scenes/StatsPresenter` | 統計總覽 + graph thumbnail + health blob |
| `Vocabulary/Scenes/TodayReviewPresenter` | 每日複習 |
| `Bookshelf/BookshelfView` | 書架 + multi-format import |
| `Welcome/WelcomeView` | 首次啟動 / guest 引導（含 login entry points） |

### iOS 資料同步流程

```
Reader 查詞
  → 暫存 VocabularyEntry（syncStatus=0, pending）
  → POST /api/vocab（batchAdd）→ 伺服器生成 embedding
  → POST /api/pipeline（fire-and-forget）→ 伺服器背景 Enrich/Link/Difficulty/Optional External Sync
  → GET /api/vocab?since=<上次同步>（pullCardsToLocal）→ 更新 SwiftData
```

### 認證流程

```
Apple/Google SSO
  → Google User ID 或自訂密語（存 Keychain）
  → 作為 Authorization: Bearer <token> 發給後端
  → 後端建立 data/users/<user_id>/ 隔離目錄
  → HTTP 401 → iOS 自動登出 + 清空 SwiftData
```

### Crash Reporting（Sentry）

**iOS env / Info.plist key / 取樣率（SoT）**：`docs/sop/deploy.md §Sentry 錯誤追蹤 → iOS env / Info.plist`。本段僅寫 iOS-side 程式碼層 wiring。

實作要點（`Services/AppCrashReporting.swift`）：
- SPM dep `sentry-cocoa` 透過 `canImport(Sentry)` 守門 — 缺套件即 pure no-op，dev / PR build 不卡編譯
- Bootstrap 順序：`AppCrashReporting.bootstrap()` 在 `BooksBrowserApp.init()` 第一步執行（早於 `ModelContainer` init，捕捉儲存初始化失敗）
- User 追蹤：`AppCrashReporting.setUser(id:)` 連動 `authManager.isLoggedIn` onChange — 登出時清除，避免多帳戶污染
- `beforeSend` 過濾：丟棄 `CancellationError` / `NSURLErrorCancelled` 噪音；HTTP breadcrumb 自動 strip query string
- `./ops/ios_ops.sh sentry --json` 會回 `kg.ios.sentry.v1`，把 source path/existence、`canImport(Sentry)` guard、`SENTRY_ENABLED_IN_DEBUG=1` / `-sentryTest` contract、release name/dist 格式提升成 machine-readable control plane，避免每次靠 grep 手動判讀 wiring
- `./ops/ios_ops.sh snapshot --json` 現在也內嵌 `sentry` surface，並把 wiring 漂移收斂成 `summary.counts.sentryWarnings`；若只想知道 release dashboard 是否因 Sentry wiring 漂掉而變黃，不必再手動額外跑 `sentry`
- 對這類 wiring surface，不要只測 happy path。`ops/test_ios_ops.sh` 現在用 fixture env 直接模擬 `source missing / canImport=false / dsnReference=false`，驗證 `snapshot --json` 會把 drift 轉成 `summary.counts.sentryWarnings` 與 `summary.nextActions[].source=="sentry"`；這是控制面經驗固化的正確模式
- 同一個 surface 不能各自重算。`doctor` 的 sentry readiness 與頂層 `doctor.sentry` 現在都直接重用 `sentry_summary_json()`；`snapshot` 也直接吃 `doctor.sentry`，避免 `doctor` / `sentry --json` / `snapshot` 三條路各自 grep、最後判讀不一致
- 連 wiring failure 清單也收斂成單一真相:`sentry_summary_json()` 直接輸出 `issues[]`（逐 wiring failure,含 key/message/command）;`doctor` verdict = `issues|length==0`、`snapshot` nextActions = `map(issues)`、`sentryWarnings` = `issues|length` 全衍生自此。新增一個 wiring check 只改 `issues[]` 一處,不必同步三處列舉——這是「判讀規則(不只資料來源)單一真相」的範例
- **聚合面用動態 passthrough,不用硬編碼 allowlist**:`snapshot` 的 `timing_summary` 從逐欄位 allowlist 改成 `($run.timings // {}) + {cacheStatus}`,wrapper 新增任何 timing 欄位(如 `lockWaitMs`)自動上第一屏,不必改 snapshot。契約測試注入 `probeMs:777` 驗 passthrough(allowlist 會吞掉)。判準:當聚合面只是「轉發子 surface 的欄位」時,passthrough > allowlist;allowlist 每加一個欄位都是一次漏接機會。
- **何時「不」收斂(false-DRY)也要明確固化**:verdict 三段式（`blocks>0→block / warns>0→warn / pass`）在 doctor/workflow/gate/snapshot 重複,但**刻意不抽**——input 異構(readiness / release-block / diag-errors / 跨源 sum)、runs 另有合理的 `unknown` 分支、跨檔 jq def 共用的耦合脆弱性 > 重複 3 行的成本。改用**一致性契約測試**(`test_ios_ops.sh` 的 canonical `rule($b;$w)`)鎖 3 個 count-based surface 不漂移。判準:重複的是「同一規則」就抽或測;重複的只是「同一形狀、不同語義的視圖」就不抽,改用契約測試防 drift。何時不 DRY 本身就是要記錄的控制面決策。

### Hot Reload（InjectionNext + Inject）

開發時免 build 即時更新 SwiftUI，把「改一行等 30 秒 build」縮到秒級。Debug-only，Release builds LLVM-strip 為 no-op，**production 零影響**。

**前置一次性設定**：
1. SPM dep：`https://github.com/krzysztofzablocki/Inject`（已加進 `BooksBrowser.xcodeproj`）
2. Build Settings → Debug → Other Linker Flags 含 `-Xlinker -interposable`（**只 Debug**）
3. 下載 [InjectionNext.app](https://github.com/johnno1962/InjectionNext) 放 `/Applications/`

**使用方式**：
1. 啟動 InjectionNext.app（menu bar 出現 icon）→ menu bar 點 **Launch Xcode** 開啟 BooksBrowser.xcworkspace
2. ⌘R 跑 Debug build 到 simulator，console 應出現 `💉 InjectionNext connected`
3. 改任何已加 `.enableInjection()` 的 SwiftUI view → 存檔 → simulator 1-2 秒內重渲染

**hot reload 範圍**：
- `Views/**/*.swift` 下所有 non-private `struct X: View`(排除 Debug/Scenarios、Readium/PDFReader bridging、ViewModifier、`#Preview` 內)已**全面注入三件套**(`import Inject` / `@ObserveInjection` / `.enableInjection()`)— 改任一 leaf view body 都能熱重載
- **可注入**：view body / modifier / layout / 文案 / `AppTheme` 色票 / padding / spacing / radius / shadow / opacity
- **不可注入(仍需 full build)**：stored property 增減、`@State` 初始值、function signature 改動、`enum` case 新增、`@Observable` macro 生成的 code(偶有時延)、Readium C++/ObjC++ bridging 改動、`UIViewRepresentable`

**自動化工具**：
- 新增 leaf view 後若忘加三件套,跑 `python3 ops/inject_codemod.py --apply` 自動補(idempotent)
- `ops/injection_lint.sh --strict` 守門:三規則 — (R1) 合格 View 必有 `@ObserveInjection`;(R2) 同檔 `@ObserveInjection` 數 == `.enableInjection()` 數;(R3) 有 `@ObserveInjection` 必有 `import Inject`
- 已知例外:body 為 `if` / `switch` 根 expression 時,codemod 跳過 — 手工包 `Group { ... }.enableInjection()`(現有 9 個 case 已處理完)

**故障排除**：
- console 無 `💉` 訊息 → InjectionNext.app 未啟、或 Xcode 不是從 menu bar 「Launch Xcode」開的
- 改 file 後 simulator 沒反應 → 看 console 是否報 `cannot inject ...`（多半是改到 stored property），需 ⌘R 重 build
- Release archive 報錯 → 確認 `-interposable` flag **只在 Debug 配置**，Release 維持原狀

### Playbook Catalog（SwiftUI 元件目錄）

DEBUG-only 元件 catalog，讓 simulator 啟動時直接進入「狀態矩陣牆」而非正常 app UI，給 CLI 截圖協作（Claude / simctl）用。Phase 1 hot reload + Phase 3 catalog 組合 = 視覺迭代閉環：你改 `AppTheme.swift` 色票 → InjectionNext 秒級重渲染 catalog → simctl 截圖讓 Claude 看到結果。

**啟用方式**：
1. Xcode → Product → Scheme → Edit Scheme → Run → Arguments → **Launch Arguments** → 加 `-catalog`
2. ⌘R 跑 Debug build，app 啟動時 `BooksBrowserApp` 偵測到 `-catalog` 改用 `CatalogScene()` 為 root view（取代正常 `ContentView`）
3. simulator 開啟即見 Playbook catalog 列表，左側分類 / 右側渲染

要回正常 app：scheme 移除 `-catalog` 即可（建議**保留兩個 scheme**：`BooksBrowser` 正常、`BooksBrowser-Catalog` 含 launch arg）。

**目錄結構**：
- `ios/BooksBrowser/Debug/CatalogScene.swift` — 入口 view + `static func buildPlaybook()`(BooksBrowserTests 也 reuse 同一份 surface registration)
- `ios/BooksBrowser/Debug/Scenarios/*Scenarios.swift` — 每個 surface 一檔，通過 `register(in:)` 加 scenarios

**Taxonomy 是 source of truth（2026-06）**：每個 Playbook category 由 `CatalogScene.Manifest` 的 `CatalogSurface` 宣告三個維度 — `kind`（`SurfaceKind`：`featureScreen` / `overlay` / `buildingBlock` / `engineering`，決定 lane）、`feature`、`screen`（`ScreenID`，**僅 `featureScreen` 有**，= app 真實全螢幕身分）。**不要在 doc 手抄 group / scenario 數**（必漂）：權威清單一律讀 source（`CatalogScene.Manifest.surfaces`）與 `CatalogCoverageTests`。

契約由 `CatalogCoverageTests` 強制（漏 register、重複螢幕、缺宣告、缺覆蓋都會紅）：
- **register 完整性**：`buildPlaybook()` 註冊的 group 必須 = `Manifest.categoryNames`。
- **一螢幕一 surface**：每個 `featureScreen` 的 `screen` 不可重複（防三胞胎，例如舊 `Today Review` / `Today Review View` / `Today Review Presenter` 渲染同一畫面的歷史病）。
- **kind 宣告完整**：每個 category 都有 `CatalogSurface`（無漏宣告 lane）。
- **覆蓋無缺口**：`Set(ScreenID.allCases) − Manifest.pendingCoverage` 必須全被 `featureScreen` 覆蓋（`pendingCoverage` 目前為空 = 全覆蓋；它是顯式遞減的 debt set，不能對已覆蓋螢幕說謊）。
- **index round-trip**：`Manifest.indexJSONData()` 必須一 category 一筆、各帶 source-declared kind/feature/screen。

**離線 gallery 消費 `catalog_index.json`（不再猜）**：snapshot run（`CatalogSnapshotTests`）在 PNG 旁吐 `catalog_index.json`（`category → {kind, feature, screen}`，來自 `Manifest.indexJSONData()`）；`ops/catalog_review_*.py` 讀它決定 lane/feature/screen，**退役**舊的透明邊緣像素 sniff + `Presenter`/` View` regex（僅在 index 缺失的 legacy artifact 才降級為 fallback）。改 lane/feature 分類 = 改 iOS source 的 `CatalogSurface`，不是改 Python heuristic。

**仍排除**：Reader 本體（Readium SDK runtime 太重，catalog 只蓋 `Reader View · Chrome` 層；ReadiumNavigator 為嵌入式不獨立）。

**新增 surface scenarios 範本**：

```swift
// ios/BooksBrowser/Debug/Scenarios/FooScenarios.swift
#if DEBUG
import Playbook
import SwiftUI

enum FooScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Foo") {
            Scenario("Loading", layout: .fill) {
                AppThemeContainer { FooView(state: .loading) }
                    .environmentObject(AppAppearanceStore.preview)
            }
            // ...
        }
    }
}
#endif
```

寫完在 `CatalogScene.Manifest.entries` 加一筆 `ManifestEntry`，用 factory 宣告 surface 的 kind/feature/screen 再掛 `register`：
- 全螢幕 → `screen("Foo View", .someFeature, .fooScreen)`（先在 `ScreenID` 加 case；一個 case 對一個 `featureScreen`）
- 浮層 → `overlay("Foo Sheet", .someFeature)`；元件 → `block("Foo Card", .someFeature)`；dev harness → `eng("Foo Presenter", .someFeature)`

漏宣告 / 漏 register / 螢幕重複 / 覆蓋缺口都會被 `CatalogCoverageTests` 擋紅。**真實全螢幕優先走統一 seam**（seeded in-memory `ModelContainer` + 注入 `CatalogPreviewAuth` + DEBUG `skipCatalogTasks` 跳 `.task` 副作用），別依賴 `AuthManager.shared` 殘留 session（曾致 Settings 顯示已登入卻標 logged-out 的像素說謊）。範式見 `VocabularyListViewScenarios` / `NotebookListViewScenarios`。

**simctl 截圖協作**：

```bash
./ops/ios_ops.sh simulator screenshot --out /tmp/kg-catalog-page.png --json
```

把 JSON 的 `artifact.path` 貼給 Claude 即可協作視覺迭代。所有 catalog 程式碼都包在 `#if DEBUG` 內，**production binary 不包含**。

### Catalog Snapshot Export（PlaybookSnapshot → PNG batch）

`BooksBrowserTests/CatalogSnapshotTests.swift` 提供 `generateAllScenarioPNGs` test，跑一次把目前 catalog 註冊的全部 scenarios × 2 appearances（iPhone15Pro portrait light/dark）渲染成 PNG，並在 root 旁吐 `catalog_index.json`（taxonomy ground truth），**不用人工逐頁截**。（scenario 數隨 source 變動，不在此手記；以 `CatalogScene.Manifest` 為準。）

**若目標是行銷 / App Store 素材，優先從 capture profile 進，不要直接手拼 snapshot 與 renderer 命令**：

```bash
# 先看完整 recipe：造景 -> catalog snapshot -> local framing -> promo render
./ops/capture_profile.py plan ops/capture_profiles/marketing_demo.json

# 真正執行時，可拆開 materialize / snapshot / render；`run` 會在 dry-run 下略過真寫入，
# 但仍自動完成 snapshot -> local framing -> final app-store PNG
./ops/capture_profile.py run ops/capture_profiles/marketing_demo.json --reuse-build
```

`capture_profile.py` 現在是 orchestrator；`catalog snapshots` 是內容畫面輸出；`frame_catalog_screenshots.py` 會在本地把 raw screenshot 套成 iPhone framed source；`render_screenshots.py` 再吃 framed source + profile 內 `shots[].copy` 產出最終 App Store PNG。ASC 截圖上傳仍是 GUI/manual，不在這條自動化內。

**執行方式**（manual，**不要主動跑** — 遵守 CLAUDE.md 鐵律 7 `ios_test.sh` 規則）：

```bash
# 先 warm reusable build cache（冷啟成本顯式拆出）
./ops/ios_ops.sh catalog prepare \
  --destination 'platform=iOS Simulator,name=iPhone 17 Pro Max'

# 再跑 scoped/full snapshot；--reuse-build 代表 miss/stale 時直接報錯，不偷偷重建
./ops/ios_ops.sh catalog snapshots \
  --destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  --scenario 'Today Review/Front' \
  --dataset marketing_demo \
  --reuse-build \
  --json

# 或直接指定任意外部檔案（不必改 iOS code）
./ops/ios_ops.sh catalog snapshots \
  --destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  --dataset-file ops/fixtures/catalog/marketing_demo.json \
  --scenario 'Today Review/Front' \
  --json

# 如需 full catalog，去掉 --scenario / --group 即可
./ops/ios_ops.sh catalog snapshots \
  --destination 'platform=iOS Simulator,name=iPhone 17 Pro Max'

# full run 會自動落地成新的 workspace artifact：
# build/snapshots/catalog-full-<UTC timestamp>/
# 並由 review entry 自動把最新可用那份視為 blessed
./ops/catalog_review_entry.py current             # payload 含 canvasHtml
./ops/catalog_review_entry.py serve --port 8787   # 服務 /catalog.html (url 直指 canvas)
./ops/catalog_review_entry.py prune-superseded --dry-run
./ops/catalog_review_entry.py prune-superseded

# Agent 查 surface 層 lane-aware 覆蓋缺口（不開瀏覽器、不 parse 整份 manifest）:
BLESSED=$(./ops/catalog_review_entry.py current | jq -r '.blessed.root')
./ops/catalog_review_cli.py "$BLESSED" gaps --min-gap 3                                # 真 backlog: 缺最多 ship-critical state 的可上架 surface
./ops/catalog_review_cli.py "$BLESSED" gaps --lane feature-surface --missing loading  # 缺特定 state 的出貨畫面

# Agent 要「看」畫面: 把多張合成一張 contact sheet, 一次 Read 取代 N 次 Read(省 image token)。
# 機器臉看圖的正解 — 不要用 preview/headless 瀏覽器截 review.html(detached server 佔 port、headless lazy-paint 全白)。
./ops/catalog_contact_sheet.py "$BLESSED" --surface "Bookshelf View" --appearance both --cols 2  # 一張看完某 surface 全 state × light/dark
./ops/catalog_contact_sheet.py "$BLESSED" --lane feature-surface --facet empty                   # 一張看完所有出貨畫面的 empty state
# → 印出合成 PNG 路徑, 直接 Read 該檔。caveat: stateFacet 由 title 推導會誤標(見 catalog memory), 看圖驗 facet 別只信 label。

# 清理 0 圖的舊 review 殼，避免 stale artifact 混進 blessed 判斷
./ops/catalog_review_entry.py current
./ops/catalog_review_entry.py prune-stale --dry-run
./ops/catalog_review_entry.py prune-stale
```

**從 simulator sandbox 撈 PNG**：

```bash
# 找 BooksBrowserTests host app 的 data container
container=$(./ops/ios_ops.sh simulator status --json | jq -r '.app.container.data // empty')
# PNG 在 NSTemporaryDirectory → tmp/kg-catalog-snapshots/<device>/<category>/<scenario>.png
find "$container/tmp/kg-catalog-snapshots" -name "*.png" 2>/dev/null
# 或直接複製到專案下供 Claude 讀
mkdir -p build/snapshots && cp -R "$container/tmp/kg-catalog-snapshots/." build/snapshots/
```

**為什麼 PlaybookSnapshot 而非 EmergeTools/SnapshotPreviews**：原本計畫用 EmergeTools 套件直接 snapshot 既有 `#Preview`，但 `playbook-ios` 內建 `PlaybookSnapshot` product 已能對 catalog scenarios 做同樣工作，且 catalog scenarios 明確、命名整齊、能注入 stub envObject — 比 raw `#Preview` 更可靠（後者常因缺 EnvironmentObject crash）。`#Preview` snapshot 留待 Phase 5 評估。

**閉環 demo**：
1. 你改 `AppTheme.swift` 一個 hue 值 + InjectionNext 秒級重渲染
2. 確認 catalog 樣式可接受後跑上述 `catalog prepare` + `catalog snapshots`
3. 撈 PNG → 貼給 Claude → Claude 跨 scenario 比對找出視覺 regression
4. 不滿意回 step 1



## 參考文件

- `docs/sop/ui-design.md` — Motion Contract + 設計系統規範
- `docs/sop/backend.md` — backend 開發主入口；跨前後端資料流問題時一起看
- `docs/reference/ui/components.md` — 現有 component / pattern inventory，開新 UI 前先查
- `docs/reference/ui/state_matrix.md` — 各主畫面 state coverage matrix，補 UX 時先查有哪些狀態不能漏
- `docs/sop/architecture.md` — 完整 iOS ↔ 後端同步協議、認證架構、資料模型詳解
